"""Black-box API regression tests using a disposable SQLite database."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import sysconfig
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.database = str(Path(cls.temp.name) / "catalog.sqlite3")
        cls.key = "test-warehouse-key-at-least-32-characters"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0)); cls.port = sock.getsockname()[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.start()

    @classmethod
    def start(cls):
        env = {**os.environ, "DATABASE_BACKEND": "sqlite", "DATABASE_PATH": cls.database, "WAREHOUSE_API_KEY": cls.key}
        # Windows virtualenv launchers may spawn a child process that outlives
        # terminate(). Start the base interpreter directly with the same packages.
        executable = sys.executable
        if os.name == "nt":
            executable = str(Path(sys.base_prefix) / "python.exe")
            env["PYTHONPATH"] = os.pathsep.join([sysconfig.get_path("purelib"), env.get("PYTHONPATH", "")])
        cls.process = subprocess.Popen([executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(cls.port)], cwd=Path(__file__).resolve().parents[1], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                if urlopen(cls.base + "/health", timeout=1).status == 200: return
            except OSError: time.sleep(.1)
        cls.process.terminate()
        raise RuntimeError("Test API did not start")

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate(); cls.process.wait(timeout=10); cls.temp.cleanup()

    def call(self, path, method="GET", body=None, staff=False):
        headers = {"Content-Type": "application/json"}
        if staff: headers["X-Warehouse-Key"] = self.key
        request = Request(self.base + "/api/v1" + path, method=method, headers=headers, data=json.dumps(body).encode() if body is not None else None)
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read()) if response.status != 204 else None
        except HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def product(self, sku="DF-GRM-900001"):
        return dict(sku=sku, name="Test food", description="Food for the regression test.", price="120.50", category="Grains & millets", collection="Balanced eating", pack_size="500 g", ingredients="Oats", allergens="Contains oats", storage="Cool and dry", origin="India", stock=4)

    def test_seed_and_public_boundary(self):
        status, data = self.call("/products")
        self.assertEqual(status, 200); self.assertEqual(data["total"], 8)
        self.assertEqual(self.call("/warehouse/products")[0], 401)
        self.assertEqual(self.call("/warehouse/products", "POST", self.product())[0], 401)
        self.assertEqual(self.call("/warehouse/products/1", "PUT", {**self.product(), "version": 1})[0], 401)
        self.assertEqual(self.call("/warehouse/products/1?version=1", "DELETE")[0], 401)
        self.assertEqual(self.call("/inventory")[0], 401)
        self.assertEqual(self.call("/products", "POST", self.product())[0], 405)
        self.assertEqual(self.call("/products/999999")[0], 404)

    def test_full_lifecycle_visibility_conflicts_and_persistence(self):
        body = self.product()
        status, created = self.call("/warehouse/products", "POST", body, True)
        self.assertEqual(status, 201)
        ident = created["id"]
        self.assertEqual(self.call(f"/products/{ident}")[0], 404)
        self.assertEqual(self.call(f"/warehouse/products/{ident}", staff=True)[0], 200)
        self.assertEqual(self.call("/warehouse/products", "POST", self.product("df-grm-900001"), True)[0], 409)
        changed = {**body, "status": "published", "version": created["version"]}
        status, published = self.call(f"/warehouse/products/{ident}", "PUT", changed, True)
        self.assertEqual(status, 200); self.assertEqual(published["version"], 2)
        self.assertEqual(self.call(f"/products/{ident}")[1]["price"], "120.50")
        self.assertEqual(self.call(f"/warehouse/products/{ident}", "PUT", changed, True)[0], 409)
        self.assertEqual(self.call(f"/warehouse/products/{ident}?version=1", "DELETE", staff=True)[0], 409)
        # A restart must preserve the edited catalog.
        self.process.terminate(); self.process.wait(timeout=10); self.start()
        self.assertEqual(self.call(f"/products/{ident}")[1]["version"], 2)
        self.assertEqual(self.call(f"/warehouse/products/{ident}?version=2", "DELETE", staff=True)[0], 204)
        self.assertEqual(self.call(f"/products/{ident}")[0], 404)
        audit = self.call("/warehouse/audit", staff=True)[1]
        self.assertEqual([a["action"] for a in audit if a["product_id"] == ident], ["deleted", "updated", "created"])

    def test_validation(self):
        for change in ({"stock": -1}, {"price": "-2"}, {"price": "12.345"}, {"name": " "}, {"image_url": "javascript:alert(1)"}, {"category": "Pets"}, {"protein_g": "60", "fibre_g": "50"}, {"best_before": "invalid"}, {"unknown": True}):
            with self.subTest(change=change):
                self.assertEqual(self.call("/warehouse/products", "POST", {**self.product(), **change}, True)[0], 422)
        self.assertEqual(self.call("/products?page=0")[0], 422)
        self.assertEqual(self.call("/products?page_size=101")[0], 422)

    def test_expiry_search_sort_and_pagination(self):
        body = {**self.product("DF-GRM-900002"), "best_before": "2020-01-01", "status": "published"}
        status, product = self.call("/warehouse/products", "POST", body, True)
        self.assertEqual(status, 201); self.assertFalse(product["available"])
        self.assertEqual(self.call("/products?q=DF-GRM-900002&in_stock=true")[1]["total"], 0)
        data = self.call("/products?q=almond")[1]; self.assertEqual(data["total"], 1)
        data = self.call("/products?sort=price-asc&page_size=2")[1]
        self.assertEqual(len(data["items"]), 2)
        self.assertLessEqual(float(data["items"][0]["price"]), float(data["items"][1]["price"]))
        self.assertEqual(self.call("/products?page=999")[1]["items"], [])
        self.call(f"/warehouse/products/{product['id']}?version=1", "DELETE", staff=True)

    def test_z_deleted_catalog_stays_empty(self):
        products = self.call("/warehouse/products?page_size=100", staff=True)[1]["items"]
        for product in products:
            self.assertEqual(self.call(f"/warehouse/products/{product['id']}?version={product['version']}", "DELETE", staff=True)[0], 204)
        self.process.terminate(); self.process.wait(timeout=10); self.start()
        self.assertEqual(self.call("/products")[1]["total"], 0)

if __name__ == "__main__": unittest.main()
