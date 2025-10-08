from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from bson import ObjectId
from db import get_collection

# ---- Schemas ----
class ProductIn(BaseModel):
    name: str
    price: str
    description: Optional[str] = None
    image: Optional[List[str]] = None

class ProductOut(ProductIn):
    id: str

def to_product_out(doc) -> ProductOut:
    return ProductOut(
        id=str(doc["_id"]),
        name=doc.get("name", "Unknown"),
        price=str(doc.get("price", "0.0")),
        description=doc.get("description"),
        image=doc.get("image"),
    )

router = APIRouter(prefix="/products", tags=["products"])

@router.get("", response_model=List[ProductOut])
@router.get("/", response_model=List[ProductOut])
async def list_products(
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
):
    col = get_collection()
    try:
        items: List[ProductOut] = []
        cursor = col.find({}, skip=skip, limit=limit)
        async for doc in cursor:
            items.append(to_product_out(doc))
        return items
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

@router.post("", response_model=ProductOut, status_code=201)
@router.post("/", response_model=ProductOut, status_code=201)
async def create_product(product: ProductIn):
    col = get_collection()
    try:
        result = await col.insert_one(product.dict())
        created = await col.find_one({"_id": result.inserted_id})
        return to_product_out(created)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

@router.get("/{product_id}", response_model=ProductOut)
async def get_product(product_id: str):
    col = get_collection()
    try:
        doc = await col.find_one({"_id": ObjectId(product_id)})
        if not doc:
            raise HTTPException(status_code=404, detail="Not found")
        return to_product_out(doc)
    except Exception as e:
        if "InvalidId" in str(e):
            raise HTTPException(status_code=400, detail="Invalid product id")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

@router.delete("/{product_id}", status_code=204)
async def delete_product(product_id: str):
    col = get_collection()
    try:
        res = await col.delete_one({"_id": ObjectId(product_id)})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Not found")
        return
    except Exception as e:
        if "InvalidId" in str(e):
            raise HTTPException(status_code=400, detail="Invalid product id")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
