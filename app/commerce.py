"""Customer identity, durable carts and immutable, unpaid billing snapshots.

All collections use the same isolated DharmicFoods database as the catalog.
No payment is collected, no stock is reserved and nothing is dispatched here.
"""
import base64
import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlencode
from uuid import uuid4

import requests
from fastapi import HTTPException
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from google.auth.exceptions import GoogleAuthError
from pymongo import ReturnDocument
from app.core.config import settings
from app import mongo_repository as db

def now():
    return datetime.now(timezone.utc)

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def initialize():
    db.collection("users").create_index("google_sub", unique=True)
    db.collection("users").create_index("email")
    db.collection("customer_sessions").create_index("expires_at", expireAfterSeconds=0)
    db.collection("customer_sessions").create_index("user_id")
    db.collection("oauth_states").create_index("expires_at", expireAfterSeconds=0)
    db.collection("carts").create_index("expires_at", expireAfterSeconds=0)
    db.collection("orders").create_index([("user_id", 1), ("idempotency_key", 1)], unique=True)
    db.collection("orders").create_index([("user_id", 1), ("created_at", -1)])
    db.collection("orders").create_index("number", unique=True)
    db.collection("auth_limits").create_index("expires_at", expireAfterSeconds=0)

@db.guarded
def limit_auth(client_address):
    # Fixed ten-minute window, shared by backend workers. Do not trust forwarded
    # IP headers unless a trusted reverse proxy is configured at deployment.
    window = int(now().timestamp()) // 600
    key = digest(f"{client_address}:{window}")
    record = db.collection("auth_limits").find_one_and_update({"_id": key}, {
        "$inc": {"count": 1}, "$setOnInsert": {"expires_at": now() + timedelta(minutes=20)}},
        upsert=True, return_document=ReturnDocument.AFTER)
    if record["count"] > 30:
        raise HTTPException(429, "Too many sign-in attempts. Please try again in ten minutes.")

def google_configured():
    return bool(settings.google_client_id and settings.google_client_secret.get_secret_value())

@db.guarded
def google_start():
    if not google_configured():
        raise HTTPException(503, "Google sign-in needs GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env")
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    db.collection("oauth_states").insert_one({"_id": digest(state), "nonce": nonce, "verifier": verifier, "expires_at": now() + timedelta(minutes=10)})
    query = urlencode({"client_id": settings.google_client_id, "redirect_uri": settings.google_redirect_uri,
        "response_type": "code", "scope": "openid email profile", "state": state, "nonce": nonce,
        "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account"})
    return {"url": "https://accounts.google.com/o/oauth2/v2/auth?" + query, "state": state}

def verify_google(code, saved):
    try:
        response = requests.post("https://oauth2.googleapis.com/token", data={"client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret.get_secret_value(), "code": code,
            "code_verifier": saved["verifier"], "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code"}, timeout=10)
        response.raise_for_status()
        transport = GoogleRequest()
        def limited_request(*args, **kwargs):
            kwargs["timeout"] = 10
            return transport(*args, **kwargs)
        claims = id_token.verify_oauth2_token(response.json()["id_token"], limited_request, settings.google_client_id)
        if claims.get("nonce") != saved["nonce"] or claims.get("email_verified") is not True or not claims.get("sub") or not claims.get("email"):
            raise ValueError("Invalid identity claims")
        return claims
    except (requests.RequestException, GoogleAuthError, ValueError, KeyError):
        raise HTTPException(401, "Google sign-in could not be verified. Please try signing in again.") from None

def public_user(user):
    return {"id": user["_id"], "name": user["name"], "email": user["email"], "email_verified": True,
        "phone": user.get("phone", ""), "phone_verified": False, "profile_complete": bool(user.get("phone")),
        "created_at": user["created_at"].isoformat()}

@db.guarded
def google_finish(state, code, guest_token=""):
    if not google_configured():
        raise HTTPException(503, "Google sign-in is not configured")
    saved = db.collection("oauth_states").find_one_and_delete({"_id": digest(state), "expires_at": {"$gt": now()}})
    if not saved:
        raise HTTPException(401, "Sign-in expired or was already used. Please try again.")
    claims = verify_google(code, saved)
    user = db.collection("users").find_one_and_update({"google_sub": claims["sub"]}, {
        "$setOnInsert": {"_id": uuid4().hex, "created_at": now(), "phone": "", "phone_verified": False},
        "$set": {"name": str(claims.get("name", "Customer"))[:120], "email": claims["email"].lower(), "email_verified": True,
            "last_login_at": now(), "updated_at": now(), "identity_provider": "google"}}, upsert=True, return_document=ReturnDocument.AFTER)
    token = secrets.token_urlsafe(32)
    db.collection("customer_sessions").insert_one({"_id": digest(token), "user_id": user["_id"], "created_at": now(), "expires_at": now() + timedelta(days=7)})
    if valid_token(guest_token):
        merge_guest(user, guest_token)
    return {"token": token, "user": public_user(user)}

def valid_token(value):
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{43,128}", value or ""))

@db.guarded
def user_for(token, required=True):
    session = db.collection("customer_sessions").find_one({"_id": digest(token), "expires_at": {"$gt": now()}}) if valid_token(token) else None
    user = db.collection("users").find_one({"_id": session["user_id"]}) if session else None
    if required and not user:
        raise HTTPException(401, "Please sign in with Google to continue")
    return user

@db.guarded
def logout(token):
    db.collection("customer_sessions").delete_one({"_id": digest(token)})

@db.guarded
def update_profile(user, body):
    doc = db.collection("users").find_one_and_update({"_id": user["_id"]}, {"$set": {"name": body.name, "phone": body.phone,
        "phone_verified": False, "updated_at": now()}}, return_document=ReturnDocument.AFTER)
    return public_user(doc)

def cart_key(user, guest_token):
    if user:
        return "user:" + user["_id"]
    if not valid_token(guest_token):
        raise HTTPException(400, "A valid cart token is required")
    return "guest:" + digest(guest_token)

def empty_cart(key):
    return {"_id": key, "items": [], "version": 0}

def load_cart(key, session=None):
    doc = db.collection("carts").find_one({"_id": key}, session=session)
    return doc if doc and (not doc.get("expires_at") or doc["expires_at"] > now()) else empty_cart(key)

def save_cart(cart, session):
    cart["version"] += 1
    cart["updated_at"] = now()
    cart["expires_at"] = now() + timedelta(days=30)
    db.collection("carts").replace_one({"_id": cart["_id"]}, cart, upsert=True, session=session)

def merge_guest(user, guest_token):
    def commit(session):
        guest_key = cart_key(None, guest_token)
        guest, target = load_cart(guest_key, session), load_cart(cart_key(user, ""), session)
        quantities = {i["product_id"]: i["quantity"] for i in target["items"]}
        for item in guest["items"]:
            quantities[item["product_id"]] = min(99, quantities.get(item["product_id"], 0) + item["quantity"])
        if len(quantities) > 50:
            raise HTTPException(409, "Your combined cart exceeds 50 different products. Remove some items and try again.")
        target["items"] = [{"product_id": k, "quantity": v} for k, v in quantities.items()]
        save_cart(target, session)
        db.collection("carts").delete_one({"_id": guest_key}, session=session)
    db.transaction(commit)

def amount(value):
    return str(Decimal(value).quantize(Decimal("0.01")))

def quote(cart, session=None):
    lines, issues, subtotal = [], [], Decimal("0")
    fingerprints = []
    for item in cart["items"]:
        doc = db.collection("products").find_one({"_id": item["product_id"]}, session=session)
        if not doc or doc["status"] != "published":
            lines.append({**item, "name": "Product no longer available", "sku": "", "pack_size": "", "image_url": "",
                "unit_price": "0.00", "line_total": "0.00", "stock": 0, "available": False})
            issues.append(f"Remove unavailable product #{item['product_id']} from your cart.")
            fingerprints.append([item["product_id"], item["quantity"], None])
            continue
        product = db.decode(doc)
        total = Decimal(product["price"]) * item["quantity"]
        subtotal += total
        lines.append({**item, "name": product["name"], "sku": product["sku"], "pack_size": product["pack_size"],
            "image_url": product["image_url"], "unit_price": amount(product["price"]), "line_total": amount(total),
            "stock": product["stock"], "available": product["available"] and product["stock"] >= item["quantity"]})
        if not product["available"] or product["stock"] < item["quantity"]:
            issues.append(f"{product['name']}: only {product['stock'] if product['available'] else 0} units available.")
        fingerprints.append([product["id"], item["quantity"], product["version"], product["price"], product["stock"], product["available"]])
    return {"items": lines, "version": cart["version"], "item_count": sum(i["quantity"] for i in cart["items"]),
        "currency": "INR", "subtotal": amount(subtotal), "shipping": "0.00", "total": amount(subtotal),
        "issues": issues, "can_checkout": bool(lines) and not issues,
        "quote_token": digest(json.dumps([cart["version"], fingerprints], sort_keys=True)),
        "billing_note": "Unpaid order summary. Shipping is free for this working model. Stock is not reserved until payment is enabled."}

@db.guarded
def get_cart(user, token):
    return quote(load_cart(cart_key(user, token)))

@db.guarded
def set_cart_item(user, token, body):
    key = cart_key(user, token)
    def commit(session):
        cart = load_cart(key, session)
        if cart["version"] != body.version:
            raise HTTPException(409, "Your cart changed in another tab. Refresh it and try again.")
        if body.quantity:
            product = db.collection("products").find_one({"_id": body.product_id, "status": "published"}, session=session)
            if not product or not db.decode(product)["available"] or product["stock"] < body.quantity:
                raise HTTPException(409, "This quantity is no longer available. Refresh your cart.")
        items = [i for i in cart["items"] if i["product_id"] != body.product_id]
        if body.quantity:
            items.append({"product_id": body.product_id, "quantity": body.quantity})
        if len(items) > 50:
            raise HTTPException(422, "Your cart can contain at most 50 different products")
        cart["items"] = items
        save_cart(cart, session)
        return quote(cart, session)
    return db.transaction(commit)

@db.guarded
def create_order(user, body):
    if not user.get("phone"):
        raise HTTPException(422, "Add a phone number to your account before preparing billing")
    def commit(session):
        previous = db.collection("orders").find_one({"user_id": user["_id"], "idempotency_key": body.idempotency_key}, session=session)
        if previous:
            return present_order(previous)
        coverage = db.collection("pages").find_one({"_id": "delivery"}, session=session)
        if coverage and coverage.get("areas") and not coverage.get("enabled"):
            raise HTTPException(503, "Delivery is temporarily paused. Please try again later.")
        if coverage and coverage.get("enabled") and not any(a["pincode"] == body.address.postal_code and a.get("enabled", True) for a in coverage.get("areas", [])):
            raise HTTPException(422, "Delivery is not available for this PIN code. Please change your delivery address.")
        cart = load_cart(cart_key(user, ""), session)
        summary = quote(cart, session)
        if not summary["can_checkout"]:
            raise HTTPException(409, "Your cart has unavailable items or is empty. Please review it.")
        if summary["version"] != body.cart_version or summary["quote_token"] != body.quote_token:
            raise HTTPException(409, "Prices, stock or your cart changed. Review the latest bill before continuing.")
        sequence = db.next_id("order", session)
        order = {"_id": uuid4().hex, "number": f"DF-{now().year}-{sequence:06d}", "user_id": user["_id"],
            "idempotency_key": body.idempotency_key, "created_at": now(), "status": "awaiting_payment", "payment_status": "unpaid",
            "fulfillment_status": "on_hold", "inventory_reserved": False, "currency": "INR",
            "customer": {"name": user["name"], "email": user["email"], "phone": user["phone"], "phone_verified": False},
            "shipping_address": body.address.model_dump(), "items": [{k: v for k, v in line.items() if k not in ("stock", "available")} for line in summary["items"]],
            "subtotal": summary["subtotal"], "shipping": summary["shipping"], "total": summary["total"],
            "document_type": "unpaid_order_summary", "billing_note": summary["billing_note"]}
        db.collection("orders").insert_one(order, session=session)
        cart["items"] = []
        save_cart(cart, session)
        return present_order(order)
    return db.transaction(commit)

def present_order(order):
    return {**{k: v for k, v in order.items() if k not in ("_id", "user_id", "idempotency_key")},
        "id": order["_id"], "created_at": order["created_at"].isoformat()}

@db.guarded
def orders(user):
    return [present_order(o) for o in db.collection("orders").find({"user_id": user["_id"]}).sort("created_at", -1).limit(100)]

@db.guarded
def order(user, ident):
    doc = db.collection("orders").find_one({"_id": ident, "user_id": user["_id"]})
    if not doc:
        raise HTTPException(404, "Order not found")
    return present_order(doc)

@db.guarded
def staff_orders():
    return [{"id": o["_id"], "number": o["number"], "created_at": o["created_at"].isoformat(),
        "customer_name": o["customer"]["name"], "item_count": sum(i["quantity"] for i in o["items"]),
        "total": o["total"], "payment_status": o["payment_status"], "fulfillment_status": o["fulfillment_status"]}
        for o in db.collection("orders").find().sort("created_at", -1).limit(100)]
