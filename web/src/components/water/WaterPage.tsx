"use client";

import * as React from "react";
import Link from "next/link";
import type { SourceSpecification, StyleImageSource } from "maplibre-gl";
import { MapCanvas, type MapLayerSpec } from "@/components/map/MapCanvas";
import { stripeCss, stripeTile } from "@/lib/map/stripe";
import { SERIES, STATUS } from "@/components/viz/palette";
import { nf, Spinner, Empty } from "@/components/ui";
import { useJson } from "@/components/useJson";

/**
 * 水道水の水源マップ（docs/WATER_SOURCE_MAP.md）。
 *
 * この画面は D1 を読まない。/geo/water_zones.geojson に水源比率まで焼き込んであり、
 * ブラウザが静的アセットを直接取る（Worker の CPU もメモリも使わない）。
 * 焼き込みは web/scripts/build-water-geo.mjs。
 *
 * 未割付の町丁目は属性 s1 を持たない。0 や「その他」で塗らずグレーにして「不明」と出す
 * （設計図 §6-3「不明は不明と表示する。もっともらしい値で埋めない」）。
 *
 * 状態は 3 つある。
 *   1. 未割付            … s1 が無い。グレー。
 *   2. 比率まで分かる    … s1/p1…。最上位水源の単色で塗る。
 *   3. 顔ぶれだけ分かる  … s1/s2 はあるが p1/p2 が無く mixed=1（神奈川県営水道の混合系統など）。
 *      **その 2 水源の色の斜めストライプ**で塗る。単色にすると「s1 が主」という嘘になり、
 *      グレーにすると「何も分かっていない」という別の嘘になる。ストライプなら
 *      「この 2 つが混ざっている・割合は言えない」がそのまま出る。
 *      パターンは出現した組み合わせから動的に作る（lib/map/stripe.ts）。
 */

/** 焼き込み済みの属性。build-water-geo.mjs の TOP_N と対応する。 */
interface ZoneProps {
  key_code: string;
  name: string;
  city_name?: string;
  s_name?: string;
  s1?: string; s1n?: string; s1t?: string; s1r?: string; p1?: number;
  s2?: string; s2n?: string; s2t?: string; s2r?: string; p2?: number;
  s3?: string; s3n?: string; s3t?: string; s3r?: string; p3?: number;
  other?: number;
  /** 1 なら「水源の顔ぶれは資料で確定・混合比は非公表」。このとき p1/p2/p3 は入っていない。 */
  mixed?: number;
  /** mixed のとき、上位3水源に載らなかった水源の**件数**（比率が無いので残余は出せない）。 */
  other_n?: number;
  conf?: "low" | "medium" | "high";
  basis?: "unknown" | "nominal" | "estimated" | "measured";
  as_of?: string;
  /** その町丁目の人口（e-Stat 2020年国勢調査 小地域）。進み具合を人口で出すために焼き込んである。 */
  pop?: number;
  /** 根拠資料と割付の note。実体は FeatureCollection 直下の辞書にある（build-water-geo.mjs）。 */
  doc_id?: string;
  note_id?: string;
}

/** 資料タイトル・URL・note は町丁目ごとに同じ文字列なので、feature ではなくここに 1 本ずつ入っている。 */
interface ZoneFC extends GeoJSON.FeatureCollection {
  docs?: Record<string, { title?: string; url?: string | null }>;
  notes?: Record<string, string>;
}

const UNASSIGNED = "#d5dbd9";

/**
 * 水源 → 地図の色。**実体に固定で割り当てる**（palette.ts の決まり: 系列は実体に固定、
 * 順位で塗り替えない、循環させない）。
 *
 * 以前は「割り付いた町丁目数の多い順」に SERIES を配っていた。事業体を足すたびに色が
 * 入れ替わり、9 種類目からは循環して同じ色が 2 つの水源に付く作りだった。
 *
 * 地図は全ペアが同時に見えるので palette.ts の MAX_SERIES_ALLPAIRS は 3。
 * 神奈川県の水道水はほぼ 3 河川に集約されるのでそこへ 3 色を固定で当て、
 * 残り（地下水・湧水・小河川）は **1 つの「その他の水源」に束ねて 4 色目**にする。
 * 4 色目は青・橙・緑と色相がいちばん離れる SERIES[4] を選んだ。
 *
 * **3 色を超えるのは規約からの逸脱**。理由は docs/WATER_SOURCE_MAP.md に書いてある。
 * 束ねるのは地図の塗りだけで、**水源カードは実際の水源名を出す**（「秦野市の地下水」など）。
 */
const MAJOR_COLOR: Record<string, string> = {
  SRC_SAGAMI: SERIES[0],
  SRC_SAKAWA: SERIES[1],
  SRC_DOSHI: SERIES[2],
};
const OTHER_COLOR = SERIES[4];
const OTHER_ID = "__other__";

function colorOfSource(id: string): string {
  return MAJOR_COLOR[id] ?? OTHER_COLOR;
}

/**
 * 比率不明の町丁目に敷く縞タイルの id。s1/s2/s3 の並び（= source_id 順）で決まる。
 * MapLibre 側は同じ文字列を `concat` 式で組み立てるので、**両方を一緒に直すこと**。
 */
function patternKey(ids: readonly string[]): string {
  return `ry-mix:${ids[0] ?? ""}|${ids[1] ?? ""}|${ids[2] ?? ""}`;
}

/** patternKey と同じ文字列を feature の属性から作る式。 */
const PATTERN_EXPR: unknown[] = [
  "concat",
  "ry-mix:",
  ["coalesce", ["get", "s1"], ""],
  "|",
  ["coalesce", ["get", "s2"], ""],
  "|",
  ["coalesce", ["get", "s3"], ""],
];

const CONF_LABEL: Record<string, string> = {
  high: "確度 高",
  medium: "確度 中",
  low: "確度 低",
};

const SOURCE_TYPE_LABEL: Record<string, string> = {
  river: "河川",
  dam: "ダム",
  groundwater: "地下水",
  spring: "湧水",
};

export function WaterPage() {
  const zones = useJson<ZoneFC>("/geo/water_zones.geojson");
  const [sel, setSel] = React.useState<ZoneProps | null>(null);

  /**
   * 凡例の行。3 大河川はそのまま、それ以外は「その他の水源」1 行に束ねて中身を並べる。
   * `zones` は「その水源が最上位で、かつ比率が出ている町丁目」の数。
   * 比率不明の町丁目には最上位が無いので数えない（縞の凡例が別に持つ）。
   */
  const sources = React.useMemo(() => {
    if (!zones.data)
      return [] as { id: string; name: string; color: string; zones: number; members?: string }[];
    const count = new Map<string, number>();
    const otherNames = new Map<string, number>();
    for (const f of zones.data.features) {
      const p = f.properties as ZoneProps | null;
      if (!p?.s1 || p.mixed) continue;
      const id = p.s1;
      count.set(id, (count.get(id) ?? 0) + 1);
      if (!(id in MAJOR_COLOR)) {
        const nm = p.s1n ?? id;
        otherNames.set(nm, (otherNames.get(nm) ?? 0) + 1);
      }
    }
    const rows: { id: string; name: string; color: string; zones: number; members?: string }[] = [];
    for (const [id, color] of Object.entries(MAJOR_COLOR)) {
      const n = count.get(id) ?? 0;
      if (n === 0) continue;
      // 名前は GeoJSON 側の表記をそのまま使う（ここで日本語を持たない）
      const nm =
        zones.data.features.find((f) => (f.properties as ZoneProps | null)?.s1 === id)?.properties
          ?.s1n ?? id;
      rows.push({ id, name: nm as string, color, zones: n });
    }
    rows.sort((a, b) => b.zones - a.zones);
    const otherTotal = [...otherNames.values()].reduce((a, b) => a + b, 0);
    if (otherTotal > 0) {
      // 束ねた側は 350 町丁目あり、その大半が地下水。「その他」とだけ書くと
      // 秦野市や座間市の人にとっていちばん意味のある答え（地下水）が消えるので、
      // 見出しは中身の種別で書き、実際の水源名を下に並べる。
      // 名前は多い順に 3 件だけ（地下水系は 20 種あり凡例が伸びるため）。全部はカードで出る。
      const top = [...otherNames.entries()].sort((a, b) => b[1] - a[1]);
      const shown = top.slice(0, 3).map(([nm]) => nm);
      const rest = top.length - shown.length;
      rows.push({
        id: OTHER_ID,
        name: "地下水・湧水・小河川",
        members: `${shown.join("・")}${rest > 0 ? ` ほか${rest}` : ""}`,
        color: OTHER_COLOR,
        zones: otherTotal,
      });
    }
    return rows;
  }, [zones.data]);

  // 縞とカードは実際の水源 id で引く。凡例の束ね方とは独立。
  const colorOf = React.useCallback((id: string) => colorOfSource(id), []);

  /**
   * 比率不明の町丁目に出てくる水源の組み合わせ。実データは「相模川＋酒匂川」がほぼ全部だが、
   * 事業体が増えれば組み合わせも増えるので固定表は作らず、GeoJSON から拾う。
   */
  const mixCombos = React.useMemo(() => {
    if (!zones.data) return [] as { key: string; ids: string[]; names: string[]; zones: number }[];
    const m = new Map<string, { ids: string[]; names: string[]; zones: number }>();
    for (const f of zones.data.features) {
      const p = f.properties as ZoneProps | null;
      if (!p?.mixed || !p.s1) continue;
      const ids: string[] = [];
      const names: string[] = [];
      for (const n of [1, 2, 3] as const) {
        const id = p[`s${n}` as const];
        if (!id) continue;
        ids.push(id);
        names.push(p[`s${n}n` as const] ?? id);
      }
      const key = patternKey(ids);
      const cur = m.get(key) ?? { ids, names, zones: 0 };
      cur.zones += 1;
      m.set(key, cur);
    }
    return [...m.entries()]
      .sort((a, b) => b[1].zones - a[1].zones || a[0].localeCompare(b[0]))
      .map(([key, v]) => ({ key, ...v }));
  }, [zones.data]);

  /** 組み合わせごとの縞タイル。MapCanvas が addLayer より先に addImage する。 */
  const images = React.useMemo(() => {
    const out: Record<string, StyleImageSource> = {};
    for (const c of mixCombos) out[c.key] = stripeTile(c.ids.map(colorOf));
    return out;
  }, [mixCombos, colorOf]);

  const total = zones.data?.features.length ?? 0;
  const withShare = sources.reduce((a, s) => a + s.zones, 0);
  const mixedZones = mixCombos.reduce((a, c) => a + c.zones, 0);
  const assigned = withShare + mixedZones;

  /**
   * 進み具合は町丁目の数より**人口**で見る方が意味がある（町丁目は面積も人口もばらばらで、
   * 中区のように 258 に細分された区もあれば 52 の戸塚区もある）。
   * `pop` は e-Stat 2020年国勢調査の小地域人口で、build-water-geo.mjs が焼き込んでいる。
   */
  const pop = React.useMemo(() => {
    let all = 0;
    let share = 0;
    let mixed = 0;
    for (const f of zones.data?.features ?? []) {
      const p = f.properties as ZoneProps | null;
      const n = Number(p?.pop ?? 0);
      if (!Number.isFinite(n)) continue;
      all += n;
      if (!p?.s1) continue;
      // 「水源が分かる」人の中に、比率まで出せている人とそうでない人がいる。
      if (p.mixed) mixed += n;
      else share += n;
    }
    return { all, share, mixed, done: share + mixed };
  }, [zones.data]);

  const mapSources = React.useMemo<Record<string, SourceSpecification>>(() => {
    const s: Record<string, SourceSpecification> = {};
    if (zones.data) s["ry-water"] = { type: "geojson", data: zones.data as never };
    return s;
  }, [zones.data]);

  const layers: MapLayerSpec[] = React.useMemo(() => {
    if (!zones.data) return [];
    // 最上位の水源で塗る。s1 を持たない町丁目は match の既定値（グレー）に落ちる。
    //
    // MapLibre の match は「ラベル→色」の組が最低 1 つ必要で、組が無い式は不正になり
    // addLayer が投げる（＝地図が真っ白になる）。割付が 1 件も無い状態は Phase 0 では
    // 正常なので、そのときは match を組み立てずに定数色にする。
    let fill: unknown;
    if (sources.length === 0) {
      fill = UNASSIGNED;
    } else {
      // 3 大河川だけを列挙し、残りは既定値（その他の水源）に落とす。
      // **未割付（s1 が無い）を先に空文字で拾って灰色にする。**
      // このレイヤの filter は mixed を外すだけで未割付は通ってくるので、
      // 既定値に落とすと「その他の水源」の色で塗られてしまう。
      const expr: unknown[] = ["match", ["coalesce", ["get", "s1"], ""], "", UNASSIGNED];
      for (const [id, color] of Object.entries(MAJOR_COLOR)) expr.push(id, color);
      expr.push(OTHER_COLOR);
      fill = expr;
    }
    const out: MapLayerSpec[] = [
      {
        id: "ry-water-fill",
        source: "ry-water",
        interactive: true,
        spec: {
          type: "fill",
          // 比率不明の町丁目はここでは塗らない（下のストライプのレイヤが受け持つ）。
          // s1 の色で塗ると「s1 が主」に見えてしまうため。
          filter: ["!", ["has", "mixed"]],
          paint: { "fill-color": fill as never, "fill-opacity": 0.75 },
        },
      },
    ];
    // 比率不明の町丁目。関係する水源の色の斜めストライプ。
    // 出現した組み合わせぶんの画像を先に登録してあり、名前は属性から組み立てる。
    if (mixCombos.length > 0) {
      out.push({
        id: "ry-water-mixed",
        source: "ry-water",
        interactive: true,
        spec: {
          type: "fill",
          filter: ["has", "mixed"],
          paint: { "fill-pattern": PATTERN_EXPR as never, "fill-opacity": 0.85 },
        },
      });
    }
    out.push({
      id: "ry-water-line",
      source: "ry-water",
      spec: {
        type: "line",
        paint: {
          "line-color": "#ffffff",
          // 県全域では境界線が潰れるので、寄ったときだけ出す
          "line-width": ["interpolate", ["linear"], ["zoom"], 9, 0.15, 13, 0.7] as never,
          "line-opacity": 0.8,
        },
      },
    });
    return out;
  }, [zones.data, sources, mixCombos]);

  return (
    <div className="flex-1 flex min-h-0">
      <div className="flex-1 relative min-w-0">
        <MapCanvas
          sources={mapSources}
          layers={layers}
          images={images}
          className="absolute inset-0"
          onFeatureClick={(f) => setSel(f.properties as ZoneProps)}
          overlay={
            <div className="absolute bottom-6 left-2 z-10 card px-2.5 py-2 shadow-sm max-w-[230px] max-h-[calc(100%-4rem)] overflow-y-auto thin-scroll no-print">
              <div className="text-[10.5px] font-semibold mb-1">いちばん多い水源</div>
              {assigned === 0 ? (
                <p className="text-[10px] text-muted leading-snug">
                  まだ 1 件も割り付いていません。町丁目の形だけが出ています。
                </p>
              ) : (
                <ul className="space-y-0.5">
                  {sources
                    .filter((s) => s.zones > 0)
                    .map((s) => (
                      <li key={s.id} className="text-[10px] text-ink-2">
                        <div className="flex items-center gap-1.5">
                          <span
                            className="w-2.5 h-2.5 rounded-sm shrink-0"
                            style={{ background: s.color }}
                          />
                          <span className="truncate">{s.name}</span>
                          <span className="ml-auto tnum text-muted">{nf(s.zones)}</span>
                        </div>
                        {s.members && (
                          <div className="pl-4 text-[9px] text-muted leading-snug">{s.members}</div>
                        )}
                      </li>
                    ))}
                </ul>
              )}
              {/* 比率が非公表の町丁目は縞。地図の見た目（角度・帯幅）を stripeCss で合わせている。 */}
              {mixCombos.length > 0 && (
                <div className="mt-1 pt-1 border-t border-line">
                  <div className="text-[10.5px] font-semibold mb-0.5">比率は非公表</div>
                  <ul className="space-y-0.5">
                    {mixCombos.map((c) => (
                      <li key={c.key} className="flex items-center gap-1.5 text-[10px] text-ink-2">
                        <span
                          className="w-2.5 h-2.5 rounded-sm shrink-0 border border-line"
                          style={{ background: stripeCss(c.ids.map(colorOf), 3) }}
                        />
                        <span className="truncate">{c.names.join("・")}</span>
                        <span className="ml-auto tnum text-muted">{nf(c.zones)}</span>
                      </li>
                    ))}
                  </ul>
                  <p className="text-[9.5px] text-muted leading-snug mt-0.5">
                    どちらの水も入りますが、割合は公表されていません。
                  </p>
                </div>
              )}
              <div className="flex items-center gap-1.5 text-[10px] text-muted mt-1 pt-1 border-t border-line">
                <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: UNASSIGNED }} />
                不明（未割付）
                <span className="ml-auto tnum">{nf(total - assigned)}</span>
              </div>
            </div>
          }
        />
        {zones.loading && (
          <div className="absolute top-2 right-12 z-10 card px-2 py-1">
            <Spinner label="町丁目を読み込み中（8MB）" />
          </div>
        )}
        {zones.error && (
          <div className="absolute top-2 left-1/2 -translate-x-1/2 z-10 card px-3 py-2 text-[11px]">
            町丁目データを読めませんでした: {zones.error}
            <div className="text-muted mt-1">
              `pnpm run prepare:geo` が通っているか確認する（docs/WATER_SOURCE_MAP.md）。
            </div>
          </div>
        )}
      </div>

      <aside className="w-[300px] shrink-0 border-l border-line bg-surface overflow-y-auto min-h-0 thin-scroll no-print">
        <div className="p-3 border-b border-line">
          <h1 className="text-[14px] font-bold">水源マップ</h1>
          <p className="text-[11px] text-muted mt-0.5 leading-snug">
            住んでいる場所をタップすると、その蛇口から出る水がどの川・ダム・地下水から
            来ているかが出ます。
          </p>
        </div>

        <div className="p-3 border-b border-line">
          <h2 className="text-[12px] font-semibold mb-1.5">選んだ町丁目</h2>
          {!sel ? (
            <p className="text-[11px] text-muted">地図をクリックすると内容が出ます。</p>
          ) : (
            <ZoneCard
              p={sel}
              colorOf={colorOf}
              doc={sel.doc_id ? zones.data?.docs?.[sel.doc_id] : undefined}
              note={sel.note_id ? zones.data?.notes?.[sel.note_id] : undefined}
            />
          )}
        </div>

        <div className="p-3 border-b border-line">
          <h2 className="text-[12px] font-semibold mb-1.5">割付の進み具合</h2>
          <div className="flex items-baseline gap-1.5">
            <span className="text-[20px] font-bold tnum">
              {pop.all ? ((pop.done / pop.all) * 100).toFixed(1) : "–"}
            </span>
            <span className="text-[11px] text-muted">
              % の人が、自分の水源を見られます
            </span>
          </div>
          <div className="h-1.5 mt-1 rounded-full bg-surface-2 overflow-hidden">
            <div
              className="h-full bg-water"
              style={{ width: `${pop.all ? (pop.done / pop.all) * 100 : 0}%` }}
            />
          </div>
          <p className="text-[10px] text-muted mt-1 tnum">
            {nf(pop.done)} / {nf(pop.all)} 人（町丁目では {nf(assigned)} / {nf(total)}）
          </p>
          {/* 「水源が分かる」の中身は 2 通りある。比率まで出せているかどうかを分けて出す。 */}
          <p className="text-[10px] text-muted mt-0.5 leading-snug">
            うち比率まで <span className="tnum">{nf(pop.share)}</span> 人 ／ 水源の顔ぶれのみ（比率は非公表）
            <span className="tnum"> {nf(pop.mixed)}</span> 人
          </p>
          <p className="text-[10px] text-muted mt-1.5 leading-snug">
            事業体の水質検査計画・水道事業年報から 1 事業体ずつ割り付けていきます。
            人口は 2020年国勢調査。目標は県内 95%。
          </p>
        </div>

        <div className="p-3 text-[10px] text-muted leading-relaxed">
          <p className="mb-1.5">
            町丁目の境界: 総務省統計局 e-Stat 統計GIS 2020年国勢調査 小地域（政府標準利用規約2.0）。
            表示用に約 5m の精度まで簡略化してあります。
          </p>
          <p className="mb-1.5">
            比率は年度の平均であって、いま蛇口から出ている水の内訳ではありません。
            「概算」と付いたものは取水量が非公開のため施設能力比から置いた値です。
          </p>
          <p className="mb-1.5">
            どの町丁目にどの浄水場の水が来ているかは、水質検査計画に載っている
            「各水源の主な給水区域」の図を読み取って割り付けています。図はあくまで「主な」区域なので、
            境目の付近では実際と食い違うことがあります。町丁目単位の給水区域は公表されていないため、
            事業体へ情報公開請求中です。回答が得られたら置き換えます。
          </p>
          <p>
            <Link href="/map" className="text-water-ink underline">
              流域マップ
            </Link>
            {" では、その水源の川がいまどうなっているか（水質・生物・土地利用の変化）を見られます。"}
          </p>
        </div>
      </aside>
    </div>
  );
}

/* ------------------------------ 部品 ------------------------------ */

function ZoneCard({
  p,
  colorOf,
  doc,
  note,
}: {
  p: ZoneProps;
  colorOf: (id: string) => string;
  doc?: { title?: string; url?: string | null };
  note?: string;
}) {
  interface Part {
    id: string;
    name: string;
    type?: string;
    river?: string;
    /** 比率が非公表の町丁目では入らない。0 では埋めない（0% と「不明」は別物）。 */
    share?: number;
  }
  // 混合比が非公表の町丁目（mixed=1）は p1/p2/p3 を持たない。水源名だけ並べる。
  const mixed = !!p.mixed;
  const parts: Part[] = ([1, 2, 3] as const).flatMap((n) => {
    const id = p[`s${n}` as const];
    const share = p[`p${n}` as const];
    if (!id || (!mixed && share == null)) return [];
    return [
      {
        id,
        name: p[`s${n}n` as const] ?? id,
        type: p[`s${n}t` as const],
        river: p[`s${n}r` as const],
        share: mixed ? undefined : share,
      },
    ];
  });

  return (
    <div>
      <div className="text-[13px] font-semibold leading-tight">{p.name}</div>
      <div className="text-[10px] text-muted font-mono mb-2">{p.key_code}</div>

      {parts.length === 0 ? (
        <Empty>
          この町丁目の水源はまだ分かりません。
          <span className="block mt-1 text-[10px]">
            事業体の給水区域の資料を読み込んだら出ます。推測では埋めていません。
          </span>
        </Empty>
      ) : (
        <>
          {/* 比率の帯。上位3水源とその他。混合比が非公表のときは帯そのものを出さない
              （幅を等分すると按分したことになる）。代わりに地図と同じ縞を 1 本だけ出す。 */}
          {mixed ? (
            <div
              className="h-3 rounded mb-2 border border-line"
              style={{ background: stripeCss(parts.map((s) => colorOf(s.id)), 4) }}
              title="混合比は公表されていません"
            />
          ) : (
            <div className="flex h-3 rounded overflow-hidden mb-2">
              {parts.map((s) => (
                <span
                  key={s.id}
                  style={{ background: colorOf(s.id), width: `${(s.share ?? 0) * 100}%` }}
                  title={s.name}
                />
              ))}
              {p.other != null && <span style={{ background: UNASSIGNED, width: `${p.other * 100}%` }} title="その他" />}
            </div>
          )}
          <ul className="space-y-1">
            {parts.map((s) => (
              <li key={s.id} className="flex items-center gap-1.5 text-[11.5px]">
                <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: colorOf(s.id) }} />
                <span className="truncate">
                  {s.name}
                  {s.type && <span className="text-[9.5px] text-muted ml-1">{SOURCE_TYPE_LABEL[s.type] ?? s.type}</span>}
                </span>
                {/* 比率が非公表のときは % を出さない。0% も --% も出さない。 */}
                {s.share != null && <span className="ml-auto tnum font-medium">{(s.share * 100).toFixed(1)}%</span>}
              </li>
            ))}
            {mixed && p.other_n != null && (
              <li className="text-[11.5px] text-muted">ほか {p.other_n} 水源</li>
            )}
            {!mixed && p.other != null && (
              <li className="flex items-center gap-1.5 text-[11.5px] text-muted">
                <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: UNASSIGNED }} />
                その他
                <span className="ml-auto tnum">{(p.other * 100).toFixed(1)}%</span>
              </li>
            )}
          </ul>
          {mixed && (
            <p className="text-[10px] text-muted mt-1.5 leading-snug">
              混合比は公表されていません。この町丁目にどの水源の水が入るかまでは資料で確定していますが、
              何割ずつかは分からないため、推測では埋めていません。
            </p>
          )}

          <div className="flex flex-wrap gap-1 mt-2">
            {p.basis === "nominal" && (
              <span className="text-[10px] px-1.5 py-0.5 rounded border border-line bg-surface-2">概算</span>
            )}
            {p.conf && (
              <span
                className="text-[10px] px-1.5 py-0.5 rounded border border-line bg-surface-2"
                // 確度は文言だけだと見分けが付かないので、low のときだけ弱い警告色にする。
                // 色は palette.ts の STATUS から。系列色には流用しないのでラベルは必ず添える。
                style={
                  p.conf === "low"
                    ? { borderColor: STATUS.warning, color: STATUS.warning }
                    : undefined
                }
              >
                {CONF_LABEL[p.conf] ?? p.conf}
              </span>
            )}
            {p.as_of && <span className="text-[10px] px-1.5 py-0.5 text-muted">{p.as_of} 時点</span>}
          </div>

          {/* その水源の川が今どうなっているか、へ渡す導線 */}
          {parts.some((s) => s.river) && (
            <Link
              href="/map"
              className="mt-2 inline-block text-[11px] px-2 py-1 rounded border border-water text-water-ink bg-water-soft"
            >
              この水源の川を流域マップで見る
            </Link>
          )}
        </>
      )}

      {/* 何を見てこの町丁目に割り付けたか。設計図 CP1「全割付に根拠資料が紐づいている」の確認用。 */}
      {(note || doc) && (
        <div className="mt-2 pt-2 border-t border-line">
          {note && <p className="text-[10px] text-muted leading-snug">{note}</p>}
          {doc?.url && (
            <a
              href={doc.url}
              target="_blank"
              rel="noopener noreferrer"
              title={doc.title}
              className="mt-1.5 inline-block text-[11px] px-2 py-1 rounded border border-line text-ink-2"
            >
              根拠資料
            </a>
          )}
          {doc && !doc.url && doc.title && (
            <p className="text-[10px] text-muted mt-1">根拠資料: {doc.title}</p>
          )}
        </div>
      )}
    </div>
  );
}
