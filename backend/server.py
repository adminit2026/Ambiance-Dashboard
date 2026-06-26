"""Ambiance Analytics Hub — FastAPI app entry point.

All shared helpers live in `core.py`; route handlers are split into
`routes/auth.py`, `routes/uploads.py`, `routes/costs.py`,
`routes/dashboard.py`, `routes/orders.py`, `routes/library.py`.
"""
import os
from datetime import datetime, timezone

from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware

from core import (
    db, client, logger,
    ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_NAME,
    hash_password, verify_password,
    get_rates, channel_to_marketplace,
)
from routes import auth, uploads, costs, dashboard, orders, library

app = FastAPI(title="Ambiance Analytics Hub")
api = APIRouter(prefix="/api")

# Mount sub-routers
api.include_router(auth.router)
api.include_router(uploads.router)
api.include_router(costs.router)
api.include_router(dashboard.router)
api.include_router(orders.router)
api.include_router(library.router)


@api.get("/")
async def root():
    return {"app": "Ambiance Analytics Hub", "status": "ok"}


app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup():
    # indexes
    await db.users.create_index("email", unique=True)
    await db.orders.create_index("line_key", unique=True)
    await db.orders.create_index([("order_date", -1)])
    await db.orders.create_index("marketplace")
    await db.orders.create_index("sku")
    await db.costs.create_index("sku", unique=True)
    await db.uploads.create_index([("uploaded_at", -1)])
    await db.asin_mappings.create_index("asin", unique=True)
    await db.sku_mappings.create_index([("marketplace", 1), ("external_id", 1)], unique=True)

    # seed admin
    existing = await db.users.find_one({"email": ADMIN_EMAIL})
    if existing is None:
        await db.users.insert_one({
            "email": ADMIN_EMAIL,
            "password_hash": hash_password(ADMIN_PASSWORD),
            "name": ADMIN_NAME,
            "role": "admin",
            "created_at": datetime.now(timezone.utc),
        })
        logger.info("Seeded admin user: %s", ADMIN_EMAIL)
    elif not verify_password(ADMIN_PASSWORD, existing["password_hash"]):
        await db.users.update_one({"email": ADMIN_EMAIL}, {"$set": {"password_hash": hash_password(ADMIN_PASSWORD)}})
        logger.info("Updated admin password to match .env")

    await get_rates()

    # Auto-renormalize marketplaces on startup so any legacy/un-normalized rows are merged
    # into their canonical labels. Idempotent: no-op if everything is already canonical.
    try:
        from pymongo import UpdateOne
        bulk = []
        changed = 0
        async for o in db.orders.find({}, {"_id": 1, "channel_raw": 1, "marketplace": 1}):
            new_mk = channel_to_marketplace(o.get("channel_raw") or o.get("marketplace") or "")
            if new_mk != o.get("marketplace"):
                bulk.append(UpdateOne({"_id": o["_id"]}, {"$set": {"marketplace": new_mk}}))
                changed += 1
            if len(bulk) >= 500:
                await db.orders.bulk_write(bulk, ordered=False)
                bulk = []
        if bulk:
            await db.orders.bulk_write(bulk, ordered=False)
        if changed:
            logger.info("Startup renormalize: merged %d orders into canonical marketplaces", changed)
    except Exception as e:
        logger.warning("Startup renormalize skipped: %s", e)


@app.on_event("shutdown")
async def on_shutdown():
    client.close()
