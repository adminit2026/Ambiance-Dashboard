"""Orders list + XLSX export."""
import io
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from openpyxl import Workbook

from core import db, get_current_user, build_match, parse_list

router = APIRouter()

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Orders")
    ws.append(fields)
    async for o in db.orders.find(match, {f: 1 for f in fields}):
        ws.append([o.get(f, "") for f in fields])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="orders_export.xlsx"'},
    )
