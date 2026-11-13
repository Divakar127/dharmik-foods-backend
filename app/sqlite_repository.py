"""Transactional catalog boundary, reusable by future MCP adapters."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from fastapi import HTTPException
from app.core.config import settings
from app.data import seed_products

@contextmanager
def connection():
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(settings.database_path, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()

def initialize():
    with connection() as db:
        db.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, sku TEXT NOT NULL COLLATE NOCASE UNIQUE, body TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1)")
        db.execute("CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL, action TEXT NOT NULL, at TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        # Seed once, even if an operator later deletes the entire catalog.
        if not db.execute("SELECT 1 FROM metadata WHERE key='seeded'").fetchone():
            for item in seed_products():
                db.execute("INSERT INTO products(sku, body) VALUES (?, ?)", (item["sku"], json.dumps(item)))
            db.execute("INSERT INTO metadata VALUES ('seeded', '1')")

def decode(row):
    item = json.loads(row["body"])
    expired = bool(item["best_before"] and item["best_before"] < date.today().isoformat())
    return {**item, "id": row["id"], "version": row["version"], "currency": "INR", "available": item["stock"] > 0 and not expired and item["status"] == "published"}

def get_product(product_id, staff=False):
    with connection() as db:
        row = db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if not row or (not staff and json.loads(row["body"])["status"] != "published"):
        raise HTTPException(404, "Product not found")
    return decode(row)

def list_products(q="", category="", collection="", in_stock=False, sort="featured", page=1, page_size=12, staff=False):
    if collection == "Sugar Smart Pantry":
        collection = "Diabetes-Friendly Picks"
    with connection() as db:
        items = [decode(row) for row in db.execute("SELECT * FROM products ORDER BY id")]
    if not staff:
        items = [p for p in items if p["status"] == "published"]
    if q:
        from app.search import rank
        items = rank(q, items)
    if category:
        items = [p for p in items if p["category"] == category]
    if collection:
        items = [p for p in items if (p.get("sugar_smart") or p["collection"] == collection) and p["category"] != "Pottery"] if collection == "Diabetes-Friendly Picks" else [p for p in items if p["collection"] == collection]
    if in_stock:
        items = [p for p in items if p["available"]]
    if sort == "price-asc":
        from decimal import Decimal
        items.sort(key=lambda p: Decimal(p["price"]))
    elif sort == "price-desc":
        from decimal import Decimal
        items.sort(key=lambda p: Decimal(p["price"]), reverse=True)
    elif sort == "name":
        items.sort(key=lambda p: p["name"].casefold())
    total = len(items)
    return {"items": items[(page-1)*page_size:page*page_size], "total": total, "page": page, "page_size": page_size}

def write_product(body, product_id=None, version=None):
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            if product_id is None:
                if not body.get("sku"):
                    from app.sku import make_sku
                    sequence = db.execute("SELECT seq FROM sqlite_sequence WHERE name='products'").fetchone()
                    body["sku"] = make_sku(body["category"], (sequence[0] if sequence else 0) + 1)
                cursor = db.execute("INSERT INTO products(sku, body) VALUES (?, ?)", (body["sku"], json.dumps(body)))
                product_id = cursor.lastrowid
                action = "created"
            else:
                row = db.execute("SELECT version, sku FROM products WHERE id=?", (product_id,)).fetchone()
                if not row:
                    raise HTTPException(404, "Product not found")
                if row["version"] != version:
                    raise HTTPException(409, "This product changed. Reload before saving again.")
                if body["sku"] != row["sku"]:
                    raise HTTPException(409, "SKU is permanent and cannot be changed after creation")
                db.execute("UPDATE products SET sku=?, body=?, version=version+1 WHERE id=?", (body["sku"], json.dumps(body), product_id))
                action = "updated"
            db.execute("INSERT INTO audit(product_id, action, at) VALUES (?, ?, ?)", (product_id, action, datetime.now(timezone.utc).isoformat()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "A product with this SKU already exists")
    return get_product(product_id, staff=True)

def delete_product(product_id, version):
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT version FROM products WHERE id=?", (product_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Product not found")
        if row["version"] != version:
            raise HTTPException(409, "This product changed. Reload before deleting.")
        db.execute("DELETE FROM products WHERE id=?", (product_id,))
        db.execute("INSERT INTO audit(product_id, action, at) VALUES (?, 'deleted', ?)", (product_id, datetime.now(timezone.utc).isoformat()))
