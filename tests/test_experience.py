"""Real MongoDB merchandising integration in disposable prefixed collections."""
import io
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock
from uuid import uuid4
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import SecretStr

class ExperienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.core.config import settings
        from app import mongo_repository as db, experience
        from app.main import app
        cls.db,cls.settings,cls.experience=db,settings,experience
        cls.old_prefix=settings.mongo_collection_prefix
        cls.prefix="qa_"+uuid4().hex[:12]+"_"
        cls.live_count=db.database()["products"].count_documents({})
        settings.mongo_collection_prefix=cls.prefix
        cls.context=TestClient(app);cls.api=cls.context.__enter__()
        cls.staff={"X-Warehouse-Key":settings.warehouse_api_key}
        from app.data import seed_products
        for p in seed_products():
            db.write_product({**p,"sugar_smart":p["name"]=="Raw almond kernels"})

    @classmethod
    def tearDownClass(cls):
        for name in cls.db.database().list_collection_names():
            if name.startswith(cls.prefix):cls.db.database().drop_collection(name)
        assert cls.db.database()["products"].count_documents({})==cls.live_count
        cls.context.__exit__(None,None,None)
        cls.settings.mongo_collection_prefix=cls.old_prefix

    def call(self,path,method="GET",body=None,staff=False):
        return self.api.request(method,"/api/v1/"+path,json=body,headers=self.staff if staff else {})

    def test_multilingual_search_typo_and_strict_sku(self):
        for q,expected in [("ராகி","Wholegrain ragi"),("kezhvaragu","Wholegrain ragi"),("badam","Raw almond kernels"),("almnds","Raw almond kernels"),("samai","Unpolished little millet")]:
            result=self.api.get("/api/v1/products",params={"q":q}).json()
            self.assertIn(expected,[p["name"] for p in result["items"]],q)
        self.assertEqual(self.api.get("/api/v1/products",params={"q":"DF-GRM-999999"}).json()["total"],0)
        self.assertEqual(self.api.get("/api/v1/products",params={"q":"low gi"}).json()["total"],0)
        self.assertEqual(self.api.get("/api/v1/products",params={"q":"diabetic"}).json()["items"][0]["name"],"Raw almond kernels")

    def test_homepage_cas_enabled_order_and_validation(self):
        self.assertEqual(self.call("warehouse/homepage").status_code,401)
        body=self.call("warehouse/homepage",staff=True).json()
        self.assertEqual(len(body["slides"]),6)
        first=body["slides"][0]["id"]
        body["slides"][0]["enabled"]=False
        body["slides"]=list(reversed(body["slides"]))
        response=self.call("warehouse/homepage","PUT",body,True)
        self.assertEqual(response.status_code,200,response.text)
        public=self.call("pages/homepage").json()
        self.assertNotIn(first,[s["id"] for s in public["slides"]])
        self.assertEqual(public["slides"][0]["id"],body["slides"][0]["id"])
        self.assertEqual(self.call("warehouse/homepage","PUT",body,True).status_code,409)
        invalid=response.json();invalid["slides"][0]["href"]="//untrusted.example"
        self.assertEqual(self.call("warehouse/homepage","PUT",invalid,True).status_code,422)
        invalid=response.json();invalid["interval_seconds"]=1
        self.assertEqual(self.call("warehouse/homepage","PUT",invalid,True).status_code,422)

    def test_newsletter_consent_deduplication_and_unsubscribe(self):
        email=uuid4().hex+"@example.com"
        self.assertEqual(self.call("newsletter/subscribe","POST",{"email":email,"consent":False}).status_code,422)
        response=self.call("newsletter/subscribe","POST",{"email":email,"consent":True})
        self.assertEqual(response.status_code,200,response.text)
        self.call("newsletter/subscribe","POST",{"email":email,"consent":True})
        self.assertEqual(self.db.collection("newsletter_subscribers").count_documents({"email":email}),1)
        token=self.call("newsletter/subscribe","POST",{"email":email,"consent":True}).json()["unsubscribe_token"]
        self.assertEqual(self.call("newsletter/unsubscribe","POST",{"token":token}).status_code,200)
        self.assertEqual(self.db.collection("newsletter_subscribers").find_one({"email":email})["status"],"unsubscribed")
        self.assertNotEqual(self.db.collection("newsletter_subscribers").find_one({"email":email})["unsubscribe_hash"],token)

    def test_gallery_gi_evidence_pottery_and_file_validation(self):
        from app.data import seed_products
        product={**next(seed_products()),"sku":"","gallery_images":["https://example.com/side.jpg","https://example.com/back.jpg"],"search_aliases":["கம்பு","kambu"]}
        created=self.call("warehouse/products","POST",product,True)
        self.assertEqual(created.status_code,201,created.text)
        self.assertEqual(len(created.json()["gallery_images"]),2)
        self.assertEqual(self.call("warehouse/products","POST",{**product,"glycemic_index":45},True).status_code,422)
        self.assertEqual(self.call("warehouse/products","POST",{**product,"category":"Pottery","sugar_smart":True},True).status_code,422)
        self.assertEqual(self.call("warehouse/products","POST",{**product,"gallery_images":["javascript:alert(1)"]},True).status_code,422)
        self.assertEqual(self.api.post("/api/v1/warehouse/media",files={"file":("bad.svg",b"<svg/>","image/svg+xml")}).status_code,401)
        self.assertEqual(self.api.post("/api/v1/warehouse/media",files={"file":("bad.svg",b"<svg/>","image/svg+xml")},headers=self.staff).status_code,422)
        data=io.BytesIO();Image.new("RGB",(12,12),"white").save(data,format="PNG")
        with tempfile.TemporaryDirectory() as directory,patch.object(self.experience,"UPLOAD_DIR",Path(directory)),patch.object(self.settings,"media_storage","local"):
            result=self.api.post("/api/v1/warehouse/media",files={"file":("test.png",data.getvalue(),"image/png")},headers=self.staff)
            self.assertEqual(result.status_code,201,result.text)
            url=result.json()["url"]
            self.assertRegex(url,r"^/media/[a-f0-9]{32}\.webp$")
            with Image.open(Path(directory)/url.split("/")[-1]) as image:self.assertEqual(image.format,"WEBP")
        service=MagicMock();container=service.__enter__.return_value.get_container_client.return_value
        with patch.object(self.settings,"media_storage","azure"),patch.object(self.settings,"azure_storage_connection_string",SecretStr("test-only")),patch.object(self.settings,"azure_media_public_base_url","https://media.example.com/dharmik"),patch("app.experience.BlobServiceClient.from_connection_string",return_value=service):
            result=self.experience.upload_image(data.getvalue())
            self.assertTrue(result["url"].startswith("https://media.example.com/dharmik/"))
            container.upload_blob.assert_called_once()
            self.assertFalse(container.set_container_access_policy.called)

    def test_staff_dashboard_customer_access_and_daily_totals(self):
        self.assertEqual(self.call("warehouse/customers").status_code,401)
        self.assertEqual(self.call("warehouse/dashboard").status_code,401)
        ident=uuid4().hex
        self.db.collection("users").insert_one({"_id":ident,"google_sub":ident,"name":"Experience QA","email":"qa@example.com","phone":"+919000000000","created_at":datetime.now(timezone.utc)})
        self.db.collection("orders").insert_one({"_id":ident,"user_id":ident,"number":"QA-"+ident,"idempotency_key":ident,"created_at":datetime.now(timezone.utc),"payment_status":"unpaid","total":"123.45"})
        data=self.call("warehouse/dashboard",staff=True)
        self.assertEqual(data.status_code,200,data.text)
        self.assertEqual(len(data.json()["daily"]),7)
        self.assertEqual(data.json()["today_orders"],1)
        self.assertEqual(data.json()["today_bill_value"],"123.45")
        self.assertEqual(data.json()["today_paid_value"],"0")
        customers=self.call("warehouse/customers?q=Experience",staff=True).json()
        self.assertEqual(customers["items"][0]["order_count"],1)
        self.assertNotIn("google_sub",customers["items"][0])

if __name__=="__main__":unittest.main()
