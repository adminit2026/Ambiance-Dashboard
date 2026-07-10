"""Upload + ASIN/SKU mapping + template routes."""
import io
import csv
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
import pandas as pd

from core import (
    db, logger, get_current_user, require_admin,
    detect_source, parse_channelengine, parse_beezup, parse_amazon_po,
    parse_amazon_edit_line_items, parse_ambiance_web,
    apply_asin_mapping, parse_asin_mapping, parse_cost_file,
    get_rates, to_eur, remap_amazon_orders,
)

router = APIRouter()


@router.post("/uploads/orders")
async def upload_orders(file: UploadFile = File(...), source: str = Form("auto"), user=Depends(require_admin)):
    content = await file.read()
    filename = file.filename or "uploaded"
    if source == "auto":
        try:
            if filename.lower().endswith(".csv"):
                text = content.decode("utf-8-sig", errors="replace")
                # Detect delimiter on the first line — ChannelEngine exports may use ; for EU files.
                first_line = next((ln for ln in text.splitlines() if ln.strip()), "")
                try:
                    delim = csv.Sniffer().sniff(first_line, delimiters=",;\t").delimiter
                except csv.Error:
                    delim = ";" if first_line.count(";") > first_line.count(",") else ","
                headers = next(csv.reader(io.StringIO(text), delimiter=delim))
            else:
                # Read sheet 0 headers; if the file has a 'Commandes' sheet (Ambiance Web) prefer that
                try:
                    xl = pd.ExcelFile(io.BytesIO(content))
                    sheet = "Commandes" if "Commandes" in xl.sheet_names else xl.sheet_names[0]
                    df_head = pd.read_excel(io.BytesIO(content), sheet_name=sheet, nrows=0)
                except Exception:
                    df_head = pd.read_excel(io.BytesIO(content), nrows=0, engine="xlrd")
                headers = list(df_head.columns)
            source = detect_source(filename, headers)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not detect source: {e}")

    if source not in ("channelengine", "beezup", "amazon_po", "amazon_edit", "ambiance_web"):
        raise HTTPException(status_code=400, detail=f"Unknown source '{source}'. Specify channelengine, beezup, amazon_po, amazon_edit, or ambiance_web.")

    try:
        if source == "channelengine":
            rows = parse_channelengine(content)
        elif source == "beezup":
            rows = parse_beezup(content)
        elif source == "amazon_edit":
            rows = parse_amazon_edit_line_items(content)
            rows = await apply_asin_mapping(rows)
        elif source == "ambiance_web":
            rows = parse_ambiance_web(content, filename)
        else:
            rows = parse_amazon_po(content)
            rows = await apply_asin_mapping(rows)
    except Exception as e:
        logger.exception("Parse error")
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {e}")

    rates = await get_rates()
    inserted, updated = 0, 0
    inserted_keys: List[str] = []
    for r in rows:
        r["order_date_iso"] = r["order_date"].isoformat() if r["order_date"] else None
        # Amazon edit line items: persist delivery / window-start iso strings too
        if r.get("delivery_date"):
            r["delivery_date_iso"] = r["delivery_date"].isoformat()
        if r.get("window_start_date"):
            r["window_start_date_iso"] = r["window_start_date"].isoformat()
        r["line_total_eur"] = to_eur(r["line_total"], r["currency"], rates)
        r["shipping_cost_eur"] = to_eur(r["shipping_cost"], r["currency"], rates)
        res = await db.orders.update_one(
            {"line_key": r["line_key"]},
            {"$set": r, "$setOnInsert": {"created_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
        if res.upserted_id:
            inserted += 1
            inserted_keys.append(r["line_key"])
        elif res.modified_count:
            updated += 1

    await db.uploads.insert_one({
        "filename": filename,
        "source": source,
        "rows_total": len(rows),
        "inserted": inserted,
        "updated": updated,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "by": user["email"],
        "inserted_keys": inserted_keys,  # Used by DELETE /uploads/{id} to reverse this upload
        "target_collection": "orders",
    })
    return {"source": source, "rows_total": len(rows), "inserted": inserted, "updated": updated}


@router.post("/uploads/costs")
async def upload_costs(file: UploadFile = File(...), user=Depends(require_admin)):
    content = await file.read()
    rows = parse_cost_file(content, file.filename or "")
    if not rows:
        raise HTTPException(status_code=400, detail="No valid cost rows found. Ensure 'sku' and 'cost_per_unit' columns exist.")
    inserted, updated = 0, 0
    inserted_keys: List[str] = []
    for r in rows:
        r["updated_at"] = datetime.now(timezone.utc).isoformat()
        res = await db.costs.update_one({"sku": r["sku"]}, {"$set": r}, upsert=True)
        if res.upserted_id:
            inserted += 1
            inserted_keys.append(r["sku"])
        else:
            updated += 1
    await db.uploads.insert_one({
        "filename": file.filename,
        "source": "costs",
        "rows_total": len(rows),
        "inserted": inserted,
        "updated": updated,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "by": user["email"],
        "inserted_keys": inserted_keys,
        "target_collection": "costs",
    })
    return {"rows_total": len(rows), "inserted": inserted, "updated": updated}


@router.get("/uploads/history")
async def uploads_history(user=Depends(get_current_user)):
    docs = await db.uploads.find({}).sort("uploaded_at", -1).to_list(100)
    # Convert _id to string id, drop the heavy inserted_keys list from the payload
    for d in docs:
        d["id"] = str(d.pop("_id"))
        d.pop("inserted_keys", None)
    return docs


@router.delete("/uploads/{upload_id}")
async def delete_upload(upload_id: str, user=Depends(require_admin)):
    """Reverse a prior upload: delete every row this upload originally inserted.
    Rows that this upload only *updated* are left alone (we can't restore prior values).
    Then delete the upload history entry itself.
    """
    from bson import ObjectId
    try:
        oid = ObjectId(upload_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid upload id")
    doc = await db.uploads.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Upload not found")
    keys = doc.get("inserted_keys") or []
    target = doc.get("target_collection")
    removed = 0
    if keys and target == "orders":
        r = await db.orders.delete_many({"line_key": {"$in": keys}})
        removed = r.deleted_count
    elif keys and target == "costs":
        r = await db.costs.delete_many({"sku": {"$in": keys}})
        removed = r.deleted_count
    elif keys and target == "sku_mappings":
        r = await db.sku_mappings.delete_many({"_id": {"$in": [ObjectId(k) for k in keys if len(k) == 24]}})
        removed = r.deleted_count
    await db.uploads.delete_one({"_id": oid})
    return {"upload_id": upload_id, "removed": removed, "filename": doc.get("filename"), "source": doc.get("source")}


@router.post("/uploads/asin-mapping")
async def upload_asin_mapping(file: UploadFile = File(...), user=Depends(require_admin)):
    content = await file.read()
    rows = parse_asin_mapping(content, file.filename or "")
    if not rows:
        raise HTTPException(status_code=400, detail="No valid rows. File must have 'asin' + 'merchant_sku' OR (SKU + Leroy Merlin ID + Amazon ASIN) columns.")
    inserted = updated = 0
    inserted_keys: List[str] = []
    asin_legacy_count = 0
    for r in rows:
        r["updated_at"] = datetime.now(timezone.utc).isoformat()
        res = await db.sku_mappings.update_one(
            {"marketplace": r["marketplace"], "external_id": r["external_id"]},
            {"$set": r},
            upsert=True,
        )
        if res.upserted_id:
            inserted += 1
            inserted_keys.append(str(res.upserted_id))
        else:
            updated += 1
        if r["marketplace"] == "Amazon Vendor":
            await db.asin_mappings.update_one(
                {"asin": r["external_id"]},
                {"$set": {"asin": r["external_id"], "merchant_sku": r["merchant_sku"], "product_name": r.get("product_name", ""), "updated_at": r["updated_at"]}},
                upsert=True,
            )
            asin_legacy_count += 1
    await db.uploads.insert_one({
        "filename": file.filename, "source": "sku_mapping",
        "rows_total": len(rows), "inserted": inserted, "updated": updated,
        "uploaded_at": datetime.now(timezone.utc).isoformat(), "by": user["email"],
        "inserted_keys": inserted_keys, "target_collection": "sku_mappings",
    })
    remapped = await remap_amazon_orders()
    return {"rows_total": len(rows), "inserted": inserted, "updated": updated, "orders_remapped": remapped}


@router.get("/asin-mappings")
async def list_asin_mappings(search: Optional[str] = None, limit: int = 5000, user=Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if search:
        s = re.escape(search)
        q["$or"] = [{"asin": {"$regex": s, "$options": "i"}}, {"merchant_sku": {"$regex": s, "$options": "i"}}]
    docs = await db.asin_mappings.find(q, {"_id": 0}).sort("updated_at", -1).to_list(limit)
    return docs


@router.get("/templates/asin-mapping")
async def asin_mapping_template(user=Depends(get_current_user)):
    pipeline = [
        {"$match": {"source": "amazon_po"}},
        {"$group": {"_id": "$asin", "product_name": {"$first": "$product_name"}, "units": {"$sum": "$quantity"}, "current_sku": {"$first": "$sku"}}},
        {"$sort": {"units": -1}},
    ]
    asins = await db.orders.aggregate(pipeline).to_list(10000)
    existing = {m["asin"]: m async for m in db.asin_mappings.find({}, {"_id": 0})}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["asin", "merchant_sku", "product_name", "units_sold"])
    for a in asins:
        asin = a["_id"]
        if not asin:
            continue
        existing_map = existing.get(asin, {})
        merchant_sku = existing_map.get("merchant_sku") or (a.get("current_sku") if a.get("current_sku") != asin else "")
        w.writerow([asin, merchant_sku, a.get("product_name") or "", a.get("units", 0)])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=asin_mapping_template.csv"},
    )


@router.get("/templates/cost")
async def download_cost_template(user=Depends(get_current_user)):
    pipeline = [
        {"$group": {"_id": "$sku", "product_name": {"$first": "$product_name"}, "units": {"$sum": "$quantity"}}},
        {"$sort": {"units": -1}},
    ]
    skus = await db.orders.aggregate(pipeline).to_list(20000)
    costs_map = {c["sku"]: c async for c in db.costs.find({}, {"_id": 0})}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["sku", "product_name", "cost_per_unit", "shipping_cost", "currency"])
    for s in skus:
        sku_id = s["_id"]
        c = costs_map.get(sku_id, {})
        w.writerow([
            sku_id,
            s.get("product_name") or c.get("product_name") or "",
            c.get("cost_per_unit", ""),
            c.get("shipping_cost", ""),
            c.get("currency", "EUR"),
        ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=cost_template.csv"},
    )
