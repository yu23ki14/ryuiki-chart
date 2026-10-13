/**
 * 概況（/）のハイライトに使う純粋な整形（クライアント・サーバ両方から読む）。
 * 地域ごとの出し分けは `lib/region.ts` の RegionUi が持つ。ここは並べ方・集計だけ。
 */

export interface CoralSpotRow {
  fiscal_year: number | null;
  cover_pct: number | null;
  cover_pct_raw: string | null;
  bleach_all_pct: number | null;
  bleach_all_pct_raw: string | null;
}

export interface CoralYearSummary {
  year: number;
  /** その年度に記録のあるスポット数 */
  spots: number;
  /** 被度が数値で読めたスポット数 */
  measured: number;
  /** 被度が「<5」など下限表記のスポット数（平均には入れない） */
  belowLimit: number;
  /** 数値で読めたスポットの被度の平均（%）。読めたものが無ければ null */
  coverMean: number | null;
  /** 白化率（全体）が数値のスポット数 */
  bleachN: number;
  /** 白化率（全体）が「<5」など下限表記のスポット数（平均には入れない） */
  bleachBelowLimit: number;
  /** 白化率（全体）の平均（%）。無ければ null */
  bleachMean: number | null;
}

const mean = (xs: number[]): number | null => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);

/**
 * サンゴ被度を年度ごとに要約する。'<5' のような下限表記は数値列が NULL で来るので、
 * 0 にも 5 にも置き換えず、平均から外して `belowLimit` に数える。年度が NULL の行は捨てる。
 */
export function summarizeCoralByYear(rows: readonly CoralSpotRow[]): CoralYearSummary[] {
  const by = new Map<number, CoralSpotRow[]>();
  for (const r of rows) {
    if (r.fiscal_year === null) continue;
    const a = by.get(r.fiscal_year);
    if (a) a.push(r);
    else by.set(r.fiscal_year, [r]);
  }
  return [...by.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([year, rs]) => {
      const cover = rs.map((r) => r.cover_pct).filter((v): v is number => v !== null && Number.isFinite(v));
      const bleach = rs.map((r) => r.bleach_all_pct).filter((v): v is number => v !== null && Number.isFinite(v));
      const isBelow = (v: number | null, raw: string | null) => v === null && (raw ?? "").trim().startsWith("<");
      const belowLimit = rs.filter((r) => isBelow(r.cover_pct, r.cover_pct_raw)).length;
      const bleachBelowLimit = rs.filter((r) => isBelow(r.bleach_all_pct, r.bleach_all_pct_raw)).length;
      return {
        year,
        spots: rs.length,
        measured: cover.length,
        belowLimit,
        coverMean: mean(cover),
        bleachN: bleach.length,
        bleachBelowLimit,
        bleachMean: mean(bleach),
      };
    });
}

const SEA_FIXED = ["基準点", "監視点"];
const SEA_LETTERS = "イロハニホヘト";
const SEA_DIGITS = "1234";

/**
 * 海域の測定点（基準点１〜４、監視点イ〜ト）の並べ替えキー。基準点が先、監視点が後。
 * 全角・半角は NFKC で揃える。接尾辞は 1 文字ちょうど（数字は 1〜4、記号はいろは順＝コードポイント順だとロが後ろにずれる）。
 * それ以外（空・複数文字・知らない名前）は末尾（名前の文字列順）。
 */
function seaStationOrderKey(name: string): [number, number, string] {
  const n = name.normalize("NFKC");
  for (let i = 0; i < SEA_FIXED.length; i++) {
    const p = SEA_FIXED[i];
    if (!n.startsWith(p)) continue;
    const rest = n.slice(p.length);
    if (rest.length !== 1) break;
    const idx = (i === 0 ? SEA_DIGITS : SEA_LETTERS).indexOf(rest);
    if (idx >= 0) return [i, idx, name];
    break;
  }
  return [99, 0, name];
}

export function compareSeaStations(a: string, b: string): number {
  const ka = seaStationOrderKey(a);
  const kb = seaStationOrderKey(b);
  return ka[0] - kb[0] || ka[1] - kb[1] || ka[2].localeCompare(kb[2], "ja");
}
