from fastapi import APIRouter, Depends, Query, UploadFile, HTTPException
from app import experience, repository, delivery
from app.core.config import settings
from app.security import require_staff

def mongo_only():
    if settings.database_backend != "mongodb":
        raise HTTPException(503, "Store experience services require MongoDB")

router = APIRouter(tags=["Store experience"], dependencies=[Depends(mongo_only)])

@router.get("/delivery/check")
def check_delivery(pincode: str = Query(pattern=r"^[1-9][0-9]{5}$")):
    return delivery.check(pincode)

@router.get("/pages/homepage")
def homepage():
    return experience.homepage()

@router.get("/search/suggestions")
def suggestions(q: str = Query(default="", max_length=120)):
    if len(q.strip()) < 2:
        return {"items": [], "suggestions": []}
    page = repository.list_products(q=q, page_size=6)
    return {"items": [{"id": p["id"], "name": p["name"], "image_url": p["image_url"], "sku": p["sku"]} for p in page["items"]], "suggestions": [p["name"] for p in page["items"][:5]]}

@router.post("/newsletter/subscribe")
def subscribe(body: experience.Subscription):
    return experience.subscribe(body)

@router.post("/newsletter/unsubscribe")
def unsubscribe(body: experience.Unsubscribe):
    return experience.unsubscribe(body)

staff = APIRouter(prefix="/warehouse", dependencies=[Depends(require_staff)])

@staff.get("/delivery")
def delivery_settings():
    return delivery.settings()

@staff.get("/delivery/preset")
def delivery_preset():
    return delivery.coimbatore_preset()

@staff.put("/delivery")
def save_delivery(body: delivery.DeliverySettings):
    return delivery.save(body)

@staff.get("/homepage")
def staff_homepage():
    return experience.homepage(staff=True)

@staff.put("/homepage")
def save_homepage(body: experience.Homepage):
    return experience.save_homepage(body)

@staff.get("/dashboard")
def dashboard():
    return experience.dashboard()

@staff.get("/customers")
def customers(q: str = Query(default="", max_length=120), page: int = Query(default=1, ge=1)):
    return experience.customers(q, page)

@staff.get("/media/config")
def media_config():
    return {"storage": settings.media_storage, "max_bytes": experience.MAX_UPLOAD, "azure_configured": bool(settings.azure_storage_connection_string.get_secret_value() and settings.azure_media_public_base_url)}

@staff.post("/media", status_code=201)
async def upload(file: UploadFile):
    try:
        data = await file.read(experience.MAX_UPLOAD + 1)
        # Image decoding and Azure network I/O run off the event loop.
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(experience.upload_image, data)
    finally:
        await file.close()

router.include_router(staff)
