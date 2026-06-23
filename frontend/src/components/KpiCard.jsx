export default function KpiCard({ label, value, sub, testId, accent }) {
  return (
    <div className="surface p-6 md:p-8 flex flex-col gap-3" data-testid={testId}>
      <div className="flex items-center justify-between">
        <span className="eyebrow">{label}</span>
        {accent && <span className="w-2 h-2 inline-block" style={{ background: accent }} />}
      </div>
      <div className="kpi-value text-4xl text-[#111215]">{value}</div>
      {sub && <div className="text-xs text-[#5E636E]">{sub}</div>}
    </div>
  );
}
