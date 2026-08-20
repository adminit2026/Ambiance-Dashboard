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
    mk_vat = constants["vat_rate_by_marketplace"] or {}
    skus_in_scope = await db.orders.distinct("sku", match)
    costs_map: Dict[str, dict] = {c["sku"]: c async for c in db.costs.find({"sku": {"$in": skus_in_scope}}, {"_id": 0, "sku": 1, "cost_per_unit": 1, "shipping_cost": 1, "currency": 1})}
    cogs = 0.0
    operational_total = 0.0
    commission_total = 0.0
    async for o in db.orders.find(match, {"sku": 1, "quantity": 1, "marketplace": 1, "line_total_eur": 1}):
        qty = int(o.get("quantity") or 0)
        mk = o.get("marketplace", "")
        line_rev = float(o.get("line_total_eur") or 0)
        c = costs_map.get(o.get("sku"))
        if c:
            cogs += to_eur((c["cost_per_unit"] + c.get("shipping_cost", 0)) * qty, c.get("currency", "EUR"), rates)
        operational_total += op_cost * qty
        commission_total += line_rev * float(mk_commission.get(mk, 0)) / 100.0
    # VAT = flat percentage of Total Revenue (rev + shipping income) per marketplace,
    # ALWAYS from Settings (ignore file values). Formula: total_rev_mk × rate / 100.
    vat_pipe = [
        {"$match": match} if match else {"$match": {}},
        {"$group": {"_id": "$marketplace",
                    "rev": {"$sum": "$line_total_eur"},
                    "ship": {"$sum": "$shipping_cost_eur"}}},
    ]
    vat_total = 0.0
    async for row in db.orders.aggregate(vat_pipe):
        mk = row["_id"] or ""
        rate = float(mk_vat.get(mk, 0))
        if rate > 0:
            total_rev_mk = float(row.get("rev") or 0) + float(row.get("ship") or 0)
            vat_total += total_rev_mk * rate / 100.0
    # Production shipping is billed PER ORDER (not per unit). Count distinct orders per marketplace.
    orders_per_mk_pipe = [
        {"$match": match} if match else {"$match": {}},
        {"$group": {"_id": {"mk": "$marketplace", "oid": "$order_id"}}},
        {"$group": {"_id": "$_id.mk", "orders": {"$sum": 1}}},
    ]
    orders_per_mk_rows = await db.orders.aggregate(orders_per_mk_pipe).to_list(500)
    prod_shipping_total = sum(
        float(mk_shipping.get(r["_id"] or "", 0)) * int(r["orders"] or 0)
        for r in orders_per_mk_rows
    )
    # Customer-paid shipping is income, not an expense — add it to revenue.
    total_revenue = revenue + shipping
    total_costs = vat_total + cogs + operational_total + prod_shipping_total + commission_total
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
        "vat_eur": round(vat_total, 2),
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
    sort_by: str = Query("revenue", pattern="^(revenue|units)$"),
    user=Depends(get_current_user),
):
    """Per-SKU performance using the SAME cost formula as /dashboard/profit-loss so
    margins reconcile line-by-line with the P&L Report:

        Total Revenue = line_total_eur + shipping_cost_eur (customer shipping = income)
        Deductions    = COGS + Operational + Production Shipping + Commission
        Net Margin €  = Total Revenue − Deductions
        Margin %      = Net Margin € / Total Revenue × 100

    Operational cost and per-marketplace commission are pulled from Settings
    and applied at the ORDER-LINE level. Production shipping is billed
    per ORDER (fixed per shipment). At the SKU level we attribute the FULL
    per-order shipping cost to every SKU that participates in the order, so
    each SKU's Ship column = distinct orders containing that SKU × rate[mk].
    NOTE: sum across SKUs will exceed the marketplace P&L total when orders
    contain multiple SKUs — this is expected. The P&L stays at rate × distinct
    orders (the actual cash out).
    """
    match = build_match(date_from, date_to, parse_list(marketplaces), sku)
    constants = await get_cost_constants()
    op_cost = float(constants["operational_cost_per_unit"])
    mk_shipping = constants["production_shipping_by_marketplace"] or {}
    mk_commission = constants["commission_by_marketplace"] or {}
    rates = await get_rates()

    # Production shipping is billed per ORDER. At the SKU level, we attribute
    # the FULL per-order shipping cost to every SKU that appears in the order,
    # so each SKU's Ship = distinct orders (containing this SKU) × rate[mk].
    # This is what the user expects when auditing SKU-level margins.
    per_sku: Dict[str, dict] = {}
    async for o in db.orders.find(
        match,
        {"sku": 1, "product_name": 1, "quantity": 1, "marketplace": 1,
         "line_total_eur": 1, "shipping_cost_eur": 1, "order_id": 1},
    ):
        sku_id = o.get("sku")
        if not sku_id:
            continue
        d = per_sku.setdefault(sku_id, {
            "sku": sku_id,
            "product_name": o.get("product_name") or "",
            "units": 0,
            "orders": set(),
            "orders_by_mk": {},  # {mk: set(order_ids)} — for per-order shipping billing
            "revenue": 0.0,
            "ship_income": 0.0,
            "operational": 0.0,
            "commission": 0.0,
        })
        qty = int(o.get("quantity") or 0)
        rev = float(o.get("line_total_eur") or 0)
        ship = float(o.get("shipping_cost_eur") or 0)
        mk = o.get("marketplace") or ""
        d["units"] += qty
        d["orders"].add(o.get("order_id"))
        d["orders_by_mk"].setdefault(mk, set()).add(o.get("order_id"))
        d["revenue"] += rev
        d["ship_income"] += ship
        d["operational"] += op_cost * qty
        d["commission"] += float(mk_commission.get(mk, 0)) / 100.0 * rev
        if not d["product_name"] and o.get("product_name"):
            d["product_name"] = o.get("product_name")

    # Per-order shipping cost: rate[mk] × distinct orders (containing this SKU) on mk
    for d in per_sku.values():
        d["prod_shipping"] = sum(
            float(mk_shipping.get(mk, 0)) * len(order_ids)
            for mk, order_ids in d["orders_by_mk"].items()
        )

    skus_needed = list(per_sku.keys())
    costs_map: Dict[str, dict] = {c["sku"]: c async for c in db.costs.find(
        {"sku": {"$in": skus_needed}},
        {"_id": 0, "sku": 1, "cost_per_unit": 1, "shipping_cost": 1, "currency": 1},
    )}

    out = []
    for sku_id, d in per_sku.items():
        c = costs_map.get(sku_id)
        units = d["units"]
        cogs = 0.0
        if c:
            cogs = to_eur(
                (c["cost_per_unit"] + c.get("shipping_cost", 0)) * units,
                c.get("currency", "EUR"),
                rates,
            )
        total_revenue = d["revenue"] + d["ship_income"]
        deductions = cogs + d["operational"] + d["prod_shipping"] + d["commission"]
        margin = total_revenue - deductions
        margin_pct = (margin / total_revenue * 100) if total_revenue else 0
        out.append({
            "sku": sku_id,
            "product_name": d["product_name"],
            "units": units,
            "orders": len(d["orders"]),
            "revenue_eur": round(d["revenue"], 2),
            "ship_income_eur": round(d["ship_income"], 2),
            "total_revenue_eur": round(total_revenue, 2),
            "cogs_eur": round(cogs, 2),
            "operational_eur": round(d["operational"], 2),
            "production_shipping_eur": round(d["prod_shipping"], 2),
            "commission_eur": round(d["commission"], 2),
            "margin_eur": round(margin, 2),
            "margin_pct": round(margin_pct, 2),
            "has_cost": bool(c),
        })
    out.sort(key=lambda x: x["units"] if sort_by == "units" else x["revenue_eur"], reverse=True)
    return out[:limit]


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
    mk_vat = constants["vat_rate_by_marketplace"] or {}
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
        orders_count = len(r["orders"])
        cogs = cogs_per_mk.get(mk, 0)
        op_total = op_cost * units
        # Production shipping is billed PER ORDER (fixed per shipment), not per unit
        prod_ship = float(mk_shipping.get(mk, 0)) * orders_count
        # Commission is computed on gross revenue (line totals), not on shipping income
        commission_eur = float(mk_commission.get(mk, 0)) / 100.0 * rev
        # VAT ALWAYS from Settings — flat percentage of Total Revenue
        # (Gross Revenue + Customer Shipping), per user's business rule.
        vat_rate = float(mk_vat.get(mk, 0))
        total_revenue = rev + ship_income
        vat_eur = total_revenue * vat_rate / 100.0
        # Margin = Total Revenue − VAT − COGS − Operational − Production Shipping − Commission
        net = total_revenue - vat_eur - cogs - op_total - prod_ship - commission_eur
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
            "vat_eur": round(vat_eur, 2),
            "vat_pct": vat_rate,
            "net_profit_eur": round(net, 2),
            "margin_pct": round((net / total_revenue * 100) if total_revenue else 0, 2),
            "units": units,
            "orders": orders_count,
        })
    out.sort(key=lambda x: x["total_revenue_eur"], reverse=True)
    return out
