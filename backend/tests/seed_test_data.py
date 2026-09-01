"""Seed / cleanup helper for loss-makers verification (iteration 13).

Preview Mongo has 0 orders, so the loss-makers endpoint legitimately returns [].
This inserts a small set of TEST_ orders (marker field `_test_seed`) on a synthetic
marketplace `TEST_MK` plus a VAT rate for that marketplace only, so the new
vat_per_unit / margin_pct fields can actually be asserted.

Usage:
    python seed_test_data.py seed
    python seed_test_data.py clean
"""
import asyncio
import sys

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import dotenv_values

ENV = dotenv_values("/app/backend/.env")
TEST_MK = "TEST_MK"
TEST_SKU = "roll-mono"  # exists in costs with cost_per_unit=3.6 EUR, shipping_cost=0
TEST_SKU_PROFIT = "roll-mono"


def _client():
    c = AsyncIOMotorClient(ENV["MONGO_URL"])
    return c, c[ENV["DB_NAME"]]


def _order(idx, sku, name, qty, unit_price, ship, mk=TEST_MK):
    return {
        "order_id": f"TEST_ORD_{idx}",
        "line_key": f"TEST_LINE_{idx}",
        "sku": sku,
        "product_name": name,
        "marketplace": mk,
        "quantity": qty,
        "unit_price": unit_price,
        "currency": "EUR",
        "line_total_eur": round(unit_price * qty, 2),
        "shipping_cost_eur": ship,
        "order_date_iso": f"2026-05-{10 + idx:02d}T10:00:00",
        "_test_seed": True,
    }


ORDERS = [
    _order(1, TEST_SKU, "TEST_ Loss Maker Roll", 2, 2.0, 1.0),
    _order(2, "col-floor-ROS-C571", "TEST_ Floor Rose", 1, 5.0, 2.0),
    _order(3, "col-roll-mat-RJ-A294_60x200cm", "TEST_ Roll Mat", 3, 4.0, 1.5),
    _order(4, "col-floor-RV-0622_60x100cm", "TEST_ Floor RV", 2, 3.0, 0.0),
    _order(5, "roll-mob-mono", "TEST_ Mob Mono Profitable", 4, 40.0, 3.0),
    _order(6, "col-floor-roll-RJ-A210", "TEST_ Floor Roll A210", 1, 10.0, 1.0, mk="TEST_MK2"),
]


async def seed():
    c, db = _client()
    await db.orders.delete_many({"_test_seed": True})
    await db.orders.insert_many([dict(o) for o in ORDERS])
    # add VAT only for the synthetic marketplace so real data stays untouched
    doc = await db.settings.find_one({"operational_cost_per_unit": {"$exists": True}})
    vat = dict(doc.get("vat_rate_by_marketplace") or {})
    vat[TEST_MK] = 20.0
    vat["TEST_MK2"] = 21.0
    await db.settings.update_one({"_id": doc["_id"]}, {"$set": {"vat_rate_by_marketplace": vat}})
    print("seeded orders:", await db.orders.count_documents({"_test_seed": True}))
    c.close()


async def clean():
    c, db = _client()
    r = await db.orders.delete_many({"_test_seed": True})
    doc = await db.settings.find_one({"operational_cost_per_unit": {"$exists": True}})
    vat = dict(doc.get("vat_rate_by_marketplace") or {})
    vat.pop(TEST_MK, None)
    vat.pop("TEST_MK2", None)
    await db.settings.update_one({"_id": doc["_id"]}, {"$set": {"vat_rate_by_marketplace": vat}})
    print("deleted", r.deleted_count)
    c.close()


if __name__ == "__main__":
    asyncio.run(seed() if sys.argv[1] == "seed" else clean())
