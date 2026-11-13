"""Initialize the user's Coimbatore coverage once, preserving later staff changes."""
from app import delivery, repository

def run():
    repository.initialize()
    delivery.initialize()
    current = delivery.settings()
    if current["areas"]:
        print("Delivery areas already configured; preserving warehouse settings.")
        return
    body = delivery.DeliverySettings(**{**current, "enabled": True, "areas": delivery.coimbatore_preset()["areas"]})
    result = delivery.save(body)
    print(f"Enabled {len(result['areas'])} Coimbatore city PIN codes. Manage them in Warehouse > Delivery.")

if __name__ == "__main__":
    try:
        run()
    finally:
        repository.close()
