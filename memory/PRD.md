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

### Iteration 5 (2026-02 fork)
- **P&L corrected** — Customer Shipping is now added to revenue (it's customer-paid income), not deducted from margin. New P&L row order: Gross Revenue → + Customer Shipping (income) → = Total Revenue → − COGS → − Operational Cost → − Production Shipping → − Commission → Net Profit → Margin %. Margin is computed against Total Revenue. Same change applied to /api/dashboard/summary.
- **Amazon "Edit Line Items" parser + Delivery view** — auto-detects the new Amazon XLSX format (PO + Window end + Expected date columns), uses Model Number as merchant SKU, persists `delivery_date_iso` (Window end), `window_start_date_iso`, and `order_date_iso` (Expected date). Same PO::ASIN line_key merges with existing PO data. New page `/amazon-delivery` filters by delivery window-end while keeping revenue attributed to the order date. KPIs: POs delivering / Units shipping / Revenue (order-dated) / Lines. Backend: GET /api/dashboard/amazon-delivery.
- **Marketplaces × Country breakdown** — Marketplaces page now shows a per-country split panel when a marketplace is active. Leroy Merlin → FR 70.8% / ES 19.0% / IT 5.1% / PT 4.8% / PL 0.3%. Backend: GET /api/dashboard/marketplace-country-breakdown. Aggregate Dashboard remains marketplace-level only.
- Iter 9 verification: 21/21 backend pytest + full UI walk pass; 0 console errors.

### Iteration 6 (2026-02 fork)
- **Production Shipping billed PER ORDER (not per unit)** — user requested change. Backend now counts distinct orders per marketplace and multiplies by rate for Dashboard summary and P&L.
- **SKU-level shipping allocation UPDATED (Iter 6b)** — user complained that lines with N orders showed less than N × rate (because we were splitting each order's shipping proportionally across the multiple SKUs sharing that order). Switched to full-order billing at SKU level: each SKU's Ship = `distinct_orders_containing_it × rate[mk]`. Applies to `/dashboard/top-skus` (Product Performance), `/library/skus` (per-unit avg), `/library/loss-makers`. Trade-off documented in code: sum across SKUs exceeds marketplace P&L when orders contain multiple SKUs — P&L keeps the real cash-out number (`rate × distinct_orders_on_mk`). Verified: LM-FR at €6.90 gives 18 orders × €6.90 = €124.20 exact per SKU row.
- **Dashboard Top 20 SKUs (2 side-by-side cards)** — new "Top 20 SKUs by Turnover" (left) + "Top 20 SKUs by Units Sold / Bestsellers" (right). Respects current FiltersBar. Backend: `GET /api/dashboard/top-skus?sort_by=units|revenue&limit=20`.
- Files touched: `/app/backend/routes/dashboard.py` (summary, profit_loss, top_skus), `/app/backend/routes/library.py` (library_skus, loss_makers), `/app/frontend/src/pages/Dashboard.jsx`, `/app/frontend/src/pages/Settings.jsx`, `/app/frontend/src/lib/i18n.jsx`.

## Next Tasks (P1)
1. Suggested-new-price column on Loss Makers (auto target-margin compute).
2. Returns CSV export and Loss Makers CSV export.
3. Amazon Delivery: per-week aggregation toggle + CSV export.

## Credentials
- admin@ambiancesticker.com / Ambiance2026!
