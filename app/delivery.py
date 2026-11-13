"""Warehouse-managed delivery coverage. No external geolocation or invented areas."""
from fastapi import HTTPException
from pydantic import Field, model_validator
from pymongo import ReturnDocument
from app import mongo_repository as db
from app.experience import Input

class Area(Input):
    pincode: str = Field(pattern=r"^[1-9][0-9]{5}$")
    label: str = Field(min_length=2, max_length=80, pattern=r"^[^,\r\n]+$")
    enabled: bool = True

class DeliverySettings(Input):
    version: int = Field(ge=1)
    enabled: bool = False
    areas: list[Area] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def valid_areas(self):
        if len({a.pincode for a in self.areas}) != len(self.areas):
            raise ValueError("Each PIN code must appear only once")
        if self.enabled and not any(a.enabled for a in self.areas):
            raise ValueError("Add at least one enabled delivery area before enabling delivery")
        return self

def initialize():
    db.collection("pages").update_one({"_id": "delivery"}, {"$setOnInsert": {
        "version": 1, "enabled": False, "areas": []}}, upsert=True)

@db.guarded
def settings():
    return db.collection("pages").find_one({"_id": "delivery"}, {"_id": 0}) or {"version": 1, "enabled": False, "areas": []}

@db.guarded
def save(body: DeliverySettings):
    initialize()
    doc = db.collection("pages").find_one_and_update({"_id": "delivery", "version": body.version}, {
        "$set": body.model_dump(exclude={"version"}), "$inc": {"version": 1}}, return_document=ReturnDocument.AFTER)
    if not doc:
        raise HTTPException(409, "Delivery areas changed. Reload before saving.")
    doc.pop("_id", None)
    return doc

@db.guarded
def check(pincode: str):
    doc = settings()
    area = next((a for a in doc["areas"] if a["pincode"] == pincode and a["enabled"]), None)
    available = bool(doc["enabled"] and area)
    status = "available" if available else "unavailable" if doc["areas"] or doc["enabled"] else "unconfigured"
    return {"pincode": pincode, "available": available, "status": status,
        "area": area["label"] if available else "",
        "message": f"Delivery is available in {area['label']}." if available else
        "We do not deliver to this PIN code yet." if doc["enabled"] else
        "Delivery is temporarily paused. Please check again later." if doc["areas"] else "Delivery areas are not available yet. Please check again later."}


def coimbatore_preset():
    import json
    from pathlib import Path
    return json.loads(Path(__file__).with_name("coimbatore_delivery.json").read_text())
