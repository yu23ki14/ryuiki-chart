# Issue #31 設計: 正準単位の併記（ADR-0023）と単位の出どころの統一

状態: 設計（承認待ち）。実装前。

## 1. 現状の実測（2026-10-06、`data/db/v2.sqlite` 読み取り専用 / `ryuiki.sqlite`）

### 1-1. 「104,410行の食い違い」は、コード上はすでに解消している
- Intake #15 の食い違いは `var_catalog.unit`（v1。原本の表記そのまま）と `registry[...].unit` の差だった。
  v1 は Issue #48 PR-5 で撤去済み（`var_catalog` は無い）。いまの `web/src/lib/ai/tools.ts` は
  `unitLabel(unit_id)`（`lib/cube/unit.ts` → レジストリ `unit.symbol`）でツール結果の最上位 `unit` と
  `registry[variableId].unit` の**両方**を作り、`SeriesChartCard.buildSeries()` はその `data.unit` を使う。
  原本の生の `unit` 文字列は web のどこからも読まれていない（`unit_raw` は `observation` 内のみ。grep 済み）。
  つまり AI の回答もチャートの縦軸も、すでに**レジストリの解決結果**に揃っている。
- 数字の照合: `measurements` で原本 `unit` が空の行は 非合成 108,385 + 合成 693。
  alias が単位を解決している行（原本空）は、合成込みで 104,410（Intake #15）、
  いまの `observation`（合成除外。Issue #61）では 103,717 行・28変数（= 104,410 − 合成 693、差は完全に説明がつく）。
  加えて `nlni_l03b_landuse_by_watershed`（原本に単位列が無い。km2 をレジストリが補う）9,716 行・26変数。
  合計 113,433 行・54変数が「原本に単位記載が無く、レジストリが補った」行。
- 残る欠け: 上記の「補った」事実が AI/画面から見えない（`observation_agg` は `unit_raw` を持たない）。

### 1-2. 正準化が要る単位（ADR-0023 の8変数 = 実データで出典間スケールが違うもの）
`observation_agg` の単位別行数（抜粋）: 0_1degc 56,960 / 0_1percent 56,960 / 0_1mm 56,471 / 0_1m_per_s 55,813 /
0_01ppmc 85,950 / 0_1ppm 14,421 / ppb 329,736 / ug_per_m3 95,138。`observation_agg.unit_id IS NULL` は 38,094 行
（単位不明。換算しない）。

## 2. 決定

### D1. 単位の出どころはレジストリの解決結果に統一（メイン決定1のとおり）
- コード側は 1-1 のとおり既に統一済み。実装は「統一を固定するテスト」と「根拠の開示」だけ。
- **`unit_basis`（'source' | 'registry' | 'mixed'）**: 原本が単位を報告したか、レジストリが補ったか。
  持ち場所は `variable_alias.unit_basis`（registry/variable_alias.csv に1列追加）。理由: この事実は
  「出典 × 表記（alias）」の性質で、`observation_agg` に列を足さずに済む。
  - 値の決め方は推測しない: alias ごとに `observation` の `unit_raw` が全行 NULL なら 'registry'、
    全行 symbol 一致なら 'source'。一度だけ実測する小スクリプトで CSV 列を生成し、diff をレビューする。
  - **b04 の `_assert_unit_evidence()` に検査3を追加**: CSV の宣言と `observation` の実態（alias 単位ではなく
    `(source_table, variable_id, unit_id)` 単位で突合）が食い違えば止まる。テストで「わざと壊すと止まる」を固定。
  - web: `lookup.ts` に `unitBasis(variableId, unitId)`（alias 行を畳む。混在なら 'mixed'）。`tools.ts` の
    `RegistryEntry` に `unitBasis` を足す（`registry[variableId]` に載る＝AI に渡る）。prompt に1文
    （「`unitBasis='registry'` は原本に単位記載が無くレジストリが補った値。断定的に『原本でも mg/L』と言わない」）。
  - 画面の注記は新設しない（最小限）。`TimeseriesExplorer` 等は既存の `unit` 表示のまま。AI だけが根拠を知る。

### D2. `unit` に `canonical_unit_id` / `scale_to_canonical`
- 列: `canonical_unit_id TEXT NOT NULL`（自分自身でもよい）、`scale_to_canonical REAL NOT NULL`
  （`値_正準 = 値_出典 × scale`）。**線形のみ。オフセット換算（℃↔K 等）は対象外**（本データに該当単位なし。
  ADR 決定2 の「オフセット列も併設」は採らない。必要になった時点で ADR を改訂）。
- 正準単位は「換算が実際に要る単位ファミリー」だけ決める。根拠が SI 換算で明らかなものだけ:

| unit_id | → canonical | scale | 根拠 |
|---|---|---:|---|
| 0_1degc | degc | 0.1 | 平塚市仕様書（unit.yaml 既存コメント）。実値=格納値×0.1 |
| 0_1percent | percent | 0.1 | 同上 |
| 0_1mm | mm | 0.1 | 同上 |
| 0_1m_per_s | m_per_s | 0.1 | 同上 |
| 0_1ppm | ppm | 0.1 | 同上 |
| ppb | ppm | 0.001 | SI 接頭辞。ADR の air.* 3変数 |
| ug_per_m3 | mg_per_m3 | 0.001 | SI 接頭辞。ADR の air.spm |
| 0_01ppmc | **自分自身** | 1 | ppmC（炭素換算）は ppm と同じ尺度と言えない（推測しない）。換算なし |
| 上記以外全部（mg_per_l, cm, m, t_p_m, …） | 自分自身 | 1 | 次元をまたぐ統一（mg/L と mg/m3、cm と m）はしない。必要な消費者が現れた時点で追加 |

  mg/L（水）と mg/m3（大気）は媒体が違い比較対象にならないため、次元だけ同じでも1つにまとめない
  （メイン決定2の「次元ごとに1つ」は、換算が要る範囲に限定して解釈する。要レビュー）。
- 変更点: `registry/unit.yaml`（2キー追加。29件全行に明示。省略不可にして書き忘れで止める）、
  `scripts/registry/build_unit_variable.py`（列追加＋検査: canonical が実在・canonical 自身は scale=1・
  canonical の canonical は自分自身・scale>0・**同じ variable に使われる全 unit が同じ canonical を持つ**——
  ADR の8変数がこれで機械的に守られる）、`web/src/db/schema-registry.ts` ＋ `pnpm run db:generate`、
  `build-registry-ts.mjs`/`generated.ts`（`GeneratedUnit` に2フィールド）、`seed-d1-local.mjs` は列名依存なら追随。

### D3. キューブが正準単位でも読める — キューブのスキーマは変えない
- 方式: 問い合わせ層で正準化する。`lib/registry/lookup.ts` に `canonicalOf(unitId) -> {unitId, symbol, scale}`、
  `lib/cube/unit.ts` に `toCanonical(value, unitId)`、`canonicalSeriesKey(series)`（`unitId` を正準に置換した系列キー）
  と、行配列を正準単位へ寄せる `canonicalizeCells(rows)`（`valueZero`/`valueLod` に scale を掛け `unitId` を正準に差し替え。
  元の `unitId` は `sourceUnitId` として残す＝出典の単位は捨てない）を足す。
- なぜキューブに列を足さないか: (1) ADR-0023 追記が「列追加で値を複製」と言うが、scale は unit の関数なので
  値の二重保持は冗長で、b04 の再ビルド（2.8GB）と v2 の鮮度指紋・D1 再投入が全部動く。(2) 横断比較の消費者が
  まだ無く、読み出し関数＋テストで ADR 決定4 の閉じる条件を満たせる。(3) ADR 決定3が言う「DuckDB 直クエリ（封筒を経由しない利用者）」
  は `unit` の2列＋`unit_id` の JOIN で自力換算できる（`unit` は D1 にも載る）。**この判断は ADR-0023 に追記**し、
  決定3（キューブ軸）は「問い合わせ層に置き換えた（スキーマ変更なし）」と明記する。
- 注意: 掛け算の浮動小数誤差（0.1 倍など）は表示側で丸める想定。出典値は無改変のまま残る。テストは `toBeCloseTo`。

## 3. 変更ファイル一覧
- registry: `registry/unit.yaml`, `registry/variable_alias.csv`（`unit_basis` 列）, `registry/README.md`（列の説明）
- ビルダ: `scripts/registry/build_unit_variable.py`（列・検査）、`scripts/b04_build_cube.py`（検査3）、
  `scripts/tests/`（unit/alias ビルダのテスト、b04 検査のテスト＝わざと壊すと止まる）
- 実測用の一回きり生成: `unit_basis` を埋める小スクリプト（コミットはしないか `scripts/migrate/` 配下に置く）
- web: `src/db/schema-registry.ts`、`drizzle/migrations/`（`db:generate`）、`src/lib/registry/generated.ts` と
  `generated-client.ts`（再生成）、`lookup.ts`（`canonicalOf`/`unitBasis`）、`lib/cube/unit.ts`（`toCanonical`/
  `canonicalizeCells`/`canonicalSeriesKey`）＋テスト、`lib/ai/tools.ts`（`RegistryEntry.unitBasis`）、`lib/ai/prompt.ts`（1文）
- docs: ADR-0023（状態「コード化済み」・追記）、`docs/plans/PHASE_B_INTAKE.md` #15（解決済みの追記）、
  `docs/plans/PHASE_B_RECONCILIATION.md:453` 付近、`CLAUDE.md` の「40テーブル」等は列追加なので変更なし
- 既存の `SeriesChartCard.tsx` は**変更しない**（すでにレジストリ経由。回帰テスト `unit` が `registry[variableId].unit` と一致を追加）

## 4. 検証方法（速い検証のみ）
1. レジストリ再生成 `r01` → `build_unit_variable` のテスト（canonical 検査の変異: 存在しない canonical、
   同一 variable で canonical 不一致、scale<=0 でそれぞれ止まる）。
2. `unit_basis` 突合: 実測スクリプトで 113,433 行（measurements 103,717 / landuse 9,716）が 'registry'、
   残りが 'source' になること。b04 検査3は小フィクスチャでテスト（宣言を1行書き換えると止まる）。
   実データでの b04 全量は走らせない（メインが `build:v2` 時に1回）。
3. vitest: `lookup.test.ts`（canonicalOf・unitBasis）、`cube/unit.test.ts`（8変数: 0_1degc 200 → degc 20.0、
   ppb 1500 → ppm 1.5、ug_per_m3 → mg_per_m3、自分自身は不変、unit_id NULL は不変・正準化しない）、
   tools の結果で `unit` == `registry[variableId].unit` となる回帰テスト。
4. 食い違い解消の前後件数: 前 = Intake #15 の定義（原本空 & レジストリ解決）104,410（合成込み）→ 実装後は
   「`unit_basis='registry'` と宣言され、b04 が宣言と実データの一致を機械検証した行」103,717 + 9,716 として
   **残す理由つきで列挙**（食い違いではなく宣言済みの補完になる）。画面/AI 側で raw と registry が違う箇所は 0。

## 5. スナップショットが動くか
- `data/sample/serving_snapshot.json`（v2 サービング）: 動かない。観測値・系列キー・`observation_agg` は不変
  （正準化は読み出し関数に閉じ、既存の問い合わせは `canonicalizeCells` を呼ばない）。
- `web/src/lib/ai/__snapshots__/prompt.test.ts.snap`: **動く**（prompt に1文足すため。差分は1文のみ・宣言する）。
- `registry` の生成物（`generated.ts` 等）: unit の2列と alias の `unit_basis` が増える（再生成物）。
- `reports/serving_fingerprint.json`: b00 のパスは触らないが、b04 の検査を足すため `b04` のコードが変わる場合は
  v2 パイプラインのコード指紋が変わる（`check_v2_fresh` が「古い」と判定→メインが `build:v2` を1回回す）。
  b00 を回すか否かは「`PIPELINE_*` に b04 が含まれるか」で決まるので、実装時に確認して報告する。
- 実行が重いもの（メインが最後に1回）: `build:v2`（b04 の検査3を実データで）、`serving:snapshot -- --mode snapshot`、b00。

## 6. 対象外・未解決
- オフセット換算、次元をまたぐ統一（mg/L↔mg/m3、cm↔m）、`0_01ppmc` の ppm 換算、`observation_agg` への正準値列の追加。
- 画面の注記（新設しない）。AI の応答文での「補った」旨の言い回しは prompt の1文に任せる。
- `sensor_timeseries` の symbol 表記ゆれ（b04 コメントの既知課題）は本 Issue 範囲外。
