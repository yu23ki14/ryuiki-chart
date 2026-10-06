/**
 * 出典メタ（名前・ライセンス・取得日・更新方式）の引き口（ADR-0014・ADR-0020、Issue #40 Phase D）。
 *
 * 読むのは registry の生成物 `generated-source.ts`（`registry.sqlite` の source / source_edition /
 * license を焼いたもの）だけで、**D1 を引かない**（rows_read 0）。応答封筒（`envelope.ts`）と
 * 画面用 API の `freshness`（`/api/timeseries`・`/api/biota`）が同じこの関数を通る。
 *
 * ## 鮮度
 *
 * 載せるのは取得日（`fetched_at`）・更新方式（`update_mode`）・経過日数（`age_days`）だけ。
 * `stale` のような閾値判定は持たない（閾値はオーナー未決。推測で埋めない）。
 * `update_mode` が宣言されていない edition は `"undeclared"` を返す（NULL を別の値に倒さない）。
 *
 * `fetched_at` は壁時計（`YYYY-MM-DDTHH:MM:SS`、時刻帯なし）なので、region の時刻帯
 * （`regionTimeZone()`）のオフセットを付けて ISO 8601 にする。日時の演算は文字列と
 * `Date.UTC` だけで行い、SQLite の日時関数は使わない（ADR-0024）。
 */
import { regionTimeZone } from "@/lib/registry/lookup-client";
import { seriesInfo, type SeriesKey } from "./series";
import {
  LICENSES,
  SOURCE_EDITIONS,
  SOURCE_META,
  type GeneratedLicense,
  type GeneratedSourceEdition,
  type GeneratedSourceMeta,
} from "@/lib/registry/generated-source";

/** 現在の配備が扱う region（単一 D1 + `region_id`。ADR-0002）。出典の region は宣言しない（NULL）ので、時刻帯はここから決める。 */
export const DEFAULT_REGION_ID = "jp-14";

export type UpdateMode = "snapshot" | "append" | "revision" | "static";
export type UpdateModeOrUndeclared = UpdateMode | "undeclared";

export interface SourceFreshness {
  source_id: string;
  source_edition_id: string | null;
  /** ISO 8601（region の時刻帯のオフセット付き）。取得日が無ければ null。 */
  fetched_at: string | null;
  update_mode: UpdateModeOrUndeclared;
  /** region の暦日で数えた、取得日から `now` までの日数（取得の翌日が 1）。`fetched_at` が無ければ null。 */
  age_days: number | null;
}

export interface SourceCitation extends SourceFreshness {
  name: string | null;
  license_id: string | null;
  /** ライセンスの表示名（無ければ license_id）。 */
  license: string | null;
  license_class: string | null;
  /** 出典の旗。出力を絞る根拠にしない（ADR-0028）。 */
  redistributable: boolean | null;
  attribution: string | null;
}

let metaById: Map<string, GeneratedSourceMeta> | undefined;
let editionsBySource: Map<string, GeneratedSourceEdition[]> | undefined;
let licenseById: Map<string, GeneratedLicense> | undefined;

function indexes() {
  metaById ??= new Map(SOURCE_META.map((m) => [m.sourceId, m]));
  licenseById ??= new Map(LICENSES.map((l) => [l.licenseId, l]));
  if (!editionsBySource) {
    editionsBySource = new Map();
    for (const e of SOURCE_EDITIONS) {
      const list = editionsBySource.get(e.sourceId) ?? [];
      list.push(e);
      editionsBySource.set(e.sourceId, list);
    }
  }
  return { metaById, licenseById, editionsBySource };
}

/**
 * 出典の「現行の版」。置換されていない edition のうち取得日が最も新しいもの
 * （取得日が同じなら edition_key の降順。取得日が無い版は最後）。
 * 版で系列が決まる出典（土地利用の 2006/2016）は `editionKey` を渡すとその版を返す。
 */
export function currentEdition(sourceId: string, editionKey?: string | null): GeneratedSourceEdition | undefined {
  const list = indexes().editionsBySource.get(sourceId);
  if (!list) return undefined;
  if (editionKey) {
    const hit = list.find((e) => e.editionKey === editionKey);
    if (hit) return hit;
  }
  const live = list.filter((e) => e.supersededBy === null);
  const pool = live.length ? live : list;
  return [...pool].sort((a, b) => {
    if (a.fetchedAt !== b.fetchedAt) {
      if (a.fetchedAt === null) return 1;
      if (b.fetchedAt === null) return -1;
      return a.fetchedAt < b.fetchedAt ? 1 : -1;
    }
    return a.editionKey < b.editionKey ? 1 : a.editionKey > b.editionKey ? -1 : 0;
  })[0];
}

const WALL_CLOCK = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})$/;

/** 壁時計の `fetched_at` に region の UTC オフセットを付ける。想定外の書式は例外（黙って直さない）。 */
export function fetchedAtIso(wallClock: string, regionId: string = DEFAULT_REGION_ID): string {
  if (!WALL_CLOCK.test(wallClock)) {
    throw new Error(`fetched_at の書式が YYYY-MM-DDTHH:MM:SS ではない: ${JSON.stringify(wallClock)}`);
  }
  return `${wallClock}${regionTimeZone(regionId).utcOffset}`;
}

/** 取得日（region の壁時計の日付）から `now`（region の壁時計へ直した日付）までの暦日差。 */
export function ageDays(fetchedAtWallClock: string, now: Date, regionId: string = DEFAULT_REGION_ID): number {
  const m = WALL_CLOCK.exec(fetchedAtWallClock);
  if (!m) throw new Error(`fetched_at の書式が YYYY-MM-DDTHH:MM:SS ではない: ${JSON.stringify(fetchedAtWallClock)}`);
  const { utcOffset } = regionTimeZone(regionId);
  const off = /^([+-])(\d{2}):(\d{2})$/.exec(utcOffset);
  if (!off) throw new Error(`utc_offset の書式が不正: ${utcOffset}`);
  const offMin = (off[1] === "-" ? -1 : 1) * (Number(off[2]) * 60 + Number(off[3]));
  const nowLocal = new Date(now.getTime() + offMin * 60_000);
  const today = Date.UTC(nowLocal.getUTCFullYear(), nowLocal.getUTCMonth(), nowLocal.getUTCDate());
  const fetched = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return Math.round((today - fetched) / 86_400_000);
}

export interface SourceMetaOpt {
  now?: Date;
  regionId?: string;
  /** 版が決まる系列（土地利用など）の edition_key。無ければ現行の版。 */
  editionKey?: string | null;
}

export function sourceFreshness(sourceId: string, opt: SourceMetaOpt = {}): SourceFreshness {
  const e = currentEdition(sourceId, opt.editionKey);
  const regionId = opt.regionId ?? DEFAULT_REGION_ID;
  const now = opt.now ?? new Date();
  return {
    source_id: sourceId,
    source_edition_id: e?.editionId ?? null,
    fetched_at: e?.fetchedAt ? fetchedAtIso(e.fetchedAt, regionId) : null,
    update_mode: (e?.updateMode as UpdateMode | null) ?? "undeclared",
    age_days: e?.fetchedAt ? ageDays(e.fetchedAt, now, regionId) : null,
  };
}

export function sourceCitation(sourceId: string, opt: SourceMetaOpt = {}): SourceCitation {
  const { metaById: metas, licenseById: lics } = indexes();
  const e = currentEdition(sourceId, opt.editionKey);
  const lic = e ? lics.get(e.licenseId) : undefined;
  return {
    ...sourceFreshness(sourceId, opt),
    name: metas.get(sourceId)?.nameJa ?? null,
    license_id: e?.licenseId ?? null,
    license: lic?.nameJa ?? e?.licenseId ?? null,
    license_class: e?.licenseClass ?? null,
    redistributable: e?.redistributable ?? null,
    attribution: lic?.attributionText ?? null,
  };
}

/** 画面用 API に加算する `freshness`（出典ごとの取得日・更新方式・経過日数）。重複は除く。 */
export function freshnessFor(sourceIds: readonly string[], opt: SourceMetaOpt = {}): SourceFreshness[] {
  return [...new Set(sourceIds)].map((id) => sourceFreshness(id, opt));
}

/** 系列の出典（`series.ts` の登録）の `freshness`。出典未記録（NULL＝合成）の alias は載せない（envelope と同じ規則）。 */
export function freshnessForSeries(series: readonly SeriesKey[], opt: SourceMetaOpt = {}): SourceFreshness[] {
  const ids: string[] = [];
  for (const s of series) for (const id of seriesInfo(s)?.sourceIds ?? []) if (id !== null) ids.push(id);
  return freshnessFor(ids, opt);
}

/**
 * 出現データ（`occurrence_agg`）の出典。画面用 API の `freshness` が使う。
 * D1 の `occurrence_agg` を `DISTINCT source_id` で舐めない（rows_read）ための固定表で、
 * 出典が増えたら `source-meta.test.ts` の突合が落ちて気づける形にしてある。
 */
export const OCCURRENCE_SOURCE_IDS: readonly string[] = ["gbif_kanagawa_occurrences", "inaturalist_kanagawa"];

/**
 * レッドリスト（`taxon_assessment` の rl2020/rl2026/rdb2022p）の出典。`/api/biota?kind=redlist` の `freshness` が使う。
 * 評価リストの `source_id`（registry.taxon_assessment.source_id の distinct。環境省外来種リスト moe_ias_list は別リスト）。
 * registry の source/source_edition で引けるので取得日・経過日数が載る。`update_mode` はマニフェストの無い出典なので
 * 宣言されるまで "undeclared"（推測で埋めない）。
 */
export const REDLIST_SOURCE_IDS: readonly string[] = ["kanagawa_redlist", "kanagawa_rdb2022_plants"];
