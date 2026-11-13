import secrets
from fastapi import Header, HTTPException
from app.core.config import settings

def require_staff(x_warehouse_key: str = Header(default="")):
    if not settings.warehouse_api_key:
        raise HTTPException(503, "Warehouse access has not been configured")
    if not secrets.compare_digest(x_warehouse_key, settings.warehouse_api_key):
        raise HTTPException(401, "Staff authentication required")
