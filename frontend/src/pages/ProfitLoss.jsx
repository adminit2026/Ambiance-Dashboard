import { useEffect, useState } from "react";
import PageHeader from "@/components/PageHeader";
import FiltersBar, { useFilters } from "@/components/FiltersBar";
import api from "@/lib/api";
import { fmtEur, fmtPct } from "@/lib/format";

export default function ProfitLoss() {
  const { filters, setFilters, params } = useFilters();
  const [rows, setRows] = useState([]);

  useEffect(() => {
    api.get("/dashboard/profit-loss", { params }).then((r) => setRows(r.data));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filters)]);

  const total = rows.reduce(
    (acc, r) => ({
      revenue: acc.revenue + r.revenue_eur,
      cogs: acc.cogs + r.cogs_eur,
      shipping: acc.shipping + r.shipping_eur,
      vat: acc.vat + r.vat_eur,
      net: acc.net + r.net_profit_eur,
    }),
    { revenue: 0, cogs: 0, shipping: 0, vat: 0, net: 0 }
  );

  return (
    <div>
      <PageHeader kicker="Financial summary" title="Profit & Loss Report" />
      <FiltersBar filters={filters} setFilters={setFilters} />

      <section className="px-8 py-6">
        <div className="surface overflow-x-auto">
          <table className="dense w-full" data-testid="pnl-table">
            <thead>
              <tr>
                <th>Line item</th>
                {rows.map((r) => (
                  <th key={r.marketplace} className="text-right">{r.marketplace}</th>
                ))}
                <th className="text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              <Row label="Gross Revenue" rows={rows} get={(r) => r.revenue_eur} totalVal={total.revenue} bold />
              <Row label="− Cost of Goods Sold" rows={rows} get={(r) => -r.cogs_eur} totalVal={-total.cogs} muted />
              <Row label="− Shipping Costs" rows={rows} get={(r) => -r.shipping_eur} totalVal={-total.shipping} muted />
              <tr><td colSpan={rows.length + 2} style={{ background: "#F7F7F8", height: 4, padding: 0 }} /></tr>
              <Row label="Net Profit" rows={rows} get={(r) => r.net_profit_eur} totalVal={total.net} bold accent />
              <Row label="Margin %" rows={rows} get={(r) => r.margin_pct} totalVal={total.revenue ? (total.net / total.revenue) * 100 : 0} pct />
            </tbody>
          </table>
        </div>
        {total.cogs === 0 && (
          <div className="mt-3 text-xs text-[#5E636E]" data-testid="pnl-cogs-warning">
            Tip: upload a Cost of Production file in <strong>Uploads</strong> to populate COGS and reveal true margin.
          </div>
        )}
      </section>
    </div>
  );
}

function Row({ label, rows, get, totalVal, bold, muted, accent, pct }) {
  const fmt = (v) => (pct ? fmtPct(v) : fmtEur(v));
  return (
    <tr>
      <td className={`${bold ? "font-semibold" : ""} ${muted ? "text-[#5E636E]" : ""}`}>{label}</td>
      {rows.map((r) => {
        const v = get(r);
        const color = accent ? (v >= 0 ? "text-[#00A859]" : "text-[#FF2A2A]") : "";
        return <td key={r.marketplace} className={`text-right font-mono-num ${color} ${bold ? "font-semibold" : ""} ${muted ? "text-[#5E636E]" : ""}`}>{fmt(v)}</td>;
      })}
      <td className={`text-right font-mono-num ${bold ? "font-semibold" : ""} ${accent ? (totalVal >= 0 ? "text-[#00A859]" : "text-[#FF2A2A]") : ""} ${muted ? "text-[#5E636E]" : ""}`}>{fmt(totalVal)}</td>
    </tr>
  );
}
