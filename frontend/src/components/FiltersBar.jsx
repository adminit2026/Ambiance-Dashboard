import { useEffect, useState } from "react";
import api from "@/lib/api";

export function useFilters(initial = {}) {
  const today = new Date();
  const yearStart = new Date(today.getFullYear(), 0, 1);
  const [filters, setFilters] = useState({
    date_from: initial.date_from || yearStart.toISOString().slice(0, 10),
    date_to: initial.date_to || today.toISOString().slice(0, 10),
    marketplaces: initial.marketplaces || "",
    sku: initial.sku || "",
  });
  const params = {};
  Object.entries(filters).forEach(([k, v]) => { if (v) params[k] = v; });
  return { filters, setFilters, params };
}

export default function FiltersBar({ filters, setFilters, showSku = true, rightSlot = null }) {
  const [marketplaces, setMarketplaces] = useState([]);
  useEffect(() => {
    api.get("/marketplaces").then((r) => setMarketplaces(r.data)).catch(() => {});
  }, []);

  const toggleMk = (mk) => {
    const list = filters.marketplaces ? filters.marketplaces.split(",") : [];
    const next = list.includes(mk) ? list.filter((x) => x !== mk) : [...list, mk];
    setFilters({ ...filters, marketplaces: next.join(",") });
  };

  const selected = filters.marketplaces ? filters.marketplaces.split(",") : [];

  return (
    <div className="surface border-b border-l-0 border-r-0 border-t-0 px-8 py-4 sticky top-0 z-20 bg-white" data-testid="filters-bar">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col">
          <label className="eyebrow mb-1">From</label>
          <input
            type="date"
            data-testid="filter-date-from"
            className="in"
            value={filters.date_from}
            onChange={(e) => setFilters({ ...filters, date_from: e.target.value })}
          />
        </div>
        <div className="flex flex-col">
          <label className="eyebrow mb-1">To</label>
          <input
            type="date"
            data-testid="filter-date-to"
            className="in"
            value={filters.date_to}
            onChange={(e) => setFilters({ ...filters, date_to: e.target.value })}
          />
        </div>
        {showSku && (
          <div className="flex flex-col">
            <label className="eyebrow mb-1">SKU contains</label>
            <input
              type="text"
              placeholder="e.g. SAND_"
              data-testid="filter-sku"
              className="in w-44"
              value={filters.sku}
              onChange={(e) => setFilters({ ...filters, sku: e.target.value })}
            />
          </div>
        )}
        <div className="flex flex-col">
          <label className="eyebrow mb-1">Marketplaces</label>
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
        <div className="flex-1" />
        {rightSlot}
      </div>
    </div>
  );
}
