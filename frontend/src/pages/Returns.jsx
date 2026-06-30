import { useEffect, useState } from "react";
import PageHeader from "@/components/PageHeader";
import FiltersBar, { useFilters } from "@/components/FiltersBar";
import api from "@/lib/api";
import { fmtEur, fmtEurExact, fmtNum, fmtPct, colorFor } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Undo2, XOctagon } from "lucide-react";

export default function Returns() {
  const { t } = useT();
  const { filters, setFilters, params } = useFilters();
  const [data, setData] = useState({ by_marketplace: [], totals: {}, recent: [] });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    api
      .get("/dashboard/returns", { params })
      .then((r) => setData(r.data))
      .finally(() => setLoading(false));
     
  }, [JSON.stringify(filters)]);

  const totals = data.totals || {};
  const rows = data.by_marketplace || [];
  const recent = data.recent || [];

  return (
    <div>
      <PageHeader kicker={t("returns.kicker")} title={t("returns.title")} />
      <FiltersBar filters={filters} setFilters={setFilters} showSku={false} />

      <section className="px-8 py-6 space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4" data-testid="returns-kpis">
          <div className="surface p-5">
            <div className="flex items-center gap-2 eyebrow">
              <Undo2 size={14} strokeWidth={1.5} /> {t("returns.refund_total")}
            </div>
            <div className="kpi-value text-2xl mt-2 text-[#FF2A2A]" data-testid="returns-refund-total">
              {fmtEur(totals.refund_eur || 0)}
            </div>
            <div className="text-xs text-[#5E636E] mt-1">
              <span className="font-mono-num">{fmtNum(totals.refund_units || 0)}</span> units ·{" "}
              <span className="font-mono-num">{fmtNum(totals.refund_orders || 0)}</span> orders
            </div>
          </div>
          <div className="surface p-5">
            <div className="flex items-center gap-2 eyebrow">
              <XOctagon size={14} strokeWidth={1.5} /> {t("returns.cancel_total")}
            </div>
            <div className="kpi-value text-2xl mt-2 text-[#A65800]" data-testid="returns-cancel-total">
              {fmtEur(totals.cancel_eur || 0)}
            </div>
            <div className="text-xs text-[#5E636E] mt-1">
              <span className="font-mono-num">{fmtNum(totals.cancel_units || 0)}</span> units ·{" "}
              <span className="font-mono-num">{fmtNum(totals.cancel_orders || 0)}</span> orders
            </div>
          </div>
          <div className="surface p-5">
            <div className="eyebrow">{t("returns.refund_rate")}</div>
            <div className="kpi-value text-2xl mt-2" data-testid="returns-refund-rate">
              {fmtPct(totals.refund_rate_pct || 0)}
            </div>
            <div className="text-xs text-[#5E636E] mt-1">
              vs. {fmtEur(totals.total_revenue_eur || 0)} gross
            </div>
          </div>
          <div className="surface p-5">
            <div className="eyebrow">{t("returns.cancel_rate")}</div>
            <div className="kpi-value text-2xl mt-2" data-testid="returns-cancel-rate">
              {fmtPct(totals.cancel_rate_pct || 0)}
            </div>
            <div className="text-xs text-[#5E636E] mt-1">
              vs. {fmtEur(totals.total_revenue_eur || 0)} gross
            </div>
          </div>
        </div>

        <div className="surface overflow-x-auto">
          <table className="dense w-full" data-testid="returns-by-marketplace">
            <thead>
              <tr>
                <th>{t("returns.col_marketplace")}</th>
                <th className="text-right">{t("returns.col_refund_orders")}</th>
                <th className="text-right">{t("returns.col_refund_units")}</th>
                <th className="text-right">{t("returns.col_refund_eur")}</th>
                <th className="text-right">{t("returns.col_cancel_orders")}</th>
                <th className="text-right">{t("returns.col_cancel_units")}</th>
                <th className="text-right">{t("returns.col_cancel_eur")}</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={7} className="text-center py-10 text-[#5E636E]">{t("common.loading")}</td>
                </tr>
              )}
              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="text-center py-10 text-[#00A859]">
                    ✓ {t("returns.empty")}
                  </td>
                </tr>
              )}
              {!loading && rows.map((r) => (
                <tr key={r.marketplace} data-testid={`returns-row-${r.marketplace}`}>
                  <td>
                    <span className="pill" style={{ background: colorFor(r.marketplace), color: "white", borderColor: "transparent" }}>
                      {r.marketplace}
                    </span>
                  </td>
                  <td className="text-right font-mono-num">{fmtNum(r.refund_orders)}</td>
                  <td className="text-right font-mono-num">{fmtNum(r.refund_units)}</td>
                  <td className="text-right font-mono-num text-[#FF2A2A] font-semibold">{fmtEur(r.refund_eur)}</td>
                  <td className="text-right font-mono-num">{fmtNum(r.cancel_orders)}</td>
                  <td className="text-right font-mono-num">{fmtNum(r.cancel_units)}</td>
                  <td className="text-right font-mono-num text-[#A65800] font-semibold">{fmtEur(r.cancel_eur)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div>
          <h3 className="text-sm font-semibold mb-3 text-[#111215]">{t("returns.recent")}</h3>
          <div className="surface overflow-x-auto">
            <table className="dense w-full" data-testid="returns-recent">
              <thead>
                <tr>
                  <th>{t("returns.col_date")}</th>
                  <th>{t("returns.col_order")}</th>
                  <th>{t("returns.col_marketplace")}</th>
                  <th>SKU</th>
                  <th>{t("returns.col_status")}</th>
                  <th className="text-right">Qty</th>
                  <th className="text-right">{t("returns.col_amount")}</th>
                </tr>
              </thead>
              <tbody>
                {recent.length === 0 && !loading && (
                  <tr><td colSpan={7} className="text-center py-8 text-[#5E636E]">—</td></tr>
                )}
                {recent.map((o, i) => (
                  <tr key={`${o.order_id}-${o.sku}-${i}`}>
                    <td className="font-mono-num">{(o.order_date_iso || "").slice(0, 10)}</td>
                    <td className="font-mono-num">{o.order_id}</td>
                    <td>
                      <span className="pill" style={{ background: colorFor(o.marketplace), color: "white", borderColor: "transparent" }}>{o.marketplace}</span>
                    </td>
                    <td className="font-mono-num">{o.sku}</td>
                    <td>{o.status}</td>
                    <td className="text-right font-mono-num">{fmtNum(o.quantity)}</td>
                    <td className="text-right font-mono-num">{fmtEurExact(o.line_total_eur || 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>
  );
}
