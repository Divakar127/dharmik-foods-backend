"""Storage interface shared by public catalog and protected warehouse APIs.

MongoDB is the application default. SQLite is explicitly selected for offline
regression tests; a MongoDB failure never silently switches storage engines.
"""
from app.core.config import settings

if settings.database_backend == "sqlite":
    from app.sqlite_repository import initialize, get_product, list_products, write_product, delete_product
    from app import sqlite_repository as adapter

    def list_inventory():
        with adapter.connection() as db:
            return [dict(product_id=p["id"], sku=p["sku"], product_name=p["name"], quantity=p["stock"], location=p["location"], best_before=p["best_before"]) for p in (adapter.decode(row) for row in db.execute("SELECT * FROM products"))]

    def list_audit():
        with adapter.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 100")]

    def health():
        with adapter.connection() as db:
            db.execute("SELECT 1")
        return {"status": "ok", "storage": "sqlite"}

    def get_about():
        import json
        from pathlib import Path
        return json.loads((Path(__file__).parent / "about_content.json").read_text(encoding="utf-8"))

    def close():
        pass
else:
    from app.mongo_repository import initialize, get_product, list_products, write_product, delete_product, list_inventory, list_audit, health, close, get_about
