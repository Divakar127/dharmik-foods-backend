from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app import repository
from app.routers import inventory, products, commerce, experience
from fastapi.staticfiles import StaticFiles
from app.experience import UPLOAD_DIR

@asynccontextmanager
async def lifespan(app):
    repository.initialize()
    if settings.database_backend == "mongodb":
        from app.commerce import initialize
        initialize()
        from app.experience import initialize as initialize_experience
        initialize_experience()
        from app.delivery import initialize as initialize_delivery
        initialize_delivery()
    try:
        yield
    finally:
        repository.close()

app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False, allow_methods=["GET"], allow_headers=["Content-Type"])
app.include_router(products.router, prefix="/api/v1")
app.include_router(inventory.router, prefix="/api/v1")
app.include_router(commerce.router, prefix="/api/v1")
app.include_router(experience.router, prefix="/api/v1")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=UPLOAD_DIR), name="media")

@app.get("/health", tags=["Health"])
def health():
    return repository.health()
