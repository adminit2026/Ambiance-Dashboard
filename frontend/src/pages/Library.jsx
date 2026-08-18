import { useEffect, useState, useMemo } from "react";
import PageHeader from "@/components/PageHeader";
import api, { API_BASE } from "@/lib/api";
import { fmtEur, fmtEurExact, fmtNum } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Search, Download } from "lucide-react";

export default function Library() {
  const { t } = useT();
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState("units_sold");
  const [sortDir, setSortDir] = useState("desc");

  useEffect(() => {
    setLoading(true);
    api.get("/library/skus", { params: { limit: 5000 } })
      .then((r) => setData(r.data))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    let rows = data;
    if (q) {
      rows = rows.filter(
        (r) => r.sku.toLowerCase().includes(q) || (r.product_name || "").toLowerCase().includes(q)
      );
    }
    rows = [...rows].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === "string") return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      return sortDir === "asc" ? (av || 0) - (bv || 0) : (bv || 0) - (av || 0);
    });
    return rows;
  }, [data, search, sortKey, sortDir]);

  const toggleSort = (key) => {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(key); setSortDir("desc"); }
  };

  const exportXlsx = async () => {
    const token = localStorage.getItem("ambiance_token");
    const resp = await fetch(`${API_BASE}/library/export`, { headers: { Authorization: `Bearer ${token}` } });
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `cost_library_${new Date().toISOString().slice(0, 10)}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const SortHead = ({ kk, children, align = "left" }) => (
    <th className={align === "right" ? "text-right" : ""}>
      <button
        onClick={() => toggleSort(kk)}
        className={`inline-flex items-center gap-1 hover:text-[#111215] transition-colors ${align === "right" ? "ml-auto" : ""}`}
        data-testid={`sort-${kk}`}
      >
        {children}
        {sortKey === kk && <span className="text-[#0055FF]">{sortDir === "asc" ? "▲" : "▼"}</span>}
      </button>
    </th>
  );

  return (
    <div>
      <PageHeader kicker={t("library.kicker")} title={t("library.title")} />
      <section className="px-8 py-6">
        <p className="text-sm text-[#5E636E] mb-4 max-w-2xl">{t("library.description")}</p>

        <div className="surface p-4 mb-4 flex items-center gap-3" data-testid="library-search-bar">
          <Search size={16} className="text-[#5E636E]" />
          <input
            className="in flex-1"
            placeholder={t("library.search_placeholder")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            data-testid="library-search-input"
          />
          <span className="text-xs text-[#5E636E] font-mono-num">
            {fmtNum(filtered.length)} / {fmtNum(data.length)}
          </span>
          <button onClick={exportXlsx} className="btn-primary inline-flex items-center gap-2" data-testid="library-export">
            <Download size={14} /> {t("library.export")}
          </button>
        </div>

        <div className="surface overflow-x-auto">
          <table className="dense w-full" data-testid="library-table">
            <thead>
              <tr>
                <SortHead kk="sku">{t("library.col_sku")}</SortHead>
                <SortHead kk="product_name">{t("library.col_product")}</SortHead>
                <SortHead kk="production_cost" align="right">{t("library.col_production_cost")}</SortHead>
                <SortHead kk="operational_cost" align="right">{t("library.col_operational_cost")}</SortHead>
                <SortHead kk="production_shipping_cost" align="right">{t("library.col_shipping_cost")}</SortHead>
                <SortHead kk="commission_pct" align="right">Commission %</SortHead>
                <SortHead kk="total_cost" align="right">{t("library.col_total")}</SortHead>
                <SortHead kk="units_sold" align="right">{t("library.col_units")}</SortHead>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={8} className="text-center py-12 text-[#5E636E]">{t("common.loading")}</td></tr>
              )}
              {!loading && filtered.length === 0 && (
                <tr><td colSpan={8} className="text-center py-12 text-[#5E636E]">{t("library.no_results")}</td></tr>
              )}
              {!loading && filtered.map((r) => (
                <tr key={r.sku} data-testid={`library-row-${r.sku}`}>
                  <td className="font-mono-num font-medium">{r.sku}</td>
                  <td className="max-w-[400px] truncate text-[#5E636E]" title={r.product_name}>{r.product_name || "—"}</td>
                  <td className="text-right font-mono-num">{r.has_cost ? fmtEurExact(r.production_cost) : <span className="text-[#D5D7DC]">—</span>}</td>
                  <td className="text-right font-mono-num text-[#5E636E]">{fmtEurExact(r.operational_cost)}</td>
                  <td className="text-right font-mono-num text-[#5E636E]">{fmtEurExact(r.production_shipping_cost)}</td>
                  <td className="text-right font-mono-num text-[#5E636E]">{r.commission_pct ? `${r.commission_pct.toFixed(1)}%` : <span className="text-[#D5D7DC]">—</span>}</td>
                  <td className="text-right font-mono-num font-semibold">{r.has_cost ? fmtEurExact(r.total_cost) : <span className="text-[#D5D7DC]">—</span>}</td>
                  <td className="text-right font-mono-num text-[#5E636E]">{fmtNum(r.units_sold)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
