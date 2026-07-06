import { useEffect, useState } from "react";
import PageHeader from "@/components/PageHeader";
import FiltersBar, { useFilters } from "@/components/FiltersBar";
import KpiCard from "@/components/KpiCard";
import api from "@/lib/api";
import { fmtEur, fmtNum, fmtPct, colorFor } from "@/lib/format";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  PieChart, Pie, Cell, BarChart, Bar,
} from "recharts";

export default function Dashboard() {
  const { filters, setFilters, params } = useFilters();
  const [summary, setSummary] = useState(null);
  const [trend, setTrend] = useState([]);
  const [breakdown, setBreakdown] = useState([]);
  const [showTotal, setShowTotal] = useState(false);

  useEffect(() => {
    api.get("/dashboard/summary", { params }).then((r) => setSummary(r.data));
    api.get("/dashboard/trend", { params: { ...params, granularity: "day", rollup: true } }).then((r) => setTrend(r.data));
    api.get("/dashboard/marketplace-breakdown", { params: { ...params, rollup: true } }).then((r) => setBreakdown(r.data));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filters)]);

  const allMks = Array.from(new Set(trend.flatMap((d) => Object.keys(d.by_marketplace || {}))));
  const chartData = trend.map((d) => ({ period: d.period, total: d.revenue_total, ...d.by_marketplace }));

  return (
    <div>
      <PageHeader kicker="Overview" title="Aggregate Dashboard" />
      <FiltersBar filters={filters} setFilters={setFilters} />

      <section className="px-8 py-6 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-0 grid-borders">
        <KpiCard testId="kpi-revenue" label="Turnover" value={fmtEur(summary?.revenue_eur)} sub={`${fmtNum(summary?.orders)} orders · gross sales before deductions`} accent="#0055FF" />
        <KpiCard testId="kpi-units" label="Units Sold" value={fmtNum(summary?.units)} sub={`${fmtNum(summary?.lines)} order lines`} accent="#111215" />
        <KpiCard testId="kpi-aov" label="Avg Order Value" value={fmtEur(summary?.aov_eur)} sub={`Shipping ${fmtEur(summary?.shipping_eur)}`} accent="#FF9900" />
        <KpiCard testId="kpi-margin" label="Net Margin" value={fmtPct(summary?.margin_pct)} sub={summary && summary.cogs_eur > 0 ? `${fmtEur(summary?.margin_eur)} after all costs` : "Upload cost file to compute"} accent="#00A859" />
      </section>

      <section className="px-8 grid grid-cols-1 lg:grid-cols-3 gap-0 grid-borders" data-testid="trend-section">
        <div className="lg:col-span-2 p-6">
          <div className="flex items-center justify-between mb-4 gap-4 flex-wrap">
            <div>
              <div className="eyebrow">Sales trend</div>
              <h3 className="font-display text-xl font-semibold mt-1">Turnover by day · per marketplace</h3>
            </div>
            <label className="flex items-center gap-2 text-sm text-[#5E636E] cursor-pointer select-none" data-testid="toggle-total">
              <input
                type="checkbox"
                checked={showTotal}
                onChange={(e) => setShowTotal(e.target.checked)}
                className="accent-[#0055FF]"
                data-testid="toggle-total-checkbox"
              />
              Show total line
            </label>
          </div>
          {trend.length === 0 ? (
            <EmptyState text="No sales in this range. Try Uploads to import orders." />
          ) : (
            <ResponsiveContainer width="100%" height={320}>
              <LineChart data={chartData} margin={{ left: 10, right: 10 }}>
                <CartesianGrid stroke="#E5E7EB" vertical={false} />
                <XAxis dataKey="period" tick={{ fontSize: 11, fill: "#5E636E" }} stroke="#E5E7EB" />
                <YAxis tick={{ fontSize: 11, fill: "#5E636E" }} stroke="#E5E7EB" tickFormatter={(v) => `€${v}`} />
                <Tooltip formatter={(v) => fmtEur(v)} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                {showTotal && (
                  <Line type="monotone" dataKey="total" name="Total" stroke="#111215" strokeWidth={2} dot={false} />
                )}
                {allMks.map((mk) => (
                  <Line key={mk} type="monotone" dataKey={mk} stroke={colorFor(mk)} strokeWidth={1.25} dot={false} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="p-6">
          <div className="eyebrow">Mix</div>
          <h3 className="font-display text-xl font-semibold mt-1 mb-4">Turnover by marketplace</h3>
          {breakdown.length === 0 ? (
            <EmptyState text="No data" />
          ) : (
            <>
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie data={breakdown} dataKey="revenue_eur" nameKey="marketplace" innerRadius={55} outerRadius={85} paddingAngle={1}>
                    {breakdown.map((d) => <Cell key={d.marketplace} fill={colorFor(d.marketplace)} />)}
                  </Pie>
                  <Tooltip formatter={(v) => fmtEur(v)} />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-1 mt-2">
                {breakdown.map((b) => (
                  <div key={b.marketplace} className="flex items-center justify-between text-sm py-1.5">
                    <div className="flex items-center gap-2">
                      <span className="w-2.5 h-2.5 inline-block" style={{ background: colorFor(b.marketplace) }} />
                      <span>{b.marketplace}</span>
                    </div>
                    <span className="font-mono-num text-[#111215]">{fmtEur(b.revenue_eur)}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </section>

      <section className="px-8 pt-0 pb-12 grid grid-cols-1 lg:grid-cols-2 gap-0 grid-borders">
        <div className="p-6">
          <div className="eyebrow">Units shipped</div>
          <h3 className="font-display text-xl font-semibold mt-1 mb-4">Units by marketplace</h3>
          {breakdown.length === 0 ? <EmptyState text="No data" /> : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={breakdown}>
                <CartesianGrid stroke="#E5E7EB" vertical={false} />
                <XAxis dataKey="marketplace" tick={{ fontSize: 11, fill: "#5E636E" }} stroke="#E5E7EB" />
                <YAxis tick={{ fontSize: 11, fill: "#5E636E" }} stroke="#E5E7EB" />
                <Tooltip />
                <Bar dataKey="units" radius={0}>
                  {breakdown.map((d) => <Cell key={d.marketplace} fill={colorFor(d.marketplace)} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="p-6">
          <div className="eyebrow">Avg order value</div>
          <h3 className="font-display text-xl font-semibold mt-1 mb-4">AOV by marketplace</h3>
          {breakdown.length === 0 ? <EmptyState text="No data" /> : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={breakdown}>
                <CartesianGrid stroke="#E5E7EB" vertical={false} />
                <XAxis dataKey="marketplace" tick={{ fontSize: 11, fill: "#5E636E" }} stroke="#E5E7EB" />
                <YAxis tick={{ fontSize: 11, fill: "#5E636E" }} stroke="#E5E7EB" tickFormatter={(v) => `€${v}`} />
                <Tooltip formatter={(v) => fmtEur(v)} />
                <Bar dataKey="aov_eur" radius={0}>
                  {breakdown.map((d) => <Cell key={d.marketplace} fill={colorFor(d.marketplace)} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </section>
    </div>
  );
}

function EmptyState({ text }) {
  return (
    <div className="h-[200px] flex items-center justify-center text-sm text-[#5E636E] border border-dashed border-[#E5E7EB]" data-testid="empty-state">
      {text}
    </div>
  );
}
