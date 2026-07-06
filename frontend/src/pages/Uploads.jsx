import { useEffect, useState, useRef } from "react";
import PageHeader from "@/components/PageHeader";
import api, { formatApiError } from "@/lib/api";
import { toast } from "sonner";
import { UploadCloud, CheckCircle2, FileText, Loader2, Trash2 } from "lucide-react";
import { fmtDate, fmtNum } from "@/lib/format";

function Dropzone({ label, hint, endpoint, accept, testId, sourceOptions, onDone }) {
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [source, setSource] = useState(sourceOptions?.[0]?.value || "auto");

  const upload = async (file) => {
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (sourceOptions) fd.append("source", source);
      const { data } = await api.post(endpoint, fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success(`${file.name} — ${data.inserted} new · ${data.updated} updated · ${data.rows_total} rows`);
      onDone?.();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Upload failed");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <div className="surface p-6" data-testid={testId}>
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="eyebrow">{label}</div>
          <h3 className="font-display text-xl font-semibold mt-1">{hint}</h3>
        </div>
        {sourceOptions && (
          <select
            className="in"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            data-testid={`${testId}-source-select`}
          >
            {sourceOptions.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        )}
      </div>
      <div
        className={`dropzone p-10 text-center cursor-pointer ${dragOver ? "drag-over" : ""}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          const f = e.dataTransfer.files?.[0];
          if (f) upload(f);
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          className="hidden"
          data-testid={`${testId}-input`}
          onChange={(e) => upload(e.target.files?.[0])}
        />
        {busy ? (
          <div className="flex items-center justify-center gap-2 text-[#0055FF]"><Loader2 className="animate-spin" size={16} /> Uploading...</div>
        ) : (
          <>
            <UploadCloud className="mx-auto mb-3 text-[#0055FF]" size={32} strokeWidth={1.5} />
            <div className="text-sm font-medium text-[#111215]">Drop file here or click to browse</div>
            <div className="text-xs text-[#5E636E] mt-1">{accept}</div>
          </>
        )}
      </div>
    </div>
  );
}

export default function Uploads() {
  const [history, setHistory] = useState([]);

  const reload = () => api.get("/uploads/history").then((r) => setHistory(r.data));
  useEffect(() => { reload(); }, []);

  const deleteUpload = async (u) => {
    const msg = `Reverse this upload?\n\nFile: ${u.filename}\nInserted: ${u.inserted} rows\n\nAll rows this upload originally created will be permanently deleted. Rows it only updated will remain (previous values cannot be restored).`;
    if (!window.confirm(msg)) return;
    try {
      const { data } = await api.delete(`/uploads/${u.id}`);
      toast.success(`Reversed · ${data.removed} rows removed`);
      reload();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Delete failed");
    }
  };

  const downloadTemplate = async () => {
    const token = localStorage.getItem("ambiance_token");
    const resp = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/templates/cost`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "cost_template_prefilled.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadAsinTemplate = async () => {
    const token = localStorage.getItem("ambiance_token");
    const resp = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/templates/asin-mapping`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "asin_mapping_template.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div>
      <PageHeader kicker="Data ingestion" title="Uploads" />
      <section className="px-8 py-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Dropzone
          label="Orders"
          hint="Marketplace orders (CSV / XLSX / XLS)"
          endpoint="/uploads/orders"
          accept=".csv,.xls,.xlsx"
          testId="dropzone-orders"
          sourceOptions={[
            { value: "auto", label: "Auto-detect (recommended)" },
            { value: "ambiance_web", label: "Ambiance Web (Prestashop XLSX)" },
            { value: "channelengine", label: "ChannelEngine (CSV, ; or , delimited)" },
            { value: "beezup", label: "BeezUP (XLSX)" },
            { value: "amazon_po", label: "Amazon Vendor PO (XLS/XLSX)" },
            { value: "amazon_edit", label: "Amazon Vendor — Edit Line Items (XLSX)" },
          ]}
          onDone={reload}
        />
        <Dropzone
          label="Cost of Production"
          hint="Per-SKU cost template (CSV / XLSX)"
          endpoint="/uploads/costs"
          accept=".csv,.xlsx"
          testId="dropzone-costs"
          onDone={reload}
        />
      </section>

      <section className="px-8 grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Dropzone
          label="ASIN ↔ Merchant SKU"
          hint="Amazon ASIN to your merchant SKU mapping"
          endpoint="/uploads/asin-mapping"
          accept=".csv,.xlsx"
          testId="dropzone-asin"
          onDone={reload}
        />
        <div className="surface p-6" data-testid="asin-info">
          <div className="eyebrow">Why this matters</div>
          <h3 className="font-display text-xl font-semibold mt-1 mb-3">Connect Amazon orders to your SKUs</h3>
          <p className="text-sm text-[#5E636E] mb-3">
            Amazon Vendor exports only contain ASINs (e.g. <span className="font-mono-num">B00PB8WM4S</span>), not your merchant SKUs (e.g. <span className="font-mono-num">SAND_116_15x20_white</span>).
            Without a mapping, Amazon orders cannot be matched to your Cost of Production rows.
          </p>
          <ol className="text-sm space-y-2 mb-4 ml-4 list-decimal text-[#5E636E]">
            <li>Download the pre-filled template below — every ASIN you sell is listed with product name and units sold.</li>
            <li>Fill the <span className="font-mono-num">merchant_sku</span> column with your SKU for each ASIN.</li>
            <li>Drop the file back here. Existing Amazon orders are re-mapped automatically.</li>
          </ol>
          <button
            onClick={downloadAsinTemplate}
            className="btn-primary inline-flex items-center gap-2"
            data-testid="download-asin-template"
          >
            <FileText size={14} /> Download ASIN mapping template
          </button>
        </div>
      </section>

      <section className="px-8 py-6">
        <div className="surface p-6">
          <div className="eyebrow">Cost template</div>
          <h3 className="font-display text-xl font-semibold mt-1 mb-3">Expected columns</h3>
          <p className="text-sm text-[#5E636E]">
            Your Cost of Production file should contain at least these columns (case-insensitive):
          </p>
          <ul className="text-sm mt-3 space-y-1 font-mono-num">
            <li><strong>sku</strong> — your merchant SKU (must match marketplace SKU)</li>
            <li><strong>cost_per_unit</strong> — production cost per unit (Cout de Production)</li>
            <li><strong>shipping_cost</strong> <span className="text-[#5E636E]">(optional)</span> — outbound shipping/packaging cost (FBM Frais poste + packaging)</li>
            <li><strong>product_name</strong> <span className="text-[#5E636E]">(optional)</span></li>
            <li><strong>currency</strong> <span className="text-[#5E636E]">(optional, default EUR)</span></li>
          </ul>
          <p className="text-xs text-[#5E636E] mt-3">
            We also natively support your legacy <strong>CostProdShippingCalc</strong> workbook — it reads <em>Sheet3</em>, column A as SKU
            and column L (<em>Cout de Production</em>) as the unit cost. Just upload the .xlsx as-is.
          </p>
          <div className="flex gap-2 mt-4">
            <button
              onClick={downloadTemplate}
              className="btn-primary inline-flex items-center gap-2"
              data-testid="download-cost-template"
            >
              <FileText size={14} /> Download template (pre-filled with your SKUs)
            </button>
            <a
              href={`data:text/csv;charset=utf-8,${encodeURIComponent("sku,product_name,cost_per_unit,shipping_cost,currency\nSAND_116_15x20_white,Baby On Board Sticker White,1.20,0.80,EUR\nroll-mono_Bordeaux_60cmx1m,Decorative Vinyl Roll,3.50,1.10,EUR")}`}
              download="cost_template_blank.csv"
              className="btn-secondary inline-flex items-center gap-2"
              data-testid="download-blank-template"
            >
              <FileText size={14} /> Blank example
            </a>
          </div>
        </div>
      </section>

      <section className="px-8 pb-12">
        <div className="surface p-6">
          <div className="eyebrow">Recent uploads</div>
          <h3 className="font-display text-xl font-semibold mt-1 mb-4">Upload history</h3>
          {history.length === 0 ? (
            <div className="text-sm text-[#5E636E]">No uploads yet.</div>
          ) : (
            <table className="dense w-full" data-testid="upload-history">
              <thead>
                <tr><th>When</th><th>File</th><th>Source</th><th className="text-right">Rows</th><th className="text-right">New</th><th className="text-right">Updated</th><th className="text-right w-16">Undo</th></tr>
              </thead>
              <tbody>
                {history.map((h, i) => (
                  <tr key={h.id || i} data-testid={`upload-row-${h.id || i}`}>
                    <td className="font-mono-num text-[#5E636E]">{fmtDate(h.uploaded_at)}</td>
                    <td className="truncate max-w-[320px]" title={h.filename}>{h.filename}</td>
                    <td><span className="pill">{h.source}</span></td>
                    <td className="text-right font-mono-num">{fmtNum(h.rows_total)}</td>
                    <td className="text-right font-mono-num text-[#00A859]">+{fmtNum(h.inserted)}</td>
                    <td className="text-right font-mono-num text-[#5E636E]">{fmtNum(h.updated)}</td>
                    <td className="text-right">
                      {h.id ? (
                        <button
                          onClick={() => deleteUpload(h)}
                          className="p-1.5 rounded hover:bg-[#FEECEC] transition-colors text-[#FF2A2A]"
                          title={`Delete this upload and remove its ${h.inserted} inserted rows`}
                          data-testid={`upload-delete-${h.id}`}
                        >
                          <Trash2 size={14} strokeWidth={1.75} />
                        </button>
                      ) : (
                        <span className="text-xs text-[#D5D7DC]">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>
    </div>
  );
}
