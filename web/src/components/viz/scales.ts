/** 最小限のスケール・目盛りユーティリティ（d3 は入れない） */

export interface LinearScale {
  (v: number): number;
  invert(px: number): number;
  domain: [number, number];
  range: [number, number];
  ticks(count?: number): number[];
}

export function linear(domain: [number, number], range: [number, number]): LinearScale {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  const fn = ((v: number) => r0 + ((v - d0) / span) * (r1 - r0)) as LinearScale;
  fn.invert = (px: number) => d0 + ((px - r0) / (r1 - r0 || 1)) * span;
  fn.domain = domain;
  fn.range = range;
  fn.ticks = (count = 5) => niceTicks(d0, d1, count);
  return fn;
}

/** log10 スケール（0 以下は下限にクリップ） */
export function log(domain: [number, number], range: [number, number]): LinearScale {
  const lo = Math.max(domain[0], 1e-6);
  const hi = Math.max(domain[1], lo * 10);
  const l0 = Math.log10(lo);
  const l1 = Math.log10(hi);
  const inner = linear([l0, l1], range);
  const fn = ((v: number) => inner(Math.log10(Math.max(v, lo)))) as LinearScale;
  fn.invert = (px: number) => Math.pow(10, inner.invert(px));
  fn.domain = [lo, hi];
  fn.range = range;
  fn.ticks = () => {
    const out: number[] = [];
    for (let e = Math.floor(l0); e <= Math.ceil(l1); e++) {
      const base = Math.pow(10, e);
      for (const m of [1, 2, 5]) {
        const v = base * m;
        if (v >= lo && v <= hi) out.push(v);
      }
    }
    return out.length > 1 ? out : [lo, hi];
  };
  return fn;
}

export function band(values: (string | number)[], range: [number, number], padding = 0.2) {
  const n = Math.max(values.length, 1);
  const step = (range[1] - range[0]) / n;
  const bw = step * (1 - padding);
  const index = new Map(values.map((v, i) => [String(v), i]));
  return {
    bandwidth: bw,
    step,
    at(v: string | number): number {
      const i = index.get(String(v));
      return i === undefined ? NaN : range[0] + i * step + (step - bw) / 2;
    },
    center(v: string | number): number {
      const x = this.at(v);
      return Number.isNaN(x) ? NaN : x + bw / 2;
    },
    /** ピクセル位置から最も近い値 */
    nearest(px: number): string | number | undefined {
      const i = Math.round((px - range[0] - step / 2) / step);
      return values[Math.max(0, Math.min(values.length - 1, i))];
    },
    domain: values,
  };
}

export function niceTicks(lo: number, hi: number, count = 5): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || lo === hi) return [lo];
  const span = hi - lo;
  const step0 = span / Math.max(count, 2);
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const norm = step0 / mag;
  const step = (norm >= 7.5 ? 10 : norm >= 3.5 ? 5 : norm >= 1.5 ? 2 : 1) * mag;
  const start = Math.ceil(lo / step) * step;
  const out: number[] = [];
  for (let v = start; v <= hi + step * 1e-6; v += step) out.push(Math.round(v / step) * step);
  return out;
}

export function extent(values: (number | null | undefined)[]): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of values) {
    if (v === null || v === undefined || !Number.isFinite(v)) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (!Number.isFinite(lo)) return [0, 1];
  return [lo, hi];
}

/** 数値の桁に応じた丸め表示 */
export function fmt(v: number | null | undefined, unit?: string | null): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  const a = Math.abs(v);
  const digits = a >= 1000 ? 0 : a >= 100 ? 1 : a >= 1 ? 2 : a >= 0.01 ? 3 : 5;
  const s = v.toLocaleString("ja-JP", { maximumFractionDigits: digits });
  return unit ? `${s} ${unit}` : s;
}

export function fmtCompact(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e8) return (v / 1e8).toFixed(1) + "億";
  if (a >= 1e4) return (v / 1e4).toFixed(a >= 1e5 ? 0 : 1) + "万";
  if (a >= 1000) return (v / 1000).toFixed(a >= 1e4 ? 0 : 1) + "千";
  return String(Math.round(v * 100) / 100);
}
