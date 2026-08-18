import { useEffect, useState, useMemo } from "react";
import PageHeader from "@/components/PageHeader";
import FiltersBar, { useFilters } from "@/components/FiltersBar";
import api, { API_BASE } from "@/lib/api";
import { fmtEur, fmtEurExact, fmtNum, colorFor } from "@/lib/format";
import { Download, Search } from "lucide-react";

export default function Prices() {
  const { filters, setFilters, params } = useFilters();
  const [data, setData] = useState({ marketplaces: [], items: [] });
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");

  useEffect(() => {
    setLoading(true);
    api.get("/skus/prices", { params: { ...params, limit: 500 } })
      .then((r) => setData(r.data))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filters)]);

  const filtered = useMemo(() => {
    if (!search.trim()) return data.items;
    const q = search.toLowerCase();
    return data.items.filter(
      (it) => it.sku.toLowerCase().includes(q) || (it.product_name || "").toLowerCase().includes(q)
    );
  }, [data.items, search]);

  const exportXlsx = async () => {
    const token = localStorage.getItem("ambiance_token");
    const qs = new URLSearchParams(params).toString();
    const resp = await fetch(`${API_BASE}/skus/prices/export?${qs}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `sku_prices_${new Date().toISOString().slice(0, 10)}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div>
      <PageHeader kicker="Price intelligence" title="SKU Price Lookup" />
      <FiltersBar
        filters={filters}
        setFilters={setFilters}
        showSku={false}
        rightSlot={
          <button onClick={exportXlsx} className="btn-primary flex items-center gap-2" data-testid="prices-export-button">
            <Download size={14} /> Export Excel
          </button>
        }
      />

      <section className="px-8 py-6">
        <div className="surface p-4 mb-4 flex items-center gap-3">
          <Search size={16} className="text-[#5E636E]" />
          <input
            className="in flex-1"
            placeholder="Search SKU or product name (e.g. 'SAND_', 'roll-mono', 'Baby On Board')"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            data-testid="prices-search-input"
          />
          <span className="text-xs text-[#5E636E] font-mono-num">
            {fmtNum(filtered.length)} / {fmtNum(data.items.length)} SKUs
          </span>
        </div>

        <div className="surface overflow-x-auto">
          <table className="dense w-full" data-testid="prices-table">
            <thead>
              <tr>
                <th className="sticky left-0 bg-[#FAFAFB] z-10">SKU</th>
                <th>Product</th>
                {data.marketplaces.map((m) => (
                  <th key={m} className="text-right">
                    <div className="flex items-center justify-end gap-1.5">
                      <span className="w-2 h-2 inline-block" style={{ background: colorFor(m) }} />
                      <span>{m}</span>
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={data.marketplaces.length + 2} className="text-center py-12 text-[#5E636E]">Loading prices...</td></tr>
              )}
              {!loading && filtered.length === 0 && (
                <tr><td colSpan={data.marketplaces.length + 2} className="text-center py-12 text-[#5E636E]">No SKUs match. Adjust filters or search.</td></tr>
              )}
              {!loading && filtered.map((it) => (
                <tr key={it.sku} data-testid={`price-row-${it.sku}`}>
                  <td className="font-mono-num font-medium sticky left-0 bg-white z-10">{it.sku}</td>
                  <td className="max-w-[320px] truncate text-[#5E636E]" title={it.product_name}>{it.product_name || "—"}</td>
                  {data.marketplaces.map((m) => {
                    const p = it.prices[m];
                    if (!p) return <td key={m} className="text-right text-[#D5D7DC]">—</td>;
                    return (
                      <td key={m} className="text-right font-mono-num">
                        <div>{fmtEurExact(p.avg)}</div>
                        {p.min !== p.max && (
                          <div className="text-[10px] text-[#5E636E]">
                            {fmtEurExact(p.min)} – {fmtEurExact(p.max)}
                          </div>
                        )}
                        <div className="text-[10px] text-[#5E636E]">{fmtNum(p.units)} units</div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-[#5E636E] mt-3">
          Each cell shows <strong>avg unit price (EUR)</strong> for that SKU on that marketplace, plus min–max range when prices vary, and total units sold.
        </p>
      </section>
    </div>
  );
}
