import re
from typing import Literal
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app import commerce
from app.core.config import settings
from app.security import require_staff

router = APIRouter(tags=["Customer commerce"])

def mongo_only():
    if settings.database_backend != "mongodb":
        raise HTTPException(503, "Customer commerce requires MongoDB")

router.dependencies.append(Depends(mongo_only))

def user(authorization: str = Header(default="")):
    return commerce.user_for(authorization.removeprefix("Bearer "))

def optional_user(authorization: str = Header(default="")):
    if authorization:
        return commerce.user_for(authorization.removeprefix("Bearer "))
    return None

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class GoogleCallback(Input):
    state: str = Field(min_length=43, max_length=128)
    code: str = Field(min_length=1, max_length=4096)
    guest_token: str = Field(default="", max_length=128)

class Profile(Input):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=10, max_length=24)

    @field_validator("phone")
    @classmethod
    def phone_format(cls, value):
        value = re.sub(r"[\s()-]", "", value)
        if not re.fullmatch(r"\+[1-9][0-9]{7,14}", value):
            raise ValueError("Use an international phone number, for example +919876543210")
        return value

class CartItem(Input):
    product_id: int = Field(gt=0)
    quantity: int = Field(ge=0, le=99)
    version: int = Field(ge=0)

class Address(Input):
    recipient: str = Field(min_length=2, max_length=120)
    line1: str = Field(min_length=5, max_length=180)
    line2: str = Field(default="", max_length=180)
    city: str = Field(min_length=2, max_length=100)
    state: str = Field(min_length=2, max_length=100)
    postal_code: str = Field(pattern=r"^[1-9][0-9]{5}$")
    country: Literal["India"] = "India"

class OrderCreate(Input):
    address: Address
    cart_version: int = Field(ge=1)
    quote_token: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key: str = Field(pattern=r"^[a-zA-Z0-9_-]{20,100}$")
    acknowledge_unpaid: Literal[True]

@router.get("/auth/config")
def auth_config():
    return {"google_configured": commerce.google_configured(), "phone_verification_enabled": False}

@router.post("/auth/google/start")
def google_start(request: Request):
    commerce.limit_auth(request.client.host if request.client else "unknown")
    return commerce.google_start()

@router.post("/auth/google/callback")
def google_callback(body: GoogleCallback, request: Request):
    commerce.limit_auth(request.client.host if request.client else "unknown")
    return commerce.google_finish(body.state, body.code, body.guest_token)

@router.get("/auth/me")
def me(current=Depends(user)):
    return commerce.public_user(current)

@router.patch("/auth/me")
def profile(body: Profile, current=Depends(user)):
    return commerce.update_profile(current, body)

@router.post("/auth/logout", status_code=204)
def logout(authorization: str = Header(default="")):
    commerce.logout(authorization.removeprefix("Bearer "))

@router.get("/cart")
def cart(current=Depends(optional_user), x_cart_token: str = Header(default="", max_length=128)):
    return commerce.get_cart(current, x_cart_token)

@router.put("/cart/items")
def cart_item(body: CartItem, current=Depends(optional_user), x_cart_token: str = Header(default="", max_length=128)):
    return commerce.set_cart_item(current, x_cart_token, body)

@router.post("/orders", status_code=201)
def create_order(body: OrderCreate, current=Depends(user)):
    return commerce.create_order(current, body)

@router.get("/orders")
def orders(current=Depends(user)):
    return commerce.orders(current)

@router.get("/orders/{ident}")
def order(ident: str, current=Depends(user)):
    return commerce.order(current, ident)

@router.get("/warehouse/orders", dependencies=[Depends(require_staff)])
def staff_orders():
    return commerce.staff_orders()
