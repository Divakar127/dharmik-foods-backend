# Dharmik Foods backend

Independent FastAPI service for the customer storefront and staff warehouse. MongoDB storage is restricted to the **DharmicFoods** database; the database embedded in the connection URI is ignored. No frontend checkout is required to run this service.

## Setup

Requires Python 3.10+ and MongoDB Atlas or a replica set supporting transactions. From this repository:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Configure `MONGODB_URI` privately in `.env`. Keep `DATABASE_NAME=DharmicFoods` and `DATABASE_BACKEND=mongodb`. Generate a staff key locally:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Set that value as `WAREHOUSE_API_KEY` in this service's `.env` and the warehouse application's `.env.local`. Keep secrets out of source control and logs. On macOS/Linux, replace `.venv/Scripts/python.exe` with `.venv/bin/python`.

```powershell
.venv/Scripts/python.exe -m app.seed
.venv/Scripts/python.exe -m app.seed_experience
.venv/Scripts/python.exe -m app.seed_delivery
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The explicit seeds populate missing sample products and initial Coimbatore delivery coverage. They preserve existing edits and configured delivery settings. Sample product metadata and prices require business review before sale. Review coverage in warehouse before accepting real orders.

- Health: http://localhost:8000/health
- Interactive API specification: http://localhost:8000/docs
- OpenAPI JSON: http://localhost:8000/openapi.json

## APIs and persistence

Public catalog endpoints expose published products, categories, search suggestions, About Us, homepage campaigns and delivery checks. Staff endpoints under `/api/v1/warehouse` require `X-Warehouse-Key` and provide product CRUD, audit, customers, orders, dashboard, merchandising and delivery controls. Use the OpenAPI specification for request schemas and routes.

MongoDB stores products, SKU counters, metadata, audit history, media, pages, users, sessions, OAuth state, carts, orders and newsletter subscriptions. Product and order operations use transactional updates, decimal prices, version checks and server-side validation. Customer APIs use separate session/cart tokens; warehouse credentials never belong in the storefront.

## Configuration

See `.env.example`. For deployed services set `CORS_ORIGINS` to the storefront and warehouse origins, use HTTPS, and run without `--reload`. Google OAuth requires `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `GOOGLE_REDIRECT_URI` matching the storefront callback. Phone numbers are collected; SMS verification is not implemented.

Local uploads use `storage/uploads` and require persistent storage in deployment. For Azure set `MEDIA_STORAGE=azure`, `AZURE_STORAGE_CONNECTION_STRING`, `AZURE_MEDIA_CONTAINER` and `AZURE_MEDIA_PUBLIC_BASE_URL`. Use a public HTTPS delivery URL without SAS credentials; provision the container's public delivery permissions separately. Runtime uploads, database files and local secrets are intentionally ignored by Git.

Billing creates unpaid orders. Payments, stock reservation, dispatch, multi-tenant isolation and MCP integration remain future work.

## Verification

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m unittest discover -s tests -p test_catalog.py
.venv/Scripts/python.exe -m unittest discover -s tests
```

Catalog tests use disposable SQLite storage and need no database credentials. The full suite also needs MongoDB and uses disposable `qa_<random>_` collections inside DharmicFoods, cleaning up afterward. GitHub Actions runs the offline catalog suite without secrets.

Companion repositories: [Storefront](https://github.com/Divakar127/dharmik-foods-storefront), [Warehouse](https://github.com/Divakar127/dharmik-foods-warehouse). Each has its own install, build and environment setup.
