import { useEffect, useMemo, useState } from "react";
import PageHeader from "@/components/PageHeader";
import FiltersBar, { useFilters } from "@/components/FiltersBar";
import api from "@/lib/api";
import { fmtEur, fmtNum, fmtPct } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Filter, X, Download } from "lucide-react";
import { toast } from "sonner";

const NUM_COLS = ["units", "orders", "revenue_eur", "vat_eur", "cogs_eur", "operational_eur", "production_shipping_eur", "commission_eur", "margin_eur", "margin_pct"];
const TEXT_COLS = ["sku", "product_name"];

// "Stock items" toggle is now global via FiltersBar (stock_only=true query param).
// Backend applies the SKU prefix filter server-side so every page picks it up automatically.

export default function Products() {
  const { t } = useT();
  const { filters, setFilters, params } = useFilters();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [colFilters, setColFilters] = useState({}); // { sku: "abc", units: { min: x, max: y } }
  const [sortKey, setSortKey] = useState("revenue_eur");
  const [sortDir, setSortDir] = useState("desc");
  const [openFilter, setOpenFilter] = useState(null);

  useEffect(() => {
    setLoading(true);
    api.get("/dashboard/top-skus", { params: { ...params, limit: 20000 } })
      .then((r) => setRows(r.data))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filters)]);

  const filtered = useMemo(() => {
    let result = rows;
    Object.entries(colFilters).forEach(([col, val]) => {
      if (!val) return;
      if (TEXT_COLS.includes(col)) {
        const q = String(val).toLowerCase();
        if (!q) return;
        // SKU uses "starts with" semantics per user preference; product_name stays contains.
        if (col === "sku") {
          result = result.filter((r) => String(r[col] || "").toLowerCase().startsWith(q));
        } else {
          result = result.filter((r) => String(r[col] || "").toLowerCase().includes(q));
        }
      } else if (NUM_COLS.includes(col)) {
        const { min, max } = val;
        if (min !== undefined && min !== "" && !isNaN(Number(min))) {
          result = result.filter((r) => Number(r[col] || 0) >= Number(min));
        }
        if (max !== undefined && max !== "" && !isNaN(Number(max))) {
          result = result.filter((r) => Number(r[col] || 0) <= Number(max));
        }
      }
    });
    result = [...result].sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey];
      if (typeof av === "string") return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      return sortDir === "asc" ? (av || 0) - (bv || 0) : (bv || 0) - (av || 0);
    });
    return result;
  }, [rows, colFilters, sortKey, sortDir]);

  const exportXlsx = async () => {
    if (filtered.length === 0) {
      toast.error("Nothing to export — check your filters");
      return;
    }
    const cols = [
      "sku", "product_name", "units", "orders",
      "revenue_eur", "ship_income_eur", "total_revenue_eur",
      "vat_eur", "vat_pct",
      "cogs_eur", "operational_eur", "production_shipping_eur", "commission_eur",
      "margin_eur", "margin_pct",
    ];
    const header = [
      "SKU", "Product", "Units", "Orders",
      "Revenue (EUR)", "Customer Shipping (EUR)", "Total Revenue (EUR)",
      "COGS (EUR)", "Operational (EUR)", "Production Shipping (EUR)", "Commission (EUR)",
      "Net Margin (EUR)", "Margin %",
    ];
    const XLSX = await import("xlsx");
    const data = [header, ...filtered.map((r) => cols.map((c) => (r[c] === undefined || r[c] === null ? "" : r[c])))];
    const ws = XLSX.utils.aoa_to_sheet(data);
    // Widen product-name column so it's readable when opened
    ws["!cols"] = [{ wch: 24 }, { wch: 40 }, { wch: 8 }, { wch: 8 }, { wch: 14 }, { wch: 18 }, { wch: 16 }, { wch: 12 }, { wch: 12 }, { wch: 20 }, { wch: 14 }, { wch: 14 }, { wch: 10 }];
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Product Performance");
    const stamp = new Date().toISOString().slice(0, 10);
    XLSX.writeFile(wb, `product_performance_${stamp}.xlsx`);
    toast.success(`Exported ${filtered.length.toLocaleString()} rows`);
  };

  const setTextFilter = (col, val) => setColFilters({ ...colFilters, [col]: val });
  const setNumFilter = (col, key, val) => setColFilters({ ...colFilters, [col]: { ...(colFilters[col] || {}), [key]: val } });
  const clearFilter = (col) => { const c = { ...colFilters }; delete c[col]; setColFilters(c); };
  const clearAll = () => setColFilters({});
  const toggleSort = (col) => {
    if (sortKey === col) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(col); setSortDir("desc"); }
  };

  const Col = ({ col, label, align = "left", type = "text" }) => {
    const f = colFilters[col];
    const hasFilter = type === "text" ? !!f : f && (f.min || f.max);
    const isOpen = openFilter === col;
    return (
      <th className={align === "right" ? "text-right relative" : "relative"}>
        <div className={`inline-flex items-center gap-1 ${align === "right" ? "ml-auto" : ""}`}>
          <button onClick={() => toggleSort(col)} className="hover:text-[#111215] transition-colors" data-testid={`sort-${col}`}>
            {label}
            {sortKey === col && <span className="text-[#0055FF] ml-1">{sortDir === "asc" ? "▲" : "▼"}</span>}
          </button>
          <button
            onClick={() => setOpenFilter(isOpen ? null : col)}
            className={`p-1 transition-colors ${hasFilter ? "text-[#0055FF]" : "text-[#9CA3AF] hover:text-[#111215]"}`}
            data-testid={`filter-icon-${col}`}
          >
            <Filter size={11} />
          </button>
        </div>
        {isOpen && (
          <div className="absolute top-full right-0 mt-1 surface p-3 z-30 min-w-[200px] shadow-lg" data-testid={`filter-popover-${col}`}>
            {type === "text" ? (
              <input
                autoFocus
                className="in w-full text-sm"
                placeholder={col === "sku" ? (t("products.filter_starts_with") || "starts with…") : (t("products.filter_text") || "contains…")}
                value={f || ""}
                onChange={(e) => setTextFilter(col, e.target.value)}
                data-testid={`filter-input-${col}`}
              />
            ) : (
              <div className="space-y-2">
                <input
                  autoFocus
                  type="number"
                  className="in w-full text-sm"
                  placeholder={t("products.filter_min")}
                  value={f?.min || ""}
                  onChange={(e) => setNumFilter(col, "min", e.target.value)}
                  data-testid={`filter-min-${col}`}
                />
                <input
                  type="number"
                  className="in w-full text-sm"
                  placeholder={t("products.filter_max")}
                  value={f?.max || ""}
                  onChange={(e) => setNumFilter(col, "max", e.target.value)}
                  data-testid={`filter-max-${col}`}
                />
              </div>
            )}
            <div className="flex justify-between items-center mt-2 pt-2 border-t border-[#E5E7EB]">
              <button onClick={() => clearFilter(col)} className="text-xs text-[#5E636E] hover:text-[#FF2A2A] transition-colors" data-testid={`filter-clear-${col}`}>Clear</button>
              <button onClick={() => setOpenFilter(null)} className="text-xs text-[#0055FF] hover:opacity-80" data-testid={`filter-close-${col}`}>Close</button>
            </div>
          </div>
        )}
      </th>
    );
  };

  const activeFilterCount = Object.values(colFilters).filter((v) => (typeof v === "string" ? v : v && (v.min || v.max))).length;

  return (
    <div>
      <PageHeader kicker={t("products.kicker")} title={t("products.title")} />
      <FiltersBar filters={filters} setFilters={setFilters} />

      <section className="px-8 py-6">
        <div className="flex items-center justify-between mb-3 text-sm text-[#5E636E]">
          <div>
            <span className="font-mono-num text-[#111215]">{fmtNum(filtered.length)}</span> / <span className="font-mono-num">{fmtNum(rows.length)}</span> products
            {activeFilterCount > 0 && (
              <span className="ml-3 pill" style={{ color: "#0055FF", background: "#E0EAFF", borderColor: "transparent" }}>{activeFilterCount} filters active</span>
            )}
          </div>
          <div className="flex items-center gap-3">
            {activeFilterCount > 0 && (
              <button onClick={clearAll} className="inline-flex items-center gap-1 text-xs hover:text-[#FF2A2A] transition-colors" data-testid="clear-all-filters">
                <X size={12} /> {t("products.clear")}
              </button>
            )}
            <button
              onClick={exportXlsx}
              className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded border border-[#111215] bg-white hover:bg-[#111215] hover:text-white transition-colors"
              data-testid="products-export"
              title="Download current view as Excel (.xlsx)"
            >
              <Download size={13} strokeWidth={2} /> Export Excel
            </button>
          </div>
        </div>

        <div className="surface overflow-x-auto" style={{ overflow: "visible" }}>
          <table className="dense w-full text-xs products-tight" data-testid="products-table">
            <thead>
              <tr>
                <Col col="sku" label={t("products.col_sku")} type="text" />
                <Col col="product_name" label={t("products.col_product")} type="text" />
                <Col col="units" label={t("products.col_units")} type="num" align="right" />
                <Col col="orders" label={t("products.col_orders")} type="num" align="right" />
                <Col col="revenue_eur" label={t("products.col_revenue")} type="num" align="right" />
                <Col col="vat_eur" label="VAT" type="num" align="right" />
                <Col col="cogs_eur" label={t("products.col_cogs")} type="num" align="right" />
                <Col col="operational_eur" label="Op" type="num" align="right" />
                <Col col="production_shipping_eur" label="Ship" type="num" align="right" />
                <Col col="commission_eur" label="Comm" type="num" align="right" />
                <Col col="margin_eur" label={t("products.col_margin")} type="num" align="right" />
                <Col col="margin_pct" label="%" type="num" align="right" />
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={12} className="text-center text-[#5E636E] py-12">{t("common.loading")}</td></tr>
              )}
              {!loading && filtered.length === 0 && (
                <tr><td colSpan={12} className="text-center text-[#5E636E] py-12">{t("products.empty")}</td></tr>
              )}
              {!loading && filtered.map((r) => (
                <tr key={r.sku} data-testid={`product-row-${r.sku}`}>
                  <td className="font-mono-num font-medium">{r.sku}</td>
                  <td className="max-w-[240px] truncate" title={r.product_name}>{r.product_name || "—"}</td>
                  <td className="text-right font-mono-num">{fmtNum(r.units)}</td>
                  <td className="text-right font-mono-num">{fmtNum(r.orders)}</td>
                  <td className="text-right font-mono-num">{fmtEur(r.revenue_eur)}</td>
                  <td className="text-right font-mono-num text-[#5E636E]" title={r.vat_pct ? `${r.vat_pct}% avg — from Settings` : "No VAT rate set for this SKU's marketplaces"}>{fmtEur(r.vat_eur || 0)}</td>
                  <td className="text-right font-mono-num text-[#5E636E]" title={r.has_cost ? "" : "Upload production cost for this SKU in Uploads"}>
                    {fmtEur(r.cogs_eur || 0)}
                    {!r.has_cost && <span className="ml-1 text-[#FF9900] font-bold" title="No production cost uploaded — COGS treated as €0">⚠</span>}
                  </td>
                  <td className="text-right font-mono-num text-[#5E636E]">{fmtEur(r.operational_eur || 0)}</td>
                  <td className="text-right font-mono-num text-[#5E636E]">{fmtEur(r.production_shipping_eur || 0)}</td>
                  <td className="text-right font-mono-num text-[#5E636E]">{fmtEur(r.commission_eur || 0)}</td>
                  <td className="text-right font-mono-num">
                    <span className={r.margin_eur >= 0 ? "text-[#00A859]" : "text-[#FF2A2A]"}>{fmtEur(r.margin_eur)}</span>
                  </td>
                  <td className="text-right font-mono-num">
                    <span className={r.margin_pct >= 0 ? "text-[#5E636E]" : "text-[#FF2A2A]"}>{fmtPct(r.margin_pct)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
