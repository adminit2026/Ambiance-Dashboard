import { useEffect, useState } from "react";
import PageHeader from "@/components/PageHeader";
import FiltersBar, { useFilters } from "@/components/FiltersBar";
import api from "@/lib/api";
import { fmtEur, fmtNum, fmtPct } from "@/lib/format";

export default function Products() {
  const { filters, setFilters, params } = useFilters();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    api.get("/dashboard/top-skus", { params: { ...params, limit: 100 } })
      .then((r) => setRows(r.data))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filters)]);

  return (
    <div>
      <PageHeader kicker="Catalog performance" title="Product Performance" />
      <FiltersBar filters={filters} setFilters={setFilters} />

      <section className="px-8 py-6">
        <div className="surface overflow-x-auto">
          <table className="dense w-full" data-testid="products-table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>Product</th>
                <th className="text-right">Units</th>
                <th className="text-right">Orders</th>
                <th className="text-right">Revenue</th>
                <th className="text-right">COGS</th>
                <th className="text-right">Margin</th>
                <th className="text-right">Margin %</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={8} className="text-center text-[#5E636E] py-12">Loading...</td></tr>
              )}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={8} className="text-center text-[#5E636E] py-12">No products yet. Upload orders first.</td></tr>
              )}
              {rows.map((r) => (
                <tr key={r.sku} data-testid={`product-row-${r.sku}`}>
                  <td className="font-mono-num font-medium">{r.sku}</td>
                  <td className="max-w-[420px] truncate" title={r.product_name}>{r.product_name || "—"}</td>
                  <td className="text-right font-mono-num">{fmtNum(r.units)}</td>
                  <td className="text-right font-mono-num">{fmtNum(r.orders)}</td>
                  <td className="text-right font-mono-num">{fmtEur(r.revenue_eur)}</td>
                  <td className="text-right font-mono-num text-[#5E636E]">
                    {r.has_cost ? fmtEur(r.cogs_eur) : <span className="pill">no cost</span>}
                  </td>
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
