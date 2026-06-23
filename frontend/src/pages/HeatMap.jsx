import { useEffect, useMemo, useState } from "react";
import PageHeader from "@/components/PageHeader";
import FiltersBar, { useFilters } from "@/components/FiltersBar";
import api from "@/lib/api";
import { fmtEur, fmtNum } from "@/lib/format";

export default function HeatMap() {
  const { filters, setFilters, params } = useFilters();
  const [data, setData] = useState([]);

  useEffect(() => {
    api.get("/dashboard/heatmap", { params }).then((r) => setData(r.data));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filters)]);

  const lookup = useMemo(() => Object.fromEntries(data.map((d) => [d.date, d])), [data]);
  const max = Math.max(1, ...data.map((d) => d.revenue_eur));

  const start = new Date(filters.date_from);
  const end = new Date(filters.date_to);
  // Build calendar grid by ISO weeks
  const grid = [];
  if (start <= end) {
    let d = new Date(start);
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); // Monday of start week
    while (d <= end) {
      const week = [];
      for (let i = 0; i < 7; i++) {
        const day = new Date(d);
        week.push(new Date(day));
        d.setDate(d.getDate() + 1);
      }
      grid.push(week);
    }
  }

  const totalRev = data.reduce((a, b) => a + b.revenue_eur, 0);
  const totalOrders = data.reduce((a, b) => a + b.orders, 0);

  return (
    <div>
      <PageHeader kicker="Activity" title="Sales Heat Map" />
      <FiltersBar filters={filters} setFilters={setFilters} />
      <section className="px-8 py-6">
        <div className="surface p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="eyebrow">Daily revenue intensity</div>
              <h3 className="font-display text-xl font-semibold mt-1">Calendar view</h3>
            </div>
            <div className="text-sm text-[#5E636E]">
              <span className="font-mono-num text-[#111215]">{fmtEur(totalRev)}</span> · <span className="font-mono-num">{fmtNum(totalOrders)}</span> orders
            </div>
          </div>
          <div className="flex gap-1 items-start overflow-x-auto" data-testid="heatmap-grid">
            {grid.map((week, wi) => (
              <div key={wi} className="flex flex-col gap-1">
                {week.map((day, di) => {
                  const key = day.toISOString().slice(0, 10);
                  const cell = lookup[key];
                  const inRange = day >= start && day <= end;
                  const intensity = cell ? Math.min(1, cell.revenue_eur / max) : 0;
                  let bg = "#F3F4F6";
                  if (inRange && cell) {
                    const v = Math.floor(intensity * 5);
                    bg = ["#E0EAFF", "#B3CDFF", "#75A6FF", "#3D7CFF", "#0055FF"][Math.min(4, v)];
                  } else if (inRange) bg = "#F3F4F6";
                  else bg = "#FAFAFB";
                  return (
                    <div
                      key={key}
                      className="heat-cell"
                      style={{ background: bg, width: 14, height: 14 }}
                      title={`${key} · ${cell ? fmtEur(cell.revenue_eur) : "€0"} · ${cell?.orders || 0} orders`}
                      data-testid={`heat-${key}`}
                    />
                  );
                })}
              </div>
            ))}
          </div>
          <div className="flex items-center gap-3 mt-5 text-xs text-[#5E636E]">
            <span>Less</span>
            {["#E0EAFF", "#B3CDFF", "#75A6FF", "#3D7CFF", "#0055FF"].map((c) => (
              <span key={c} className="heat-cell" style={{ background: c }} />
            ))}
            <span>More</span>
          </div>
        </div>
      </section>
    </div>
  );
}
