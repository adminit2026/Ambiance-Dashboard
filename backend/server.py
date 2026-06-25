from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import io
import csv
import re
import logging
import uuid
import bcrypt
import jwt
import pandas as pd
from datetime import datetime, timezone, timedelta, date
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field
from bson import ObjectId


# ------------------- CONFIG -------------------
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGO = "HS256"
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@ambiancesticker.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Ambiance2026!")
ADMIN_NAME = os.environ.get("ADMIN_NAME", "Ambiance Admin")

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="Ambiance Analytics Hub")
api = APIRouter(prefix="/api")

logger = logging.getLogger("ambiance")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")


# ------------------- AUTH HELPERS -------------------
def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except Exception:
        return False


def create_access_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(hours=12),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return {"id": str(user["_id"]), "email": user["email"], "name": user.get("name", ""), "role": user.get("role", "admin")}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ------------------- MODELS -------------------
class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ExchangeRateUpdate(BaseModel):
    rates: Dict[str, float]  # ISO -> rate (1 unit = X EUR)


class CostManualIn(BaseModel):
    sku: str
    product_name: Optional[str] = ""
    cost_per_unit: float
    shipping_cost: float = 0.0
    currency: str = "EUR"


# ------------------- UTILITIES -------------------
def parse_number(v) -> float:
    """Parse number that may use comma as decimal (European format)."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        if pd.isna(v):
            return 0.0
        return float(v)
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return 0.0
    # remove thousand sep, normalize decimal
    s = s.replace("\u00a0", "").replace(" ", "")
    if "," in s and "." in s:
        # likely thousand-sep ',' and decimal '.'
        s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_date(v) -> Optional[datetime]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)
    s = str(v).strip()
    if not s:
        return None
    # Try common formats
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%m/%d/%Y %H:%M:%S %z",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y",
        "%d/%m/%Y",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except ValueError:
            continue
    # last resort: pandas
    try:
        ts = pd.to_datetime(s, utc=True, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.to_pydatetime()
    except Exception:
        return None


def detect_source(filename: str, headers: List[str]) -> str:
    fn = (filename or "").lower()
    cols = [c.lower() for c in headers]
    cols_set = set(cols)
    if "po" in cols_set and "asin" in cols_set:
        return "amazon_po"
    if "marketplace" in cols_set and "order_marketplaceorderid" in cols_set:
        return "beezup"
    if any("line.merchantproductno" in c for c in cols) or any("order.channelname" in c for c in cols):
        return "channelengine"
    # filename-based fallback
    if "channelengine" in fn:
        return "channelengine"
    if "beezup" in fn:
        return "beezup"
    if "poitem" in fn or "amazon" in fn:
        return "amazon_po"
    return "unknown"


def channel_to_marketplace(channel_name: str) -> str:
    """Normalize channel/source names to canonical marketplace labels.
    Canonical list: CDiscount, Maison, Leroy Merlin, Mano Mano,
    PinkConnect Veepee - FR/BE/NL, Castorama, Maxeda - NL/BE,
    BOL.COM, Zooplus, Kaufland, Appros, Amazon Vendor, Ambiance Web.
    """
    if not channel_name:
        return "Unknown"
    n = channel_name.strip()
    low = n.lower()
    # Ambiance Web — these payment-method values represent direct sales on the brand site
    ambiance_web_keys = (
        "paiement par carte bancaire et paypal",
        "carte bancaire",
        "kredietkaart",
        "credit card",
        "tarjeta de credito",
        "ambiance web",
        "ambiance-sticker",
        "ambiancesticker",
    )
    if any(k in low for k in ambiance_web_keys):
        return "Ambiance Web"
    # Amazon Vendor
    if "amazon" in low:
        return "Amazon Vendor"
    # Leroy Merlin (incl. Polish variant LEROYMERLIN_POL)
    if "leroy" in low or "leroymerlin" in low:
        return "Leroy Merlin"
    # Castorama
    if "castorama" in low:
        return "Castorama"
    # Maison (du Monde)
    if "maison" in low or "maisondumonde" in low:
        return "Maison"
    # Mon Echelle = ManoMano alias
    if "monechelle" in low or "mon echelle" in low or "mon-echelle" in low:
        return "Mano Mano"
    # PinkConnect Veepee variants — order matters: check BEL_NL before BEL
    if "pinkconnect" in low or "veepee" in low:
        if "bel_nl" in low or "bel-nl" in low:
            return "PinkConnect Veepee - BE"
        if "_nld" in low or "-nld" in low or low.endswith("nl") or "_nl" in low or "-nl" in low:
            return "PinkConnect Veepee - NL"
        if "_bel" in low or "-bel" in low or "belgium" in low or low.endswith("be"):
            return "PinkConnect Veepee - BE"
        return "PinkConnect Veepee - FR"
    # CDiscount
    if "cdiscount" in low:
        return "CDiscount"
    # Bol.com
    if "bol.com" in low or low.startswith("bol ") or low == "bol":
        return "BOL.COM"
    # Maxeda
    if "maxeda" in low:
        if "_bel" in low or "-bel" in low or "belgium" in low:
            return "Maxeda - BE"
        return "Maxeda - NL"
    # Kaufland
    if "kaufland" in low:
        return "Kaufland"
    # Mano Mano
    if "mano" in low:
        return "Mano Mano"
    # Zooplus
    if "zooplus" in low or "zoo plus" in low:
        return "Zooplus"
    # Appros
    if "appros" in low:
        return "Appros"
    # Fallback: keep original
    return n


# ------------------- PARSERS -------------------
def parse_channelengine(content: bytes) -> List[dict]:
    """ChannelEngine CSV - comma separated, quoted, ~100 columns."""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for r in reader:
        if not r:
            continue
        order_id = r.get("Order.ChannelOrderNo") or r.get("Order.Id") or r.get("Order.MerchantOrderNo")
        sku = r.get("Line.MerchantProductNo") or r.get("Line.ChannelProductNo") or ""
        if not order_id or not sku:
            continue
        channel = r.get("Order.ChannelName", "")
        order_date = parse_date(r.get("Order.OrderDate") or r.get("Order.CreatedAt"))
        qty = int(parse_number(r.get("Line.Quantity", 1) or 1))
        unit_price = parse_number(r.get("Line.UnitPriceInclVat") or r.get("Line.UnitPriceExclVat"))
        line_total = parse_number(r.get("Line.LineTotalInclVat") or r.get("Line.LineTotalExclVat"))
        shipping = parse_number(r.get("Order.ShippingCostsInclVat") or r.get("Order.ShippingCostsExclVat"))
        vat = parse_number(r.get("Line.LineVat"))
        currency = (r.get("Order.CurrencyCode") or "EUR").strip() or "EUR"
        status = (r.get("Order.Status") or "").strip()
        country = (r.get("ShippingAddress.CountryIso") or r.get("BillingAddress.CountryIso") or "").strip()
        city = (r.get("ShippingAddress.City") or r.get("BillingAddress.City") or "").strip()
        customer_email = (r.get("Order.Email") or "").strip()
        product_name = (r.get("Line.ProductName") or "").strip()
        rows.append({
            "source": "channelengine",
            "marketplace": channel_to_marketplace(channel),
            "channel_raw": channel,
            "order_id": str(order_id),
            "line_key": f"{order_id}::{sku}",
            "sku": str(sku).strip(),
            "product_name": product_name,
            "quantity": qty,
            "unit_price": unit_price,
            "line_total": line_total,
            "shipping_cost": shipping,
            "vat": vat,
            "currency": currency,
            "order_date": order_date,
            "status": status,
            "country": country,
            "city": city,
            "customer_email": customer_email,
        })
    return rows


def parse_beezup(content: bytes) -> List[dict]:
    df = pd.read_excel(io.BytesIO(content), sheet_name=0, dtype=str)
    df = df.fillna("")
    rows = []
    for _, r in df.iterrows():
        marketplace = channel_to_marketplace(r.get("MarketPlace", ""))
        order_id = (r.get("Order_MarketPlaceOrderId") or r.get("Order_MerchantOrderId") or "").strip()
        sku = (r.get("OrderItem_MerchantProductId") or "").strip()
        if not order_id or not sku:
            continue
        order_date = parse_date(r.get("Order_PurchaseUtcDate"))
        qty = int(parse_number(r.get("OrderItem_Quantity") or 1))
        unit_price = parse_number(r.get("OrderItem_ItemPrice"))
        line_total = parse_number(r.get("OrderItem_TotalPrice"))
        shipping = parse_number(r.get("OrderItem_Shipping_Price") or r.get("Order_Shipping_Price"))
        vat = parse_number(r.get("OrderItem_ItemTax"))
        currency = (r.get("Order_CurrencyCode") or "EUR").strip() or "EUR"
        status = (r.get("Order_Status_BeezUPOrderStatus") or "").strip()
        country = (r.get("Order_Shipping_AddressCountryIsoCodeAlpha2") or "").strip()
        city = (r.get("Order_Shipping_AddressCity") or "").strip()
        customer_email = (r.get("Order_Buyer_Email") or "").strip()
        product_name = (r.get("OrderItem_Title") or "").strip()
        rows.append({
            "source": "beezup",
            "marketplace": marketplace,
            "channel_raw": r.get("MarketPlace", ""),
            "order_id": order_id,
            "line_key": f"{order_id}::{sku}",
            "sku": sku,
            "product_name": product_name,
            "quantity": qty,
            "unit_price": unit_price,
            "line_total": line_total,
            "shipping_cost": shipping,
            "vat": vat,
            "currency": currency,
            "order_date": order_date,
            "status": status,
            "country": country,
            "city": city,
            "customer_email": customer_email,
        })
    return rows


def parse_amazon_po(content: bytes) -> List[dict]:
    # Try xls first, then xlsx
    try:
        df = pd.read_excel(io.BytesIO(content), sheet_name=0, engine="xlrd")
    except Exception:
        df = pd.read_excel(io.BytesIO(content), sheet_name=0)
    rows = []

    def s(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        return str(v).strip()

    for _, r in df.iterrows():
        po = s(r.get("PO"))
        sku = s(r.get("Merchant SKU")) or s(r.get("ASIN"))
        if not po or not sku or sku.lower() in ("nan", "none"):
            continue
        order_date = parse_date(r.get("Order date"))
        qty_req = int(parse_number(r.get("Requested quantity") or 0))
        qty_acc = int(parse_number(r.get("Accepted quantity") or 0))
        qty = qty_acc or qty_req
        unit_cost = parse_number(r.get("Cost"))
        total_acc = parse_number(r.get("Total accepted cost") or 0)
        total_req = parse_number(r.get("Total requested cost") or 0)
        line_total = total_acc if total_acc else (total_req if total_req else unit_cost * qty)
        currency = s(r.get("Currency")) or "EUR"
        ship_to = s(r.get("Ship-to location"))
        product_name = s(r.get("Product name"))
        status = s(r.get("Status"))
        rows.append({
            "source": "amazon_po",
            "marketplace": "Amazon Vendor",
            "channel_raw": "Amazon Vendor PO",
            "order_id": po,
            "line_key": f"{po}::{sku}",
            "sku": sku,
            "product_name": product_name,
            "quantity": qty,
            "unit_price": unit_cost,
            "line_total": line_total,
            "shipping_cost": 0.0,
            "vat": 0.0,
            "currency": currency,
            "order_date": order_date,
            "status": status,
            "country": ship_to,
            "city": ship_to,
            "customer_email": "",
        })
    return rows


def parse_cost_file(content: bytes, filename: str) -> List[dict]:
    """Cost upload. Supports two formats:
    1) Standard template (CSV/XLSX) with columns: sku, cost_per_unit (or cost), shipping_cost (opt), product_name (opt), currency (opt).
    2) Ambiance legacy workbook 'CostProdShippingCalc' with Sheet3, header on row 3 (idx 2),
       SKU in column A, 'Cout de Production' in column L (idx 11),
       'FBM Frais poste + packaging' in column M (idx 12).
    """
    fn = (filename or "").lower()
    # Detect legacy Ambiance workbook by sheet name
    if not fn.endswith(".csv"):
        try:
            xl = pd.ExcelFile(io.BytesIO(content), engine="openpyxl")
            sheets_lower = [s.lower() for s in xl.sheet_names]
            if "sheet3" in sheets_lower:
                # Legacy ambiance cost workbook
                raw = pd.read_excel(io.BytesIO(content), sheet_name="Sheet3", header=None, engine="openpyxl")
                # Use row index 2 as header
                headers = [str(x).strip() if pd.notna(x) else "" for x in raw.iloc[2].tolist()]
                data = raw.iloc[3:].reset_index(drop=True)
                data.columns = headers + [f"_col{i}" for i in range(len(data.columns) - len(headers))] if len(data.columns) > len(headers) else headers[: len(data.columns)]
                out = []
                for _, r in data.iterrows():
                    sku = r.get("SKU")
                    if not isinstance(sku, str):
                        if pd.isna(sku):
                            continue
                        sku = str(sku).strip()
                    sku = sku.strip()
                    if not sku or sku.lower() in ("sample", "sku", "nan"):
                        continue
                    cost = parse_number(r.get("Cout de Production"))
                    if cost <= 0:
                        continue
                    shipping = parse_number(r.get("FBM Frais poste + packaging") or r.get("FBA SHIPPING") or 0)
                    out.append({
                        "sku": sku,
                        "product_name": (str(r.get("Product description")).strip() if pd.notna(r.get("Product description")) else ""),
                        "cost_per_unit": cost,
                        "shipping_cost": shipping,
                        "currency": "EUR",
                    })
                return out
        except Exception:
            pass

    # Fallback: standard template parsing
    if fn.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        df = pd.read_csv(io.StringIO(text))
    else:
        try:
            df = pd.read_excel(io.BytesIO(content), engine="openpyxl")
        except Exception:
            df = pd.read_excel(io.BytesIO(content))
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    def pick(row, *keys):
        for k in keys:
            if k in row and not pd.isna(row[k]):
                return row[k]
        return None
    out = []
    for _, r in df.iterrows():
        row = r.to_dict()
        sku = pick(row, "sku", "merchant_sku", "merchant_product_id")
        if not sku or (isinstance(sku, float) and pd.isna(sku)):
            continue
        cost = parse_number(pick(row, "cost_per_unit", "cost", "production_cost", "cout_de_production", "unit_cost"))
        if cost <= 0:
            continue
        shipping = parse_number(pick(row, "shipping_cost", "shipping", "fbm_shipping", "frais_poste", "fbm_frais_poste_+_packaging"))
        product_name = str(pick(row, "product_name", "title", "description", "product_description") or "").strip()
        currency = str(pick(row, "currency") or "EUR").strip() or "EUR"
        out.append({
            "sku": str(sku).strip(),
            "product_name": product_name,
            "cost_per_unit": cost,
            "shipping_cost": shipping,
            "currency": currency,
        })
    return out


# ------------------- STARTUP -------------------
async def get_rates() -> Dict[str, float]:
    doc = await db.settings.find_one({"_id": "exchange_rates"})
    if not doc:
        defaults = {"EUR": 1.0, "USD": 0.92, "GBP": 1.17, "PLN": 0.23, "SEK": 0.087, "DKK": 0.134, "CHF": 1.05, "CZK": 0.04, "NOK": 0.085}
        await db.settings.update_one({"_id": "exchange_rates"}, {"$set": {"rates": defaults}}, upsert=True)
        return defaults
    return doc.get("rates", {"EUR": 1.0})


async def get_cost_constants() -> Dict[str, Any]:
    """Returns {'operational_cost_per_unit': float, 'production_shipping_by_marketplace': {mk: float}}"""
    doc = await db.settings.find_one({"_id": "cost_constants"})
    if not doc:
        defaults = {"operational_cost_per_unit": 0.5, "production_shipping_by_marketplace": {}}
        await db.settings.update_one({"_id": "cost_constants"}, {"$set": defaults}, upsert=True)
        return defaults
    return {
        "operational_cost_per_unit": float(doc.get("operational_cost_per_unit", 0.5)),
        "production_shipping_by_marketplace": doc.get("production_shipping_by_marketplace", {}),
    }


def to_eur(amount: float, currency: str, rates: Dict[str, float]) -> float:
    c = (currency or "EUR").upper()
    return amount * rates.get(c, 1.0)


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


@app.on_event("shutdown")
async def on_shutdown():
    client.close()


# ------------------- AUTH ROUTES -------------------
@api.post("/auth/login")
async def login(payload: LoginIn, response: Response):
    email = payload.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(str(user["_id"]), user["email"])
    response.set_cookie("access_token", token, httponly=True, samesite="lax", max_age=12 * 3600, path="/")
    return {
        "token": token,
        "user": {"id": str(user["_id"]), "email": user["email"], "name": user.get("name", ""), "role": user.get("role", "admin")},
    }


@api.post("/auth/logout")
async def logout(response: Response, user=Depends(get_current_user)):
    response.delete_cookie("access_token", path="/")
    return {"ok": True}


@api.get("/auth/me")
async def me(user=Depends(get_current_user)):
    return user


# ------------------- UPLOADS -------------------
@api.post("/uploads/orders")
async def upload_orders(file: UploadFile = File(...), source: str = Form("auto"), user=Depends(get_current_user)):
    content = await file.read()
    filename = file.filename or "uploaded"
    # detect headers if auto
    if source == "auto":
        try:
            if filename.lower().endswith(".csv"):
                text = content.decode("utf-8-sig", errors="replace")
                headers = next(csv.reader(io.StringIO(text)))
            else:
                try:
                    df_head = pd.read_excel(io.BytesIO(content), nrows=0)
                except Exception:
                    df_head = pd.read_excel(io.BytesIO(content), nrows=0, engine="xlrd")
                headers = list(df_head.columns)
            source = detect_source(filename, headers)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not detect source: {e}")

    if source not in ("channelengine", "beezup", "amazon_po"):
        raise HTTPException(status_code=400, detail=f"Unknown source '{source}'. Specify channelengine, beezup, or amazon_po.")

    try:
        if source == "channelengine":
            rows = parse_channelengine(content)
        elif source == "beezup":
            rows = parse_beezup(content)
        else:
            rows = parse_amazon_po(content)
    except Exception as e:
        logger.exception("Parse error")
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {e}")

    rates = await get_rates()
    inserted, updated = 0, 0
    for r in rows:
        r["order_date_iso"] = r["order_date"].isoformat() if r["order_date"] else None
        r["line_total_eur"] = to_eur(r["line_total"], r["currency"], rates)
        r["shipping_cost_eur"] = to_eur(r["shipping_cost"], r["currency"], rates)
        res = await db.orders.update_one(
            {"line_key": r["line_key"]},
            {"$set": r, "$setOnInsert": {"created_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
        if res.upserted_id:
            inserted += 1
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
    })
    return {"source": source, "rows_total": len(rows), "inserted": inserted, "updated": updated}


@api.post("/uploads/costs")
async def upload_costs(file: UploadFile = File(...), user=Depends(get_current_user)):
    content = await file.read()
    rows = parse_cost_file(content, file.filename or "")
    if not rows:
        raise HTTPException(status_code=400, detail="No valid cost rows found. Ensure 'sku' and 'cost_per_unit' columns exist.")
    inserted, updated = 0, 0
    for r in rows:
        r["updated_at"] = datetime.now(timezone.utc).isoformat()
        res = await db.costs.update_one({"sku": r["sku"]}, {"$set": r}, upsert=True)
        if res.upserted_id:
            inserted += 1
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
    })
    return {"rows_total": len(rows), "inserted": inserted, "updated": updated}


@api.get("/uploads/history")
async def uploads_history(user=Depends(get_current_user)):
    docs = await db.uploads.find({}, {"_id": 0}).sort("uploaded_at", -1).to_list(100)
    return docs


# ------------------- COSTS -------------------
@api.get("/costs")
async def list_costs(user=Depends(get_current_user)):
    docs = await db.costs.find({}, {"_id": 0}).sort("sku", 1).to_list(5000)
    return docs


@api.post("/costs/manual")
async def manual_cost(payload: CostManualIn, user=Depends(get_current_user)):
    doc = payload.model_dump()
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.costs.update_one({"sku": payload.sku}, {"$set": doc}, upsert=True)
    return {"ok": True}


@api.delete("/costs/{sku}")
async def delete_cost(sku: str, user=Depends(get_current_user)):
    await db.costs.delete_one({"sku": sku})
    return {"ok": True}


# ------------------- EXCHANGE RATES -------------------
@api.get("/exchange-rates")
async def get_exchange_rates(user=Depends(get_current_user)):
    return await get_rates()


@api.put("/exchange-rates")
async def update_exchange_rates(payload: ExchangeRateUpdate, user=Depends(get_current_user)):
    rates = {k.upper(): float(v) for k, v in payload.rates.items()}
    rates["EUR"] = 1.0
    await db.settings.update_one({"_id": "exchange_rates"}, {"$set": {"rates": rates}}, upsert=True)
    # Recompute EUR amounts on all orders
    async for o in db.orders.find({}, {"_id": 1, "line_total": 1, "shipping_cost": 1, "currency": 1}):
        await db.orders.update_one(
            {"_id": o["_id"]},
            {"$set": {
                "line_total_eur": to_eur(o.get("line_total", 0), o.get("currency", "EUR"), rates),
                "shipping_cost_eur": to_eur(o.get("shipping_cost", 0), o.get("currency", "EUR"), rates),
            }},
        )
    return rates


# ------------------- FILTER HELPER -------------------
def build_match(date_from: Optional[str], date_to: Optional[str], marketplaces: Optional[List[str]], sku: Optional[str]):
    m: Dict[str, Any] = {}
    if date_from or date_to:
        m["order_date_iso"] = {}
        if date_from:
            m["order_date_iso"]["$gte"] = date_from
        if date_to:
            m["order_date_iso"]["$lte"] = date_to + "T23:59:59"
    if marketplaces:
        m["marketplace"] = {"$in": marketplaces}
    if sku:
        m["sku"] = {"$regex": re.escape(sku), "$options": "i"}
    return m


def parse_list(q: Optional[str]) -> Optional[List[str]]:
    if not q:
        return None
    return [s.strip() for s in q.split(",") if s.strip()]


# ------------------- DASHBOARD -------------------
@api.get("/dashboard/summary")
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

    # COGS via per-sku cost lookup + constants
    costs_map: Dict[str, dict] = {c["sku"]: c async for c in db.costs.find({}, {"_id": 0})}
    rates = await get_rates()
    constants = await get_cost_constants()
    op_cost = float(constants["operational_cost_per_unit"])
    mk_shipping = constants["production_shipping_by_marketplace"] or {}
    cogs = 0.0
    operational_total = 0.0
    prod_shipping_total = 0.0
    async for o in db.orders.find(match, {"sku": 1, "quantity": 1, "currency": 1, "marketplace": 1}):
        qty = int(o.get("quantity") or 0)
        c = costs_map.get(o.get("sku"))
        if c:
            cogs += to_eur((c["cost_per_unit"] + c.get("shipping_cost", 0)) * qty, c.get("currency", "EUR"), rates)
        operational_total += op_cost * qty
        prod_shipping_total += float(mk_shipping.get(o.get("marketplace", ""), 0)) * qty
    total_costs = cogs + shipping + operational_total + prod_shipping_total
    margin = revenue - total_costs
    margin_pct = (margin / revenue * 100) if revenue else 0
    return {
        "revenue_eur": round(revenue, 2),
        "shipping_eur": round(shipping, 2),
        "orders": orders_count,
        "units": units,
        "lines": lines,
        "aov_eur": round(aov, 2),
        "cogs_eur": round(cogs, 2),
        "operational_eur": round(operational_total, 2),
        "production_shipping_eur": round(prod_shipping_total, 2),
        "margin_eur": round(margin, 2),
        "margin_pct": round(margin_pct, 2),
    }


@api.get("/dashboard/trend")
async def dashboard_trend(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    marketplaces: Optional[str] = None,
    sku: Optional[str] = None,
    granularity: str = Query("day", pattern="^(day|month)$"),
    user=Depends(get_current_user),
):
    match = build_match(date_from, date_to, parse_list(marketplaces), sku)
    match["order_date_iso"] = match.get("order_date_iso", {})
    match["order_date_iso"]["$ne"] = None
    if match["order_date_iso"] == {"$ne": None}:
        pass
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
        if period not in out:
            out[period] = {"period": period, "revenue_total": 0, "by_marketplace": {}, "orders_total": 0, "units_total": 0}
        out[period]["by_marketplace"][mk] = round(float(r["revenue"] or 0), 2)
        out[period]["revenue_total"] += float(r["revenue"] or 0)
        out[period]["orders_total"] += len(r["orders"])
        out[period]["units_total"] += int(r["units"] or 0)
    series = sorted(out.values(), key=lambda x: x["period"])
    for s in series:
        s["revenue_total"] = round(s["revenue_total"], 2)
    return series


@api.get("/dashboard/marketplace-breakdown")
async def marketplace_breakdown(
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
            "_id": "$marketplace",
            "revenue": {"$sum": "$line_total_eur"},
            "shipping": {"$sum": "$shipping_cost_eur"},
            "units": {"$sum": "$quantity"},
            "orders": {"$addToSet": "$order_id"},
        }},
        {"$sort": {"revenue": -1}},
    ]
    rows = await db.orders.aggregate(pipeline).to_list(100)
    return [{
        "marketplace": r["_id"] or "Unknown",
        "revenue_eur": round(float(r["revenue"] or 0), 2),
        "shipping_eur": round(float(r["shipping"] or 0), 2),
        "units": int(r["units"] or 0),
        "orders": len(r["orders"]),
        "aov_eur": round(float(r["revenue"] or 0) / len(r["orders"]), 2) if r["orders"] else 0,
    } for r in rows]


@api.get("/dashboard/top-skus")
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
    costs_map: Dict[str, dict] = {c["sku"]: c async for c in db.costs.find({}, {"_id": 0})}
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


@api.get("/dashboard/customers")
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


@api.get("/dashboard/heatmap")
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


@api.get("/dashboard/profit-loss")
async def profit_loss(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    marketplaces: Optional[str] = None,
    sku: Optional[str] = None,
    user=Depends(get_current_user),
):
    match = build_match(date_from, date_to, parse_list(marketplaces), sku)
    costs_map: Dict[str, dict] = {c["sku"]: c async for c in db.costs.find({}, {"_id": 0})}
    rates = await get_rates()
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
    # compute COGS per marketplace
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
        ship = float(r["shipping"] or 0)
        units = int(r["units"] or 0)
        cogs = cogs_per_mk.get(mk, 0)
        op_total = op_cost * units
        prod_ship = float(mk_shipping.get(mk, 0)) * units
        net = rev - cogs - ship - op_total - prod_ship
        out.append({
            "marketplace": mk,
            "revenue_eur": round(rev, 2),
            "cogs_eur": round(cogs, 2),
            "shipping_eur": round(ship, 2),
            "operational_eur": round(op_total, 2),
            "production_shipping_eur": round(prod_ship, 2),
            "vat_eur": round(float(r["vat"] or 0), 2),
            "net_profit_eur": round(net, 2),
            "margin_pct": round((net / rev * 100) if rev else 0, 2),
            "units": units,
            "orders": len(r["orders"]),
        })
    out.sort(key=lambda x: x["revenue_eur"], reverse=True)
    return out


# ------------------- ORDERS LIST + EXPORT -------------------
@api.get("/orders")
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


@api.get("/orders/export")
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


# ------------------- COST CONSTANTS -------------------
class CostConstantsUpdate(BaseModel):
    operational_cost_per_unit: float
    production_shipping_by_marketplace: Dict[str, float]


@api.get("/cost-constants")
async def get_cost_constants_endpoint(user=Depends(get_current_user)):
    return await get_cost_constants()


@api.put("/cost-constants")
async def update_cost_constants(payload: CostConstantsUpdate, user=Depends(get_current_user)):
    doc = {
        "operational_cost_per_unit": float(payload.operational_cost_per_unit),
        "production_shipping_by_marketplace": {
            k: float(v) for k, v in (payload.production_shipping_by_marketplace or {}).items()
        },
    }
    await db.settings.update_one({"_id": "cost_constants"}, {"$set": doc}, upsert=True)
    return doc


# ------------------- LIBRARY -------------------
@api.get("/library/skus")
async def library_skus(
    search: Optional[str] = None,
    limit: int = 5000,
    user=Depends(get_current_user),
):
    """Return all SKUs (from orders ∪ costs) with their cost breakdown."""
    constants = await get_cost_constants()
    op_cost = float(constants["operational_cost_per_unit"])
    # gather all SKUs from orders
    order_skus = await db.orders.aggregate([
        {"$group": {"_id": "$sku", "product_name": {"$first": "$product_name"}, "units": {"$sum": "$quantity"}}},
    ]).to_list(20000)
    order_map = {r["_id"]: r for r in order_skus if r["_id"]}
    # costs
    costs_map = {c["sku"]: c async for c in db.costs.find({}, {"_id": 0})}
    all_skus = set(order_map.keys()) | set(costs_map.keys())
    if search:
        q = search.lower()
        all_skus = {s for s in all_skus if q in s.lower() or q in (order_map.get(s, {}).get("product_name") or costs_map.get(s, {}).get("product_name") or "").lower()}
    out = []
    for sku in all_skus:
        o = order_map.get(sku, {})
        c = costs_map.get(sku, {})
        production_cost = float(c.get("cost_per_unit", 0)) if c else 0
        prod_shipping = float(c.get("shipping_cost", 0)) if c else 0
        product_name = o.get("product_name") or c.get("product_name") or ""
        units_sold = int(o.get("units", 0) or 0)
        total = production_cost + op_cost + prod_shipping
        out.append({
            "sku": sku,
            "product_name": product_name,
            "production_cost": round(production_cost, 4),
            "operational_cost": round(op_cost, 4),
            "production_shipping_cost": round(prod_shipping, 4),
            "total_cost": round(total, 4),
            "units_sold": units_sold,
            "has_cost": bool(c),
        })
    out.sort(key=lambda x: x["units_sold"], reverse=True)
    return out[:limit]


@api.get("/library/export")
async def library_export(user=Depends(get_current_user)):
    rows = await library_skus(limit=20000, user=user)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["SKU", "Product", "Production Cost (EUR)", "Operational Cost (EUR)", "Production Shipping Cost (EUR)", "Total Cost (EUR)", "Units Sold"])
    for r in rows:
        w.writerow([r["sku"], r["product_name"], r["production_cost"], r["operational_cost"], r["production_shipping_cost"], r["total_cost"], r["units_sold"]])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=cost_library.csv"},
    )


@api.get("/marketplaces")
async def list_marketplaces(user=Depends(get_current_user)):
    mks = await db.orders.distinct("marketplace")
    return sorted([m for m in mks if m])


@api.post("/admin/renormalize-marketplaces")
async def renormalize_marketplaces(user=Depends(get_current_user)):
    """Re-apply channel_to_marketplace mapping to all existing orders."""
    from pymongo import UpdateOne
    bulk = []
    changed = 0
    async for o in db.orders.find({}, {"_id": 1, "channel_raw": 1, "marketplace": 1}):
        new_mk = channel_to_marketplace(o.get("channel_raw") or o.get("marketplace") or "")
        if new_mk != o.get("marketplace"):
            bulk.append(UpdateOne({"_id": o["_id"]}, {"$set": {"marketplace": new_mk}}))
            changed += 1
        if len(bulk) >= 500:
            await db.orders.bulk_write(bulk)
            bulk = []
    if bulk:
        await db.orders.bulk_write(bulk)
    return {"updated": changed}


@api.get("/skus")
async def list_skus(user=Depends(get_current_user), limit: int = 500):
    pipeline = [
        {"$group": {"_id": "$sku", "product_name": {"$first": "$product_name"}, "units": {"$sum": "$quantity"}}},
        {"$sort": {"units": -1}},
        {"$limit": limit},
    ]
    rows = await db.orders.aggregate(pipeline).to_list(limit)
    return [{"sku": r["_id"], "product_name": r["product_name"] or "", "units": int(r["units"] or 0)} for r in rows]


@api.get("/skus/prices")
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
    # Pivot into {sku, product_name, prices: { marketplace: { avg, min, max, units, currency, last_order } } }
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
    # Sort by total units desc, apply limit
    items = sorted(by_sku.values(), key=lambda x: x["total_units"], reverse=True)[:limit]
    # Collect marketplaces present
    marketplaces_present = sorted({mk for it in items for mk in it["prices"].keys()})
    return {"marketplaces": marketplaces_present, "items": items}


@api.get("/skus/prices/export")
async def sku_prices_export(
    sku: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    marketplaces: Optional[str] = None,
    user=Depends(get_current_user),
):
    data = await sku_prices(sku=sku, date_from=date_from, date_to=date_to, marketplaces=marketplaces, limit=10000, user=user)
    mks = data["marketplaces"]
    buf = io.StringIO()
    w = csv.writer(buf)
    header = ["SKU", "Product"] + [f"{m} (avg)" for m in mks] + [f"{m} (units)" for m in mks]
    w.writerow(header)
    for it in data["items"]:
        row = [it["sku"], it["product_name"]]
        for m in mks:
            p = it["prices"].get(m)
            row.append(p["avg"] if p else "")
        for m in mks:
            p = it["prices"].get(m)
            row.append(p["units"] if p else "")
        w.writerow(row)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sku_prices.csv"},
    )


@api.get("/templates/cost")
async def download_cost_template(user=Depends(get_current_user)):
    """Generate a cost-upload template pre-filled with all SKUs currently in orders.
    Columns: sku, product_name, cost_per_unit, shipping_cost, currency.
    Existing costs are pre-populated so the user can edit and re-upload."""
    # Pull all unique SKUs from orders
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


@api.get("/")
async def root():
    return {"app": "Ambiance Analytics Hub", "status": "ok"}


# Register router and CORS
app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
