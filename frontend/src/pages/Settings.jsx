import { useEffect, useState } from "react";
import PageHeader from "@/components/PageHeader";
import api, { formatApiError } from "@/lib/api";
import { toast } from "sonner";
import { fmtDate, fmtEur } from "@/lib/format";
import { Trash2 } from "lucide-react";

export default function Settings() {
  const [rates, setRates] = useState({});
  const [draftRates, setDraftRates] = useState({});
  const [costs, setCosts] = useState([]);
  const [busy, setBusy] = useState(false);
  const [manual, setManual] = useState({ sku: "", cost_per_unit: "", shipping_cost: "", currency: "EUR" });

  const loadRates = () =>
    api.get("/exchange-rates").then((r) => {
      setRates(r.data);
      setDraftRates(r.data);
    });
  const loadCosts = () => api.get("/costs").then((r) => setCosts(r.data));

  useEffect(() => {
    loadRates();
    loadCosts();
  }, []);

  const saveRates = async () => {
    setBusy(true);
    try {
      const parsed = {};
      Object.entries(draftRates).forEach(([k, v]) => {
        const n = Number(v);
        if (!isNaN(n) && n > 0) parsed[k] = n;
      });
      const { data } = await api.put("/exchange-rates", { rates: parsed });
      setRates(data);
      setDraftRates(data);
      toast.success("Exchange rates updated — order totals recomputed");
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail) || "Failed");
    } finally {
      setBusy(false);
    }
  };

  const saveManual = async (e) => {
    e.preventDefault();
    if (!manual.sku || !manual.cost_per_unit) return;
    setBusy(true);
    try {
      await api.post("/costs/manual", {
        sku: manual.sku.trim(),
        cost_per_unit: Number(manual.cost_per_unit),
        shipping_cost: Number(manual.shipping_cost || 0),
        currency: manual.currency || "EUR",
      });
      toast.success(`Cost for ${manual.sku} saved`);
      setManual({ sku: "", cost_per_unit: "", shipping_cost: "", currency: "EUR" });
      loadCosts();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail) || "Failed");
    } finally {
      setBusy(false);
    }
  };

  const deleteCost = async (sku) => {
    await api.delete(`/costs/${encodeURIComponent(sku)}`);
    toast.success(`Removed cost for ${sku}`);
    loadCosts();
  };

  const renormalize = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/admin/renormalize-marketplaces");
      toast.success(`Re-normalized ${data.updated} orders`);
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail) || "Failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader kicker="Configuration" title="Settings" />

      <section className="px-8 py-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="surface p-6">
          <div className="eyebrow">Currency conversion</div>
          <h3 className="font-display text-xl font-semibold mt-1 mb-1">Exchange rates → EUR</h3>
          <p className="text-sm text-[#5E636E] mb-4">All revenue is normalized to EUR using these rates. EUR is fixed at 1.0.</p>
          <div className="space-y-2" data-testid="exchange-rates-list">
            {Object.entries(draftRates).sort().map(([k, v]) => (
              <div key={k} className="flex items-center gap-3">
                <div className="w-16 font-mono-num text-sm">{k}</div>
                <input
                  type="number"
                  step="0.0001"
                  className="in w-40"
                  value={v}
                  disabled={k === "EUR"}
                  data-testid={`rate-${k}`}
                  onChange={(e) => setDraftRates({ ...draftRates, [k]: e.target.value })}
                />
                <div className="text-xs text-[#5E636E]">1 {k} = {Number(v).toFixed(4)} EUR</div>
              </div>
            ))}
          </div>
          <div className="mt-5 flex gap-2">
            <button onClick={saveRates} disabled={busy} className="btn-primary" data-testid="save-rates-button">Save & recompute</button>
            <button
              onClick={() => {
                const k = prompt("Currency ISO code (e.g. CAD)")?.toUpperCase();
                if (k) setDraftRates({ ...draftRates, [k]: 1.0 });
              }}
              className="btn-secondary"
              data-testid="add-currency-button"
            >+ Add currency</button>
          </div>
        </div>

        <div className="surface p-6">
          <div className="eyebrow">Manual cost entry</div>
          <h3 className="font-display text-xl font-semibold mt-1 mb-4">Add or update per-SKU cost</h3>
          <form onSubmit={saveManual} className="space-y-3" data-testid="manual-cost-form">
            <input className="in w-full" placeholder="SKU" value={manual.sku} onChange={(e) => setManual({ ...manual, sku: e.target.value })} data-testid="manual-cost-sku" required />
            <div className="grid grid-cols-2 gap-3">
              <input className="in w-full" type="number" step="0.01" placeholder="Cost per unit" value={manual.cost_per_unit} onChange={(e) => setManual({ ...manual, cost_per_unit: e.target.value })} data-testid="manual-cost-amount" required />
              <input className="in w-full" type="number" step="0.01" placeholder="Shipping cost (opt)" value={manual.shipping_cost} onChange={(e) => setManual({ ...manual, shipping_cost: e.target.value })} data-testid="manual-cost-shipping" />
            </div>
            <input className="in w-full" placeholder="Currency (default EUR)" value={manual.currency} onChange={(e) => setManual({ ...manual, currency: e.target.value })} data-testid="manual-cost-currency" />
            <button className="btn-primary w-full" disabled={busy} data-testid="manual-cost-save">Save cost</button>
          </form>

          <div className="mt-8 pt-6 border-t border-[#E5E7EB]">
            <div className="eyebrow">Marketplace labels</div>
            <h4 className="font-display text-base font-semibold mt-1 mb-2">Re-normalize existing orders</h4>
            <p className="text-xs text-[#5E636E] mb-3">
              Re-applies the latest channel→marketplace mapping (CDiscount, Maison, Castorama, Maxeda - NL/BE,
              PinkConnect Veepee - FR/BE/NL, BOL.COM, Ambiance Web, etc.) to every existing order.
            </p>
            <button onClick={renormalize} disabled={busy} className="btn-secondary" data-testid="renormalize-button">
              Re-normalize marketplaces
            </button>
          </div>
        </div>
      </section>

      <section className="px-8 pb-12">
        <div className="surface p-6">
          <div className="eyebrow">Cost catalog</div>
          <h3 className="font-display text-xl font-semibold mt-1 mb-4">{costs.length} SKUs with cost</h3>
          {costs.length === 0 ? (
            <div className="text-sm text-[#5E636E]">No costs yet. Upload a cost file in <strong>Uploads</strong> or use the manual entry form above.</div>
          ) : (
            <div className="max-h-[420px] overflow-y-auto">
              <table className="dense w-full" data-testid="costs-catalog">
                <thead>
                  <tr><th>SKU</th><th>Product</th><th className="text-right">Cost / unit</th><th className="text-right">Shipping</th><th>Currency</th><th>Updated</th><th></th></tr>
                </thead>
                <tbody>
                  {costs.map((c) => (
                    <tr key={c.sku}>
                      <td className="font-mono-num">{c.sku}</td>
                      <td className="max-w-[320px] truncate" title={c.product_name}>{c.product_name || "—"}</td>
                      <td className="text-right font-mono-num">{Number(c.cost_per_unit).toFixed(2)}</td>
                      <td className="text-right font-mono-num text-[#5E636E]">{Number(c.shipping_cost || 0).toFixed(2)}</td>
                      <td>{c.currency}</td>
                      <td className="font-mono-num text-[#5E636E]">{fmtDate(c.updated_at)}</td>
                      <td><button onClick={() => deleteCost(c.sku)} className="text-[#FF2A2A] hover:opacity-80" data-testid={`delete-cost-${c.sku}`}><Trash2 size={14} /></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
