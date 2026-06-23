# Ambiance Analytics Hub — PRD

## Original Problem Statement
Build a multi-marketplace seller analytics website (like Seller Legend, but for all marketplaces where Ambiance Sticker is sold). Features: login, sales overview per marketplace, pricing per marketplace, shipping prices, daily/monthly/YTD sales per marketplace, Analytics Dashboard, P&L Reporting, Product Performance, Customer Analytics, Sales Heat Maps, Aggregate Dashboard, Orders & Settlements. Upload CSV/XLSX from each marketplace to update data, separately upload Cost of Production per SKU to compute revenue & margin. Filter and download data.

## User Decisions (verbatim choices)
- Auth: Simple JWT login (single seller account).
- Marketplaces: Open / extensible — user wants to add more in future.
- Currency: Multi-currency support, primary EUR.
- Cost template: Simple per-SKU schema (sku, cost_per_unit, shipping_cost, optional product_name/currency).
- Data: Persistent historical data (deduplication by order_id + sku line key).

## Architecture
- **Backend**: FastAPI + MongoDB (motor), all routes under `/api`.
  - JWT auth (12h tokens), bcrypt password hashing, admin seeded from `.env`.
  - Multipart upload endpoints parse ChannelEngine CSV, BeezUP XLSX, Amazon Vendor PO XLS/XLSX, and a simple cost template.
  - Aggregation endpoints return KPI summary, trend, marketplace breakdown, top SKUs, customers, heatmap, P&L, orders list, CSV export.
  - Configurable exchange rates (settings collection) drive EUR normalization across all metrics.
- **Frontend**: React 19 + Tailwind + Recharts + Sonner toast + custom Swiss/high-contrast design (Cabinet Grotesk + IBM Plex Sans).
  - Sidebar (dark) + main area (light) layout.
  - Pages: Login, Aggregate Dashboard, Marketplaces, Products, Customers, Profit & Loss, Orders, Heat Map, Uploads, Settings.
  - Filters bar (date range, marketplaces toggle pills, SKU contains) applies app-wide.

## Implemented (2026-06-23 — MVP)
- JWT auth, admin seeded (`admin@ambiancesticker.com` / `Ambiance2026!`).
- Parsers for ChannelEngine, BeezUP, Amazon Vendor PO (auto-detect by columns).
- Cost upload (CSV / XLSX) + manual cost entry + cost catalog (CRUD).
- Aggregate dashboard with KPIs, sales-by-day line chart, marketplace donut, units/AOV bar charts.
- Marketplace tabs with monthly comparison and revenue ranking.
- Product performance table with COGS/margin where cost is known.
- Customer analytics by country.
- Profit & Loss ledger per marketplace (Revenue − COGS − Shipping = Net) with totals.
- Orders table with pagination + CSV export.
- Calendar heat map (daily revenue intensity).
- Settings: editable multi-currency exchange rates (recomputes all order EUR amounts), per-SKU manual cost entry, cost catalog with delete.
- Uploads page with auto-detect dropzones, source override dropdown, history table, downloadable cost template.

## Verified Against Real Data
- ChannelEngine CSV (69 rows) → 69 orders inserted.
- BeezUP XLSX (1,293 rows) → 1,266 distinct order lines.
- Amazon Vendor PO XLS (6,580 rows) → 661 inserted + 5,913 updated (re-upload idempotent).
- 14 marketplaces detected: Amazon Vendor, Bol.com, Kaufland, Leroy Merlin, Cdiscount, CASTORAMA, MAISONDUMONDE, MAXEDA, MAXEDA_BEL, MONECHELLE, PinkConnect-VEEPEE (+ NL/BEL variants).
- Aggregate metrics: €80,185 revenue over 1,317 orders / 3,810 units / AOV €60.89 in YTD 2026 window.

## Prioritized Backlog
- **P1**: Returns/refunds tracking (the data has Refund fields — currently ignored).
- **P1**: Date-range presets (Today / WTD / MTD / YTD / Last 30d).
- **P1**: Bulk cost import via the user's existing messy Cost-Production workbook (multi-sheet, French headers).
- **P2**: Marketplace fees / commissions (BeezUP `Order_TotalCommission`, ChannelEngine `Line.FeeFixed/Rate`).
- **P2**: VAT report (data captured but not surfaced).
- **P2**: Email digest (weekly/monthly summary).
- **P2**: Multi-user with team roles.
- **P3**: Cohort/retention, repeat-customer analytics.
- **P3**: Live exchange-rate auto-update via API.

## Next Tasks
- Add returns/refunds parsing and a Returns page.
- Add date presets to the filter bar.
- Expose marketplace fees in P&L (subtract commissions before Net).
