import { useEffect, useState } from "react";
import PageHeader from "@/components/PageHeader";
import FiltersBar, { useFilters } from "@/components/FiltersBar";
import api from "@/lib/api";
import { fmtEur, fmtNum, colorFor } from "@/lib/format";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell,
  LineChart, Line, Legend,
} from "recharts";

export default function Marketplaces() {
  const { filters, setFilters, params } = useFilters();
  const [breakdown, setBreakdown] = useState([]);
  const [byCountry, setByCountry] = useState([]);
  const [trend, setTrend] = useState([]);
  const [active, setActive] = useState(null);

  useEffect(() => {
    api.get("/dashboard/marketplace-breakdown", { params }).then((r) => {
      setBreakdown(r.data);
      if (!active && r.data.length > 0) setActive(r.data[0].marketplace);
    });
    api.get("/dashboard/marketplace-country-breakdown", { params }).then((r) => setByCountry(r.data));
    api.get("/dashboard/trend", { params: { ...params, granularity: "month" } }).then((r) => setTrend(r.data));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filters)]);

  const monthly = trend.map((d) => ({ period: d.period, ...d.by_marketplace }));
  const allMks = Array.from(new Set(trend.flatMap((d) => Object.keys(d.by_marketplace || {}))));
  const activeData = breakdown.find((b) => b.marketplace === active);
  const activeCountries = byCountry.find((b) => b.marketplace === active)?.countries || [];

  return (
    <div>
      <PageHeader kicker="Channel performance" title="Marketplaces" />
      <FiltersBar filters={filters} setFilters={setFilters} />

      <section className="px-8 py-6">
        <div className="flex flex-wrap gap-0 grid-borders" data-testid="marketplace-tabs">
          {breakdown.map((b) => (
            <button
              key={b.marketplace}
              data-testid={`mk-tab-${b.marketplace}`}
              onClick={() => setActive(b.marketplace)}
              className={`p-5 flex flex-col items-start min-w-[180px] text-left transition-colors ${active === b.marketplace ? "bg-[#111215] text-white border-[#111215]" : "hover:bg-[#FAFAFB]"}`}
            >
              <div className="flex items-center gap-2 text-xs">
                <span className="w-2 h-2 inline-block" style={{ background: colorFor(b.marketplace) }} />
                <span className={active === b.marketplace ? "text-white/70" : "text-[#5E636E]"}>{b.marketplace}</span>
              </div>
              <div className="kpi-value text-2xl mt-2">{fmtEur(b.revenue_eur)}</div>
              <div className={`text-xs mt-1 ${active === b.marketplace ? "text-white/60" : "text-[#5E636E]"}`}>
                {fmtNum(b.orders)} orders · {fmtNum(b.units)} units
              </div>
            </button>
          ))}
        </div>
      </section>

      {activeData && (
        <section className="px-8 grid grid-cols-1 md:grid-cols-4 gap-0 grid-borders" data-testid="mk-kpis">
          <Kpi label="Revenue" value={fmtEur(activeData.revenue_eur)} />
          <Kpi label="Orders" value={fmtNum(activeData.orders)} />
          <Kpi label="Units" value={fmtNum(activeData.units)} />
          <Kpi label="AOV" value={fmtEur(activeData.aov_eur)} />
        </section>
      )}

      {activeCountries.length > 0 && (
        <section className="px-8 py-6">
          <div className="surface overflow-x-auto" data-testid="mk-country-breakdown">
            <div className="px-6 pt-5 pb-3">
              <div className="eyebrow">Country split</div>
              <h3 className="font-display text-lg font-semibold mt-1">{active} by country</h3>
            </div>
            <table className="dense w-full">
              <thead>
                <tr>
                  <th>Country</th>
                  <th className="text-right">Revenue</th>
                  <th className="text-right">Orders</th>
                  <th className="text-right">Units</th>
                  <th className="text-right">AOV</th>
                  <th className="text-right">% of {active}</th>
                </tr>
              </thead>
              <tbody>
                {activeCountries.map((c) => {
                  const pct = activeData.revenue_eur ? (c.revenue_eur / activeData.revenue_eur) * 100 : 0;
                  return (
                    <tr key={c.country} data-testid={`mk-country-${c.country}`}>
                      <td className="font-mono-num">{c.country}</td>
                      <td className="text-right font-mono-num font-semibold">{fmtEur(c.revenue_eur)}</td>
                      <td className="text-right font-mono-num">{fmtNum(c.orders)}</td>
                      <td className="text-right font-mono-num">{fmtNum(c.units)}</td>
                      <td className="text-right font-mono-num">{fmtEur(c.aov_eur)}</td>
                      <td className="text-right font-mono-num text-[#5E636E]">{pct.toFixed(1)}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="px-8 py-6">
        <div className="surface p-6">
          <div className="eyebrow">Monthly revenue</div>
          <h3 className="font-display text-xl font-semibold mt-1 mb-4">All marketplaces · monthly comparison</h3>
          {monthly.length === 0 ? (
            <div className="h-[260px] flex items-center justify-center text-sm text-[#5E636E]">No data</div>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={monthly}>
                <CartesianGrid stroke="#E5E7EB" vertical={false} />
                <XAxis dataKey="period" tick={{ fontSize: 11, fill: "#5E636E" }} stroke="#E5E7EB" />
                <YAxis tick={{ fontSize: 11, fill: "#5E636E" }} stroke="#E5E7EB" tickFormatter={(v) => `€${v}`} />
                <Tooltip formatter={(v) => fmtEur(v)} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                {allMks.map((mk) => (
                  <Line key={mk} type="monotone" dataKey={mk} stroke={colorFor(mk)} strokeWidth={1.5} dot={false} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </section>

      <section className="px-8 pb-12">
        <div className="surface p-6">
          <div className="eyebrow">Revenue ranking</div>
          <h3 className="font-display text-xl font-semibold mt-1 mb-4">Revenue by marketplace</h3>
          {breakdown.length === 0 ? (
            <div className="text-sm text-[#5E636E]">No data</div>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={breakdown} layout="vertical" margin={{ left: 90 }}>
                <CartesianGrid stroke="#E5E7EB" horizontal={false} />
                <XAxis type="number" tickFormatter={(v) => `€${v}`} tick={{ fontSize: 11, fill: "#5E636E" }} stroke="#E5E7EB" />
                <YAxis type="category" dataKey="marketplace" tick={{ fontSize: 12, fill: "#111215" }} stroke="#E5E7EB" />
                <Tooltip formatter={(v) => fmtEur(v)} />
                <Bar dataKey="revenue_eur" radius={0}>
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

function Kpi({ label, value }) {
  return (
    <div className="p-6">
      <div className="eyebrow">{label}</div>
      <div className="kpi-value text-3xl mt-2">{value}</div>
    </div>
  );
}
