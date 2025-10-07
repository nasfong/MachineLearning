from fastapi import FastAPI
from pymongo.errors import ServerSelectionTimeoutError
from db import get_client
from products import router as products_router

app = FastAPI(title="Products API with MongoDB")

@app.on_event("startup")
async def startup_event():
    """
    Warm up Mongo connection pool and verify connectivity at startup.
    """
    client = get_client()
    try:
        await client.admin.command("ping")
        print("✅ MongoDB connection established and pool warmed.")
    except ServerSelectionTimeoutError as e:
        print("❌ MongoDB connection failed:", e)
        raise e

@app.get("/health")
async def health_check():
    """
    Health check endpoint for Docker or load balancer.
    """
    return {"status": "ok"}

@app.get("/")
def root():
    return {"message": "API is running"}

# Register products routes
app.include_router(products_router)
