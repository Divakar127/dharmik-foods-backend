import unittest
from uuid import uuid4
from fastapi.testclient import TestClient

class DeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.core.config import settings
        from app import mongo_repository as db
        from app.main import app
        cls.db,cls.settings=db,settings
        cls.old_prefix=settings.mongo_collection_prefix
        cls.prefix="qa_"+uuid4().hex[:12]+"_"
        settings.mongo_collection_prefix=cls.prefix
        cls.context=TestClient(app);cls.api=cls.context.__enter__()
        cls.staff={"X-Warehouse-Key":settings.warehouse_api_key}

    @classmethod
    def tearDownClass(cls):
        for name in cls.db.database().list_collection_names():
            if name.startswith(cls.prefix):cls.db.database().drop_collection(name)
        cls.context.__exit__(None,None,None)
        cls.settings.mongo_collection_prefix=cls.old_prefix

    def test_coverage_permissions_validation_and_conflicts(self):
        base="/api/v1/"
        self.assertEqual(self.api.get(base+"warehouse/delivery").status_code,401)
        self.assertEqual(self.api.put(base+"warehouse/delivery",json={}).status_code,401)
        self.assertEqual(self.api.get(base+"delivery/check?pincode=641").status_code,422)
        self.assertEqual(self.api.get(base+"delivery/check?pincode=000000").status_code,422)
        self.assertFalse(self.api.get(base+"delivery/check?pincode=641001").json()["available"])
        body=self.api.get(base+"warehouse/delivery",headers=self.staff).json()
        body.update(enabled=True,areas=[{"pincode":"641001","label":"Coimbatore","enabled":True},{"pincode":"641002","label":"RS Puram","enabled":False}])
        saved=self.api.put(base+"warehouse/delivery",headers=self.staff,json=body)
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertTrue(self.api.get(base+"delivery/check?pincode=641001").json()["available"])
        for code in ["641002","600001","641601"]:
            self.assertFalse(self.api.get(base+"delivery/check?pincode="+code).json()["available"])
        self.assertEqual(self.api.put(base+"warehouse/delivery",headers=self.staff,json=body).status_code,409)
        duplicate=saved.json();duplicate["areas"].append(duplicate["areas"][0])
        self.assertEqual(self.api.put(base+"warehouse/delivery",headers=self.staff,json=duplicate).status_code,422)
        from app import commerce
        from app.routers.commerce import OrderCreate
        from fastapi import HTTPException
        order=OrderCreate(address={"recipient":"Test buyer","line1":"Test delivery address","city":"Chennai","state":"Tamil Nadu","postal_code":"600001"},cart_version=1,quote_token="0"*64,idempotency_key="delivery-test-"+uuid4().hex,acknowledge_unpaid=True)
        with self.assertRaises(HTTPException) as blocked:
            commerce.create_order({"_id":uuid4().hex,"phone":"9999999999"},order)
        self.assertEqual(blocked.exception.status_code,422)
        self.assertIn("Delivery is not available",blocked.exception.detail)

    def test_banner_dimensions_and_preset(self):
        from app.experience import Homepage, default_homepage
        from pydantic import ValidationError
        model=Homepage(**default_homepage())
        self.assertEqual((model.banner_width,model.banner_height),(1500,536))
        with self.assertRaises(ValidationError):Homepage(**{**default_homepage(),"banner_width":0})
        preset=self.api.get("/api/v1/warehouse/delivery/preset",headers=self.staff).json()
        codes={a["pincode"] for a in preset["areas"]}
        self.assertIn("641035",codes)
        self.assertNotIn("641601",codes)
        self.assertEqual(len(codes),len(preset["areas"]))
