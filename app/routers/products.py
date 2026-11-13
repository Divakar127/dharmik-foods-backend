from typing import Literal
from fastapi import APIRouter, Depends, Query, Response
from app import repository
from app.schemas import Product, ProductPage, ProductWrite, ProductUpdate, Category, Collection
from app.security import require_staff

router = APIRouter(tags=["Catalog"])

@router.get("/pages/about-us", tags=["Content"])
def about_page():
    return repository.get_about()

@router.get("/catalog/options")
def options():
    from typing import get_args
    return {"categories": get_args(Category), "collections": get_args(Collection)}

def filters(q: str = Query(default="", max_length=120), category: str = "", collection: str = "", in_stock: bool = False,
            sort: Literal["featured", "price-asc", "price-desc", "name"] = "featured", page: int = Query(default=1, ge=1), page_size: int = Query(default=12, ge=1, le=100)):
    return dict(q=q, category=category, collection=collection, in_stock=in_stock, sort=sort, page=page, page_size=page_size)

@router.get("/products", response_model=ProductPage)
def products(params: dict = Depends(filters)):
    return repository.list_products(**params)

@router.get("/products/{product_id}", response_model=Product)
def product(product_id: int):
    return repository.get_product(product_id)

staff = APIRouter(prefix="/warehouse", tags=["Warehouse"], dependencies=[Depends(require_staff)])

@staff.get("/products", response_model=ProductPage)
def warehouse_products(params: dict = Depends(filters)):
    return repository.list_products(**params, staff=True)

@staff.get("/products/{product_id}", response_model=Product)
def warehouse_product(product_id: int):
    return repository.get_product(product_id, staff=True)

@staff.post("/products", response_model=Product, status_code=201)
def create(body: ProductWrite):
    return repository.write_product(body.model_dump(mode="json"))

@staff.put("/products/{product_id}", response_model=Product)
def update(product_id: int, body: ProductUpdate):
    return repository.write_product(body.model_dump(mode="json", exclude={"version"}), product_id, body.version)

@staff.delete("/products/{product_id}", status_code=204)
def delete(product_id: int, version: int = Query(ge=1)):
    repository.delete_product(product_id, version)
    return Response(status_code=204)

@staff.get("/audit")
def audit():
    return repository.list_audit()

router.include_router(staff)
