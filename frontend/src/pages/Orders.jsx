import { useEffect, useState } from "react";
import PageHeader from "@/components/PageHeader";
import FiltersBar, { useFilters } from "@/components/FiltersBar";
import api, { API_BASE } from "@/lib/api";
import { fmtEur, fmtEurExact, fmtNum, fmtDate } from "@/lib/format";
import { Download } from "lucide-react";

export default function Orders() {
  const { filters, setFilters, params } = useFilters();
  const [data, setData] = useState({ total: 0, items: [] });
  const [page, setPage] = useState(0);
  const limit = 50;

  useEffect(() => {
    api.get("/orders", { params: { ...params, limit, skip: page * limit } }).then((r) => setData(r.data));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filters), page]);

  useEffect(() => { setPage(0); }, [JSON.stringify(filters)]);

  const exportCsv = async () => {
    const token = localStorage.getItem("ambiance_token");
    const qs = new URLSearchParams(params).toString();
    const resp = await fetch(`${API_BASE}/orders/export?${qs}`, { headers: { Authorization: `Bearer ${token}` } });
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `orders_${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div>
      <PageHeader kicker="Records" title="Orders & Settlements" />
      <FiltersBar
        filters={filters}
        setFilters={setFilters}
        rightSlot={
          <button onClick={exportCsv} className="btn-primary flex items-center gap-2" data-testid="export-csv-button">
            <Download size={14} /> Export CSV
          </button>
        }
      />

      <section className="px-8 py-6">
        <div className="flex items-center justify-between mb-3 text-sm text-[#5E636E]">
          <div>
            Showing <span className="font-mono-num text-[#111215]">{data.items.length}</span> of{" "}
            <span className="font-mono-num text-[#111215]">{fmtNum(data.total)}</span> records
          </div>
          <div className="flex items-center gap-2">
            <button disabled={page === 0} onClick={() => setPage((p) => p - 1)} className="btn-secondary disabled:opacity-50" data-testid="orders-prev">Prev</button>
            <span className="font-mono-num">{page + 1}</span>
            <button disabled={(page + 1) * limit >= data.total} onClick={() => setPage((p) => p + 1)} className="btn-secondary disabled:opacity-50" data-testid="orders-next">Next</button>
          </div>
        </div>
        <div className="surface overflow-x-auto">
          <table className="dense w-full" data-testid="orders-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Marketplace</th>
                <th>Order ID</th>
                <th>SKU</th>
                <th>Product</th>
                <th className="text-right">Qty</th>
                <th className="text-right">Unit</th>
                <th className="text-right">Total</th>
                <th className="text-right">€ Total</th>
                <th>Country</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {data.items.length === 0 && (
                <tr><td colSpan={11} className="text-center py-12 text-[#5E636E]">No orders yet — head to Uploads.</td></tr>
              )}
              {data.items.map((o) => (
                <tr key={o.line_key}>
                  <td className="font-mono-num text-[#5E636E]">{fmtDate(o.order_date_iso)}</td>
                  <td>{o.marketplace}</td>
                  <td className="font-mono-num">{o.order_id}</td>
                  <td className="font-mono-num">{o.sku}</td>
                  <td className="max-w-[280px] truncate" title={o.product_name}>{o.product_name || "—"}</td>
                  <td className="text-right font-mono-num">{o.quantity}</td>
                  <td className="text-right font-mono-num">{Number(o.unit_price || 0).toFixed(2)} {o.currency}</td>
                  <td className="text-right font-mono-num">{Number(o.line_total || 0).toFixed(2)} {o.currency}</td>
                  <td className="text-right font-mono-num">{fmtEurExact(o.line_total_eur)}</td>
                  <td>{o.country || "—"}</td>
                  <td><span className="pill">{o.status || "—"}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
