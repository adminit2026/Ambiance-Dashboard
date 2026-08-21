import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useT } from "@/lib/i18n";

function isoDate(d) {
  // Format to local YYYY-MM-DD. Using toISOString() would shift dates to UTC
  // which, for users east of UTC (e.g. Europe), turns "July 1 00:00 local"
  // into "June 30 22:00 UTC" and breaks presets like MTD.
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function presetRange(key) {
  const today = new Date();
  const start = new Date(today);
  switch (key) {
    case "today":
      return { from: isoDate(today), to: isoDate(today) };
    case "wtd": {
      const day = (today.getDay() + 6) % 7; // Mon=0
      start.setDate(today.getDate() - day);
      return { from: isoDate(start), to: isoDate(today) };
    }
    case "mtd":
      return { from: isoDate(new Date(today.getFullYear(), today.getMonth(), 1)), to: isoDate(today) };
    case "ytd":
      return { from: isoDate(new Date(today.getFullYear(), 0, 1)), to: isoDate(today) };
    case "last30":
      start.setDate(today.getDate() - 29);
      return { from: isoDate(start), to: isoDate(today) };
    case "last90":
      start.setDate(today.getDate() - 89);
      return { from: isoDate(start), to: isoDate(today) };
    default:
      return null;
  }
}

const PRESETS = [
  { key: "today", labelKey: "filters.preset_today", fallback: "Today" },
  { key: "wtd", labelKey: "filters.preset_wtd", fallback: "WTD" },
  { key: "mtd", labelKey: "filters.preset_mtd", fallback: "MTD" },
  { key: "last30", labelKey: "filters.preset_last30", fallback: "Last 30d" },
  { key: "last90", labelKey: "filters.preset_last90", fallback: "Last 90d" },
  { key: "ytd", labelKey: "filters.preset_ytd", fallback: "YTD" },
];

export function useFilters(initial = {}) {
  const today = new Date();
  const yearStart = new Date(today.getFullYear(), 0, 1);
  const [filters, setFilters] = useState({
    date_from: initial.date_from || isoDate(yearStart),
    date_to: initial.date_to || isoDate(today),
    marketplaces: initial.marketplaces || "",
    sku: initial.sku || "",
    stock_only: initial.stock_only ?? false,
  });
  const params = {};
  Object.entries(filters).forEach(([k, v]) => {
    if (k === "stock_only") { if (v) params[k] = "true"; return; }
    if (v) params[k] = v;
  });
  return { filters, setFilters, params };
}

export default function FiltersBar({ filters, setFilters, showSku = true, rightSlot = null }) {
  const [marketplaces, setMarketplaces] = useState([]);
  const { t } = useT();
  useEffect(() => {
    api.get("/marketplaces").then((r) => setMarketplaces(r.data)).catch(() => {});
  }, []);

  const toggleMk = (mk) => {
    const list = filters.marketplaces ? filters.marketplaces.split(",") : [];
    const next = list.includes(mk) ? list.filter((x) => x !== mk) : [...list, mk];
    setFilters({ ...filters, marketplaces: next.join(",") });
  };

  const applyPreset = (key) => {
    const r = presetRange(key);
    if (r) setFilters({ ...filters, date_from: r.from, date_to: r.to });
  };

  const activePreset = (() => {
    for (const p of PRESETS) {
      const r = presetRange(p.key);
      if (r && r.from === filters.date_from && r.to === filters.date_to) return p.key;
    }
    return null;
  })();

  const selected = filters.marketplaces ? filters.marketplaces.split(",") : [];

  return (
    <div className="surface border-b border-l-0 border-r-0 border-t-0 px-8 py-4 sticky top-0 z-20 bg-white" data-testid="filters-bar">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col">
          <label className="eyebrow mb-1">{t("filters.from") || "From"}</label>
          <input
            type="date"
            data-testid="filter-date-from"
            className="in"
            value={filters.date_from}
            onChange={(e) => setFilters({ ...filters, date_from: e.target.value })}
          />
        </div>
        <div className="flex flex-col">
          <label className="eyebrow mb-1">{t("filters.to") || "To"}</label>
          <input
            type="date"
            data-testid="filter-date-to"
            className="in"
            value={filters.date_to}
            onChange={(e) => setFilters({ ...filters, date_to: e.target.value })}
          />
        </div>
        <div className="flex flex-col">
          <label className="eyebrow mb-1">{t("filters.presets") || "Quick range"}</label>
          <div className="flex flex-wrap gap-1.5" data-testid="filter-presets">
            {PRESETS.map((p) => {
              const active = activePreset === p.key;
              return (
                <button
                  key={p.key}
                  data-testid={`filter-preset-${p.key}`}
                  onClick={() => applyPreset(p.key)}
                  className="pill transition-colors"
                  style={active ? { background: "#0055FF", color: "white", borderColor: "transparent" } : {}}
                >
                  {t(p.labelKey) || p.fallback}
                </button>
              );
            })}
          </div>
        </div>
        {showSku && (
          <div className="flex flex-col">
            <label className="eyebrow mb-1">{t("filters.sku") || "SKU starts with"}</label>
            <input
              type="text"
              placeholder="e.g. col-lam-"
              data-testid="filter-sku"
              className="in w-44"
              value={filters.sku}
              onChange={(e) => setFilters({ ...filters, sku: e.target.value })}
            />
          </div>
        )}
        <div className="flex flex-col">
          <div className="flex items-center gap-3 mb-1">
            <label className="eyebrow">{t("filters.marketplaces") || "Marketplaces"}</label>
            <div className="flex gap-1.5">
              <button
                type="button"
                data-testid="filter-mk-select-all"
                onClick={() => setFilters({ ...filters, marketplaces: marketplaces.join(",") })}
                className="text-[10px] uppercase tracking-wider text-[#0055FF] hover:underline"
              >
                Select all
              </button>
              <span className="text-[10px] text-[#5E636E]">·</span>
              <button
                type="button"
                data-testid="filter-mk-clear-all"
                onClick={() => setFilters({ ...filters, marketplaces: "" })}
                className="text-[10px] uppercase tracking-wider text-[#5E636E] hover:underline"
              >
                Deselect all
              </button>
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5" data-testid="filter-marketplaces">
            {marketplaces.length === 0 && (
              <span className="text-xs text-[#5E636E]">Upload orders to populate</span>
            )}
            {marketplaces.map((mk) => {
              const active = selected.includes(mk);
              return (
                <button
                  key={mk}
                  data-testid={`filter-mk-${mk}`}
                  onClick={() => toggleMk(mk)}
                  className={`pill ${active ? "" : ""} transition-colors`}
                  style={active ? { background: "#111215", color: "white", borderColor: "transparent" } : {}}
                >
                  {mk}
                </button>
              );
            })}
          </div>
        </div>
        <div className="flex flex-col">
          <label className="eyebrow mb-1">Stock</label>
          <button
            type="button"
            data-testid="filter-stock-only"
            onClick={() => setFilters({ ...filters, stock_only: !filters.stock_only })}
            className={`pill transition-colors`}
            style={filters.stock_only ? { background: "#00A859", color: "white", borderColor: "transparent" } : {}}
            title="Show only stock items — SKUs starting with AMB-, J-, J3-, J4-, 3D-, carp- (excludes J3-privacy)"
          >
            {filters.stock_only ? "✓ Stock items only" : "Stock items"}
          </button>
        </div>
        <div className="flex-1" />
        {rightSlot}
      </div>
    </div>
  );
}
