export const fmtEur = (v) =>
  new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR", maximumFractionDigits: 2 }).format(Number(v || 0));

export const fmtNum = (v) =>
  new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(Number(v || 0));

export const fmtPct = (v) => `${Number(v || 0).toFixed(1)}%`;

export const fmtDate = (v) => {
  if (!v) return "—";
  try {
    return new Date(v).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  } catch {
    return String(v);
  }
};

export const MARKETPLACE_COLORS = {
  "BOL.COM": "#1B83C5",
  "Kaufland": "#E10915",
  "Amazon Vendor": "#FF9900",
  "Leroy Merlin": "#78BE20",
  "CDiscount": "#ED1C24",
  "Mano Mano": "#00B388",
  "Maison": "#C99A2E",
  "Castorama": "#2C3E91",
  "Maxeda - NL": "#FF6F1F",
  "Maxeda - BE": "#C75A19",
  "PinkConnect Veepee - FR": "#E91E63",
  "PinkConnect Veepee - BE": "#AD1457",
  "PinkConnect Veepee - NL": "#F06292",
  "Zooplus": "#0099CC",
  "Appros": "#7B5BA7",
  "Ambiance Web": "#111215",
  "Mon Echelle": "#9B7B4F",
  "Unknown": "#9CA3AF",
};

export const colorFor = (mk) => MARKETPLACE_COLORS[mk] || ["#0055FF", "#00A859", "#FF9900", "#7C3AED", "#06B6D4", "#F43F5E"][Math.abs(hash(mk || "x")) % 6];

function hash(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h << 5) - h + s.charCodeAt(i);
  return h;
}
