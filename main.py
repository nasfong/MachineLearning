from fastapi import FastAPI, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List, Optional
from pydantic import BaseModel
import os

# MongoDB connection
MONGO_URL = os.getenv(
    "MONGO_URL", 
    "mongodb://admin:your_mongo_password@mongodb.nasfong.site:443?ssl=true&authSource=admin"
)

app = FastAPI(title="Products API")

client = AsyncIOMotorClient(MONGO_URL)
db = client["motor"]
collection = db["products"]

# ----- Model -----
class Product(BaseModel):
    id: str
    # name: str
    # price: str
    # description: Optional[str] = None
    # image: Optional[List[str]] = None


# ----- Routes -----
@app.get("/")
def root():
    return {"message": "API is running"}


@app.get("/products", response_model=List[Product])
async def list_products():
    try:
        products: List[Product] = []

        async for doc in collection.find():
            # Normalize image: ensure it's a list
            images = doc.get("image", [])
            if isinstance(images, str):
                images = [images]
            elif images is None:
                images = []

            # Create Product model instance
            product = Product(
                id=str(doc["_id"]),
                name=doc.get("name", "Unknown"),
                price=str(doc.get("price", "0.0")),
                description=doc.get("description"),
                image=images,
            )
            products.append(product)

        return products

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
