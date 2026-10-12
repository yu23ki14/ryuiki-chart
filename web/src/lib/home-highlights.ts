/**
 * 概況（/）のハイライトに使う純粋な整形（クライアント・サーバ両方から読む）。
 * 地域ごとの出し分けは `lib/region.ts` の RegionUi が持つ。ここは並べ方・集計だけ。
 */

export interface CoralSpotRow {
  fiscal_year: number | null;
  cover_pct: number | null;
  cover_pct_raw: string | null;
  bleach_all_pct: number | null;
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
      const belowLimit = rs.filter((r) => r.cover_pct === null && (r.cover_pct_raw ?? "").trim().startsWith("<")).length;
      return {
        year,
        spots: rs.length,
        measured: cover.length,
        belowLimit,
        coverMean: mean(cover),
        bleachN: bleach.length,
        bleachMean: mean(bleach),
      };
    });
}

const SEA_FIXED = ["基準点", "監視点"];
const SEA_LETTERS = "イロハニホヘト";
const DIGITS = "０１２３４５６７８９";

/**
 * 海域の測定点（基準点１〜４、監視点イ〜ト）の並べ替えキー。基準点が先、監視点が後。
 * 数字は全角、監視点の記号はいろは順（コードポイント順ではロが後ろにずれる）。
 * 知らない名前は末尾（名前の文字列順）。
 */
export function seaStationOrderKey(name: string): [number, number, string] {
  for (let i = 0; i < SEA_FIXED.length; i++) {
    const p = SEA_FIXED[i];
    if (!name.startsWith(p)) continue;
    const rest = name.slice(p.length);
    const d = DIGITS.indexOf(rest);
    const l = SEA_LETTERS.indexOf(rest);
    const idx = d >= 0 ? d : l >= 0 ? l : 99;
    return [i, idx, name];
  }
  return [99, 0, name];
}

export function compareSeaStations(a: string, b: string): number {
  const ka = seaStationOrderKey(a);
  const kb = seaStationOrderKey(b);
  return ka[0] - kb[0] || ka[1] - kb[1] || ka[2].localeCompare(kb[2], "ja");
}
