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
    hash_password, verify_password,
    get_rates, channel_to_marketplace, refine_marketplace,
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

    # seed users — idempotent. If a user exists, only refresh its password hash / role
    # (never overwrite email or created_at). Delete legacy demo user if present.
    users_to_seed = [
        {
            "email": "amazon.marketplace@ambiance-sticker.com",
            "password": "Stickers2026!",
            "name": "Amazon Marketplace",
            "role": "admin",
        },
        {
            "email": "info@ambiance-sticker.com",
            "password": "Ambiance2026!",
            "name": "Ambiance Team",
            "role": "user",
        },
    ]
    for u in users_to_seed:
        existing = await db.users.find_one({"email": u["email"]})
        if existing is None:
            await db.users.insert_one({
                "email": u["email"],
                "password_hash": hash_password(u["password"]),
                "name": u["name"],
                "role": u["role"],
                "created_at": datetime.now(timezone.utc),
            })
            logger.info("Seeded user: %s (%s)", u["email"], u["role"])
        else:
            updates = {"role": u["role"], "name": u["name"]}
            if not verify_password(u["password"], existing.get("password_hash", "")):
                updates["password_hash"] = hash_password(u["password"])
            await db.users.update_one({"email": u["email"]}, {"$set": updates})
    # remove legacy demo admin if it exists and isn't one of the new users
    legacy = ["admin@ambiancesticker.com"]
    for e in legacy:
        if e not in {u["email"] for u in users_to_seed}:
            r = await db.users.delete_one({"email": e})
            if r.deleted_count:
                logger.info("Removed legacy user: %s", e)

    await get_rates()

    # Auto-renormalize marketplaces on startup so any legacy/un-normalized rows are merged
    # into their canonical labels. Idempotent: no-op if everything is already canonical.
    try:
        from pymongo import UpdateOne
        bulk = []
        changed = 0
        async for o in db.orders.find({}, {"_id": 1, "channel_raw": 1, "marketplace": 1, "country": 1}):
            base_mk = channel_to_marketplace(o.get("channel_raw") or o.get("marketplace") or "")
            new_mk = refine_marketplace(base_mk, o.get("country") or "")
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
