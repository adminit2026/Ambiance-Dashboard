"""Dashboard endpoints: summary, returns, trend, marketplace-breakdown,
top-skus, customers, heatmap, profit-loss."""
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, Query

from core import (
    db, get_current_user, build_match, parse_list,
    get_rates, get_cost_constants, to_eur,
    rollup_marketplace,
)

router = APIRouter()


@router.get("/dashboard/summary")
async def dashboard_summary(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    marketplaces: Optional[str] = None,
    sku: Optional[str] = None,
    user=Depends(get_current_user),
):
    match = build_match(date_from, date_to, parse_list(marketplaces), sku)
    pipeline = [{"$match": match}] if match else []
    pipeline += [{
        "$group": {
            "_id": None,
            "revenue_eur": {"$sum": "$line_total_eur"},
            "shipping_eur": {"$sum": "$shipping_cost_eur"},
            "orders": {"$addToSet": "$order_id"},
            "units": {"$sum": "$quantity"},
            "lines": {"$sum": 1},
        }
    }]
    res = await db.orders.aggregate(pipeline).to_list(1)
    if not res:
        return {"revenue_eur": 0, "shipping_eur": 0, "orders": 0, "units": 0, "lines": 0, "aov_eur": 0, "cogs_eur": 0, "margin_eur": 0, "margin_pct": 0}
    r = res[0]
    revenue = float(r["revenue_eur"] or 0)
    shipping = float(r["shipping_eur"] or 0)
    orders_count = len(r["orders"])
    units = int(r["units"] or 0)
    lines = int(r["lines"] or 0)
    aov = revenue / orders_count if orders_count else 0

    rates = await get_rates()
    constants = await get_cost_constants()
    op_cost = float(constants["operational_cost_per_unit"])
    mk_shipping = constants["production_shipping_by_marketplace"] or {}
    mk_commission = constants["commission_by_marketplace"] or {}
    skus_in_scope = await db.orders.distinct("sku", match)
    costs_map: Dict[str, dict] = {c["sku"]: c async for c in db.costs.find({"sku": {"$in": skus_in_scope}}, {"_id": 0, "sku": 1, "cost_per_unit": 1, "shipping_cost": 1, "currency": 1})}
    cogs = 0.0
    operational_total = 0.0
    prod_shipping_total = 0.0
    commission_total = 0.0
    async for o in db.orders.find(match, {"sku": 1, "quantity": 1, "marketplace": 1, "line_total_eur": 1}):
        qty = int(o.get("quantity") or 0)
        mk = o.get("marketplace", "")
        c = costs_map.get(o.get("sku"))
        if c:
            cogs += to_eur((c["cost_per_unit"] + c.get("shipping_cost", 0)) * qty, c.get("currency", "EUR"), rates)
        operational_total += op_cost * qty
        prod_shipping_total += float(mk_shipping.get(mk, 0)) * qty
        commission_total += float(o.get("line_total_eur") or 0) * float(mk_commission.get(mk, 0)) / 100.0
    # Customer-paid shipping is income, not an expense — add it to revenue.
    total_revenue = revenue + shipping
    total_costs = cogs + operational_total + prod_shipping_total + commission_total
    margin = total_revenue - total_costs
    margin_pct = (margin / total_revenue * 100) if total_revenue else 0
    return {
        "revenue_eur": round(revenue, 2),
        "shipping_eur": round(shipping, 2),
        "shipping_income_eur": round(shipping, 2),
        "total_revenue_eur": round(total_revenue, 2),
        "orders": orders_count,
        "units": units,
        "lines": lines,
        "aov_eur": round(aov, 2),
        "cogs_eur": round(cogs, 2),
        "operational_eur": round(operational_total, 2),
        "production_shipping_eur": round(prod_shipping_total, 2),
        "commission_eur": round(commission_total, 2),
        "margin_eur": round(margin, 2),
        "margin_pct": round(margin_pct, 2),
    }


@router.get("/dashboard/returns")
async def dashboard_returns(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    marketplaces: Optional[str] = None,
    sku: Optional[str] = None,
    user=Depends(get_current_user),
):
    """Summary of refunded / returned / cancelled orders, broken down by marketplace.
    Classification (case-insensitive on status):
      - refund: status contains 'refund' or 'return'
      - cancel: status contains 'cancel'
    """
    base_match = build_match(date_from, date_to, parse_list(marketplaces), sku)
    match = {
        **base_match,
        "status": {"$regex": "refund|return|cancel|annul|rembours", "$options": "i"},
    }
    pipeline = [
        {"$match": match},
        {"$addFields": {
            "bucket": {
                "$cond": [
                    {"$regexMatch": {"input": {"$ifNull": ["$status", ""]}, "regex": "cancel|annul", "options": "i"}},
                    "cancel",
                    "refund",
                ]
            }
        }},
        {"$group": {
            "_id": {"mk": "$marketplace", "bucket": "$bucket"},
            "lines": {"$sum": 1},
            "units": {"$sum": "$quantity"},
            "amount_eur": {"$sum": "$line_total_eur"},
            "orders": {"$addToSet": "$order_id"},
        }},
    ]
    rows = await db.orders.aggregate(pipeline).to_list(2000)

    by_mk: Dict[str, dict] = {}
    totals = {"refund_units": 0, "refund_eur": 0.0, "refund_orders": 0,
              "cancel_units": 0, "cancel_eur": 0.0, "cancel_orders": 0}
    for r in rows:
        mk = r["_id"]["mk"] or "Unknown"
        bucket = r["_id"]["bucket"]
        d = by_mk.setdefault(mk, {"marketplace": mk,
                                  "refund_units": 0, "refund_eur": 0.0, "refund_orders": 0,
                                  "cancel_units": 0, "cancel_eur": 0.0, "cancel_orders": 0})
        units = int(r["units"] or 0)
        amt = float(r["amount_eur"] or 0)
        n_orders = len(r["orders"])
        d[f"{bucket}_units"] += units
        d[f"{bucket}_eur"] += amt
        d[f"{bucket}_orders"] += n_orders
        totals[f"{bucket}_units"] += units
        totals[f"{bucket}_eur"] += amt
        totals[f"{bucket}_orders"] += n_orders

    by_mk_list = sorted(by_mk.values(), key=lambda x: (x["refund_eur"] + x["cancel_eur"]), reverse=True)
    for d in by_mk_list:
        d["refund_eur"] = round(d["refund_eur"], 2)
        d["cancel_eur"] = round(d["cancel_eur"], 2)
    for k in ("refund_eur", "cancel_eur"):
        totals[k] = round(totals[k], 2)

    total_pipe = [{"$match": base_match}, {"$group": {"_id": None, "rev": {"$sum": "$line_total_eur"}, "units": {"$sum": "$quantity"}}}]
    tot = await db.orders.aggregate(total_pipe).to_list(1)
    total_rev = float(tot[0]["rev"]) if tot else 0.0
    total_units = int(tot[0]["units"]) if tot else 0
    refund_rate_pct = (totals["refund_eur"] / total_rev * 100) if total_rev else 0
    cancel_rate_pct = (totals["cancel_eur"] / total_rev * 100) if total_rev else 0

    recent = await db.orders.find(
        match,
        {"_id": 0, "order_id": 1, "order_date_iso": 1, "marketplace": 1, "sku": 1, "product_name": 1,
         "quantity": 1, "line_total_eur": 1, "status": 1, "customer_name": 1, "country": 1},
    ).sort("order_date_iso", -1).to_list(200)

    return {
        "by_marketplace": by_mk_list,
        "totals": {
            **totals,
            "total_revenue_eur": round(total_rev, 2),
            "total_units": total_units,
            "refund_rate_pct": round(refund_rate_pct, 2),
            "cancel_rate_pct": round(cancel_rate_pct, 2),
        },
        "recent": recent,
    }


@router.get("/dashboard/trend")
async def dashboard_trend(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    marketplaces: Optional[str] = None,
    sku: Optional[str] = None,
    granularity: str = Query("day", pattern="^(day|month)$"),
    rollup: bool = False,
    user=Depends(get_current_user),
):
    match = build_match(date_from, date_to, parse_list(marketplaces), sku)
    fmt = "%Y-%m-%d" if granularity == "day" else "%Y-%m"
    pipeline = [
        {"$match": {**match, "order_date_iso": {**match.get("order_date_iso", {}), "$ne": None}}},
        {"$addFields": {"order_dt": {"$dateFromString": {"dateString": "$order_date_iso", "onError": None}}}},
        {"$match": {"order_dt": {"$ne": None}}},
        {"$group": {
            "_id": {"period": {"$dateToString": {"format": fmt, "date": "$order_dt"}}, "marketplace": "$marketplace"},
            "revenue": {"$sum": "$line_total_eur"},
            "orders": {"$addToSet": "$order_id"},
            "units": {"$sum": "$quantity"},
        }},
        {"$sort": {"_id.period": 1}},
    ]
    rows = await db.orders.aggregate(pipeline).to_list(10000)
    out: Dict[str, dict] = {}
    for r in rows:
        period = r["_id"]["period"]
        mk = r["_id"]["marketplace"]
        if rollup:
            mk = rollup_marketplace(mk)
        if period not in out:
            out[period] = {"period": period, "revenue_total": 0, "by_marketplace": {}, "orders_total": 0, "units_total": 0}
        out[period]["by_marketplace"][mk] = out[period]["by_marketplace"].get(mk, 0) + round(float(r["revenue"] or 0), 2)
        out[period]["revenue_total"] += float(r["revenue"] or 0)
        out[period]["orders_total"] += len(r["orders"])
        out[period]["units_total"] += int(r["units"] or 0)
    series = sorted(out.values(), key=lambda x: x["period"])
    for s in series:
        s["revenue_total"] = round(s["revenue_total"], 2)
        s["by_marketplace"] = {k: round(v, 2) for k, v in s["by_marketplace"].items()}
    return series


@router.get("/dashboard/marketplace-breakdown")
async def marketplace_breakdown(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    marketplaces: Optional[str] = None,
    sku: Optional[str] = None,
    rollup: bool = False,
    user=Depends(get_current_user),
):
    match = build_match(date_from, date_to, parse_list(marketplaces), sku)
    pipeline = [
        {"$match": match} if match else {"$match": {}},
        {"$group": {
            "_id": "$marketplace",
            "revenue": {"$sum": "$line_total_eur"},
            "shipping": {"$sum": "$shipping_cost_eur"},
            "units": {"$sum": "$quantity"},
            "orders": {"$addToSet": "$order_id"},
        }},
        {"$sort": {"revenue": -1}},
    ]
    rows = await db.orders.aggregate(pipeline).to_list(100)
    if not rollup:
        return [{
            "marketplace": r["_id"] or "Unknown",
            "revenue_eur": round(float(r["revenue"] or 0), 2),
            "shipping_eur": round(float(r["shipping"] or 0), 2),
            "units": int(r["units"] or 0),
            "orders": len(r["orders"]),
            "aov_eur": round(float(r["revenue"] or 0) / len(r["orders"]), 2) if r["orders"] else 0,
        } for r in rows]

    # Collapse split marketplaces (Maxeda BE+NL → Maxeda, Veepee BE/FR/NL → Veepee).
    merged: Dict[str, dict] = {}
    for r in rows:
        parent = rollup_marketplace(r["_id"] or "Unknown")
        m = merged.setdefault(parent, {
            "marketplace": parent,
            "revenue_eur": 0.0,
            "shipping_eur": 0.0,
            "units": 0,
            "orders": set(),
        })
        m["revenue_eur"] += float(r["revenue"] or 0)
        m["shipping_eur"] += float(r["shipping"] or 0)
        m["units"] += int(r["units"] or 0)
        m["orders"].update(r["orders"])
    out = []
    for m in merged.values():
        orders_count = len(m["orders"])
        out.append({
            "marketplace": m["marketplace"],
            "revenue_eur": round(m["revenue_eur"], 2),
            "shipping_eur": round(m["shipping_eur"], 2),
            "units": m["units"],
            "orders": orders_count,
            "aov_eur": round(m["revenue_eur"] / orders_count, 2) if orders_count else 0,
        })
    out.sort(key=lambda x: x["revenue_eur"], reverse=True)
    return out


@router.get("/dashboard/marketplace-country-breakdown")
async def marketplace_country_breakdown(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    marketplaces: Optional[str] = None,
    sku: Optional[str] = None,
    user=Depends(get_current_user),
):
    """Same breakdown as /dashboard/marketplace-breakdown but split per (marketplace, country).
    Useful for marketplaces that span multiple countries (e.g. Leroy Merlin → FR/ES/IT/PT/PL).
    """
    match = build_match(date_from, date_to, parse_list(marketplaces), sku)
    pipeline = [
        {"$match": match} if match else {"$match": {}},
        {"$group": {
            "_id": {"mk": "$marketplace", "country": "$country"},
            "revenue": {"$sum": "$line_total_eur"},
            "shipping": {"$sum": "$shipping_cost_eur"},
            "units": {"$sum": "$quantity"},
            "orders": {"$addToSet": "$order_id"},
        }},
        {"$sort": {"revenue": -1}},
    ]
    rows = await db.orders.aggregate(pipeline).to_list(2000)
    # Group children under their marketplace parent
    parents: Dict[str, dict] = {}
    for r in rows:
        mk = r["_id"]["mk"] or "Unknown"
        country = (r["_id"]["country"] or "").strip() or "—"
        rev = float(r["revenue"] or 0)
        ship = float(r["shipping"] or 0)
        units = int(r["units"] or 0)
        n_orders = len(r["orders"])
        p = parents.setdefault(mk, {
            "marketplace": mk,
            "revenue_eur": 0.0,
            "shipping_eur": 0.0,
            "units": 0,
            "orders": 0,
            "countries": [],
        })
        p["revenue_eur"] += rev
        p["shipping_eur"] += ship
        p["units"] += units
        p["orders"] += n_orders
        p["countries"].append({
            "country": country,
            "revenue_eur": round(rev, 2),
            "shipping_eur": round(ship, 2),
            "units": units,
            "orders": n_orders,
            "aov_eur": round(rev / n_orders, 2) if n_orders else 0,
        })
    out = []
    for p in parents.values():
        p["revenue_eur"] = round(p["revenue_eur"], 2)
        p["shipping_eur"] = round(p["shipping_eur"], 2)
        p["aov_eur"] = round(p["revenue_eur"] / p["orders"], 2) if p["orders"] else 0
        p["countries"].sort(key=lambda x: x["revenue_eur"], reverse=True)
        out.append(p)
    out.sort(key=lambda x: x["revenue_eur"], reverse=True)
    return out


@router.get("/dashboard/amazon-delivery")
async def amazon_delivery(
    delivery_from: Optional[str] = None,
    delivery_to: Optional[str] = None,
    sku: Optional[str] = None,
    user=Depends(get_current_user),
):
    """Amazon Vendor view filtered by DELIVERY date (Window end) instead of order date.
    Revenue stays attributed to its booking/order date (`order_date_iso`) — only the
    filtering window changes. Used to track upcoming/recent shipments without misstating
    the period in which revenue was earned.
    """
    match: Dict[str, Any] = {"source": "amazon_po", "delivery_date_iso": {"$ne": None}}
    if delivery_from or delivery_to:
        d_range: Dict[str, Any] = {}
        if delivery_from:
            d_range["$gte"] = delivery_from
        if delivery_to:
            d_range["$lte"] = delivery_to + "T23:59:59"
        match["delivery_date_iso"] = {**match["delivery_date_iso"], **d_range}
    if sku:
        import re
        match["sku"] = {"$regex": re.escape(sku), "$options": "i"}

    # Per-PO summary so user sees each shipment
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": {"po": "$order_id", "delivery": "$delivery_date_iso", "window_start": "$window_start_date_iso"},
            "order_date_iso": {"$min": "$order_date_iso"},
            "warehouse": {"$first": "$country"},
            "status": {"$first": "$status"},
            "units": {"$sum": "$quantity"},
            "revenue_eur": {"$sum": "$line_total_eur"},
            "lines": {"$sum": 1},
        }},
        {"$sort": {"_id.delivery": 1}},
    ]
    pos = await db.orders.aggregate(pipeline).to_list(10000)
    out_pos = [{
        "po": p["_id"]["po"],
        "delivery_date": (p["_id"]["delivery"] or "")[:10],
        "window_start": (p["_id"].get("window_start") or "")[:10],
        "order_date": (p.get("order_date_iso") or "")[:10],
        "warehouse": p.get("warehouse") or "",
        "status": p.get("status") or "",
        "units": int(p.get("units") or 0),
        "lines": int(p.get("lines") or 0),
        "revenue_eur": round(float(p.get("revenue_eur") or 0), 2),
    } for p in pos]

    # KPI totals
    totals = {
        "pos": len({p["po"] for p in out_pos}),
        "units": sum(p["units"] for p in out_pos),
        "revenue_eur": round(sum(p["revenue_eur"] for p in out_pos), 2),
        "delivery_lines": len(out_pos),
    }

    # Group by delivery date
    by_day: Dict[str, dict] = {}
    for p in out_pos:
        d = p["delivery_date"] or "—"
        slot = by_day.setdefault(d, {"delivery_date": d, "pos": 0, "units": 0, "revenue_eur": 0.0})
        slot["pos"] += 1
        slot["units"] += p["units"]
        slot["revenue_eur"] += p["revenue_eur"]
    timeline = sorted(by_day.values(), key=lambda x: x["delivery_date"])
    for slot in timeline:
        slot["revenue_eur"] = round(slot["revenue_eur"], 2)

    return {"totals": totals, "timeline": timeline, "pos": out_pos}


@router.get("/dashboard/top-skus")
async def top_skus(
    limit: int = 25,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    marketplaces: Optional[str] = None,
    sku: Optional[str] = None,
    user=Depends(get_current_user),
):
    match = build_match(date_from, date_to, parse_list(marketplaces), sku)
    pipeline = [
        {"$match": match} if match else {"$match": {}},
        {"$group": {
            "_id": "$sku",
            "product_name": {"$first": "$product_name"},
            "revenue": {"$sum": "$line_total_eur"},
            "units": {"$sum": "$quantity"},
            "orders": {"$addToSet": "$order_id"},
        }},
        {"$sort": {"revenue": -1}},
        {"$limit": limit},
    ]
    rows = await db.orders.aggregate(pipeline).to_list(limit)
    skus_needed = [r["_id"] for r in rows]
    costs_map: Dict[str, dict] = {c["sku"]: c async for c in db.costs.find({"sku": {"$in": skus_needed}}, {"_id": 0, "sku": 1, "cost_per_unit": 1, "shipping_cost": 1, "currency": 1})}
    rates = await get_rates()
    out = []
    for r in rows:
        sku_id = r["_id"]
        c = costs_map.get(sku_id)
        units = int(r["units"] or 0)
        revenue = float(r["revenue"] or 0)
        cogs = 0
        if c:
            cogs = to_eur((c["cost_per_unit"] + c.get("shipping_cost", 0)) * units, c.get("currency", "EUR"), rates)
        margin = revenue - cogs
        out.append({
            "sku": sku_id,
            "product_name": r["product_name"] or "",
            "revenue_eur": round(revenue, 2),
            "units": units,
            "orders": len(r["orders"]),
            "cogs_eur": round(cogs, 2),
            "margin_eur": round(margin, 2),
            "margin_pct": round((margin / revenue * 100) if revenue else 0, 2),
            "has_cost": bool(c),
        })
    return out


@router.get("/dashboard/customers")
async def customers_analytics(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    marketplaces: Optional[str] = None,
    sku: Optional[str] = None,
    user=Depends(get_current_user),
):
    match = build_match(date_from, date_to, parse_list(marketplaces), sku)
    pipeline = [
        {"$match": match} if match else {"$match": {}},
        {"$group": {
            "_id": "$country",
            "revenue": {"$sum": "$line_total_eur"},
            "orders": {"$addToSet": "$order_id"},
            "units": {"$sum": "$quantity"},
        }},
        {"$sort": {"revenue": -1}},
    ]
    rows = await db.orders.aggregate(pipeline).to_list(200)
    return [{
        "country": (r["_id"] or "Unknown") or "Unknown",
        "revenue_eur": round(float(r["revenue"] or 0), 2),
        "orders": len(r["orders"]),
        "units": int(r["units"] or 0),
    } for r in rows]


@router.get("/dashboard/heatmap")
async def heatmap(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    marketplaces: Optional[str] = None,
    sku: Optional[str] = None,
    user=Depends(get_current_user),
):
    match = build_match(date_from, date_to, parse_list(marketplaces), sku)
    pipeline = [
        {"$match": {**match, "order_date_iso": {"$ne": None}}},
        {"$addFields": {"order_dt": {"$dateFromString": {"dateString": "$order_date_iso", "onError": None}}}},
        {"$match": {"order_dt": {"$ne": None}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$order_dt"}},
            "revenue": {"$sum": "$line_total_eur"},
            "orders": {"$addToSet": "$order_id"},
            "units": {"$sum": "$quantity"},
        }},
        {"$sort": {"_id": 1}},
    ]
    rows = await db.orders.aggregate(pipeline).to_list(2000)
    return [{
        "date": r["_id"],
        "revenue_eur": round(float(r["revenue"] or 0), 2),
        "orders": len(r["orders"]),
        "units": int(r["units"] or 0),
    } for r in rows]


@router.get("/dashboard/profit-loss")
async def profit_loss(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    marketplaces: Optional[str] = None,
    sku: Optional[str] = None,
    user=Depends(get_current_user),
):
    match = build_match(date_from, date_to, parse_list(marketplaces), sku)
    rates = await get_rates()
    skus_in_scope = await db.orders.distinct("sku", match)
    costs_map: Dict[str, dict] = {c["sku"]: c async for c in db.costs.find({"sku": {"$in": skus_in_scope}}, {"_id": 0, "sku": 1, "cost_per_unit": 1, "shipping_cost": 1, "currency": 1})}
    pipeline = [
        {"$match": match} if match else {"$match": {}},
        {"$group": {
            "_id": "$marketplace",
            "revenue": {"$sum": "$line_total_eur"},
            "shipping": {"$sum": "$shipping_cost_eur"},
            "vat": {"$sum": "$vat"},
            "units": {"$sum": "$quantity"},
            "orders": {"$addToSet": "$order_id"},
        }},
    ]
    base = await db.orders.aggregate(pipeline).to_list(100)
    constants = await get_cost_constants()
    op_cost = float(constants["operational_cost_per_unit"])
    mk_shipping = constants["production_shipping_by_marketplace"] or {}
    mk_commission = constants["commission_by_marketplace"] or {}
    cogs_per_mk: Dict[str, float] = {}
    async for o in db.orders.find(match, {"sku": 1, "quantity": 1, "marketplace": 1, "currency": 1}):
        c = costs_map.get(o.get("sku"))
        if c:
            v = to_eur((c["cost_per_unit"] + c.get("shipping_cost", 0)) * o["quantity"], c.get("currency", "EUR"), rates)
            cogs_per_mk[o["marketplace"]] = cogs_per_mk.get(o["marketplace"], 0) + v
    out = []
    for r in base:
        mk = r["_id"] or "Unknown"
        rev = float(r["revenue"] or 0)
        ship_income = float(r["shipping"] or 0)  # customer-paid shipping = income
        units = int(r["units"] or 0)
        cogs = cogs_per_mk.get(mk, 0)
        op_total = op_cost * units
        prod_ship = float(mk_shipping.get(mk, 0)) * units
        # Commission is computed on gross revenue (line totals), not on shipping income
        commission_eur = float(mk_commission.get(mk, 0)) / 100.0 * rev
        total_revenue = rev + ship_income
        net = total_revenue - cogs - op_total - prod_ship - commission_eur
        out.append({
            "marketplace": mk,
            "revenue_eur": round(rev, 2),
            "shipping_income_eur": round(ship_income, 2),
            "total_revenue_eur": round(total_revenue, 2),
            "cogs_eur": round(cogs, 2),
            "shipping_eur": round(ship_income, 2),  # kept for backward compat
            "operational_eur": round(op_total, 2),
            "production_shipping_eur": round(prod_ship, 2),
            "commission_eur": round(commission_eur, 2),
            "commission_pct": float(mk_commission.get(mk, 0)),
            "vat_eur": round(float(r["vat"] or 0), 2),
            "net_profit_eur": round(net, 2),
            "margin_pct": round((net / total_revenue * 100) if total_revenue else 0, 2),
            "units": units,
            "orders": len(r["orders"]),
        })
    out.sort(key=lambda x: x["total_revenue_eur"], reverse=True)
    return out
