import { useEffect, useMemo, useState } from "react";
import PageHeader from "@/components/PageHeader";
import FiltersBar, { useFilters } from "@/components/FiltersBar";
import api from "@/lib/api";
import { fmtEur, fmtNum, fmtPct } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Filter, X, Download, Boxes } from "lucide-react";
import { toast } from "sonner";

const NUM_COLS = ["units", "orders", "revenue_eur", "cogs_eur", "operational_eur", "production_shipping_eur", "commission_eur", "margin_eur", "margin_pct"];
const TEXT_COLS = ["sku", "product_name"];

// "Stock items" preset — keeps only SKUs starting with any of these prefixes
// (case-insensitive). J3-privacy is explicitly excluded even though J3- matches.
const STOCK_PREFIXES = ["amb-", "j-", "j3-", "j4-", "3d-", "carp-"];
const STOCK_EXCLUDE_PREFIXES = ["j3-privacy"];

function isStockSku(sku) {
  const s = String(sku || "").toLowerCase();
  if (!STOCK_PREFIXES.some((p) => s.startsWith(p))) return false;
  if (STOCK_EXCLUDE_PREFIXES.some((p) => s.startsWith(p))) return false;
  return true;
}

export default function Products() {
  const { t } = useT();
  const { filters, setFilters, params } = useFilters();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [colFilters, setColFilters] = useState({}); // { sku: "abc", units: { min: x, max: y } }
  const [sortKey, setSortKey] = useState("revenue_eur");
  const [sortDir, setSortDir] = useState("desc");
  const [openFilter, setOpenFilter] = useState(null);
  const [stockOnly, setStockOnly] = useState(false);

  useEffect(() => {
    setLoading(true);
    api.get("/dashboard/top-skus", { params: { ...params, limit: 20000 } })
      .then((r) => setRows(r.data))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filters)]);

  const filtered = useMemo(() => {
    let result = rows;
    if (stockOnly) {
      result = result.filter((r) => isStockSku(r.sku));
    }
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
  }, [rows, colFilters, sortKey, sortDir, stockOnly]);

  const exportCsv = () => {
    if (filtered.length === 0) {
      toast.error("Nothing to export — check your filters");
      return;
    }
    const cols = [
      "sku", "product_name", "units", "orders",
      "revenue_eur", "ship_income_eur", "total_revenue_eur",
      "cogs_eur", "operational_eur", "production_shipping_eur", "commission_eur",
      "margin_eur", "margin_pct",
    ];
    const header = [
      "SKU", "Product", "Units", "Orders",
      "Revenue (EUR)", "Customer Shipping (EUR)", "Total Revenue (EUR)",
      "COGS (EUR)", "Operational (EUR)", "Production Shipping (EUR)", "Commission (EUR)",
      "Net Margin (EUR)", "Margin %",
    ];
    const esc = (v) => {
      const s = v === null || v === undefined ? "" : String(v);
      return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const lines = [header.join(","), ...filtered.map((r) => cols.map((c) => esc(r[c])).join(","))];
    const blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const stamp = new Date().toISOString().slice(0, 10);
    a.download = `product_performance_${stamp}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
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
            <button
              onClick={() => setStockOnly((v) => !v)}
              className={`inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded border transition-colors ${
                stockOnly
                  ? "bg-[#0055FF] text-white border-transparent"
                  : "bg-white text-[#111215] border-[#D5D7DC] hover:border-[#0055FF] hover:text-[#0055FF]"
              }`}
              data-testid="products-stock-only"
              title="Show only stock items — SKUs starting with AMB-, J-, J3-, J4-, 3D-, carp- (excludes J3-privacy)"
            >
              <Boxes size={13} strokeWidth={2} /> Stock items{stockOnly ? " · ON" : ""}
            </button>
            {activeFilterCount > 0 && (
              <button onClick={clearAll} className="inline-flex items-center gap-1 text-xs hover:text-[#FF2A2A] transition-colors" data-testid="clear-all-filters">
                <X size={12} /> {t("products.clear")}
              </button>
            )}
            <button
              onClick={exportCsv}
              className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded border border-[#111215] bg-white hover:bg-[#111215] hover:text-white transition-colors"
              data-testid="products-export"
              title="Download current view as CSV"
            >
              <Download size={13} strokeWidth={2} /> Export CSV
            </button>
          </div>
        </div>

        <div className="surface overflow-x-auto" style={{ overflow: "visible" }}>
          <table className="dense w-full" data-testid="products-table">
            <thead>
              <tr>
                <Col col="sku" label={t("products.col_sku")} type="text" />
                <Col col="product_name" label={t("products.col_product")} type="text" />
                <Col col="units" label={t("products.col_units")} type="num" align="right" />
                <Col col="orders" label={t("products.col_orders")} type="num" align="right" />
                <Col col="revenue_eur" label={t("products.col_revenue")} type="num" align="right" />
                <Col col="cogs_eur" label={t("products.col_cogs")} type="num" align="right" />
                <Col col="operational_eur" label="Op." type="num" align="right" />
                <Col col="production_shipping_eur" label="Prod. ship" type="num" align="right" />
                <Col col="commission_eur" label="Commission" type="num" align="right" />
                <Col col="margin_eur" label={t("products.col_margin")} type="num" align="right" />
                <Col col="margin_pct" label={t("products.col_margin_pct")} type="num" align="right" />
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={11} className="text-center text-[#5E636E] py-12">{t("common.loading")}</td></tr>
              )}
              {!loading && filtered.length === 0 && (
                <tr><td colSpan={11} className="text-center text-[#5E636E] py-12">{t("products.empty")}</td></tr>
              )}
              {!loading && filtered.map((r) => (
                <tr key={r.sku} data-testid={`product-row-${r.sku}`}>
                  <td className="font-mono-num font-medium">{r.sku}</td>
                  <td className="max-w-[400px] truncate" title={r.product_name}>{r.product_name || "—"}</td>
                  <td className="text-right font-mono-num">{fmtNum(r.units)}</td>
                  <td className="text-right font-mono-num">{fmtNum(r.orders)}</td>
                  <td className="text-right font-mono-num">{fmtEur(r.revenue_eur)}</td>
                  <td className="text-right font-mono-num text-[#5E636E]">{r.has_cost ? fmtEur(r.cogs_eur) : <span className="pill">{t("products.no_cost")}</span>}</td>
                  <td className="text-right font-mono-num text-[#5E636E]">{fmtEur(r.operational_eur || 0)}</td>
                  <td className="text-right font-mono-num text-[#5E636E]">{fmtEur(r.production_shipping_eur || 0)}</td>
                  <td className="text-right font-mono-num text-[#5E636E]">{fmtEur(r.commission_eur || 0)}</td>
                  <td className="text-right font-mono-num">
                    {r.has_cost ? (
                      <span className={r.margin_eur >= 0 ? "text-[#00A859]" : "text-[#FF2A2A]"}>{fmtEur(r.margin_eur)}</span>
                    ) : "—"}
                  </td>
                  <td className="text-right font-mono-num">
                    {r.has_cost ? (
                      <span className={`pill ${r.margin_pct >= 0 ? "pos" : "neg"}`}>{fmtPct(r.margin_pct)}</span>
                    ) : "—"}
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
