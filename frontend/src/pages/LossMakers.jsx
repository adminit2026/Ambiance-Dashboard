import { useEffect, useState } from "react";
import PageHeader from "@/components/PageHeader";
import FiltersBar, { useFilters } from "@/components/FiltersBar";
import api from "@/lib/api";
import { fmtEur, fmtNum, colorFor } from "@/lib/format";
import { AlertTriangle } from "lucide-react";

export default function LossMakers() {
  const { filters, setFilters, params } = useFilters();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    api.get("/library/loss-makers", { params }).then((r) => setRows(r.data)).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filters)]);

  const totalLoss = rows.reduce((acc, r) => acc + r.total_loss_eur, 0);
  const totalUnits = rows.reduce((acc, r) => acc + r.units, 0);

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
              across <span className="font-mono-num">{fmtNum(rows.length)}</span> SKU × marketplace combos · <span className="font-mono-num">{fmtNum(totalUnits)}</span> units sold at a loss
            </div>
          </div>
          <div className="text-right max-w-md text-xs text-[#5E636E]">
            Net per unit = avg unit price − (production + operational + production shipping + commission). Only SKUs with cost data are evaluated.
          </div>
        </div>

        <div className="surface overflow-x-auto">
          <table className="dense w-full" data-testid="loss-table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>Marketplace</th>
                <th>Product</th>
                <th className="text-right">Units</th>
                <th className="text-right">Avg Price</th>
                <th className="text-right">Prod Cost</th>
                <th className="text-right">+Op</th>
                <th className="text-right">+Ship</th>
                <th className="text-right">+Comm</th>
                <th className="text-right">Total Cost</th>
                <th className="text-right">Net / unit</th>
                <th className="text-right">Total Loss</th>
              </tr>
            </thead>
            <tbody>
              {loading && (<tr><td colSpan={12} className="text-center py-12 text-[#5E636E]">Analyzing margins...</td></tr>)}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={12} className="text-center py-12 text-[#00A859]">
                  ✓ No loss-makers found! Every SKU with cost data is profitable in this date range.
                </td></tr>
              )}
              {!loading && rows.map((r, i) => (
                <tr key={`${r.sku}-${r.marketplace}-${i}`} data-testid={`loss-row-${r.sku}`}>
                  <td className="font-mono-num font-medium">{r.sku}</td>
                  <td>
                    <span className="pill" style={{ background: colorFor(r.marketplace), color: "white", borderColor: "transparent" }}>{r.marketplace}</span>
                  </td>
                  <td className="max-w-[260px] truncate text-[#5E636E]" title={r.product_name}>{r.product_name || "—"}</td>
                  <td className="text-right font-mono-num">{fmtNum(r.units)}</td>
                  <td className="text-right font-mono-num">{fmtEur(r.avg_unit_price)}</td>
                  <td className="text-right font-mono-num text-[#5E636E]">{fmtEur(r.production_cost)}</td>
                  <td className="text-right font-mono-num text-[#5E636E]">{fmtEur(r.operational_cost)}</td>
                  <td className="text-right font-mono-num text-[#5E636E]">{fmtEur(r.production_shipping)}</td>
                  <td className="text-right font-mono-num text-[#5E636E]">{fmtEur(r.commission_per_unit)}</td>
                  <td className="text-right font-mono-num font-semibold">{fmtEur(r.total_cost_per_unit)}</td>
                  <td className="text-right font-mono-num text-[#FF2A2A] font-semibold">{fmtEur(r.net_per_unit)}</td>
                  <td className="text-right font-mono-num text-[#FF2A2A] font-bold">{fmtEur(r.total_loss_eur)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
