from fastapi import FastAPI, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from typing import List
import os

# MongoDB connection URL
MONGO_URL = "mongodb://admin:your_mongo_password@mongodb.nasfong.site:443/motor?ssl=true&authSource=admin"

app = FastAPI(title="ML API", version="1.0")

# MongoDB client and database
client = AsyncIOMotorClient(MONGO_URL)
db = client["motor"]  # database name is "motor"
collection = db["products"]  # collection name is "products"


# Define product model for response
class Product(BaseModel):
    id: str
    name: str
    price: float | None = None
    description: str | None = None


@app.get("/")
def root():
    return {"message": "ML API is running"}


@app.get("/products", response_model=List[Product])
async def list_products():
    """Fetch all products from MongoDB"""
    try:
        products_cursor = collection.find()
        products = []
        async for product in products_cursor:
            try:
                # Validate and convert price
                price = product.get("price", 0.0)
                if isinstance(price, str):
                    # Try to parse string to float, skip if invalid
                    try:
                        price = float(price)
                    except ValueError:
                        print(f"Skipping product {product.get('_id')} - invalid price: {price}")
                        continue
                
                products.append(
                    Product(
                        id=str(product["_id"]),
                        name=product.get("name", "Unknown"),
                        price=price,
                        description=product.get("description", None),
                    )
                )
            except Exception as e:
                print(f"Error processing product {product.get('_id')}: {e}")
                continue
        
        return products
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
