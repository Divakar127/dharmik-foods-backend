"""Homepage merchandising, newsletter, customer insights and media ingestion."""
import hashlib
import io
import re
import secrets
import warnings
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.storage.blob import BlobServiceClient, ContentSettings
from app.core.config import settings
from app import mongo_repository as db

UPLOAD_DIR = Path(__file__).resolve().parents[1] / "storage" / "uploads"
MAX_UPLOAD = 8 * 1024 * 1024

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

def image_path(value):
    from app.schemas import ProductWrite
    if value == "/food/photos/traditional-meal.webp":
        return value
    return ProductWrite.safe_image(value)

class Slide(Input):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,40}$")
    title: str = Field(min_length=3, max_length=100)
    description: str = Field(min_length=5, max_length=240)
    image_url: str = Field(min_length=1, max_length=1000)
    alt: str = Field(min_length=5, max_length=180)
    href: str = Field(default="/#catalog", max_length=300)
    link_label: str = Field(default="Explore the range", min_length=2, max_length=45)
    enabled: bool = True
    @field_validator("image_url")
    @classmethod
    def safe_image(cls, value):
        return image_path(value)
    @field_validator("href")
    @classmethod
    def safe_href(cls, value):
        if not value.startswith("/") or value.startswith("//") or "\\" in value or any(ord(c) < 32 for c in value):
            raise ValueError("Use a link within this store")
        return value

class Homepage(Input):
    version: int = Field(ge=1)
    banner_width: int = Field(default=1500, ge=320, le=2000)
    banner_height: int = Field(default=536, ge=200, le=2000)
    interval_seconds: int = Field(default=8, ge=5, le=30)
    slides: list[Slide] = Field(min_length=1, max_length=10)
    @model_validator(mode="after")
    def unique_slides(self):
        if len({s.id for s in self.slides}) != len(self.slides):
            raise ValueError("Slide IDs must be unique")
        if not any(s.enabled for s in self.slides):
            raise ValueError("Keep at least one slide enabled")
        return self

def default_homepage():
    content = [
        ("everyday", "Real ingredients. Better everyday food choices.", "Stock your kitchen with familiar staples and thoughtful choices for every day.", "/campaigns/promo-v2/everyday.webp", "Everyday food. Rooted in tradition. Shop the pantry — illustrative campaign", "/#catalog"),
        ("millets", "Small grains. A bigger place at your table.", "Rediscover ragi, little millet and everyday wholegrain favourites.", "/campaigns/promo-v2/millets.webp", "Make room for millets. Shop grains & millets — illustrative campaign", "/?category=Grains%20%26%20millets#catalog"),
        ("nuts", "Small additions. Thoughtful everyday choices.", "Meet Diabetes-Friendly Picks: browse ingredients and nutrition with care.", "/campaigns/promo-v2/nuts.webp", "Know your food. Choose your balance. Compare ingredients — illustrative campaign", "/sugar-smart"),
        ("tea", "Make a little time for your daily ritual.", "Ginger, tulsi and pantry infusions for a moment worth slowing down for.", "/campaigns/promo-v2/tea.webp", "A little time. A daily ritual. Shop drinks & infusions — illustrative campaign", "/?category=Drinks%20%26%20infusions#catalog"),
        ("pottery", "From earth. For your everyday kitchen.", "Explore clay cookware and bring the craft of traditional cooking home.", "/campaigns/promo-v2/pottery.webp", "Clay cookware. Everyday tradition. Shop pottery — illustrative campaign", "/?category=Pottery#catalog"),
        ("tradition", "Good food carries a story.", "Our purpose is to make traditional ingredients feel at home in a modern kitchen.", "/campaigns/promo-v2/tradition.webp", "Bring tradition to the table. Read our story — illustrative campaign", "/about"),
    ]
    return {"version": 1, "interval_seconds": 8, "slides": [{"id": ident, "title": title, "description": description, "image_url": image, "alt": alt, "href": href, "link_label": "Discover more", "enabled": True} for ident,title,description,image,alt,href in content]}

def initialize():
    db.collection("newsletter_subscribers").create_index("email", unique=True)
    db.collection("newsletter_subscribers").create_index("unsubscribe_hash", unique=True)
    db.collection("pages").update_one({"_id": "homepage"}, {"$setOnInsert": default_homepage()}, upsert=True)
    db.collection("media").create_index("url", sparse=True)
    db.collection("products").update_many({"collection": "Sugar Smart Pantry"}, {"$set": {"collection": "Diabetes-Friendly Picks"}, "$inc": {"version": 1}})
    db.collection("collections").update_one({"_id": "Sugar Smart Pantry"}, {"$set": {"active": False}})
    db.collection("collections").update_one({"_id": "Diabetes-Friendly Picks"}, {"$setOnInsert": {"name": "Diabetes-Friendly Picks", "active": True, "sort_order": 4}}, upsert=True)

@db.guarded
def homepage(staff=False):
    doc = db.collection("pages").find_one({"_id": "homepage"}, {"_id": 0}) or default_homepage()
    doc.setdefault("banner_width", 1500)
    doc.setdefault("banner_height", 536)
    if not staff:
        doc["slides"] = [slide for slide in doc["slides"] if slide["enabled"]]
    return doc

@db.guarded
def save_homepage(body):
    from pymongo import ReturnDocument
    doc = db.collection("pages").find_one_and_update({"_id": "homepage", "version": body.version}, {
        "$set": body.model_dump(exclude={"version"}), "$inc": {"version": 1}}, return_document=ReturnDocument.AFTER)
    if not doc:
        raise HTTPException(409, "Homepage preferences changed. Reload before saving.")
    doc.pop("_id", None)
    return doc

class Subscription(Input):
    email: str = Field(min_length=5, max_length=254)
    consent: bool
    website: str = Field(default="", max_length=200)
    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+", value):
            raise ValueError("Enter a valid email address")
        return value.lower()
    @field_validator("consent")
    @classmethod
    def explicit_consent(cls, value):
        if not value:
            raise ValueError("Please agree to receive the newsletter")
        return value

@db.guarded
def subscribe(body):
    if body.website:
        return {"message": "Thank you for your interest."}
    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    # Always respond the same way for new and existing addresses. Rotating the
    # unsubscribe token permits the submitting person to keep a private link.
    db.collection("newsletter_subscribers").update_one({"email": body.email}, {
        "$setOnInsert": {"_id": uuid4().hex, "created_at": now},
        "$set": {"status": "subscribed", "consent_version": "newsletter-v1", "consented_at": now,
            "unsubscribe_hash": hashlib.sha256(token.encode()).hexdigest(), "source": "storefront"}}, upsert=True)
    return {"message": "You're on the list. Your preference has been saved.", "unsubscribe_token": token}

class Unsubscribe(Input):
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")

@db.guarded
def unsubscribe(body):
    db.collection("newsletter_subscribers").update_one({"unsubscribe_hash": hashlib.sha256(body.token.encode()).hexdigest()}, {"$set": {"status": "unsubscribed", "unsubscribed_at": datetime.now(timezone.utc)}})
    return {"message": "Your newsletter preference has been updated."}

@db.guarded
def customers(q="", page=1):
    query = {"$or": [{k: {"$regex": re.escape(q), "$options": "i"}} for k in ("name", "email", "phone")]} if q else {}
    docs = list(db.collection("users").find(query).sort("created_at", -1).skip((page-1)*20).limit(20))
    ids = [u["_id"] for u in docs]
    counts = {row["_id"]: row["count"] for row in db.collection("orders").aggregate([
        {"$match": {"user_id": {"$in": ids}}}, {"$group": {"_id": "$user_id", "count": {"$sum": 1}}}])} if ids else {}
    return {"items": [{"id": u["_id"], "name": u["name"], "email": u["email"], "phone": u.get("phone", ""),
        "phone_verified": False, "created_at": u["created_at"].isoformat(), "order_count": counts.get(u["_id"], 0)} for u in docs],
        "total": db.collection("users").count_documents(query), "page": page, "page_size": 20}

@db.guarded
def dashboard():
    tz = ZoneInfo("Asia/Kolkata")
    today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=6)
    rows = list(db.collection("orders").aggregate([
        {"$match": {"created_at": {"$gte": start}}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at", "timezone": "Asia/Kolkata"}},
            "orders": {"$sum": 1}, "bill_value": {"$sum": {"$toDecimal": "$total"}},
            "paid_value": {"$sum": {"$cond": [{"$eq": ["$payment_status", "paid"]}, {"$toDecimal": "$total"}, 0]}}}}]))
    by_day = {r["_id"]: r for r in rows}
    daily = []
    for day in range(7):
        date = (start + timedelta(days=day)).date().isoformat()
        row = by_day.get(date, {})
        daily.append({"date": date, "orders": row.get("orders", 0), "bill_value": str(row.get("bill_value", Decimal("0.00"))), "paid_value": str(row.get("paid_value", Decimal("0.00")))})
    return {"timezone": "Asia/Kolkata", "daily": daily, "today_orders": daily[-1]["orders"], "today_bill_value": daily[-1]["bill_value"],
        "today_paid_value": daily[-1]["paid_value"], "total_customers": db.collection("users").count_documents({}),
        "unpaid_orders": db.collection("orders").count_documents({"payment_status": "unpaid"}),
        "active_carts": db.collection("carts").count_documents({"expires_at": {"$gt": datetime.now(timezone.utc)}, "items.0": {"$exists": True}}),
        "newsletter_subscribers": db.collection("newsletter_subscribers").count_documents({"status": "subscribed"}),
        "low_stock_products": db.collection("products").count_documents({"stock": {"$gte": 1, "$lt": 10}}),
        "out_of_stock_products": db.collection("products").count_documents({"stock": 0})}

def convert_image(data):
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Images must be 8 MB or smaller")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in ("JPEG", "PNG", "WEBP") or source.width * source.height > 24000000:
                    raise ValueError("Unsupported image")
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((2000, 2000))
                out = io.BytesIO()
                image.save(out, format="WEBP", quality=87)
                return out.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(422, "Upload a valid JPEG, PNG or WebP image under 24 megapixels") from None

@db.guarded
def upload_image(data):
    converted = convert_image(data)
    with Image.open(io.BytesIO(converted)) as saved_image:
        width, height = saved_image.size
    name = uuid4().hex + ".webp"
    if settings.media_storage == "azure":
        if not settings.azure_storage_connection_string.get_secret_value() or not settings.azure_media_public_base_url.startswith("https://"):
            raise HTTPException(503, "Azure media needs its connection string and public base URL configured on the backend")
        try:
            with BlobServiceClient.from_connection_string(settings.azure_storage_connection_string.get_secret_value(), connection_timeout=10, read_timeout=20) as service:
                container = service.get_container_client(settings.azure_media_container)
                container.get_container_properties()  # Do not change access on an existing storage account.
                container.upload_blob(name, converted, overwrite=False, content_settings=ContentSettings(content_type="image/webp", cache_control="public, max-age=31536000, immutable"))
            url = settings.azure_media_public_base_url.rstrip("/") + "/" + name
        except (AzureError, ValueError):
            raise HTTPException(503, "Azure upload failed. Check the container, credentials and public delivery URL.") from None
    else:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        (UPLOAD_DIR / name).write_bytes(converted)
        url = "/media/" + name
    db.collection("media").insert_one({"_id": name[:-5], "url": url, "storage": settings.media_storage,
        "content_type": "image/webp", "bytes": len(converted), "created_at": datetime.now(timezone.utc), "actor": "warehouse"})
    return {"url": url, "storage": settings.media_storage, "bytes": len(converted), "width": width, "height": height}
