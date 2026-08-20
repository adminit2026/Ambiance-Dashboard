"""Costs catalog, cost-constants, exchange rates, and admin operations."""
from datetime import datetime, timezone
from typing import Dict

from fastapi import APIRouter, Depends
from pymongo import UpdateOne

from core import (
    db, CostManualIn, CostConstantsUpdate, ExchangeRateUpdate,
    get_current_user, require_admin,
    get_rates, get_cost_constants, to_eur, channel_to_marketplace, refine_marketplace,
    remap_amazon_orders,
)

router = APIRouter()


# ------------------- Costs catalog -------------------
@router.get("/costs")
async def list_costs(user=Depends(get_current_user)):
    docs = await db.costs.find({}, {"_id": 0}).sort("sku", 1).to_list(5000)
    return docs


@router.post("/costs/manual")
async def manual_cost(payload: CostManualIn, user=Depends(require_admin)):
    doc = payload.model_dump()
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.costs.update_one({"sku": payload.sku}, {"$set": doc}, upsert=True)
    return {"ok": True}


@router.delete("/costs/{sku}")
async def delete_cost(sku: str, user=Depends(require_admin)):
    await db.costs.delete_one({"sku": sku})
    return {"ok": True}


# ------------------- Master price list (canonical snapshot) -------------------
@router.get("/costs/master/status")
async def master_status(user=Depends(get_current_user)):
    """Return metadata about the saved master price list (if any)."""
    meta = await db.costs_master_meta.find_one({"_id": "master"}, {"_id": 0})
    count = await db.costs_master.count_documents({})
    return {"exists": count > 0, "count": count, "saved_at": (meta or {}).get("saved_at"), "saved_by": (meta or {}).get("saved_by")}


@router.post("/costs/master/save")
async def save_master(user=Depends(require_admin)):
    """Freeze the current costs collection as the canonical master price list."""
    await db.costs_master.delete_many({})
    docs = [c async for c in db.costs.find({}, {"_id": 0})]
    if docs:
        await db.costs_master.insert_many(docs)
    now = datetime.now(timezone.utc).isoformat()
    await db.costs_master_meta.update_one(
        {"_id": "master"},
        {"$set": {"saved_at": now, "saved_by": user["email"], "count": len(docs)}},
        upsert=True,
    )
    return {"saved": len(docs), "saved_at": now}


@router.post("/costs/master/restore")
async def restore_master(user=Depends(require_admin)):
    """Replace the working costs collection with the master price list snapshot."""
    count = await db.costs_master.count_documents({})
    if count == 0:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="No master price list saved yet. Save one first.")
    await db.costs.delete_many({})
    docs = [c async for c in db.costs_master.find({}, {"_id": 0})]
    if docs:
        await db.costs.insert_many(docs)
    return {"restored": len(docs)}


# ------------------- Exchange rates -------------------
@router.get("/exchange-rates")
async def get_exchange_rates(user=Depends(get_current_user)):
    return await get_rates()


@router.put("/exchange-rates")
async def update_exchange_rates(payload: ExchangeRateUpdate, user=Depends(require_admin)):
    rates = {k.upper(): float(v) for k, v in payload.rates.items()}
    rates["EUR"] = 1.0
    await db.settings.update_one({"_id": "exchange_rates"}, {"$set": {"rates": rates}}, upsert=True)
    async for o in db.orders.find({}, {"_id": 1, "line_total": 1, "shipping_cost": 1, "currency": 1}):
        await db.orders.update_one(
            {"_id": o["_id"]},
            {"$set": {
                "line_total_eur": to_eur(o.get("line_total", 0), o.get("currency", "EUR"), rates),
                "shipping_cost_eur": to_eur(o.get("shipping_cost", 0), o.get("currency", "EUR"), rates),
            }},
        )
    return rates


# ------------------- Cost constants -------------------
@router.get("/cost-constants")
async def get_cost_constants_endpoint(user=Depends(get_current_user)):
    return await get_cost_constants()


@router.put("/cost-constants")
async def update_cost_constants(payload: CostConstantsUpdate, user=Depends(require_admin)):
    doc = {
        "operational_cost_per_unit": float(payload.operational_cost_per_unit),
        "production_shipping_by_marketplace": {
            k: float(v) for k, v in (payload.production_shipping_by_marketplace or {}).items()
        },
        "commission_by_marketplace": {
            k: float(v) for k, v in (payload.commission_by_marketplace or {}).items()
        },
        "vat_rate_by_marketplace": {
            k: float(v) for k, v in (payload.vat_rate_by_marketplace or {}).items()
        },
    }
    await db.settings.update_one({"_id": "cost_constants"}, {"$set": doc}, upsert=True)
    return doc


# ------------------- Danger zone: erase all sales data -------------------
@router.post("/admin/orders/erase-all")
@router.delete("/admin/orders/all")
async def erase_all_orders(confirm: str = "", user=Depends(require_admin)):
    """Erase every order + order-upload history. Keeps costs, mappings, settings, and users intact.
    Requires ?confirm=ERASE (or JSON body {"confirm": "ERASE"}) to protect against accidental calls.
    Exposed as both POST /admin/orders/erase-all and DELETE /admin/orders/all for proxy compatibility.
    """
    from fastapi import HTTPException
    if confirm != "ERASE":
        raise HTTPException(status_code=400, detail="Pass confirm=ERASE to authorize this destructive action")
    orders_res = await db.orders.delete_many({})
    # Only remove order-source uploads; keep cost upload history (needed for cost undo)
    uploads_res = await db.uploads.delete_many({"target_collection": {"$ne": "costs"}})
    return {
        "orders_deleted": orders_res.deleted_count,
        "order_uploads_deleted": uploads_res.deleted_count,
    }


# ------------------- Admin operations -------------------
@router.post("/admin/reprocess-amazon-asins")
async def reprocess_amazon_asins(user=Depends(require_admin)):
    n = await remap_amazon_orders()
    return {"orders_remapped": n}


@router.post("/admin/renormalize-marketplaces")
async def renormalize_marketplaces(user=Depends(require_admin)):
    bulk = []
    changed = 0
    async for o in db.orders.find({}, {"_id": 1, "channel_raw": 1, "marketplace": 1, "country": 1}):
        base_mk = channel_to_marketplace(o.get("channel_raw") or o.get("marketplace") or "")
        new_mk = refine_marketplace(base_mk, o.get("country") or "")
        if new_mk != o.get("marketplace"):
            bulk.append(UpdateOne({"_id": o["_id"]}, {"$set": {"marketplace": new_mk}}))
            changed += 1
        if len(bulk) >= 500:
            await db.orders.bulk_write(bulk)
            bulk = []
    if bulk:
        await db.orders.bulk_write(bulk)
    return {"updated": changed}
