import os
from motor.motor_asyncio import AsyncIOMotorClient

# Read MongoDB connection string
MONGO_URL = os.getenv(
    "MONGO_URL", 
    "mongodb://localhost:27017/motor"
)

# Global Mongo client (lazy singleton)
_client: AsyncIOMotorClient | None = None

def get_client() -> AsyncIOMotorClient:
    """
    Lazily create and return a global Motor client.
    Motor manages an internal connection pool automatically.
    """
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(MONGO_URL)
    return _client

def get_collection():
    """
    Returns the products collection.
    """
    client = get_client()
    return client["motor"]["products"]
