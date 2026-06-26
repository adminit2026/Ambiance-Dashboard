"""Orders list + CSV export."""
import io
import csv
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from core import db, get_current_user, build_match, parse_list

router = APIRouter()


@router.get("/orders")
async def list_orders(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    marketplaces: Optional[str] = None,
    sku: Optional[str] = None,
    limit: int = 100,
    skip: int = 0,
    user=Depends(get_current_user),
):
    match = build_match(date_from, date_to, parse_list(marketplaces), sku)
    cursor = db.orders.find(match, {"_id": 0}).sort("order_date_iso", -1).skip(skip).limit(min(limit, 500))
    docs = await cursor.to_list(min(limit, 500))
    total = await db.orders.count_documents(match)
    return {"total": total, "items": docs}


@router.get("/orders/export")
async def export_orders(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    marketplaces: Optional[str] = None,
    sku: Optional[str] = None,
    user=Depends(get_current_user),
):
    match = build_match(date_from, date_to, parse_list(marketplaces), sku)
    fields = [
        "order_date_iso", "marketplace", "channel_raw", "order_id", "sku", "product_name",
        "quantity", "unit_price", "line_total", "currency", "line_total_eur",
        "shipping_cost", "shipping_cost_eur", "vat", "status", "country", "city", "customer_email", "source",
    ]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(fields)
    async for o in db.orders.find(match, {f: 1 for f in fields}):
        w.writerow([o.get(f, "") for f in fields])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=orders_export.csv"},
    )
