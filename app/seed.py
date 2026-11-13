"""Idempotently populate DharmicFoods without replacing warehouse changes."""
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import get_args
from app.core.config import settings
from app import mongo_repository as repo
from app.data import seed_products
from app.schemas import ProductWrite, Category, Collection

def seed():
    if settings.database_backend != "mongodb" or settings.database_name != "DharmicFoods" or settings.mongo_collection_prefix:
        raise RuntimeError("Seeding is restricted to the main DharmicFoods MongoDB database")
    repo.initialize()
    inserted = 0
    for item in seed_products():
        body = ProductWrite.model_validate(item).model_dump(mode="json")
        if repo.collection("products").find_one({"sku_key": body["sku"].casefold()}, {"_id": 1}) is None:
            repo.write_product(body)
            inserted += 1
    for collection_name, values in (("categories", get_args(Category)), ("collections", get_args(Collection))):
        for index, name in enumerate(values):
            repo.collection(collection_name).update_one({"_id": name}, {"$setOnInsert": {"name": name, "sort_order": index, "active": True}}, upsert=True)
    manifest = json.loads((Path(__file__).parent / "photo_manifest.json").read_text(encoding="utf-8"))
    for photo in manifest:
        doc = {k:v for k,v in photo.items() if k != "download_path"}
        repo.collection("media").update_one({"_id": photo["slug"]}, {"$setOnInsert": doc}, upsert=True)
    content = Path(__file__).parent / "about_content.json"
    if content.exists():
        repo.collection("pages").update_one({"_id": "about-us"}, {"$setOnInsert": json.loads(content.read_text(encoding="utf-8"))}, upsert=True)
    repo.collection("metadata").update_one({"_id": "sample_seed_v1"}, {"$setOnInsert": {"applied_at": datetime.now(timezone.utc), "sample_data": True}}, upsert=True)
    print(f"DharmicFoods is ready: {repo.collection('products').count_documents({})} products, {inserted} newly inserted.")
    print("Collections: " + ", ".join(sorted(repo.database().list_collection_names())))

if __name__ == "__main__":
    try:
        seed()
    except Exception as exc:
        print("Seed failed:", type(exc).__name__, "Check the MongoDB connection and permissions; credentials are not logged.")
        raise SystemExit(1)
    finally:
        repo.close()
