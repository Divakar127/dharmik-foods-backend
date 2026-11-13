"""MongoDB persistence scoped exclusively to the DharmicFoods database."""
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from functools import wraps
from bson.decimal128 import Decimal128
from fastapi import HTTPException
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern
from app.core.config import settings
from app.schemas import ProductWrite

_client = None

def client():
    global _client
    if _client is None:
        uri = settings.mongodb_uri.get_secret_value()
        if not uri:
            raise RuntimeError("MONGODB_URI is required for DharmicFoods")
        _client = MongoClient(uri, appname="DharmicFoods", serverSelectionTimeoutMS=10000, connectTimeoutMS=10000, socketTimeoutMS=15000, tz_aware=True)
    return _client

def database():
    # Deliberately ignore the database encoded in Furry's shared connection URI.
    if settings.database_name != "DharmicFoods":
        raise RuntimeError("Database must be DharmicFoods")
    return client()["DharmicFoods"]

def collection(name):
    return database()[settings.mongo_collection_prefix + name]

def guarded(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except DuplicateKeyError:
            raise HTTPException(409, "A product with this SKU already exists") from None
        except PyMongoError:
            # Never include connection strings, credentials or driver diagnostics in API responses.
            raise HTTPException(503, "Food catalog storage is temporarily unavailable. Please try again.") from None
    return wrapped

def initialize():
    client().admin.command("ping")
    for name in ("products", "audit", "counters", "metadata", "categories", "collections", "pages", "media"):
        full_name = settings.mongo_collection_prefix + name
        if full_name not in database().list_collection_names():
            try:
                database().create_collection(full_name)
            except PyMongoError as exc:
                # A second worker may create the same collection during startup.
                if getattr(exc, "code", None) != 48:
                    raise
    collection("products").create_index("sku_key", unique=True, name="unique_sku")
    collection("products").create_index([("status", 1), ("category", 1), ("_id", 1)], name="public_category")
    collection("products").create_index([("status", 1), ("collection", 1)], name="public_collection")
    collection("products").create_index("price_amount", name="price_sort")
    collection("audit").create_index([("at", -1)], name="recent_activity")
    collection("audit").create_index("product_id", name="product_activity")
    collection("metadata").update_one({"_id": "application"}, {"$setOnInsert": {"name": "Dharmik Foods", "database": "DharmicFoods", "schema_version": 2, "created_at": datetime.now(timezone.utc)}}, upsert=True)

def decode(doc):
    item = {key: doc[key] for key in ProductWrite.model_fields if key in doc}
    expired = bool(item.get("best_before") and item["best_before"] < date.today().isoformat())
    return {**item, "id": doc["_id"], "version": doc["version"], "currency": "INR", "available": item["stock"] > 0 and not expired and item["status"] == "published"}

def next_id(name, session):
    return collection("counters").find_one_and_update({"_id": name}, {"$inc": {"value": 1}}, upsert=True, return_document=ReturnDocument.AFTER, session=session)["value"]

def event(product_id, action, session):
    collection("audit").insert_one({"_id": next_id("audit", session), "product_id": product_id, "action": action, "at": datetime.now(timezone.utc), "actor": "warehouse"}, session=session)

def transaction(callback):
    with client().start_session() as session:
        return session.with_transaction(callback, read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"), max_commit_time_ms=10000)

@guarded
def get_product(product_id, staff=False):
    query = {"_id": product_id}
    if not staff:
        query["status"] = "published"
    doc = collection("products").find_one(query)
    if doc is None:
        raise HTTPException(404, "Product not found")
    return decode(doc)

@guarded
def list_products(q="", category="", collection="", in_stock=False, sort="featured", page=1, page_size=12, staff=False):
    if collection == "Sugar Smart Pantry":
        collection = "Diabetes-Friendly Picks"
    query = {}
    if not staff:
        query["status"] = "published"
    if q:
        pass  # Relevance ranking below also supports Tamil, Tanglish and typos.
    if category:
        query["category"] = category
    if collection:
        if collection == "Diabetes-Friendly Picks":
            query["$or"] = [{"sugar_smart": True}, {"collection": collection}]
            query["category"] = {"$ne": "Pottery"} if not category else category
        else:
            query["collection"] = collection
    if in_stock:
        query.update({"stock": {"$gt": 0}, "status": "published"})
        query["$and"] = [{"$or": [{"best_before": None}, {"best_before": {"$gte": date.today().isoformat()}}]}]
    products = database()[settings.mongo_collection_prefix + "products"]
    order = {"price-asc": [("price_amount", 1), ("_id", 1)], "price-desc": [("price_amount", -1), ("_id", 1)], "name": [("name", 1), ("_id", 1)]}.get(sort, [("_id", 1)])
    if q:
        from app.search import rank, suggestions
        candidates = list(products.find(query).sort("_id", 1).limit(5000))
        matches = rank(q, candidates)
        names = [p["name"] for p in matches[:5]]
        if sort in ("price-asc", "price-desc"):
            matches.sort(key=lambda p: p["price_amount"].to_decimal(), reverse=sort == "price-desc")
        elif sort == "name":
            matches.sort(key=lambda p: p["name"].casefold())
        return {"items": [decode(doc) for doc in matches[(page-1)*page_size:page*page_size]], "total": len(matches), "page": page, "page_size": page_size, "search_suggestions": names}
    items = list(products.find(query).sort(order).skip((page-1)*page_size).limit(page_size))
    return {"items": [decode(doc) for doc in items], "total": products.count_documents(query), "page": page, "page_size": page_size}

@guarded
def write_product(body, product_id=None, version=None):
    body = ProductWrite.model_validate(body).model_dump(mode="json")
    now = datetime.now(timezone.utc)
    prepared = {**body, "sku_key": body["sku"].casefold(), "price_amount": Decimal128(Decimal(body["price"])), "updated_at": now}
    def commit(session):
        fields = dict(prepared)
        if product_id is None:
            ident = next_id("product", session)
            if not fields["sku"]:
                from app.sku import make_sku
                fields["sku"] = make_sku(fields["category"], ident)
                # An authorized legacy import may already own a future-looking
                # SKU. Skip it instead of permanently blocking the counter.
                while collection("products").find_one({"sku_key": fields["sku"].casefold()}, {"_id": 1}, session=session):
                    ident = next_id("product", session)
                    fields["sku"] = make_sku(fields["category"], ident)
                fields["sku_key"] = fields["sku"].casefold()
            doc = {**fields, "_id": ident, "version": 1, "created_at": now}
            collection("products").insert_one(doc, session=session)
            event(ident, "created", session)
        else:
            ident = product_id
            current = collection("products").find_one({"_id": ident}, session=session)
            if current and fields["sku"] != current["sku"]:
                raise HTTPException(409, "SKU is permanent and cannot be changed after creation")
            doc = collection("products").find_one_and_update({"_id": ident, "version": version}, {"$set": fields, "$inc": {"version": 1}}, return_document=ReturnDocument.AFTER, session=session)
            if doc is None:
                if collection("products").find_one({"_id": ident}, {"_id": 1}, session=session) is None:
                    raise HTTPException(404, "Product not found")
                raise HTTPException(409, "This product changed. Reload before saving again.")
            event(ident, "updated", session)
        return decode(doc)
    return transaction(commit)

@guarded
def delete_product(product_id, version):
    def commit(session):
        doc = collection("products").find_one_and_delete({"_id": product_id, "version": version}, session=session)
        if doc is None:
            if collection("products").find_one({"_id": product_id}, {"_id": 1}, session=session) is None:
                raise HTTPException(404, "Product not found")
            raise HTTPException(409, "This product changed. Reload before deleting.")
        event(product_id, "deleted", session)
    transaction(commit)

@guarded
def list_inventory():
    return [dict(product_id=p["_id"], sku=p["sku"], product_name=p["name"], quantity=p["stock"], location=p["location"], best_before=p.get("best_before")) for p in collection("products").find().sort("_id", 1)]

@guarded
def list_audit():
    return [{"id": p["_id"], "product_id": p["product_id"], "action": p["action"], "at": p["at"].isoformat(), "actor": p.get("actor", "warehouse")} for p in collection("audit").find().sort("_id", -1).limit(100)]

@guarded
def health():
    database().command("ping")
    return {"status": "ok", "storage": "mongodb", "database": "DharmicFoods"}

def close():
    global _client
    if _client is not None:
        _client.close()
        _client = None

@guarded
def get_about():
    page = collection("pages").find_one({"_id": "about-us"}, {"_id": 0})
    if page is None:
        raise HTTPException(404, "About page not configured")
    return page
