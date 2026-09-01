import { useEffect, useMemo, useState } from "react";
import PageHeader from "@/components/PageHeader";
import FiltersBar, { useFilters } from "@/components/FiltersBar";
import api from "@/lib/api";
import { fmtEur, fmtEurExact, fmtNum, colorFor } from "@/lib/format";
import { AlertTriangle, Filter, X } from "lucide-react";

// Column config used both for sorting/filtering and column visibility.
const ALL_COLS = [
  { key: "sku",                 label: "SKU",              type: "text",  align: "left",  always: true },
  { key: "marketplace",         label: "Marketplace",      type: "text",  align: "left",  always: true },
  { key: "product_name",        label: "Product",          type: "text",  align: "left" },
  { key: "units",               label: "Units",            type: "num",   align: "right" },
  { key: "avg_unit_price",      label: "Avg Price",        type: "num",   align: "right" },
  { key: "production_cost",     label: "Prod Cost",        type: "num",   align: "right" },
  { key: "operational_cost",    label: "+Op",              type: "num",   align: "right" },
  { key: "production_shipping", label: "+Ship",            type: "num",   align: "right" },
  { key: "commission_per_unit", label: "+Comm",            type: "num",   align: "right" },
  { key: "vat_per_unit",        label: "+VAT",             type: "num",   align: "right" },
  { key: "total_cost_per_unit", label: "Total Cost",       type: "num",   align: "right" },
  { key: "net_per_unit",        label: "Net / unit",       type: "num",   align: "right" },
  { key: "margin_pct",          label: "Margin %",         type: "num",   align: "right" },
  { key: "total_loss_eur",      label: "Total Loss",       type: "num",   align: "right" },
  { key: "suggested_price_eur", label: "Suggested Price",  type: "num",   align: "right" },
  { key: "price_uplift_pct",    label: "Uplift",           type: "num",   align: "right" },
];
const DEFAULT_HIDDEN = new Set([]);

export default function LossMakers() {
  const { filters, setFilters, params } = useFilters();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [targetMargin, setTargetMargin] = useState(0);
  const [colFilters, setColFilters] = useState({});
  const [sortKey, setSortKey] = useState("total_loss_eur");
  const [sortDir, setSortDir] = useState("asc"); // most negative first
  const [openFilter, setOpenFilter] = useState(null);
  const [hiddenCols, setHiddenCols] = useState(DEFAULT_HIDDEN);
  const [showColPicker, setShowColPicker] = useState(false);

  useEffect(() => {
    setLoading(true);
    api
      .get("/library/loss-makers", { params: { ...params, target_margin_pct: Number(targetMargin) || 0 } })
      .then((r) => setRows(r.data))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filters), targetMargin]);

  const setTextFilter = (col, val) => setColFilters({ ...colFilters, [col]: val });
  const setNumFilter = (col, key, val) => setColFilters({ ...colFilters, [col]: { ...(colFilters[col] || {}), [key]: val } });
  const clearFilter = (col) => { const c = { ...colFilters }; delete c[col]; setColFilters(c); };
  const clearAll = () => setColFilters({});
  const toggleSort = (col) => {
    if (sortKey === col) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(col); setSortDir("desc"); }
  };
  const toggleCol = (key) => {
    setHiddenCols((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const filtered = useMemo(() => {
    let result = rows;
    Object.entries(colFilters).forEach(([col, val]) => {
      if (!val) return;
      const meta = ALL_COLS.find((c) => c.key === col);
      if (!meta) return;
      if (meta.type === "text") {
        const q = String(val).toLowerCase();
        if (!q) return;
        if (col === "sku") result = result.filter((r) => String(r[col] || "").toLowerCase().startsWith(q));
        else result = result.filter((r) => String(r[col] || "").toLowerCase().includes(q));
      } else {
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

  const totalLoss = filtered.reduce((acc, r) => acc + r.total_loss_eur, 0);
  const totalUnits = filtered.reduce((acc, r) => acc + r.units, 0);
  const activeFilterCount = Object.values(colFilters).filter((v) => {
    if (typeof v === "string") return v !== "";
    return !!(v && ((v.min !== undefined && v.min !== "") || (v.max !== undefined && v.max !== "")));
  }).length;

  // renderCol MUST NOT be a component (<Col/>) — that gives it a new identity
  // every render and remounts the <th>, killing input focus after each keystroke.
  const renderCol = (meta) => {
    const { key: col, label, align, type } = meta;
    const f = colFilters[col];
    const hasFilter = type === "text"
      ? (typeof f === "string" && f !== "")
      : !!(f && ((f.min !== undefined && f.min !== "") || (f.max !== undefined && f.max !== "")));
    const isOpen = openFilter === col;
    return (
      <th key={col} className={align === "right" ? "text-right relative" : "relative"}>
        <div className={`flex items-center gap-1 ${align === "right" ? "justify-end" : ""}`}>
          <button onClick={() => toggleSort(col)} className="hover:text-[#111215] transition-colors" data-testid={`loss-sort-${col}`}>
            {label}
            {sortKey === col && <span className="text-[#0055FF] ml-1">{sortDir === "asc" ? "▲" : "▼"}</span>}
          </button>
          <button
            onClick={() => setOpenFilter(isOpen ? null : col)}
            className={`p-1 transition-colors ${hasFilter ? "text-[#0055FF]" : "text-[#9CA3AF] hover:text-[#111215]"}`}
            data-testid={`loss-filter-icon-${col}`}
          >
            <Filter size={11} />
          </button>
        </div>
        {isOpen && (
          <div
            className="absolute top-full right-0 mt-1 surface p-3 z-30 min-w-[200px] shadow-lg"
            data-testid={`loss-filter-popover-${col}`}
            onClick={(e) => e.stopPropagation()}
          >
            {type === "text" ? (
              <input
                autoFocus
                className="in w-full text-sm"
                placeholder={col === "sku" ? "starts with…" : "contains…"}
                value={typeof f === "string" ? f : ""}
                onChange={(e) => setTextFilter(col, e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === "Escape") setOpenFilter(null); }}
                data-testid={`loss-filter-input-${col}`}
              />
            ) : (
              <div className="space-y-2">
                <input
                  autoFocus
                  type="number"
                  step="any"
                  className="in w-full text-sm"
                  placeholder="min"
                  value={f?.min ?? ""}
                  onChange={(e) => setNumFilter(col, "min", e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === "Escape") setOpenFilter(null); }}
                  data-testid={`loss-filter-min-${col}`}
                />
                <input
                  type="number"
                  step="any"
                  className="in w-full text-sm"
                  placeholder="max"
                  value={f?.max ?? ""}
                  onChange={(e) => setNumFilter(col, "max", e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === "Escape") setOpenFilter(null); }}
                  data-testid={`loss-filter-max-${col}`}
                />
              </div>
            )}
            <div className="flex justify-between items-center mt-2 pt-2 border-t border-[#E5E7EB]">
              <button onClick={() => clearFilter(col)} className="text-xs text-[#5E636E] hover:text-[#FF2A2A]" data-testid={`loss-filter-clear-${col}`}>Clear</button>
              <button onClick={() => setOpenFilter(null)} className="text-xs text-[#0055FF]" data-testid={`loss-filter-close-${col}`}>Close</button>
            </div>
          </div>
        )}
      </th>
    );
  };

  const visibleCols = ALL_COLS.filter((c) => !hiddenCols.has(c.key));

  const renderCell = (r, colKey) => {
    switch (colKey) {
      case "sku": return <td key={colKey} className="font-mono-num font-medium">{r.sku}</td>;
      case "marketplace": return <td key={colKey}><span className="pill" style={{ background: colorFor(r.marketplace), color: "white", borderColor: "transparent" }}>{r.marketplace}</span></td>;
      case "product_name": return <td key={colKey} className="max-w-[260px] truncate text-[#5E636E]" title={r.product_name}>{r.product_name || "—"}</td>;
      case "units": return <td key={colKey} className="text-right font-mono-num">{fmtNum(r.units)}</td>;
      case "avg_unit_price": return <td key={colKey} className="text-right font-mono-num">{fmtEurExact(r.avg_unit_price)}</td>;
      case "production_cost": return <td key={colKey} className="text-right font-mono-num text-[#5E636E]">{fmtEurExact(r.production_cost)}</td>;
      case "operational_cost": return <td key={colKey} className="text-right font-mono-num text-[#5E636E]">{fmtEurExact(r.operational_cost)}</td>;
      case "production_shipping": return <td key={colKey} className="text-right font-mono-num text-[#5E636E]">{fmtEurExact(r.production_shipping)}</td>;
      case "commission_per_unit": return <td key={colKey} className="text-right font-mono-num text-[#5E636E]">{fmtEurExact(r.commission_per_unit)}</td>;
      case "vat_per_unit": return <td key={colKey} className="text-right font-mono-num text-[#5E636E]" title={r.vat_pct ? `${r.vat_pct}% (from Settings)` : "No VAT rate set for this marketplace"}>{fmtEurExact(r.vat_per_unit || 0)}</td>;
      case "total_cost_per_unit": return <td key={colKey} className="text-right font-mono-num font-semibold">{fmtEurExact(r.total_cost_per_unit)}</td>;
      case "net_per_unit": return <td key={colKey} className="text-right font-mono-num text-[#FF2A2A] font-semibold">{fmtEurExact(r.net_per_unit)}</td>;
      case "margin_pct": return <td key={colKey} className="text-right font-mono-num text-[#FF2A2A]">{Number(r.margin_pct || 0).toFixed(2)}%</td>;
      case "total_loss_eur": return <td key={colKey} className="text-right font-mono-num text-[#FF2A2A] font-bold">{fmtEur(r.total_loss_eur)}</td>;
      case "suggested_price_eur": return <td key={colKey} className="text-right font-mono-num text-[#00A859] font-bold border-l border-[#E5E7EB]" data-testid={`suggested-price-${r.sku}`}>{r.suggested_price_eur > 0 ? fmtEurExact(r.suggested_price_eur) : "—"}</td>;
      case "price_uplift_pct": return <td key={colKey} className="text-right font-mono-num text-[#00A859]">{r.suggested_price_eur > 0 ? `+${r.price_uplift_pct}%` : "—"}</td>;
      default: return <td key={colKey}>—</td>;
    }
  };

  return (
    <div>
      <PageHeader kicker="Margin alerts" title="Loss-Making SKUs" />
      <FiltersBar filters={filters} setFilters={setFilters} showSku={false} />

      <section className="px-8 py-6">
        <div className="surface p-6 mb-6 flex items-center gap-6" data-testid="loss-summary">
          <AlertTriangle className="text-[#FF2A2A]" size={36} strokeWidth={1.5} />
          <div className="flex-1">
            <div className="eyebrow">Total margin bleed</div>
            <div className="kpi-value text-3xl text-[#FF2A2A] mt-1">{fmtEur(totalLoss)}</div>
            <div className="text-xs text-[#5E636E] mt-1">
              across <span className="font-mono-num">{fmtNum(filtered.length)}</span> SKU × marketplace combos · <span className="font-mono-num">{fmtNum(totalUnits)}</span> units sold at a loss
            </div>
          </div>
          <div className="flex flex-col items-end gap-2">
            <label className="eyebrow" htmlFor="target-margin-input">Target margin %</label>
            <div className="flex items-center gap-2">
              <input
                id="target-margin-input"
                type="number"
                step="1"
                min="0"
                max="90"
                value={targetMargin}
                onChange={(e) => setTargetMargin(e.target.value)}
                className="in w-24 text-right"
                data-testid="target-margin-input"
              />
              <span className="text-sm text-[#5E636E]">%</span>
            </div>
            <div className="text-[10px] text-[#5E636E] max-w-[220px] text-right leading-snug">
              0% = break-even. Suggested price covers COGS, operational, per-order shipping, commission and VAT, plus this margin.
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between mb-3 text-sm text-[#5E636E]">
          <div>
            <span className="font-mono-num text-[#111215]">{fmtNum(filtered.length)}</span> / <span className="font-mono-num">{fmtNum(rows.length)}</span> combos
            {activeFilterCount > 0 && (
              <span className="ml-3 pill" style={{ color: "#0055FF", background: "#E0EAFF", borderColor: "transparent" }}>{activeFilterCount} {activeFilterCount === 1 ? "filter" : "filters"} active</span>
            )}
          </div>
          <div className="flex items-center gap-3 relative">
            {activeFilterCount > 0 && (
              <button onClick={clearAll} className="inline-flex items-center gap-1 text-xs hover:text-[#FF2A2A]" data-testid="loss-clear-all-filters">
                <X size={12} /> Clear filters
              </button>
            )}
            <button
              onClick={() => setShowColPicker((v) => !v)}
              className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded border border-[#111215] bg-white hover:bg-[#111215] hover:text-white transition-colors"
              data-testid="loss-columns-toggle"
            >
              Columns ({visibleCols.length}/{ALL_COLS.length})
            </button>
            {showColPicker && (
              <div className="absolute top-full right-0 mt-2 surface p-3 z-40 min-w-[220px] shadow-lg" data-testid="loss-columns-picker" onClick={(e) => e.stopPropagation()}>
                <div className="eyebrow mb-2">Visible columns</div>
                {ALL_COLS.map((c) => (
                  <label key={c.key} className="flex items-center gap-2 py-1 text-xs cursor-pointer hover:bg-[#F5F6F8] px-1 rounded">
                    <input
                      type="checkbox"
                      checked={!hiddenCols.has(c.key)}
                      onChange={() => !c.always && toggleCol(c.key)}
                      disabled={c.always}
                      data-testid={`loss-col-toggle-${c.key}`}
                    />
                    <span className={c.always ? "text-[#9CA3AF]" : ""}>{c.label}{c.always ? " (locked)" : ""}</span>
                  </label>
                ))}
                <div className="mt-2 pt-2 border-t border-[#E5E7EB] flex justify-end">
                  <button onClick={() => setShowColPicker(false)} className="text-xs text-[#0055FF]" data-testid="loss-columns-close">Close</button>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="surface overflow-x-auto" style={{ overflow: "visible" }}>
          <table className="dense w-full" data-testid="loss-table">
            <thead>
              <tr>{visibleCols.map(renderCol)}</tr>
            </thead>
            <tbody>
              {loading && (<tr><td colSpan={visibleCols.length} className="text-center py-12 text-[#5E636E]">Analyzing margins...</td></tr>)}
              {!loading && filtered.length === 0 && (
                <tr><td colSpan={visibleCols.length} className="text-center py-12 text-[#00A859]">
                  ✓ No loss-makers match. Every SKU with cost data is profitable in this range (with current filters).
                </td></tr>
              )}
              {!loading && filtered.map((r, i) => (
                <tr key={`${r.sku}-${r.marketplace}-${i}`} data-testid={`loss-row-${r.sku}`}>
                  {visibleCols.map((c) => renderCell(r, c.key))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
