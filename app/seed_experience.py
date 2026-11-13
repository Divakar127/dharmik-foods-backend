"""Add the merchandising slice without replacing warehouse-managed content."""
from datetime import datetime, timezone
from typing import get_args
from app import mongo_repository as db, experience
from app.schemas import Category, Collection

ALIASES = {"DF-GRM-000001": ["ராகி", "கேழ்வரகு", "kezhvaragu", "kelvaragu"], "DF-GRM-000002": ["ஓட்ஸ்", "oats"],
    "DF-NTS-000003": ["பாதாம்", "badam", "badaam"], "DF-NTS-000004": ["சியா", "chia seeds"],
    "DF-PNY-000005": ["தேங்காய் எண்ணெய்", "thengai ennai"], "DF-DRK-000006": ["தண்ணீர்", "thanni", "thanneer"],
    "DF-DRK-000007": ["இஞ்சி", "துளசி", "inji", "thulasi"], "DF-GRM-000008": ["சாமை", "samai", "saamai"]}

def seed():
    db.initialize(); experience.initialize()
    for sku, aliases in ALIASES.items():
        db.collection("products").update_one({"sku": sku, "search_aliases": {"$exists": False}}, {"$set": {"search_aliases": aliases}})
    db.collection("products").update_many({"sku": {"$in": ["DF-GRM-000002", "DF-NTS-000003", "DF-NTS-000004", "DF-DRK-000006"]}, "sugar_smart": {"$exists": False}}, {"$set": {"sugar_smart": True}})
    if not db.collection("products").find_one({"sample_key": "pottery-v1"}):
        body = {"name": "Terracotta cooking pot", "sku": "", "description": "An illustrative clay-cookware sample for the traditional kitchen. Confirm food-contact safety, capacity, seasoning, heat-source compatibility and care instructions with the supplier before sale or use. The campaign image is illustrative, not a verified supplier pack photograph.",
            "category": "Pottery", "collection": "Everyday nourishment", "price": "699.00", "pack_size": "1 pot · sample 2 L size",
            "ingredients": "Terracotta clay; supplier composition to be verified", "allergens": "Not a food product. Verify food-contact safety with the supplier.",
            "origin": "India · sample origin", "storage": "Follow the supplier's seasoning and care instructions. Avoid sudden temperature changes. Dry fully before storage.",
            "image_url": "/campaigns/pottery.webp", "image_credit": "AI-generated illustrative campaign image; sample cookware only.", "stock": 12, "location": "P-01", "status": "published",
            "nutrition_basis": "Not applicable — cookware", "search_aliases": ["மண்பானை", "மண் பானை", "manpaanai", "mannpaanai", "clay pot", "earthen pot"]}
        product = db.write_product(body)
        db.collection("products").update_one({"_id": product["id"]}, {"$set": {"sample_key": "pottery-v1"}})
    for name, values in (("categories", get_args(Category)), ("collections", get_args(Collection))):
        for index, value in enumerate(values):
            db.collection(name).update_one({"_id": value}, {"$setOnInsert": {"name": value, "sort_order": index, "active": True}}, upsert=True)
    db.collection("metadata").update_one({"_id": "experience_v1"}, {"$setOnInsert": {"applied_at": datetime.now(timezone.utc)}}, upsert=True)
    print("Experience defaults ready: banners, multilingual aliases, Sugar Smart curation and pottery sample. Existing edits preserved.")

if __name__ == "__main__":
    try:
        seed()
    finally:
        db.close()
