"""Real MongoDB integration tests, isolated to a disposable qa_<random>_ prefix.

Google identity verification is mocked only inside tests. The application has
no test-login endpoint or production authentication bypass.
"""
import secrets
import unittest
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch
from uuid import uuid4
from fastapi.testclient import TestClient
from pydantic import SecretStr

class CommerceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.core.config import settings
        from app import mongo_repository as db, commerce
        from app.main import app
        cls.settings, cls.db, cls.commerce = settings, db, commerce
        cls.prefix = "qa_" + uuid4().hex[:12] + "_"
        cls.original = (settings.mongo_collection_prefix, settings.google_client_id, settings.google_client_secret)
        cls.live_count = db.database()["products"].count_documents({})
        settings.mongo_collection_prefix = cls.prefix
        settings.google_client_id = "test-client.apps.googleusercontent.com"
        settings.google_client_secret = SecretStr("test-only-secret")
        cls.context = TestClient(app)
        cls.api = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls):
        # Drop only collections created by this test run, inside DharmicFoods.
        for name in cls.db.database().list_collection_names():
            if name.startswith(cls.prefix):
                cls.db.database().drop_collection(name)
        assert cls.db.database()["products"].count_documents({}) == cls.live_count
        cls.context.__exit__(None, None, None)
        cls.settings.mongo_collection_prefix, cls.settings.google_client_id, cls.settings.google_client_secret = cls.original

    def setUp(self):
        from app.data import seed_products
        self.product = self.db.write_product({**next(seed_products()), "sku": "", "stock": 8})
        self.guest = {"X-Cart-Token": secrets.token_urlsafe(32)}

    def call(self, path, method="GET", body=None, headers=None):
        return self.api.request(method, "/api/v1/" + path, json=body, headers=headers or {})

    def login(self, sub=None, guest=""):
        sub = sub or uuid4().hex
        start = self.call("auth/google/start", "POST").json()
        claims = {"sub": sub, "email": f"{sub}@example.com", "name": "QA Customer"}
        with patch("app.commerce.verify_google", return_value=claims):
            result = self.call("auth/google/callback", "POST", {"state": start["state"], "code": "test-code", "guest_token": guest})
        self.assertEqual(result.status_code, 200, result.text)
        token = result.json()["token"]
        self.assertIsNone(self.db.collection("customer_sessions").find_one({"_id": token}))
        return {"Authorization": "Bearer " + token}, result.json()["user"], start

    def add(self, headers=None, quantity=2):
        headers = headers or self.guest
        cart = self.call("cart", headers=headers).json()
        response = self.call("cart/items", "PUT", {"product_id": self.product["id"], "quantity": quantity, "version": cart["version"]}, headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def order_body(self, cart):
        return {"address": {"recipient": "QA Customer", "line1": "123 Test Street", "city": "Chennai", "state": "Tamil Nadu", "postal_code": "600001"},
            "cart_version": cart["version"], "quote_token": cart["quote_token"], "idempotency_key": uuid4().hex, "acknowledge_unpaid": True}

    def test_guest_cart_persistence_versions_and_stock(self):
        self.assertEqual(self.call("cart").status_code, 400)
        cart = self.add()
        self.assertEqual(cart["total"], str(Decimal(self.product["price"]) * 2))
        self.assertEqual(self.call("cart", headers=self.guest).json()["item_count"], 2)
        for quantity, version, status in [(3, 0, 409), (9, cart["version"], 409), (-1, cart["version"], 422)]:
            result = self.call("cart/items", "PUT", {"product_id": self.product["id"], "quantity": quantity, "version": version}, self.guest)
            self.assertEqual(result.status_code, status)
        self.assertEqual(self.call("cart", headers={"X-Cart-Token": secrets.token_urlsafe(32)}).json()["items"], [])
        self.add(quantity=0)
        self.assertFalse(self.call("cart", headers=self.guest).json()["can_checkout"])

    def test_google_state_merge_revocation_and_phone(self):
        self.add()
        headers, user, start = self.login(guest=self.guest["X-Cart-Token"])
        self.assertEqual(self.call("cart", headers=headers).json()["item_count"], 2)
        self.assertEqual(self.call("cart", headers=self.guest).json()["items"], [])
        replay = self.call("auth/google/callback", "POST", {"state": start["state"], "code": "test-code"})
        self.assertEqual(replay.status_code, 401)
        self.assertFalse(user["profile_complete"])
        self.assertEqual(self.call("auth/me", "PATCH", {"name": "Test", "phone": "123"}, headers).status_code, 422)
        profile = self.call("auth/me", "PATCH", {"name": "Customer Name", "phone": "+91 98765 43210"}, headers)
        self.assertEqual(profile.json()["phone"], "+919876543210")
        self.assertFalse(profile.json()["phone_verified"])
        token_hash = self.commerce.digest(headers["Authorization"].removeprefix("Bearer "))
        self.db.collection("customer_sessions").update_one({"_id": token_hash}, {"$set": {"expires_at": self.commerce.now() - timedelta(seconds=1)}})
        self.assertEqual(self.call("auth/me", headers=headers).status_code, 401)
        headers, _, _ = self.login()
        self.assertEqual(self.call("auth/logout", "POST", headers=headers).status_code, 204)
        self.assertEqual(self.call("auth/me", headers=headers).status_code, 401)

    def test_order_prices_idempotency_ownership_and_immutable_snapshot(self):
        headers, _, _ = self.login()
        cart = self.add(headers)
        body = self.order_body(cart)
        self.assertEqual(self.call("orders", "POST", body).status_code, 401)
        self.assertEqual(self.call("orders", "POST", body, headers).status_code, 422)
        self.call("auth/me", "PATCH", {"name": "Customer Name", "phone": "+919876543210"}, headers)
        self.assertEqual(self.call("orders", "POST", {**body, "total": "0.01"}, headers).status_code, 422)
        self.assertEqual(self.call("orders", "POST", {**body, "acknowledge_unpaid": False}, headers).status_code, 422)
        # Warehouse price changes must require the customer to review a fresh quote.
        from app.schemas import ProductWrite
        product_body = {k: self.product[k] for k in ProductWrite.model_fields}
        self.db.write_product({**product_body, "price": "199.00"}, self.product["id"], self.product["version"])
        self.assertEqual(self.call("orders", "POST", body, headers).status_code, 409)
        cart = self.call("cart", headers=headers).json()
        body = self.order_body(cart)
        response = self.call("orders", "POST", body, headers)
        self.assertEqual(response.status_code, 201, response.text)
        order = response.json()
        self.assertEqual(order["total"], "398.00")
        self.assertEqual(order["payment_status"], "unpaid")
        self.assertEqual(order["fulfillment_status"], "on_hold")
        self.assertFalse(order["inventory_reserved"])
        self.assertEqual(self.db.get_product(self.product["id"])["stock"], 8)
        self.assertEqual(self.call("orders", "POST", body, headers).json()["id"], order["id"])
        self.assertEqual(self.call("cart", headers=headers).json()["items"], [])
        other, _, _ = self.login()
        self.assertEqual(self.call("orders/" + order["id"], headers=other).status_code, 404)
        self.assertEqual(self.call("orders", headers=other).json(), [])
        self.call("auth/me", "PATCH", {"name": "Changed Name", "phone": "+919111111111"}, headers)
        self.db.delete_product(self.product["id"], self.db.get_product(self.product["id"])["version"])
        saved = self.call("orders/" + order["id"], headers=headers).json()
        self.assertEqual(saved["customer"]["name"], "Customer Name")
        self.assertEqual(saved["items"][0]["sku"], self.product["sku"])
        self.assertEqual(saved["total"], "398.00")
        self.assertEqual(self.call("warehouse/orders").status_code, 401)

    def test_unavailable_items_and_automatic_immutable_sku(self):
        self.assertRegex(self.product["sku"], r"^DF-GRM-\d{6}$")
        from app.schemas import ProductWrite
        body = {k: self.product[k] for k in ProductWrite.model_fields}
        with self.assertRaisesRegex(Exception, "SKU is permanent"):
            self.db.write_product({**body, "sku": "DF-GRM-999999"}, self.product["id"], self.product["version"])
        self.add()
        self.db.delete_product(self.product["id"], self.product["version"])
        cart = self.call("cart", headers=self.guest).json()
        self.assertFalse(cart["can_checkout"])
        self.assertEqual(len(cart["issues"]), 1)
        self.add(quantity=0)

    def test_invalid_google_claims_rejected(self):
        saved = {"nonce": "expected", "verifier": "test-verifier"}
        response = Mock()
        response.json.return_value = {"id_token": "test-token"}
        with patch("app.commerce.requests.post", return_value=response), patch("app.commerce.id_token.verify_oauth2_token", return_value={"nonce": "wrong", "email_verified": True, "sub": "test", "email": "test@example.com"}):
            with self.assertRaisesRegex(Exception, "could not be verified"):
                self.commerce.verify_google("code", saved)

    def test_automatic_sku_skips_identifier_reserved_by_import(self):
        from app.schemas import ProductWrite
        body = {k: self.product[k] for k in ProductWrite.model_fields}
        reserved = f"DF-GRM-{self.product['id'] + 2:06d}"
        self.db.write_product({**body, "sku": reserved})
        automatic = self.db.write_product({**body, "sku": ""})
        self.assertNotEqual(automatic["sku"], reserved)
        self.assertEqual(automatic["sku"], f"DF-GRM-{automatic['id']:06d}")

if __name__ == "__main__":
    unittest.main()
