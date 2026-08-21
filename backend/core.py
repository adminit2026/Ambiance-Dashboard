"""Shared backend primitives: db client, config, models, auth helpers, parsers,
util functions and settings store. Imported by every router module."""
from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env", override=False)

import os
import io
import csv
import re
import logging
from datetime import datetime, timezone, timedelta, date
from typing import Optional, List, Dict, Any

import bcrypt
import jwt
import pandas as pd
from fastapi import Depends, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr
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


async def require_admin(user=Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


# ------------------- MODELS -------------------
class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ExchangeRateUpdate(BaseModel):
    rates: Dict[str, float]


class CostManualIn(BaseModel):
    sku: str
    product_name: Optional[str] = ""
    cost_per_unit: float
    shipping_cost: float = 0.0
    currency: str = "EUR"


class CostConstantsUpdate(BaseModel):
    operational_cost_per_unit: float
    production_shipping_by_marketplace: Dict[str, float]
    commission_by_marketplace: Dict[str, float] = {}
    vat_rate_by_marketplace: Dict[str, float] = {}


# ------------------- UTILITIES -------------------
def parse_number(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        if pd.isna(v):
            return 0.0
        return float(v)
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return 0.0
    s = s.replace("\u00a0", "").replace(" ", "")
    if "," in s and "." in s:
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
    try:
        ts = pd.to_datetime(s, utc=True, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.to_pydatetime()
    except Exception:
        return None


def parse_list(q: Optional[str]) -> Optional[List[str]]:
    if not q:
        return None
    return [s.strip() for s in q.split(",") if s.strip()]


def build_match(date_from: Optional[str], date_to: Optional[str], marketplaces: Optional[List[str]], sku: Optional[str], stock_only: bool = False):
    m: Dict[str, Any] = {}
    if date_from or date_to:
        m["order_date_iso"] = {}
        if date_from:
            m["order_date_iso"]["$gte"] = date_from
        if date_to:
            m["order_date_iso"]["$lte"] = date_to + "T23:59:59"
    if marketplaces:
        m["marketplace"] = {"$in": marketplaces}
    sku_conds: List[Dict[str, Any]] = []
    if sku:
        # Prefix match to be consistent with the frontend "SKU starts with" filter.
        sku_conds.append({"sku": {"$regex": "^" + re.escape(sku), "$options": "i"}})
    if stock_only:
        # Same rule as Products page: keep SKUs starting with AMB-, J-, J3-, J4-, 3D-, carp-;
        # explicitly exclude J3-privacy.
        sku_conds.append({"sku": {"$regex": r"^(amb-|j-|j3-|j4-|3d-|carp-)", "$options": "i"}})
        sku_conds.append({"sku": {"$not": {"$regex": r"^j3-privacy", "$options": "i"}}})
    if len(sku_conds) == 1:
        m.update(sku_conds[0])
    elif len(sku_conds) > 1:
        m["$and"] = sku_conds
    return m


def to_eur(amount: float, currency: str, rates: Dict[str, float]) -> float:
    c = (currency or "EUR").upper()
    return amount * rates.get(c, 1.0)


# ------------------- MARKETPLACE NORMALIZATION -------------------
CANONICAL_MARKETPLACES = [
    "Amazon Vendor",
    "Ambiance Web",
    "BOL.COM",
    "CDiscount",
    "Castorama",
    "Kaufland",
    "Leroy Merlin - ES",
    "Leroy Merlin - FR",
    "Leroy Merlin - IT",
    "Leroy Merlin - PL",
    "Leroy Merlin - PT",
    "Maison",
    "Mano Mano",
    "Maxeda - BE",
    "Maxeda - NL",
    "PinkConnect Veepee - BE",
    "PinkConnect Veepee - FR",
    "PinkConnect Veepee - NL",
]


# Rollup used only by the Aggregate Dashboard (donut + trend legend).
# The Marketplaces page keeps the raw canonical labels above.
AGGREGATE_ROLLUP = {
    "Maxeda - BE": "Maxeda",
    "Maxeda - NL": "Maxeda",
    "PinkConnect Veepee - BE": "Veepee",
    "PinkConnect Veepee - FR": "Veepee",
    "PinkConnect Veepee - NL": "Veepee",
    "Leroy Merlin - FR": "Leroy Merlin",
    "Leroy Merlin - ES": "Leroy Merlin",
    "Leroy Merlin - IT": "Leroy Merlin",
    "Leroy Merlin - PT": "Leroy Merlin",
    "Leroy Merlin - PL": "Leroy Merlin",
}


def rollup_marketplace(mk: str) -> str:
    return AGGREGATE_ROLLUP.get(mk, mk)


# Marketplaces that we split further by shipping-destination country. Extendable.
LEROY_MERLIN_COUNTRIES = {"FR", "ES", "IT", "PT", "PL"}


def refine_marketplace(mk: str, country: str) -> str:
    """Split country-billed marketplaces so per-country shipping/commission rates apply.

    Currently: Leroy Merlin ships FR/ES/IT/PT/PL orders at different production shipping
    costs, so we tag each order with the destination-country marketplace label.
    """
    if not mk:
        return mk
    if mk == "Leroy Merlin" and country:
        c = country.strip().upper()
        if c in LEROY_MERLIN_COUNTRIES:
            return f"Leroy Merlin - {c}"
    return mk


def channel_to_marketplace(channel_name: str) -> str:
    if not channel_name:
        return "Unknown"
    n = channel_name.strip()
    low = n.lower()
    ambiance_web_keys = (
        "paiement par carte bancaire et paypal",
        "carte bancaire",
        "kredietkaart",
        "credit card",
        "carta di credito",
        "kredit- und debitkarten",
        "kredit und debitkarten",
        "kredit-und debitkarten",
        "virement bancaire",
        "virement",
        "tarjeta de credito",
        "tarjeta de crédito",
        "tarjeta de cr&eacute;dito",
        "carte bancaire (visa, mastercard, cb)",
        "paypal",
        "ambiance web",
        "ambiance-sticker",
        "ambiancesticker",
    )
    if any(k in low for k in ambiance_web_keys):
        return "Ambiance Web"
    if "amazon" in low:
        return "Amazon Vendor"
    if "leroy" in low or "leroymerlin" in low:
        return "Leroy Merlin"
    if "castorama" in low:
        return "Castorama"
    if "maison" in low or "maisondumonde" in low:
        return "Maison"
    if "monechelle" in low or "mon echelle" in low or "mon-echelle" in low:
        return "Mano Mano"
    if "pinkconnect" in low or "veepee" in low:
        if "bel_nl" in low or "bel-nl" in low:
            return "PinkConnect Veepee - BE"
        if "_nld" in low or "-nld" in low or low.endswith("nl") or "_nl" in low or "-nl" in low:
            return "PinkConnect Veepee - NL"
        if "_bel" in low or "-bel" in low or "belgium" in low or low.endswith("be"):
            return "PinkConnect Veepee - BE"
        return "PinkConnect Veepee - FR"
    if "cdiscount" in low:
        return "CDiscount"
    if "bol.com" in low or low.startswith("bol ") or low == "bol":
        return "BOL.COM"
    if "maxeda" in low:
        if "_bel" in low or "-bel" in low or "belgium" in low:
            return "Maxeda - BE"
        return "Maxeda - NL"
    if "kaufland" in low:
        return "Kaufland"
    if "mano" in low:
        return "Mano Mano"
    return n


def detect_source(filename: str, headers: List[str]) -> str:
    fn = (filename or "").lower()
    cols = [c.lower() for c in headers]
    cols_set = set(cols)
    # Ambiance Web (Prestashop export) — French headers
    if "numéro commande" in cols_set and ("produit : référence" in cols_set or "produit : ean" in cols_set):
        return "ambiance_web"
    # Amazon "Edit Line Items" export — richer than basic PO export (carries delivery window dates)
    if "window end" in cols_set and "expected date" in cols_set and "po" in cols_set:
        return "amazon_edit"
    if "po" in cols_set and "asin" in cols_set:
        return "amazon_po"
    if "marketplace" in cols_set and "order_marketplaceorderid" in cols_set:
        return "beezup"
    if any("line.merchantproductno" in c for c in cols) or any("order.channelname" in c for c in cols):
        return "channelengine"
    if "channelengine" in fn:
        return "channelengine"
    if "beezup" in fn:
        return "beezup"
    if "editlineitems" in fn:
        return "amazon_edit"
    if "ambiance" in fn and "web" in fn:
        return "ambiance_web"
    if "poitem" in fn or "amazon" in fn:
        return "amazon_po"
    return "unknown"


# ------------------- SETTINGS STORE -------------------
async def get_rates() -> Dict[str, float]:
    doc = await db.settings.find_one({"_id": "exchange_rates"})
    if not doc:
        defaults = {"EUR": 1.0, "USD": 0.92, "GBP": 1.17, "PLN": 0.23, "SEK": 0.087, "DKK": 0.134, "CHF": 1.05, "CZK": 0.04, "NOK": 0.085}
        await db.settings.update_one({"_id": "exchange_rates"}, {"$set": {"rates": defaults}}, upsert=True)
        return defaults
    return doc.get("rates", {"EUR": 1.0})


async def get_cost_constants() -> Dict[str, Any]:
    doc = await db.settings.find_one({"_id": "cost_constants"})
    if not doc:
        defaults = {"operational_cost_per_unit": 0.5, "production_shipping_by_marketplace": {}, "commission_by_marketplace": {}, "vat_rate_by_marketplace": {}}
        await db.settings.update_one({"_id": "cost_constants"}, {"$set": defaults}, upsert=True)
        return defaults
    return {
        "operational_cost_per_unit": float(doc.get("operational_cost_per_unit", 0.5)),
        "production_shipping_by_marketplace": doc.get("production_shipping_by_marketplace", {}),
        "commission_by_marketplace": doc.get("commission_by_marketplace", {}),
        "vat_rate_by_marketplace": doc.get("vat_rate_by_marketplace", {}),
    }


# ------------------- PARSERS -------------------
def parse_channelengine(content: bytes) -> List[dict]:
    text = content.decode("utf-8-sig", errors="replace")
    # Auto-detect delimiter — ChannelEngine exports come as both ',' (default)
    # and ';' (Bol.com / EU locale exports). Sniff the first non-empty line.
    sample = ""
    for line in text.splitlines():
        if line.strip():
            sample = line
            break
    delimiter = ","
    if sample:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
        except csv.Error:
            # Heuristic fallback: pick whichever character appears most outside quotes.
            n_semi = sample.count(";")
            n_comma = sample.count(",")
            if n_semi > n_comma:
                delimiter = ";"
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
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
            "marketplace": refine_marketplace(marketplace, country),
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
        merchant_sku = s(r.get("Merchant SKU"))
        asin = s(r.get("ASIN"))
        sku = merchant_sku or asin
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
            "line_key": f"{po}::{asin}",
            "sku": sku,
            "asin": asin,
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


def parse_amazon_edit_line_items(content: bytes) -> List[dict]:
    """Amazon 'Edit Line Items' export — same PO data as parse_amazon_po PLUS
    delivery window dates. Columns: PO, Vendor, Warehouse, ASIN, External ID,
    External Id Type, Model Number (= merchant SKU), Title, Availability (= status),
    Window Type, Window start, Window end (= delivery date), Expected date (= order date),
    Quantity Requested, Expected Quantity, Unit Cost.
    Currency is in an unnamed column right after Unit Cost (typically 'EUR').
    """
    try:
        df = pd.read_excel(io.BytesIO(content), sheet_name=0, dtype=str)
    except Exception:
        df = pd.read_excel(io.BytesIO(content), sheet_name=0, dtype=str, engine="openpyxl")
    df = df.fillna("")

    def s(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        return str(v).strip()

    # Currency column may be unnamed (sits after Unit Cost)
    currency_col = None
    cols = list(df.columns)
    if "Unit Cost" in cols:
        idx = cols.index("Unit Cost")
        if idx + 1 < len(cols):
            currency_col = cols[idx + 1]

    rows = []
    for _, r in df.iterrows():
        po = s(r.get("PO"))
        asin = s(r.get("ASIN"))
        merchant_sku = s(r.get("Model Number"))
        sku = merchant_sku or asin
        if not po or not sku or sku.lower() in ("nan", "none"):
            continue
        order_date = parse_date(r.get("Expected date"))
        delivery_date = parse_date(r.get("Window end"))
        window_start = parse_date(r.get("Window start"))
        qty_exp = int(parse_number(r.get("Expected Quantity") or 0))
        qty_req = int(parse_number(r.get("Quantity Requested") or 0))
        qty = qty_exp or qty_req
        unit_cost = parse_number(r.get("Unit Cost"))
        line_total = unit_cost * qty
        currency = (s(r.get(currency_col)) if currency_col else "") or "EUR"
        warehouse = s(r.get("Warehouse"))
        product_name = s(r.get("Title"))
        status = s(r.get("Availability"))
        rows.append({
            "source": "amazon_po",  # keep same source so existing dashboards see it
            "marketplace": "Amazon Vendor",
            "channel_raw": "Amazon Vendor PO",
            "order_id": po,
            "line_key": f"{po}::{asin}",  # SAME line_key as parse_amazon_po so re-uploads merge
            "sku": sku,
            "asin": asin,
            "product_name": product_name,
            "quantity": qty,
            "unit_price": unit_cost,
            "line_total": line_total,
            "shipping_cost": 0.0,
            "vat": 0.0,
            "currency": currency,
            "order_date": order_date,
            "delivery_date": delivery_date,
            "window_start_date": window_start,
            "status": status,
            "country": warehouse,
            "city": warehouse,
            "customer_email": "",
        })
    return rows


def parse_ambiance_web(content: bytes, filename: str = "") -> List[dict]:
    """Ambiance Sticker website (Prestashop) 'Commandes' export.

    Accepts BOTH the single-sheet XLSX export and the CSV/TSV export
    (`export_commandes_*.csv`). Column names are identical (French Prestashop),
    the CSV version may be tab-, semicolon- or comma-delimited.

    Each row = one product line inside an order. Columns (verbatim French):
      Numéro commande, Date (DD/MM/YYYY), Statut, Méthode de paiement,
      Nombre d'articles, Produit : référence (= SKU), Produit : options,
      Produit : quantité, Produit : total prix TTC, Produit : prix unitaire TTC,
      Produit : ean, Product : Reference stock

    The CSV variant of this file MIXES all marketplaces in one export (Ambiance
    Web + Leroy Merlin + Castorama + …). We keep only rows whose payment method
    is NOT a marketplace shorthand (LEROYMERLIN, CASTORAMA, CDISCOUNT,
    PinkConnect-VEEPEE, MONECHELLE, MAXEDA, BOL, KAUFLAND, MAISON, MANO). Every
    remaining row is booked as marketplace = 'Ambiance Web'.

    line_key = f"{order_id}::{sku}::{options_hash}::{line_idx}" — deterministic
    across re-uploads, unique even when the same (order,sku,options) triplet
    appears more than once in a single order.
    """
    import hashlib

    def s(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        return str(v).strip()

    fn = (filename or "").lower()
    df = None
    if fn.endswith((".csv", ".tsv", ".txt")):
        # Detect encoding
        text = None
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = content.decode("utf-8", errors="replace")
        # Detect delimiter — Prestashop CSV export defaults to TAB
        first_line = next((ln for ln in text.splitlines() if ln.strip()), "")
        try:
            delim = csv.Sniffer().sniff(first_line, delimiters=",;\t").delimiter
        except csv.Error:
            counts = {d: first_line.count(d) for d in ",;\t"}
            delim = max(counts, key=counts.get)
        df = pd.read_csv(io.StringIO(text), delimiter=delim, dtype=str)
    else:
        try:
            df = pd.read_excel(io.BytesIO(content), sheet_name="Commandes", dtype=str)
        except Exception:
            df = pd.read_excel(io.BytesIO(content), sheet_name=0, dtype=str)
    df = df.fillna("")

    # Marketplace payment method tokens — these rows must NOT be booked as
    # Ambiance Web because they belong to other marketplaces we already ingest
    # via ChannelEngine / BeezUP / Amazon.
    EXCLUDE_TOKENS = (
        "leroymerlin", "castorama", "cdiscount",
        "pinkconnect", "veepee", "monechelle",
        "maxeda", "bol_", "bol.com", "kaufland",
        "maison", "manomano", "mano_mano",
    )

    rows: List[dict] = []
    line_counter: Dict[tuple, int] = {}
    skipped_by_channel = 0

    # This Prestashop export can come in two shapes:
    #   (a) Fat rows — every row has order metadata + product line (XLSX export).
    #   (b) Header + child rows — order metadata is on a stand-alone "header" row
    #       and the product lines below have empty order fields (TSV export).
    # Detect (b) by carrying forward the last seen order/date/status/payment
    # whenever we hit a product-line row that lacks order_id.
    current: Dict[str, str] = {"order_id": "", "date": "", "status": "", "payment": ""}
    for _, r in df.iterrows():
        row_order_id = s(r.get("Numéro commande"))
        row_date = s(r.get("Date"))
        row_status = s(r.get("Statut"))
        row_payment = s(r.get("Méthode de paiement"))
        sku = s(r.get("Produit : référence"))

        # Header row: refresh the "current" order metadata
        if row_order_id:
            current = {
                "order_id": row_order_id,
                "date": row_date or current["date"],
                "status": row_status or current["status"],
                "payment": row_payment or current["payment"],
            }
            # Header-only rows have no SKU — nothing to book, continue
            if not sku:
                continue
        else:
            # Child product-line row → inherit from current header
            row_order_id = current["order_id"]
            row_date = current["date"]
            row_status = current["status"]
            row_payment = current["payment"]

        if not row_order_id or not sku:
            continue

        p_low = row_payment.lower()
        if any(tok in p_low for tok in EXCLUDE_TOKENS):
            skipped_by_channel += 1
            continue

        options = s(r.get("Produit : options"))
        options_hash = hashlib.md5(options.encode("utf-8")).hexdigest()[:8] if options else "no_opts"
        combo = (row_order_id, sku, options_hash)
        line_counter[combo] = line_counter.get(combo, 0) + 1
        line_idx = line_counter[combo]

        qty = int(parse_number(r.get("Produit : quantité") or 1))
        line_total = parse_number(r.get("Produit : total prix TTC"))
        unit_price = parse_number(r.get("Produit : prix unitaire TTC"))
        if unit_price == 0 and qty > 0 and line_total > 0:
            unit_price = line_total / qty

        order_date = parse_date(row_date)
        product_name = options or s(r.get("Product : Reference stock"))

        rows.append({
            "source": "ambiance_web",
            "marketplace": "Ambiance Web",
            "channel_raw": row_payment or "Ambiance Web",
            "order_id": row_order_id,
            "line_key": f"{row_order_id}::{sku}::{options_hash}::{line_idx}",
            "sku": sku,
            "product_name": product_name,
            "quantity": qty,
            "unit_price": unit_price,
            "line_total": line_total,
            "shipping_cost": 0.0,
            "vat": 0.0,
            "currency": "EUR",
            "order_date": order_date,
            "status": row_status,
            "country": "",
            "city": "",
            "customer_email": "",
        })

    if skipped_by_channel:
        logger.info("parse_ambiance_web: skipped %d rows belonging to other marketplaces", skipped_by_channel)
    return rows


async def apply_asin_mapping(rows: List[dict]) -> List[dict]:
    needed = set()
    for r in rows:
        if r.get("source") == "amazon_po" and r.get("asin"):
            needed.add(("Amazon Vendor", r["asin"]))
        elif r.get("source") == "beezup" and r.get("marketplace") == "Leroy Merlin" and r.get("sku"):
            needed.add(("Leroy Merlin", str(r["sku"])))
    if not needed:
        return rows
    marketplaces = list({m for m, _ in needed})
    ext_ids = list({e for _, e in needed})
    mappings: Dict[tuple, str] = {}
    async for m in db.sku_mappings.find({"marketplace": {"$in": marketplaces}, "external_id": {"$in": ext_ids}}):
        mappings[(m["marketplace"], m["external_id"])] = m["merchant_sku"]
    asins_to_check = [aid for mk, aid in needed if mk == "Amazon Vendor" and ("Amazon Vendor", aid) not in mappings]
    if asins_to_check:
        async for am in db.asin_mappings.find({"asin": {"$in": asins_to_check}}):
            mappings[("Amazon Vendor", am["asin"])] = am["merchant_sku"]
    for r in rows:
        if r.get("source") == "amazon_po" and r.get("asin"):
            ms = mappings.get(("Amazon Vendor", r["asin"]))
            if ms:
                r["sku"] = ms
        elif r.get("source") == "beezup" and r.get("marketplace") == "Leroy Merlin" and r.get("sku"):
            ms = mappings.get(("Leroy Merlin", str(r["sku"])))
            if ms:
                r["sku"] = ms
    return rows


def parse_asin_mapping(content: bytes, filename: str) -> List[dict]:
    fn = (filename or "").lower()
    if fn.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        df = pd.read_csv(io.StringIO(text))
    else:
        try:
            df = pd.read_excel(io.BytesIO(content), engine="openpyxl")
        except Exception:
            df = pd.read_excel(io.BytesIO(content))
    cols_lower = {str(c).strip().lower(): c for c in df.columns}
    out = []

    def s(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        return str(v).strip()

    is_combined = "amazon asin" in cols_lower and "leroy merlin id" in cols_lower and "sku" in cols_lower
    if is_combined:
        for _, r in df.iterrows():
            merchant_sku = s(r.get(cols_lower["sku"]))
            asin = s(r.get(cols_lower["amazon asin"]))
            lrm_id_raw = r.get(cols_lower["leroy merlin id"])
            lrm_id = ""
            if lrm_id_raw is not None and not (isinstance(lrm_id_raw, float) and pd.isna(lrm_id_raw)):
                if isinstance(lrm_id_raw, float):
                    lrm_id = str(int(lrm_id_raw))
                else:
                    lrm_id = str(lrm_id_raw).strip().rstrip(".0").strip() if "." in str(lrm_id_raw) else str(lrm_id_raw).strip()
                    try:
                        lrm_id = str(int(float(lrm_id_raw)))
                    except (ValueError, TypeError):
                        pass
            amz_title = s(r.get(cols_lower.get("amazon title", "amazon title")))
            lrm_title = s(r.get(cols_lower.get("leroy merlin title", "leroy merlin title")))
            if not merchant_sku or merchant_sku.lower() == "nan":
                continue
            if asin and asin.lower() != "nan":
                out.append({"marketplace": "Amazon Vendor", "external_id": asin, "merchant_sku": merchant_sku, "product_name": amz_title})
            if lrm_id and lrm_id.lower() != "nan":
                out.append({"marketplace": "Leroy Merlin", "external_id": lrm_id, "merchant_sku": merchant_sku, "product_name": lrm_title})
        return out

    norm_cols = {str(c).strip().lower().replace(" ", "_"): c for c in df.columns}
    for _, r in df.iterrows():
        asin = r.get(norm_cols.get("asin", "asin"))
        merchant_sku = r.get(norm_cols.get("merchant_sku", "merchant_sku")) if "merchant_sku" in norm_cols else r.get(norm_cols.get("sku", "sku"))
        if asin is None or (isinstance(asin, float) and pd.isna(asin)):
            continue
        if merchant_sku is None or (isinstance(merchant_sku, float) and pd.isna(merchant_sku)):
            continue
        asin_s = s(asin)
        sku_s = s(merchant_sku)
        if not asin_s or not sku_s or sku_s.lower() == "nan":
            continue
        product_name = s(r.get(norm_cols.get("product_name", "product_name")) or r.get(norm_cols.get("title", "title"), ""))
        out.append({"marketplace": "Amazon Vendor", "external_id": asin_s, "merchant_sku": sku_s, "product_name": product_name})
    return out


def parse_cost_file(content: bytes, filename: str) -> List[dict]:
    fn = (filename or "").lower()
    if not fn.endswith(".csv"):
        try:
            xl = pd.ExcelFile(io.BytesIO(content), engine="openpyxl")
            sheets_lower = [s.lower() for s in xl.sheet_names]
            if "sheet3" in sheets_lower:
                raw = pd.read_excel(io.BytesIO(content), sheet_name="Sheet3", header=None, engine="openpyxl")
                header_row = None
                for i in range(min(5, len(raw))):
                    row_vals = [str(x).strip().upper() for x in raw.iloc[i].tolist() if pd.notna(x)]
                    if "SKU" in row_vals:
                        header_row = i
                        break
                if header_row is not None:
                    headers = [str(x).strip() if pd.notna(x) else f"_col{j}" for j, x in enumerate(raw.iloc[header_row].tolist())]
                    data = raw.iloc[header_row + 1:].reset_index(drop=True)
                    data.columns = headers[: len(data.columns)]
                    out = []
                    for _, r in data.iterrows():
                        sku_v = r.get("SKU")
                        if not isinstance(sku_v, str):
                            if pd.isna(sku_v):
                                continue
                            sku_v = str(sku_v).strip()
                        sku = sku_v.strip()
                        if not sku or sku.lower() in ("sample", "sku", "nan"):
                            continue
                        cost = parse_number(r.get("Cout de Production"))
                        if cost <= 0:
                            continue
                        shipping = parse_number(
                            r.get("FBM Frais poste + packaging")
                            if "FBM Frais poste + packaging" in data.columns
                            else r.get("FBA SHIPPING") if "FBA SHIPPING" in data.columns else 0
                        )
                        prod_desc = r.get("Product description") if "Product description" in data.columns else None
                        out.append({
                            "sku": sku,
                            "product_name": (str(prod_desc).strip() if prod_desc is not None and pd.notna(prod_desc) else ""),
                            "cost_per_unit": cost,
                            "shipping_cost": shipping,
                            "currency": "EUR",
                        })
                    if out:
                        return out
        except Exception as e:
            logger.warning("Sheet3 detect failed: %s", e)

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


async def remap_amazon_orders() -> int:
    """Re-apply all sku_mappings to existing orders (Amazon by ASIN, Leroy Merlin by external LRM ID).
    Updates sku only — never line_key, so re-uploads stay idempotent."""
    from pymongo import UpdateOne
    mappings: Dict[tuple, str] = {}
    async for m in db.sku_mappings.find({}, {"_id": 0}):
        mappings[(m["marketplace"], m["external_id"])] = m["merchant_sku"]
    async for m in db.asin_mappings.find({}, {"_id": 0}):
        mappings.setdefault(("Amazon Vendor", m["asin"]), m["merchant_sku"])
    if not mappings:
        return 0
    changed = 0
    bulk = []
    async for o in db.orders.find({"source": "amazon_po"}, {"_id": 1, "asin": 1, "sku": 1}):
        asin = o.get("asin") or o.get("sku")
        new_sku = mappings.get(("Amazon Vendor", asin))
        if not new_sku or new_sku == o.get("sku"):
            continue
        bulk.append(UpdateOne({"_id": o["_id"]}, {"$set": {"sku": new_sku}}))
        changed += 1
        if len(bulk) >= 500:
            await db.orders.bulk_write(bulk, ordered=False)
            bulk = []
    async for o in db.orders.find({"source": "beezup", "marketplace": "Leroy Merlin"}, {"_id": 1, "sku": 1, "line_key": 1}):
        lk = o.get("line_key", "")
        ext_id = lk.split("::", 1)[1] if "::" in lk else o.get("sku")
        new_sku = mappings.get(("Leroy Merlin", ext_id))
        if not new_sku or new_sku == o.get("sku"):
            continue
        bulk.append(UpdateOne({"_id": o["_id"]}, {"$set": {"sku": new_sku}}))
        changed += 1
        if len(bulk) >= 500:
            await db.orders.bulk_write(bulk, ordered=False)
            bulk = []
    if bulk:
        await db.orders.bulk_write(bulk, ordered=False)
    return changed
