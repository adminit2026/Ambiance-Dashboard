# Ambiance Analytics Hub — PRD

## Original Problem Statement
Multi-marketplace seller analytics dashboard (Seller Legend style) for Ambiance Sticker. Login, sales overview, daily/monthly/YTD per marketplace, Analytics Dashboard, P&L, Product Performance, Customer Analytics, Sales Heat Maps, Aggregate Dashboard, Orders & Settlements. Upload CSV/XLSX from each marketplace and Cost of Production per SKU. Filter, download, multi-currency (EUR primary), persistent historical data.

## Canonical Marketplaces (locked in)
CDiscount, Maison, Leroy Merlin, Mano Mano (was MONECHELLE), PinkConnect Veepee - FR/BE/NL, Castorama, Maxeda - NL/BE, BOL.COM, Zooplus, Kaufland, Appros, Amazon Vendor, Ambiance Web (auto-groups payment-method values: Paiement par carte bancaire et PayPal, Carte Bancaire, Kredietkaart, Credit Card, Tarjeta de Credito).

## Implemented (2026-06-23)

### MVP (iteration 1)
- JWT auth, admin seeded.
- Parsers for ChannelEngine, BeezUP, Amazon Vendor PO (auto-detect).
- Cost upload (CSV/XLSX) + manual cost entry + cost catalog CRUD.
- Aggregate dashboard (KPIs, daily trend, marketplace mix).
- Marketplace tabs, Product performance, Customer geo, P&L ledger.
- Orders pagination + CSV export.
- Sales heat map calendar.
- Settings: exchange rates (recompute on save).

### Iteration 2 (this session)
- Canonical marketplace normalization (504 + 117 orders relabeled).
- Ambiance Web payment-method mapping.
- **Mon Echelle → Mano Mano** alias.
- **Prices page** — SKU search + per-marketplace avg/min-max/units + CSV export.
- **Legacy CostProdShippingCalc workbook parser** — reads Sheet3 col A=SKU, col L=Cout de Production, col M=FBM Frais poste. 30,450 SKU costs loaded from user's file.
- **Pre-filled cost template download** — server emits CSV with every SKU currently in orders + existing cost data.
- **Amazon PO ASIN fix** — was storing literal "nan", now correctly falls back to ASIN. May totals now reconcile (€14,694 vs PO reference €14,683).
- **Renormalize endpoint** — re-apply latest channel mapping to existing orders via Settings button.

## Verified Data
- 13 active marketplaces in DB.
- ~7,000 orders.
- 30,450 SKU costs loaded.
- May 2026 Amazon Vendor: 28 POs / 1,494 units / €14,694 (matches user's PO reference).

## Known Gaps / Future Work
- **ASIN ↔ Merchant SKU mapping**: Amazon orders are keyed by ASIN, costs are keyed by Merchant SKU. Top SKUs by revenue are now all Amazon ASINs with no cost match. Need a mapping table or a column in the cost template.
- May 2026 Leroy Merlin / BeezUP data: user needs to upload fresh export (last BeezUP file goes through April only).
- Returns/refunds tracking (raw data captured, not surfaced).
- Date-range presets (Today / WTD / MTD / YTD / Last 30d).
- Marketplace fees/commissions deduction in P&L.
- Server-side: split server.py into routers, add role checks, batch large mongo aggregations.

### Iteration 3 (2026-02 fork)
- **Loss-Making SKUs view** (`/loss-makers`) — flags SKU × marketplace combos where avg unit price minus (production + operational + production shipping + commission) is negative. Sorted by largest total bleed first. Skips SKUs with no cost data to avoid false positives. EN/FR i18n (`Loss Makers` / `Pertes`). Backend `GET /api/library/loss-makers` (JWT-protected, supports date_from / date_to / marketplaces filters). Verified iter 7: 17/17 backend tests + full frontend regression green. Current DB state: 63 loss-making combos, -€332.96 bleed across 736 units.

### Iteration 4 (2026-02 fork)
- **Admin-role guard** — added `require_admin` dependency, applied to every write endpoint: `POST /api/uploads/orders|costs|asin-mapping`, `PUT /api/cost-constants`, `PUT /api/exchange-rates`, `POST /api/admin/renormalize-marketplaces`, `POST /api/admin/reprocess-amazon-asins`, `POST /api/costs/manual`, `DELETE /api/costs/{sku}`. Read endpoints unchanged (auth-only).
- **Returns & Refunds page** (`/returns`) — new dashboard surfacing refunded / returned / cancelled orders broken down by marketplace, with 4 KPI cards (refund total, cancel total, refund rate %, cancel rate %), a per-marketplace table, and a recent-200-lines table. Backend `GET /api/dashboard/returns` with date_from/to/marketplaces/sku filters. Current data: 1.3% refund rate (€1,516.59) and 0.7% cancel rate (€787.16) across 6 marketplaces.
- **Date-range preset chips** on FiltersBar: Today / WTD / MTD / Last 30d / Last 90d / YTD. Active chip highlights blue. EN/FR labels.
- **Backend split into routers** — `server.py` shrunk from 1,882 → 103 lines. Shared primitives moved to `/app/backend/core.py` (db, models, auth, parsers, util, settings store, marketplace normalization). Route handlers split into `/app/backend/routes/{auth, uploads, costs, dashboard, orders, library}.py`. Verified iter 8: 50/52 backend tests pass + 100% frontend regression (13 sidebar links, 6 preset chips, 6 returns testids, EN/FR toggle, 0 console errors).

## Next Tasks (P1)
1. Date-range presets — server-side default on `/api/dashboard/summary` and `/api/library/loss-makers` so unfiltered API consumers see same numbers as UI (optional polish).
2. Email alert when a new SKU becomes a loss-maker.
3. Suggested-new-price column on Loss Makers page (target margin auto-compute).

## Credentials
- admin@ambiancesticker.com / Ambiance2026!
