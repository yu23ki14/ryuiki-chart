/**
 * 可視化の配色。dataviz スキルの validate_palette.js で検証済みの値だけを使う。
 * - SERIES: カテゴリカル8色。系列(実体)に固定で割り当てる。順位で塗り替えない。循環させない。
 * - ZONE:   Ridge to Reef 1-5 は順序尺度なので単一色相の序列ランプ。
 * - SEQ:    連続量(件数・密度)用の逐次ランプ。ゾーンと同時に出るため別色相。
 * - STATUS: 状態色。系列には流用せず、必ずラベルを添える。
 */

export const SERIES = [
  "#2a78d6",
  "#eb6834",
  "#1baf7a",
  "#eda100",
  "#e87ba4",
  "#008300",
  "#4a3aa7",
  "#e34948",
] as const;

/** 9系列目以降は作らない。呼び出し側で「その他」にまとめること。 */
export const MAX_SERIES = SERIES.length;

/** 散布図・地図など全ペアが同時に見える形では先頭3色までしか安全でない */
export const MAX_SERIES_ALLPAIRS = 3;

export const ZONE_COLORS: Record<number, string> = {
  1: "#86b6ef",
  2: "#5598e7",
  3: "#2a78d6",
  4: "#1c5cab",
  5: "#104281",
};

export const ZONE_LABELS: Record<number, string> = {
  1: "山地源流域",
  2: "山地渓流",
  3: "丘陵・扇状地",
  4: "平野・沖積低地",
  5: "河口・沿岸",
};

export const ZONE_ELEV: Record<number, string> = {
  1: "標高 800m 超",
  2: "標高 400–800m",
  3: "標高 100–400m",
  4: "標高 100m 以下・海岸から2km超",
  5: "標高 100m 以下・海岸から2km以内",
};

export const SEQ = [
  "#ffe3d8",
  "#f9ccbc",
  "#edb19b",
  "#e0967b",
  "#d27a5a",
  "#c25a33",
  "#b03700",
  "#971200",
] as const;

/**
 * 2つ目の逐次ランプ。地図で流域の塗り分けと生物メッシュを同時に出すとき、
 * 同じ色相だと2つの量が見分けられなくなるため色相を変える。
 */
export const SEQ2 = [
  "#d6f3e4",
  "#b9e3cd",
  "#96d0b3",
  "#72bd99",
  "#49ab80",
  "#009564",
  "#007d4c",
  "#006637",
] as const;

export const STATUS = {
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
} as const;

/** 品質段階。順序があるので序列として扱い、必ずラベルとセットで出す。 */
export const QUALITY_STAGE: Record<string, { color: string; order: number }> = {
  暫定: { color: STATUS.warning, order: 1 },
  検証済: { color: "#5598e7", order: 2 },
  公開済: { color: STATUS.good, order: 3 },
};

export const INK = {
  primary: "#12211f",
  secondary: "#40514f",
  muted: "#6b7a78",
  grid: "#e6eae8",
  axis: "#c3cfcc",
  surface: "#ffffff",
} as const;

export function seriesColor(i: number): string {
  return SERIES[i % SERIES.length];
}

/** 0-1 の値を逐次ランプの色に写す */
export function seqColor(t: number): string {
  if (!Number.isFinite(t)) return SEQ[0];
  const i = Math.min(SEQ.length - 1, Math.max(0, Math.round(t * (SEQ.length - 1))));
  return SEQ[i];
}

/** 閾値配列から MapLibre の step 式を作る */
export function seqStepExpression(field: string, breaks: number[]): unknown[] {
  const expr: unknown[] = ["step", ["get", field], SEQ[0]];
  breaks.forEach((b, i) => {
    expr.push(b, SEQ[Math.min(i + 1, SEQ.length - 1)]);
  });
  return expr;
}

/**
 * 発散配色（正負のある量）。寒色↔暖色で、中央は無彩色。
 * 「増えた/減った」のように 0 に意味がある指標にだけ使う。
 */
export const DIVERGING = {
  neg: ["#104281", "#1c5cab", "#2a78d6", "#86b6ef"], // 減 ← 強い順
  mid: "#eceeed",
  pos: ["#edb19b", "#d27a5a", "#b03700", "#971200"], // 増 → 強い順
} as const;

/** breaks は昇順（負→正）。MapLibre の step 式を返す。 */
export function divergingStepExpression(field: string, breaks: number[]): unknown[] {
  const colors = [...DIVERGING.neg, DIVERGING.mid, ...DIVERGING.pos];
  const expr: unknown[] = ["step", ["get", field], colors[0]];
  breaks.forEach((b, i) => expr.push(b, colors[Math.min(i + 1, colors.length - 1)]));
  return expr;
}
