import time
import redis
from fastapi import HTTPException
import logging

logger = logging.getLogger(__name__)

r = redis.Redis(host="localhost", port=6379, decode_responses=True)
class RateLimitExceeded(HTTPException):
    def __init__(self, detail="Rate limit exceeded", retry_after=None):
        headers = {"Retry-After": str(retry_after)} if retry_after else None
        super().__init__(status_code=429, detail=detail, headers=headers)

class TokenBucket:
    def __init__(self, capacity=10, refill_rate=1):
        self.capacity = capacity
        self.refill_rate = refill_rate  # tokens per second

    def check_redis_connection(self):
        """Check if Redis is accessible"""
        try:
            r.ping()
            return True
        except redis.ConnectionError as e:
            logger.error(f"Redis connection failed: {str(e)}")
            raise Exception("Redis connection failed")

    def get_stats(self, ip: str):
        """Get current rate limit statistics for an IP"""
        now = time.time()
        key = f"bucket:{ip}"
        
        try:
            data = r.hmget(key, "tokens", "last")
            
            if data[0] is None:
                return {
                    "tokens_available": self.capacity,
                    "capacity": self.capacity,
                    "refill_rate": self.refill_rate,
                    "status": "new"
                }
            
            tokens = float(data[0])
            last = float(data[1]) if data[1] else now
            
            # Calculate current tokens with refill
            delta = now - last
            current_tokens = min(self.capacity, tokens + delta * self.refill_rate)
            
            return {
                "tokens_available": round(current_tokens, 2),
                "capacity": self.capacity,
                "refill_rate": self.refill_rate,
                "last_request": last,
                "time_since_last": round(delta, 2),
                "status": "active"
            }
        except Exception as e:
            logger.error(f"Error getting stats for {ip}: {str(e)}")
            raise

    def allow_request(self, ip: str):
        now = time.time()
        key = f"bucket:{ip}"

        try:
            # Get last state
            data = r.hmget(key, "tokens", "last")

            tokens = float(data[0]) if data[0] else self.capacity
            last = float(data[1]) if data[1] else now

            # Refill tokens
            delta = now - last
            tokens = min(self.capacity, tokens + delta * self.refill_rate)

            if tokens < 1:
                # Calculate retry after time
                retry_after = int((1 - tokens) / self.refill_rate) + 1
                logger.warning(f"Rate limit exceeded for {ip}. Retry after {retry_after}s")
                raise RateLimitExceeded(
                    detail=f"Rate limit exceeded. Try again in {retry_after} seconds",
                    retry_after=retry_after
                )

            # Consume token
            tokens -= 1

            # Save back to Redis
            r.hset(key, mapping={"tokens": tokens, "last": now})
            r.expire(key, 60)

            logger.debug(f"Request allowed for {ip}. Tokens remaining: {tokens:.2f}")
            return True
        except RateLimitExceeded:
            raise
        except Exception as e:
            logger.error(f"Error processing rate limit for {ip}: {str(e)}")
            # Fail open - allow request if Redis is down
            return True
