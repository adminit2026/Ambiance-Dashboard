import { useEffect, useState } from "react";
import PageHeader from "@/components/PageHeader";
import FiltersBar, { useFilters } from "@/components/FiltersBar";
import api from "@/lib/api";
import { fmtEur, fmtNum } from "@/lib/format";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell,
} from "recharts";

export default function Customers() {
  const { filters, setFilters, params } = useFilters();
  const [rows, setRows] = useState([]);

  useEffect(() => {
    api.get("/dashboard/customers", { params }).then((r) => setRows(r.data));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filters)]);

  const top = rows.slice(0, 15);
  return (
    <div>
      <PageHeader kicker="Geography" title="Customer Analytics" />
      <FiltersBar filters={filters} setFilters={setFilters} />

      <section className="px-8 py-6 grid grid-cols-1 lg:grid-cols-3 gap-0 grid-borders">
        <div className="lg:col-span-2 p-6">
          <div className="eyebrow">Top countries</div>
          <h3 className="font-display text-xl font-semibold mt-1 mb-4">Revenue by destination</h3>
          {top.length === 0 ? (
            <div className="h-[240px] flex items-center justify-center text-sm text-[#5E636E]">No data</div>
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(320, top.length * 30)}>
              <BarChart data={top} layout="vertical" margin={{ left: 80 }}>
                <CartesianGrid stroke="#E5E7EB" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 11, fill: "#5E636E" }} stroke="#E5E7EB" tickFormatter={(v) => `€${v}`} />
                <YAxis type="category" dataKey="country" tick={{ fontSize: 12, fill: "#111215" }} stroke="#E5E7EB" width={80} />
                <Tooltip formatter={(v) => fmtEur(v)} />
                <Bar dataKey="revenue_eur" fill="#0055FF" radius={0}>
                  {top.map((d, i) => <Cell key={i} fill="#0055FF" />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="p-6">
          <div className="eyebrow">Full table</div>
          <h3 className="font-display text-xl font-semibold mt-1 mb-4">All destinations</h3>
          <div className="max-h-[420px] overflow-y-auto">
            <table className="dense w-full" data-testid="customers-table">
              <thead>
                <tr><th>Country</th><th className="text-right">Orders</th><th className="text-right">Revenue</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.country}>
                    <td>{r.country}</td>
                    <td className="text-right font-mono-num">{fmtNum(r.orders)}</td>
                    <td className="text-right font-mono-num">{fmtEur(r.revenue_eur)}</td>
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
