from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from test import TokenBucket, RateLimitExceeded
import logging
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Rate Limited API",
    description="A FastAPI application with Redis-backed rate limiting",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bucket = TokenBucket()   # Redis-backed, shared

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests"""
    start_time = time.time()
    logger.info(f"Request: {request.method} {request.url.path} from {request.client.host}")
    
    response = await call_next(request)
    
    process_time = time.time() - start_time
    logger.info(f"Response: {response.status_code} in {process_time:.4f}s")
    
    return response

@app.get("/")
def root():
    """Root endpoint with API information"""
    return {
        "message": "Welcome to Rate Limited API",
        "version": "1.0.0",
        "endpoints": {
            "/limited": "Rate limited endpoint (10 requests per window)",
            "/unlimited": "Unlimited endpoint",
            "/health": "Health check endpoint",
            "/stats/{ip}": "Get rate limit stats for an IP"
        }
    }

@app.get("/health")
def health_check():
    """Health check endpoint"""
    try:
        bucket.check_redis_connection()
        return JSONResponse(
            status_code=200,
            content={
                "status": "healthy",
                "redis": "connected",
                "timestamp": time.time()
            }
        )
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "redis": "disconnected",
                "error": str(e),
                "timestamp": time.time()
            }
        )

@app.get("/limited")
def limited(request: Request):
    """Rate limited endpoint"""
    ip = request.client.host
    logger.info(f"Limited endpoint accessed by {ip}")

    try:
        bucket.allow_request(ip)
        return {
            "message": "This is a limited use API",
            "ip": ip,
            "status": "success"
        }
    except RateLimitExceeded as e:
        logger.warning(f"Rate limit exceeded for {ip}")
        raise e

@app.get("/unlimited")
def unlimited(request: Request):
    """Unlimited endpoint"""
    ip = request.client.host
    logger.info(f"Unlimited endpoint accessed by {ip}")
    return {
        "message": "Free to use API limitless",
        "ip": ip,
        "status": "success"
    }

@app.get("/stats/{ip}")
def get_stats(ip: str):
    """Get rate limit statistics for a specific IP"""
    try:
        stats = bucket.get_stats(ip)
        return {
            "ip": ip,
            "stats": stats
        }
    except Exception as e:
        logger.error(f"Error getting stats for {ip}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
