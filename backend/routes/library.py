"""Library (cost catalog), SKU prices, marketplaces, loss-makers."""
import io
import csv
from typing import Optional, Dict

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from openpyxl import Workbook

from core import (
    db, CANONICAL_MARKETPLACES,
    get_current_user, build_match, parse_list,
    get_cost_constants,
)

router = APIRouter()


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx_response(rows: list, headers: list, filename: str, sheet_name: str = "Sheet1") -> StreamingResponse:
    """Serialise rows into an in-memory .xlsx workbook and return it as a download."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name[:31] or "Sheet1"
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/library/skus")
async def library_skus(
    search: Optional[str] = None,
    limit: int = 5000,
    user=Depends(get_current_user),
):
    """Return all SKUs with cost breakdown.
    Production Shipping = per-order rate from Settings, allocated across SKUs
    proportionally by quantity within each order, then averaged per unit.
    Commission = weighted avg commission % per marketplace, computed against revenue.
    """
    constants = await get_cost_constants()
    op_cost = float(constants["operational_cost_per_unit"])
    mk_shipping = constants["production_shipping_by_marketplace"] or {}
    mk_commission = constants["commission_by_marketplace"] or {}

    # First pass: total qty per (order_id, marketplace) so we can split the
    # per-order shipping cost proportionally across the SKUs in that order.
    order_totals: Dict[tuple, int] = {}
    async for r in db.orders.aggregate([
        {"$group": {"_id": {"oid": "$order_id", "mk": "$marketplace"}, "total_qty": {"$sum": "$quantity"}}},
    ]):
        order_totals[(r["_id"]["oid"], r["_id"]["mk"])] = int(r["total_qty"] or 0)

    sku_data: Dict[str, dict] = {}
    async for o in db.orders.find({}, {"sku": 1, "marketplace": 1, "quantity": 1, "line_total_eur": 1, "product_name": 1, "order_id": 1}):
        sku = o.get("sku")
        if not sku:
            continue
        mk = o.get("marketplace") or "Unknown"
        qty = int(o.get("quantity") or 0)
        rev = float(o.get("line_total_eur") or 0)
        d = sku_data.setdefault(sku, {"product_name": o.get("product_name") or "", "units_total": 0, "revenue_total": 0.0, "prod_ship_alloc": 0.0, "commission_eur": 0.0})
        if not d["product_name"] and o.get("product_name"):
            d["product_name"] = o.get("product_name")
        d["units_total"] += qty
        d["revenue_total"] += rev
        order_qty = order_totals.get((o.get("order_id"), mk), qty) or qty
        if order_qty > 0:
            d["prod_ship_alloc"] += float(mk_shipping.get(mk, 0)) * (qty / order_qty)
        d["commission_eur"] += float(mk_commission.get(mk, 0)) / 100.0 * rev

    costs_map = {c["sku"]: c async for c in db.costs.find({}, {"_id": 0, "sku": 1, "cost_per_unit": 1, "shipping_cost": 1, "currency": 1, "product_name": 1})}
    all_skus = set(sku_data.keys()) | set(costs_map.keys())

    if search:
        q = search.lower()
        all_skus = {s for s in all_skus if q in s.lower() or q in (sku_data.get(s, {}).get("product_name") or costs_map.get(s, {}).get("product_name") or "").lower()}

    out = []
    for sku in all_skus:
        sd = sku_data.get(sku, {})
        c = costs_map.get(sku, {})
        production_cost = float(c.get("cost_per_unit", 0)) if c else 0
        units_total = sd.get("units_total", 0)
        revenue_total = sd.get("revenue_total", 0.0)
        prod_ship_alloc = sd.get("prod_ship_alloc", 0.0)
        commission_eur = sd.get("commission_eur", 0.0)
        prod_shipping = (prod_ship_alloc / units_total) if units_total > 0 else 0.0
        commission_pct_weighted = (commission_eur / revenue_total * 100.0) if revenue_total > 0 else 0.0
        product_name = sd.get("product_name") or c.get("product_name") or ""
        total = production_cost + op_cost + prod_shipping
        out.append({
            "sku": sku,
            "product_name": product_name,
            "production_cost": round(production_cost, 4),
            "operational_cost": round(op_cost, 4),
            "production_shipping_cost": round(prod_shipping, 4),
            "commission_pct": round(commission_pct_weighted, 2),
            "commission_eur_per_unit": round(commission_eur / units_total, 4) if units_total else 0,
            "total_cost": round(total, 4),
            "units_sold": units_total,
            "revenue_eur": round(revenue_total, 2),
            "has_cost": bool(c),
        })
    out.sort(key=lambda x: x["units_sold"], reverse=True)
    return out[:limit]


@router.get("/library/export")
async def library_export(user=Depends(get_current_user)):
    rows_data = await library_skus(limit=20000, user=user)
    headers = ["SKU", "Product", "Production Cost (EUR)", "Operational Cost (EUR)", "Production Shipping Cost (EUR)", "Commission %", "Commission EUR / unit", "Total Cost (EUR)", "Units Sold", "Revenue (EUR)"]
    rows = [[r["sku"], r["product_name"], r["production_cost"], r["operational_cost"], r["production_shipping_cost"], r["commission_pct"], r["commission_eur_per_unit"], r["total_cost"], r["units_sold"], r["revenue_eur"]] for r in rows_data]
    return _xlsx_response(rows, headers, "cost_library.xlsx", sheet_name="Cost Library")


@router.get("/library/loss-makers")
async def loss_makers(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    marketplaces: Optional[str] = None,
    user=Depends(get_current_user),
):
    """Return per-SKU per-marketplace combos where net profit/unit < 0.

    Production shipping is billed PER ORDER; at the SKU×MK level we allocate
    each order's shipping cost proportionally by quantity across the SKUs in
    that order, then average per unit for this (sku, mk).

    Net/unit = avg_unit_price − (production_cost + operational_cost + prod_ship_per_unit + avg_price × commission[mk]/100)
    """
    match = build_match(date_from, date_to, parse_list(marketplaces), None)
    constants = await get_cost_constants()
    op_cost = float(constants["operational_cost_per_unit"])
    mk_shipping = constants["production_shipping_by_marketplace"] or {}
    mk_commission = constants["commission_by_marketplace"] or {}

    # First pass: total qty per (order_id, marketplace) — for proportional split
    order_totals_pipe = [
        {"$match": match} if match else {"$match": {}},
        {"$group": {"_id": {"oid": "$order_id", "mk": "$marketplace"}, "total_qty": {"$sum": "$quantity"}}},
    ]
    order_totals: Dict[tuple, int] = {}
    async for r in db.orders.aggregate(order_totals_pipe):
        order_totals[(r["_id"]["oid"], r["_id"]["mk"])] = int(r["total_qty"] or 0)

    # Second pass: aggregate (sku, mk) — units, revenue, allocated shipping, orders
    grouped: Dict[tuple, dict] = {}
    line_match = {**match, "unit_price": {"$gt": 0}}
    async for o in db.orders.find(line_match, {"sku": 1, "marketplace": 1, "quantity": 1, "line_total_eur": 1, "order_id": 1, "product_name": 1}):
        sku = o.get("sku")
        if not sku:
            continue
        mk = o.get("marketplace") or "Unknown"
        qty = int(o.get("quantity") or 0)
        rev = float(o.get("line_total_eur") or 0)
        key = (sku, mk)
        d = grouped.setdefault(key, {"sku": sku, "mk": mk, "product_name": o.get("product_name") or "", "units": 0, "revenue": 0.0, "prod_ship_alloc": 0.0, "orders": set()})
        d["units"] += qty
        d["revenue"] += rev
        d["orders"].add(o.get("order_id"))
        order_qty = order_totals.get((o.get("order_id"), mk), qty) or qty
        if order_qty > 0:
            d["prod_ship_alloc"] += float(mk_shipping.get(mk, 0)) * (qty / order_qty)
        if not d["product_name"] and o.get("product_name"):
            d["product_name"] = o.get("product_name")

    skus = list({k[0] for k in grouped.keys()})
    costs_map = {c["sku"]: c async for c in db.costs.find({"sku": {"$in": skus}}, {"_id": 0, "sku": 1, "cost_per_unit": 1, "shipping_cost": 1, "currency": 1})}

    out = []
    for (sku, mk), d in grouped.items():
        units = d["units"]
        revenue = d["revenue"]
        if units == 0:
            continue
        avg_price = revenue / units
        c = costs_map.get(sku, {})
        prod_cost = float(c.get("cost_per_unit", 0))
        prod_ship_per_unit = d["prod_ship_alloc"] / units  # allocated per-order shipping, averaged per unit
        commission_per_unit = avg_price * float(mk_commission.get(mk, 0)) / 100.0
        total_cost_per_unit = prod_cost + op_cost + prod_ship_per_unit + commission_per_unit
        net_per_unit = avg_price - total_cost_per_unit
        if net_per_unit < 0 and prod_cost > 0:
            total_loss = net_per_unit * units
            out.append({
                "sku": sku,
                "marketplace": mk,
                "product_name": d.get("product_name") or "",
                "units": units,
                "orders": len(d["orders"]),
                "avg_unit_price": round(avg_price, 2),
                "production_cost": round(prod_cost, 2),
                "operational_cost": round(op_cost, 2),
                "production_shipping": round(prod_ship_per_unit, 2),
                "commission_per_unit": round(commission_per_unit, 2),
                "total_cost_per_unit": round(total_cost_per_unit, 2),
                "net_per_unit": round(net_per_unit, 2),
                "total_loss_eur": round(total_loss, 2),
                "revenue_eur": round(revenue, 2),
            })
    out.sort(key=lambda x: x["total_loss_eur"])
    return out


@router.get("/marketplaces")
async def list_marketplaces(user=Depends(get_current_user)):
    mks = await db.orders.distinct("marketplace")
    combined = sorted(set([m for m in mks if m] + CANONICAL_MARKETPLACES))
    return combined


@router.get("/skus")
async def list_skus(user=Depends(get_current_user), limit: int = 500):
    pipeline = [
        {"$group": {"_id": "$sku", "product_name": {"$first": "$product_name"}, "units": {"$sum": "$quantity"}}},
        {"$sort": {"units": -1}},
        {"$limit": limit},
    ]
    rows = await db.orders.aggregate(pipeline).to_list(limit)
    return [{"sku": r["_id"], "product_name": r["product_name"] or "", "units": int(r["units"] or 0)} for r in rows]


@router.get("/skus/prices")
async def sku_prices(
    sku: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    marketplaces: Optional[str] = None,
    limit: int = 200,
    user=Depends(get_current_user),
):
    """Returns per-SKU per-marketplace avg/min/max unit prices."""
    match = build_match(date_from, date_to, parse_list(marketplaces), sku)
    pipeline = [
        {"$match": match} if match else {"$match": {}},
        {"$match": {"unit_price": {"$gt": 0}}},
        {"$group": {
            "_id": {"sku": "$sku", "marketplace": "$marketplace", "currency": "$currency"},
            "product_name": {"$first": "$product_name"},
            "avg_price": {"$avg": "$unit_price"},
            "min_price": {"$min": "$unit_price"},
            "max_price": {"$max": "$unit_price"},
            "units": {"$sum": "$quantity"},
            "orders": {"$addToSet": "$order_id"},
            "last_order": {"$max": "$order_date_iso"},
        }},
        {"$sort": {"_id.sku": 1, "_id.marketplace": 1}},
    ]
    rows = await db.orders.aggregate(pipeline).to_list(20000)
    by_sku: Dict[str, dict] = {}
    for r in rows:
        sku_id = r["_id"]["sku"]
        mk = r["_id"]["marketplace"] or "Unknown"
        cur = r["_id"]["currency"] or "EUR"
        if sku_id not in by_sku:
            by_sku[sku_id] = {
                "sku": sku_id,
                "product_name": r["product_name"] or "",
                "prices": {},
                "total_units": 0,
            }
        by_sku[sku_id]["prices"][mk] = {
            "avg": round(float(r["avg_price"] or 0), 2),
            "min": round(float(r["min_price"] or 0), 2),
            "max": round(float(r["max_price"] or 0), 2),
            "units": int(r["units"] or 0),
            "orders": len(r["orders"]),
            "currency": cur,
            "last_order": r.get("last_order"),
        }
        by_sku[sku_id]["total_units"] += int(r["units"] or 0)
    items = sorted(by_sku.values(), key=lambda x: x["total_units"], reverse=True)[:limit]
    marketplaces_present = sorted({mk for it in items for mk in it["prices"].keys()})
    return {"marketplaces": marketplaces_present, "items": items}


@router.get("/skus/prices/export")
async def sku_prices_export(
    sku: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    marketplaces: Optional[str] = None,
    user=Depends(get_current_user),
):
    data = await sku_prices(sku=sku, date_from=date_from, date_to=date_to, marketplaces=marketplaces, limit=10000, user=user)
    mks = data["marketplaces"]
    headers = ["SKU", "Product"] + [f"{m} (avg)" for m in mks] + [f"{m} (units)" for m in mks]
    rows = []
    for it in data["items"]:
        row = [it["sku"], it["product_name"]]
        for m in mks:
            p = it["prices"].get(m)
            row.append(p["avg"] if p else "")
        for m in mks:
            p = it["prices"].get(m)
            row.append(p["units"] if p else "")
        rows.append(row)
    return _xlsx_response(rows, headers, "sku_prices.xlsx", sheet_name="SKU Prices")
