import { useEffect, useState } from "react";
import PageHeader from "@/components/PageHeader";
import api from "@/lib/api";
import { fmtEur, fmtNum } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Truck } from "lucide-react";

function isoToday() {
  return new Date().toISOString().slice(0, 10);
}
function isoPlusDays(days) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export default function AmazonDelivery() {
  const { t } = useT();
  const [from, setFrom] = useState(isoToday());
  const [to, setTo] = useState(isoPlusDays(60));
  const [sku, setSku] = useState("");
  const [data, setData] = useState({ totals: {}, timeline: [], pos: [] });
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true);
    const params = {};
    if (from) params.delivery_from = from;
    if (to) params.delivery_to = to;
    if (sku) params.sku = sku;
    api
      .get("/dashboard/amazon-delivery", { params })
      .then((r) => setData(r.data))
      .finally(() => setLoading(false));
  };

  // Auto-load on mount and when range changes
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [from, to, sku]);

  const totals = data.totals || {};
  const timeline = data.timeline || [];
  const pos = data.pos || [];

  return (
    <div>
      <PageHeader kicker={t("amazon.kicker")} title={t("amazon.title")} />

      <div className="surface border-b border-l-0 border-r-0 border-t-0 px-8 py-4 sticky top-0 z-20 bg-white" data-testid="amazon-filters">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col">
            <label className="eyebrow mb-1">{t("amazon.delivery_from")}</label>
            <input type="date" className="in" value={from} onChange={(e) => setFrom(e.target.value)} data-testid="amazon-delivery-from" />
          </div>
          <div className="flex flex-col">
            <label className="eyebrow mb-1">{t("amazon.delivery_to")}</label>
            <input type="date" className="in" value={to} onChange={(e) => setTo(e.target.value)} data-testid="amazon-delivery-to" />
          </div>
          <div className="flex flex-col">
            <label className="eyebrow mb-1">{t("filters.sku")}</label>
            <input type="text" placeholder="e.g. col-lam-" className="in w-44" value={sku} onChange={(e) => setSku(e.target.value)} data-testid="amazon-filter-sku" />
          </div>
          <div className="flex-1" />
          <div className="text-xs text-[#5E636E] max-w-md text-right">
            {t("amazon.help")}
          </div>
        </div>
      </div>

      <section className="px-8 py-6 space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4" data-testid="amazon-kpis">
          <div className="surface p-5">
            <div className="flex items-center gap-2 eyebrow">
              <Truck size={14} strokeWidth={1.5} /> {t("amazon.kpi_pos")}
            </div>
            <div className="kpi-value text-2xl mt-2" data-testid="amazon-kpi-pos">{fmtNum(totals.pos || 0)}</div>
          </div>
          <div className="surface p-5">
            <div className="eyebrow">{t("amazon.kpi_units")}</div>
            <div className="kpi-value text-2xl mt-2" data-testid="amazon-kpi-units">{fmtNum(totals.units || 0)}</div>
          </div>
          <div className="surface p-5">
            <div className="eyebrow">{t("amazon.kpi_revenue")}</div>
            <div className="kpi-value text-2xl mt-2 text-[#00A859]" data-testid="amazon-kpi-revenue">{fmtEur(totals.revenue_eur || 0)}</div>
            <div className="text-xs text-[#5E636E] mt-1">{t("amazon.kpi_revenue_sub")}</div>
          </div>
          <div className="surface p-5">
            <div className="eyebrow">{t("amazon.kpi_lines")}</div>
            <div className="kpi-value text-2xl mt-2" data-testid="amazon-kpi-lines">{fmtNum(totals.delivery_lines || 0)}</div>
          </div>
        </div>

        <div>
          <h3 className="text-sm font-semibold mb-3 text-[#111215]">{t("amazon.timeline_title")}</h3>
          <div className="surface overflow-x-auto">
            <table className="dense w-full" data-testid="amazon-timeline">
              <thead>
                <tr>
                  <th>{t("amazon.col_delivery_date")}</th>
                  <th className="text-right">{t("amazon.col_pos")}</th>
                  <th className="text-right">{t("amazon.col_units")}</th>
                  <th className="text-right">{t("amazon.col_revenue")}</th>
                </tr>
              </thead>
              <tbody>
                {loading && (<tr><td colSpan={4} className="text-center py-10 text-[#5E636E]">{t("common.loading")}</td></tr>)}
                {!loading && timeline.length === 0 && (
                  <tr><td colSpan={4} className="text-center py-10 text-[#5E636E]">{t("amazon.empty")}</td></tr>
                )}
                {!loading && timeline.map((r) => (
                  <tr key={r.delivery_date}>
                    <td className="font-mono-num font-semibold">{r.delivery_date}</td>
                    <td className="text-right font-mono-num">{fmtNum(r.pos)}</td>
                    <td className="text-right font-mono-num">{fmtNum(r.units)}</td>
                    <td className="text-right font-mono-num">{fmtEur(r.revenue_eur)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div>
          <h3 className="text-sm font-semibold mb-3 text-[#111215]">{t("amazon.pos_title")}</h3>
          <div className="surface overflow-x-auto">
            <table className="dense w-full" data-testid="amazon-pos">
              <thead>
                <tr>
                  <th>{t("amazon.col_po")}</th>
                  <th>{t("amazon.col_delivery_date")}</th>
                  <th>{t("amazon.col_window_start")}</th>
                  <th>{t("amazon.col_order_date")}</th>
                  <th>{t("amazon.col_warehouse")}</th>
                  <th>{t("amazon.col_status")}</th>
                  <th className="text-right">{t("amazon.col_lines")}</th>
                  <th className="text-right">{t("amazon.col_units")}</th>
                  <th className="text-right">{t("amazon.col_revenue")}</th>
                </tr>
              </thead>
              <tbody>
                {!loading && pos.length === 0 && (
                  <tr><td colSpan={9} className="text-center py-10 text-[#5E636E]">—</td></tr>
                )}
                {pos.map((p) => (
                  <tr key={p.po} data-testid={`amazon-po-${p.po}`}>
                    <td className="font-mono-num font-semibold">{p.po}</td>
                    <td className="font-mono-num">{p.delivery_date}</td>
                    <td className="font-mono-num text-[#5E636E]">{p.window_start}</td>
                    <td className="font-mono-num text-[#5E636E]">{p.order_date}</td>
                    <td className="text-[#5E636E]">{p.warehouse}</td>
                    <td>{p.status}</td>
                    <td className="text-right font-mono-num">{fmtNum(p.lines)}</td>
                    <td className="text-right font-mono-num">{fmtNum(p.units)}</td>
                    <td className="text-right font-mono-num font-semibold">{fmtEur(p.revenue_eur)}</td>
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
