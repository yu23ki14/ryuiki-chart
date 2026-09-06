import * as React from "react";

export function Card({
  title,
  subtitle,
  right,
  children,
  className = "",
  bodyClassName = "",
}: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  right?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || right) && (
        <header className="flex items-start gap-3 px-3.5 py-2.5 border-b border-line">
          <div className="min-w-0">
            {title && <h2 className="text-[13px] font-semibold leading-tight">{title}</h2>}
            {subtitle && <p className="text-[11px] text-muted mt-0.5 leading-snug">{subtitle}</p>}
          </div>
          {right && <div className="ml-auto shrink-0 flex items-center gap-1.5">{right}</div>}
        </header>
      )}
      <div className={bodyClassName || "p-3.5"}>{children}</div>
    </section>
  );
}

export function Stat({
  label,
  value,
  unit,
  note,
  tone = "default",
}: {
  label: string;
  value: React.ReactNode;
  unit?: string;
  note?: React.ReactNode;
  tone?: "default" | "ok" | "warn" | "bad";
}) {
  const toneColor =
    tone === "ok" ? "text-ok" : tone === "warn" ? "text-warn" : tone === "bad" ? "text-bad" : "text-ink";
  return (
    <div className="min-w-0">
      <div className="text-[11px] text-muted leading-tight">{label}</div>
      <div className={`tnum ${toneColor} text-[22px] font-bold leading-tight mt-0.5`}>
        {value}
        {unit && <span className="text-[11px] font-normal text-muted ml-1">{unit}</span>}
      </div>
      {note && <div className="text-[10.5px] text-muted mt-0.5 leading-snug">{note}</div>}
    </div>
  );
}

export function Btn({
  children,
  active,
  className = "",
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }) {
  return (
    <button
      {...rest}
      className={`text-[12px] px-2.5 py-1 rounded border whitespace-nowrap transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
        active
          ? "bg-water text-white border-water"
          : "bg-surface border-line hover:bg-surface-2 text-ink-2"
      } ${className}`}
    >
      {children}
    </button>
  );
}

export function Tag({ children, color }: { children: React.ReactNode; color?: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 text-[10.5px] px-1.5 py-0.5 rounded border border-line bg-surface-2 text-ink-2 whitespace-nowrap"
      style={color ? { borderColor: color, color } : undefined}
    >
      {children}
    </span>
  );
}

export function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="block min-w-0">
      <span className="block text-[10.5px] text-muted mb-1 leading-none">{label}</span>
      {children}
      {hint && <span className="block text-[10px] text-muted mt-1">{hint}</span>}
    </label>
  );
}

export const inputCls =
  "w-full text-[12px] px-2 py-1 rounded border border-line bg-surface focus:outline-none focus:ring-2 focus:ring-water/30 focus:border-water";

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="text-[12px] text-muted py-8 text-center">{children}</div>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-[11.5px] text-muted">
      <span className="inline-block w-3 h-3 rounded-full border-2 border-line border-t-water animate-spin" />
      {label}
    </span>
  );
}

/** 出典の明示。デモとはいえ根拠を消さない。 */
export function Provenance({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[10.5px] text-muted leading-relaxed border-t border-line pt-2 mt-2">
      <span className="font-medium">出典・注記: </span>
      {children}
    </p>
  );
}

export function nf(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "–";
  return n.toLocaleString("ja-JP", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}
