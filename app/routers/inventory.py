from fastapi import APIRouter, Depends
from app import repository
from app.security import require_staff
router = APIRouter(prefix="/inventory", tags=["Warehouse"], dependencies=[Depends(require_staff)])

@router.get("")
def inventory():
    return repository.list_inventory()
