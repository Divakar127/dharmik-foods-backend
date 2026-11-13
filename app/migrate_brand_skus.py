"""Explicit, repeatable migration of DM branding and legacy inventory SKUs."""
import re
from datetime import datetime, timezone
from app import mongo_repository as db
from app.sku import make_sku

def renamed(value):
    if isinstance(value, str):
        return value.replace("Dharmic Foods", "Dharmik Foods").replace("DHARMIC FOODS", "DHARMIK FOODS")
    if isinstance(value, list):
        return [renamed(v) for v in value]
    if isinstance(value, dict):
        return {k: renamed(v) for k, v in value.items()}
    return value

def migrate():
    db.initialize()
    def commit(session):
        changed = 0
        for doc in db.collection("products").find({}, session=session):
            if re.fullmatch(r"DF-(GRM|NTS|PNY|DRK|POT)-[0-9]{6,}", doc["sku"]):
                continue
            sku = make_sku(doc["category"], doc["_id"])
            db.collection("products").update_one({"_id": doc["_id"], "version": doc["version"]}, {
                "$set": {"sku": sku, "sku_key": sku.casefold(), "legacy_sku": doc["sku"], "updated_at": datetime.now(timezone.utc)},
                "$inc": {"version": 1}}, session=session)
            db.event(doc["_id"], "sku_standardized", session)
            changed += 1
        page = db.collection("pages").find_one({"_id": "about-us"}, session=session)
        if page:
            db.collection("pages").replace_one({"_id": "about-us"}, renamed(page), session=session)
        db.collection("metadata").update_one({"_id": "application"}, {"$set": {"name": "Dharmik Foods", "schema_version": 2}}, session=session)
        return changed
    print(f"DharmicFoods migration complete: {db.transaction(commit)} legacy SKUs standardized. Database name preserved.")

if __name__ == "__main__":
    try:
        migrate()
    finally:
        db.close()
