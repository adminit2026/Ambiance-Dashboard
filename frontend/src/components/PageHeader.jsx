export default function PageHeader({ title, kicker, right }) {
  return (
    <div className="px-8 pt-8 pb-4 flex items-end justify-between gap-4 flex-wrap" data-testid="page-header">
      <div>
        {kicker && <div className="eyebrow mb-2">{kicker}</div>}
        <h1 className="font-display text-3xl lg:text-4xl font-bold text-[#111215] tracking-tight">{title}</h1>
      </div>
      {right}
    </div>
  );
}
