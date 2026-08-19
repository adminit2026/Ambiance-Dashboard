import { useEffect, useRef, useState } from "react";
import PageHeader from "@/components/PageHeader";
import api, { formatApiError } from "@/lib/api";
import { toast } from "sonner";
import { fmtDate } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Trash2, UploadCloud, Loader2, Undo2, Shield, ShieldCheck } from "lucide-react";

export default function Settings() {
  const { t } = useT();
  const [rates, setRates] = useState({});
  const [draftRates, setDraftRates] = useState({});
  const [costs, setCosts] = useState([]);
  const [busy, setBusy] = useState(false);
  const [manual, setManual] = useState({ sku: "", cost_per_unit: "", shipping_cost: "", currency: "EUR" });
  const [marketplaces, setMarketplaces] = useState([]);
  const [constants, setConstants] = useState({ operational_cost_per_unit: 0.5, production_shipping_by_marketplace: {}, commission_by_marketplace: {} });
  const bulkInputRef = useRef(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [lastCostUpload, setLastCostUpload] = useState(null);
  const [master, setMaster] = useState({ exists: false, count: 0, saved_at: null, saved_by: null });

  const loadRates = () => api.get("/exchange-rates").then((r) => { setRates(r.data); setDraftRates(r.data); });
  const loadCosts = () => api.get("/costs").then((r) => setCosts(r.data));
  const loadMaster = () => api.get("/costs/master/status").then((r) => setMaster(r.data));
  const loadLastCostUpload = () =>
    api.get("/uploads/history").then((r) => {
      const last = (r.data || []).find((u) => u.source === "costs");
      setLastCostUpload(last || null);
    });
  const loadMks = () => api.get("/marketplaces").then((r) => setMarketplaces(r.data));
  const loadConstants = () => api.get("/cost-constants").then((r) => setConstants({
    operational_cost_per_unit: r.data.operational_cost_per_unit ?? 0.5,
    production_shipping_by_marketplace: r.data.production_shipping_by_marketplace || {},
    commission_by_marketplace: r.data.commission_by_marketplace || {},
  }));

  useEffect(() => { loadRates(); loadCosts(); loadMks(); loadConstants(); loadLastCostUpload(); loadMaster(); }, []);

  const saveRates = async () => {
    setBusy(true);
    try {
      const parsed = {};
      Object.entries(draftRates).forEach(([k, v]) => {
        const n = Number(v);
        if (!isNaN(n) && n > 0) parsed[k] = n;
      });
      const { data } = await api.put("/exchange-rates", { rates: parsed });
      setRates(data); setDraftRates(data);
      toast.success("Exchange rates updated — order totals recomputed");
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail) || "Failed");
    } finally { setBusy(false); }
  };

  const saveConstants = async () => {
    setBusy(true);
    try {
      const op = Number(constants.operational_cost_per_unit) || 0;
      const ship = {};
      Object.entries(constants.production_shipping_by_marketplace).forEach(([k, v]) => {
        const n = Number(v);
        if (!isNaN(n) && n >= 0) ship[k] = n;
      });
      const comm = {};
      Object.entries(constants.commission_by_marketplace || {}).forEach(([k, v]) => {
        const n = Number(v);
        if (!isNaN(n) && n >= 0) comm[k] = n;
      });
      const { data } = await api.put("/cost-constants", {
        operational_cost_per_unit: op,
        production_shipping_by_marketplace: ship,
        commission_by_marketplace: comm,
      });
      setConstants(data);
      toast.success("Cost constants saved");
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail) || "Failed");
    } finally { setBusy(false); }
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
    } finally { setBusy(false); }
  };

  const deleteCost = async (sku) => {
    await api.delete(`/costs/${encodeURIComponent(sku)}`);
    toast.success(`Removed cost for ${sku}`);
    loadCosts();
  };

  const bulkUpload = async (file) => {
    if (!file) return;
    setBulkBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await api.post("/uploads/costs", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success(`${file.name} — ${data.inserted} new · ${data.updated} updated · ${data.rows_total} rows`);
      loadCosts();
      loadLastCostUpload();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail) || "Bulk upload failed");
    } finally {
      setBulkBusy(false);
      if (bulkInputRef.current) bulkInputRef.current.value = "";
    }
  };

  const undoLastCostUpload = async () => {
    if (!lastCostUpload) return;
    const label = lastCostUpload.filename || "last upload";
    const msg = `Undo "${label}"?\n\n• ${lastCostUpload.inserted || 0} SKUs added will be deleted\n• ${lastCostUpload.updated || 0} SKUs updated will be restored to their previous cost`;
    if (!window.confirm(msg)) return;
    setBulkBusy(true);
    try {
      const { data } = await api.delete(`/uploads/${lastCostUpload.id}`);
      toast.success(`Reverted — ${data.removed} removed · ${data.restored} restored`);
      loadCosts();
      loadLastCostUpload();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail) || "Undo failed");
    } finally {
      setBulkBusy(false);
    }
  };

  const saveMaster = async () => {
    const msg = master.exists
      ? `Overwrite the existing master price list?\n\nCurrent master has ${master.count} SKUs, saved on ${fmtDate(master.saved_at)}.\nThe new master will be a snapshot of ${costs.length} current SKU costs.`
      : `Save the current ${costs.length} SKU costs as your master price list?\n\nYou can Restore back to this snapshot anytime — even if a future upload corrupts your prices.`;
    if (!window.confirm(msg)) return;
    setBulkBusy(true);
    try {
      const { data } = await api.post("/costs/master/save");
      toast.success(`Master saved — ${data.saved} SKUs locked in`);
      loadMaster();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail) || "Save failed");
    } finally { setBulkBusy(false); }
  };

  const restoreMaster = async () => {
    if (!master.exists) return;
    const msg = `Restore ALL costs to the master price list?\n\n• Every current cost will be REPLACED with the master values (${master.count} SKUs)\n• Any changes made since ${fmtDate(master.saved_at)} will be lost\n\nProceed?`;
    if (!window.confirm(msg)) return;
    setBulkBusy(true);
    try {
      const { data } = await api.post("/costs/master/restore");
      toast.success(`Restored — ${data.restored} SKUs reset to master`);
      loadCosts();
      loadLastCostUpload();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail) || "Restore failed");
    } finally { setBulkBusy(false); }
  };

  const renormalize = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/admin/renormalize-marketplaces");
      toast.success(`Re-normalized ${data.updated} orders`);
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail) || "Failed");
    } finally { setBusy(false); }
  };

  return (
    <div>
      <PageHeader kicker={t("settings.kicker")} title={t("settings.title")} />

      <section className="px-8 py-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="surface p-6">
          <div className="eyebrow">{t("settings.cost_constants")}</div>
          <h3 className="font-display text-xl font-semibold mt-1 mb-1">{t("settings.cost_constants_sub")}</h3>
          <p className="text-sm text-[#5E636E] mb-4">
            These constants are applied to every order line in <strong>{t("pnl.title")}</strong> and the <strong>{t("library.title")}</strong>.
          </p>

          <div className="mb-5">
            <label className="eyebrow block mb-2">{t("settings.op_cost")}</label>
            <input
              type="number"
              step="0.01"
              className="in w-40"
              value={constants.operational_cost_per_unit}
              onChange={(e) => setConstants({ ...constants, operational_cost_per_unit: e.target.value })}
              data-testid="op-cost-input"
            />
            <span className="text-xs text-[#5E636E] ml-3">per unit, applied to every product</span>
          </div>

          <label className="eyebrow block mb-2">{t("settings.prod_shipping_mk")}</label>
          <div className="space-y-2 max-h-[220px] overflow-y-auto" data-testid="prod-shipping-list">
            {marketplaces.length === 0 && (
              <div className="text-xs text-[#5E636E]">Upload orders first to populate marketplaces.</div>
            )}
            {marketplaces.map((mk) => (
              <div key={mk} className="flex items-center gap-3">
                <div className="w-44 text-sm">{mk}</div>
                <input
                  type="number"
                  step="0.01"
                  className="in w-32"
                  placeholder="0.00"
                  value={constants.production_shipping_by_marketplace[mk] ?? ""}
                  onChange={(e) => setConstants({
                    ...constants,
                    production_shipping_by_marketplace: {
                      ...constants.production_shipping_by_marketplace,
                      [mk]: e.target.value,
                    },
                  })}
                  data-testid={`prod-shipping-${mk}`}
                />
                <span className="text-xs text-[#5E636E]">EUR / order</span>
              </div>
            ))}
          </div>

          <label className="eyebrow block mb-2 mt-6">Commission % by marketplace</label>
          <div className="space-y-2 max-h-[220px] overflow-y-auto" data-testid="commission-list">
            {marketplaces.map((mk) => (
              <div key={mk} className="flex items-center gap-3">
                <div className="w-44 text-sm">{mk}</div>
                <input
                  type="number"
                  step="0.1"
                  className="in w-32"
                  placeholder="0.0"
                  value={constants.commission_by_marketplace[mk] ?? ""}
                  onChange={(e) => setConstants({
                    ...constants,
                    commission_by_marketplace: {
                      ...constants.commission_by_marketplace,
                      [mk]: e.target.value,
                    },
                  })}
                  data-testid={`commission-${mk}`}
                />
                <span className="text-xs text-[#5E636E]">% of revenue</span>
              </div>
            ))}
          </div>

          <button
            onClick={saveConstants}
            disabled={busy}
            className="btn-primary mt-5"
            data-testid="save-constants-button"
          >
            {t("settings.save_constants")}
          </button>
        </div>

        <div className="surface p-6">
          <div className="eyebrow">{t("settings.fx")}</div>
          <h3 className="font-display text-xl font-semibold mt-1 mb-1">{t("settings.fx_subtitle")}</h3>
          <p className="text-sm text-[#5E636E] mb-4">{t("settings.fx_help")}</p>
          <div className="space-y-2 max-h-[300px] overflow-y-auto" data-testid="exchange-rates-list">
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
            <button onClick={saveRates} disabled={busy} className="btn-primary" data-testid="save-rates-button">{t("settings.fx_save")}</button>
            <button
              onClick={() => {
                const k = prompt("Currency ISO code (e.g. CAD)")?.toUpperCase();
                if (k) setDraftRates({ ...draftRates, [k]: 1.0 });
              }}
              className="btn-secondary"
              data-testid="add-currency-button"
            >{t("settings.add_currency")}</button>
          </div>
        </div>
      </section>

      <section className="px-8 grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="surface p-6">
          <div className="eyebrow">{t("settings.manual_cost")}</div>
          <h3 className="font-display text-xl font-semibold mt-1 mb-4">{t("settings.manual_cost_sub")}</h3>
          <form onSubmit={saveManual} className="space-y-3" data-testid="manual-cost-form">
            <input className="in w-full" placeholder="SKU" value={manual.sku} onChange={(e) => setManual({ ...manual, sku: e.target.value })} data-testid="manual-cost-sku" required />
            <div className="grid grid-cols-2 gap-3">
              <input className="in w-full" type="number" step="0.01" placeholder="Cost per unit" value={manual.cost_per_unit} onChange={(e) => setManual({ ...manual, cost_per_unit: e.target.value })} data-testid="manual-cost-amount" required />
              <input className="in w-full" type="number" step="0.01" placeholder="Shipping cost (opt)" value={manual.shipping_cost} onChange={(e) => setManual({ ...manual, shipping_cost: e.target.value })} data-testid="manual-cost-shipping" />
            </div>
            <input className="in w-full" placeholder="Currency (default EUR)" value={manual.currency} onChange={(e) => setManual({ ...manual, currency: e.target.value })} data-testid="manual-cost-currency" />
            <button className="btn-primary w-full" disabled={busy} data-testid="manual-cost-save">{t("settings.save_cost")}</button>
          </form>

          <div className="mt-6 pt-6 border-t border-[#E5E7EB]" data-testid="bulk-cost-upload">
            <div className="flex items-center justify-between mb-2">
              <div>
                <div className="eyebrow">Bulk upload</div>
                <div className="text-sm text-[#5E636E] mt-1">CSV or XLSX with columns: <code className="text-[11px] bg-[#F5F6F8] px-1 py-0.5 rounded">sku, cost_per_unit, shipping_cost, currency</code></div>
              </div>
              <a
                className="text-xs text-[#0055FF] hover:underline whitespace-nowrap"
                href={`data:text/csv;charset=utf-8,${encodeURIComponent("sku,product_name,cost_per_unit,shipping_cost,currency\nSAND_118_15x20_white,Baby On Board Sticker White,1.20,0.00,EUR\nroll-mono_Bordeaux_60cmx1m,Decorative Vinyl Roll,3.50,0.00,EUR")}`}
                download="cost_template.csv"
                data-testid="bulk-cost-template"
              >
                Download template
              </a>
            </div>
            <input
              ref={bulkInputRef}
              type="file"
              accept=".csv,.xlsx,.xls,.tsv,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              onChange={(e) => bulkUpload(e.target.files?.[0])}
              className="hidden"
              data-testid="bulk-cost-file-input"
            />
            <button
              type="button"
              onClick={() => bulkInputRef.current?.click()}
              disabled={bulkBusy}
              className="btn-secondary w-full flex items-center justify-center gap-2"
              data-testid="bulk-cost-upload-btn"
            >
              {bulkBusy ? <><Loader2 size={16} className="animate-spin" /> Uploading…</> : <><UploadCloud size={16} /> Upload CSV / XLSX</>}
            </button>

            {lastCostUpload && (
              <div className="mt-3 p-3 rounded-lg bg-[#F8F9FB] border border-[#E5E7EB] flex items-center gap-3" data-testid="last-cost-upload">
                <div className="flex-1 min-w-0">
                  <div className="text-[10px] uppercase tracking-wider text-[#5E636E] font-semibold">Last upload</div>
                  <div className="text-sm font-medium truncate" title={lastCostUpload.filename}>{lastCostUpload.filename || "—"}</div>
                  <div className="text-xs text-[#5E636E] mt-0.5">
                    <span className="font-mono-num">{lastCostUpload.inserted || 0}</span> new ·{" "}
                    <span className="font-mono-num">{lastCostUpload.updated || 0}</span> updated ·{" "}
                    {lastCostUpload.uploaded_at ? fmtDate(lastCostUpload.uploaded_at) : ""}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={undoLastCostUpload}
                  disabled={bulkBusy}
                  className="btn-secondary text-xs px-3 py-2 flex items-center gap-1.5 !text-[#FF2A2A] !border-[#FFCFCF] hover:!bg-[#FFF3F3]"
                  data-testid="undo-cost-upload-btn"
                  title="Delete rows this upload added, and restore rows it overwrote to their previous values"
                >
                  <Undo2 size={14} /> Undo
                </button>
              </div>
            )}

            <div className="mt-4 p-3 rounded-lg border border-[#0055FF]/20 bg-[#EAF1FF]" data-testid="master-price-list">
              <div className="flex items-start gap-3">
                {master.exists ? <ShieldCheck size={20} className="text-[#0055FF] mt-0.5 shrink-0" /> : <Shield size={20} className="text-[#5E636E] mt-0.5 shrink-0" />}
                <div className="flex-1 min-w-0">
                  <div className="text-[10px] uppercase tracking-wider text-[#0055FF] font-semibold">Master price list</div>
                  {master.exists ? (
                    <div className="text-xs text-[#5E636E] mt-0.5">
                      <span className="font-mono-num text-[#0F1116] font-semibold">{master.count}</span> SKUs locked in ·{" "}
                      saved {fmtDate(master.saved_at)}
                    </div>
                  ) : (
                    <div className="text-xs text-[#5E636E] mt-0.5">No master saved yet. Save your current costs as the master to protect against bad uploads.</div>
                  )}
                  <div className="mt-2 flex gap-2">
                    <button
                      type="button"
                      onClick={saveMaster}
                      disabled={bulkBusy || costs.length === 0}
                      className="btn-secondary text-xs px-3 py-1.5"
                      data-testid="save-master-btn"
                      title="Snapshot current costs as the canonical master price list"
                    >
                      {master.exists ? "Overwrite master" : "Save as master"}
                    </button>
                    {master.exists && (
                      <button
                        type="button"
                        onClick={restoreMaster}
                        disabled={bulkBusy}
                        className="btn-primary text-xs px-3 py-1.5"
                        data-testid="restore-master-btn"
                        title="Reset every SKU cost back to the master price list"
                      >
                        Restore from master
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="surface p-6">
          <div className="eyebrow">{t("settings.renormalize")}</div>
          <h3 className="font-display text-xl font-semibold mt-1 mb-2">Marketplace labels</h3>
          <p className="text-sm text-[#5E636E] mb-4">{t("settings.renormalize_sub")}</p>
          <button onClick={renormalize} disabled={busy} className="btn-secondary" data-testid="renormalize-button">
            {t("settings.renormalize")}
          </button>
        </div>
      </section>

      <section className="px-8 py-6">
        <div className="surface p-6">
          <div className="eyebrow">{t("settings.cost_catalog")}</div>
          <h3 className="font-display text-xl font-semibold mt-1 mb-4">{costs.length} SKUs with cost</h3>
          {costs.length === 0 ? (
            <div className="text-sm text-[#5E636E]">No costs yet. Upload a cost file in <strong>{t("nav.uploads")}</strong>.</div>
          ) : (
            <div className="max-h-[420px] overflow-y-auto">
              <table className="dense w-full" data-testid="costs-catalog">
                <thead>
                  <tr><th>SKU</th><th>Product</th><th className="text-right">Cost / unit</th><th className="text-right">Shipping</th><th>{t("common.currency")}</th><th>{t("common.updated")}</th><th></th></tr>
                </thead>
                <tbody>
                  {costs.slice(0, 200).map((c) => (
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
              {costs.length > 200 && <div className="text-xs text-[#5E636E] mt-3">Showing 200 of {costs.length} SKUs. Use Library for full view.</div>}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
