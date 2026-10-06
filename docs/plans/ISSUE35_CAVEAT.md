# Issue #35 注記の整備（＋ #33-5）設計

状態: 設計のみ（実装は承認後）。2026-10-06。担当: Sonnet 設計担当。
レビュー（severity/kind）はオーナー委任で行った判断で、**2026-10-07 にオーナーが全件を変更なしで確認済み**（`review.owner_confirmed_on`）。
数値はすべて `ryuiki.sqlite`（読み取り専用）・`v2.sqlite`・`registry.sqlite` の実測（2026-10-06）。

## 1. 現状の実測

注記は `registry/caveat.yaml` に17件、`cells.notes` 由来207件、計224件（`registry.sqlite`）。
Issue 本文の「14件・blocking 7件」は古い。yaml の blocking は現在9件
（censoredLod・aboveLod・effort・synthetic・regimes・gbifCutoff・share・isAlien・unitUnknown）、null は8件。

`caveat_scope` の現行の種類と行数の出どころ（`scripts/registry/build_caveat.py` の Python 定数）:
`table`(sites のみ)・`place_kind`(site/zone/grid01)・`dataset`(measurements/organism_records/synthetic)・
`source_id`(moe_ias_list)・`variable_theme`(landuse)・`variable`(unitUnknown の8変数)・
`cell`(doc_id)・`cell_table`(doc#table)。`table_prefix` は行が0。
読み手: `web/src/lib/cube/caveats.ts`（`caveatsForFacets`）、`lookup-client.ts`（`caveatsForTables`、
`sites` だけが使う）、`web/src/lib/registry/index.ts`（`getCaveatsForDocument` が `scope_kind='cell'`）、
`web/scripts/build-registry-ts.mjs`（既知 kind の許容リスト）。

#33-5 の検証結果（`summary_watershed_occurrence` = 流域の生物記録数。日付あり 816,856 件のうち
流域外・未解決 `place_id IS NULL` が 83,515 件=10.2%、流域内 733,341 件、289 流域＋NULL 行）。
流域に付く注記は `dataset=organism_records` 経由の5件（organismSite/effort/regimes/gbifCutoff/share）:

| 注記 | 主張 | 実データ | 判定 |
|---|---|---|---|
| organismSite | `site_id` 原本で全件 NULL、流域は W12(1977) 点内包 | NULL 823,692/823,692。`occurrence_place` は point_in_polygon:even_odd・W12 377 面 | 正しい。ただし流域外 10.2% がある（本文に無い。追記候補） |
| regimes | 2013–16 標本の植物／2017–24 eBird の鳥類／2025– iNat の昆虫・植物・菌類 | 流域内でも 2013–16 被子植物 7,864〜11,531/年（PRESERVED_SPECIMEN、2016 は鳥 1,912 も）、2017–24 鳥類 5,125→66,497/年（出典は URN:catalog:CLO:EBIRD）、2025 昆虫 14,740・被子植物 10,746・菌類 6,897・鳥類 5,606 | 概ね正しい（「中心」の言い方で許容）。変更なし |
| gbifCutoff | 「2025年1月に月8,750件→399件」 | GBIF 月別: 2024-12 は 6,789 件、2025-01 は 399 件。8,750 は **2024-01** の件数（2023–25 の最大は 2024-04 の 9,026）。鳥類は 2024 年 70,897→2025 年 2,980（全体） | **本文が不正確**（8,750 の位置づけが違う）。直す |
| effort | 「観察努力（記録した人の数）」 | 記録者列 `identified_by` は GBIF の 88.6%（583,158/658,360）・iNat の 100% が NULL。記録者数は測れない。年間記録数は 2013 年 約1.4万→2024 年 約9.95万（流域内）で増加の事実はある | 「記録した人の数」は**実データで裏付けできない**。直す（測れる事実に置き換え） |
| share | 「同じ分類群の中での割合（‰）で比べている」 | 流域表は割合を持たず生の件数（`n`/`n_red_list`/`n_alien`）。割合は grid01 の種別トレンド（`speciesShareTrend`）だけ | **流域には当てはまらない**。流域から外す（scope を grid01 のみへ） |

他の本文の事実確認（ついで）:
- measuredOn: 「検体値 216,990 行・年度集計値 98,328 行」は古い。非合成で 215,445 行（10桁）・105,454 行（4桁）。直す。
- censoredLod「約24%」: `<` 75,689/320,899 = 23.6%。合っている。aboveLod「26行」: `>` は26行・すべて透明度。合っている。
- inatBackfill「96%が解決」: 実測は学名先頭2語一致 117,007/165,332=70.8%、属一致 25,093=15.2%、未解決 22,671=13.7%
  （`taxon.classification_basis`）。96% は再現できない。直す。「165,332 件」は合っている。
- fishClass: Chordata で class が NULL 8,863 件、Actinopterygii は 0 件。合っている。
- isAlien: 同一二名法内で is_alien が混在する種 102。オオクチバス 139 件・ウシガエル 88 件はフラグ 0。合っている。
- municipality「290地点／62地点」: 合っている（env_kousui 290、他4出典 62）。zone「zone 1 に水質データなし」: zone 1 は4地点、測定0件。合っている。
- 流量の逆流: 流量関連 4,668 行・うち負値 180 行・14 地点（全83地点中）。最小 -8.5。合っている。

見つかった不整合（要判断、§7）: `unitUnknown` の対象 variable_id に `hydro.flow` が入っている。
`variable_alias.csv` の流量 alias は `unit_id` が空だが、`variable.yaml` は `unit_id=m3_per_s`・status ok と確定済み
（`observation_agg` の hydro.flow は unit_id NULL が 12,325 セル）。注記は「レジストリでも単位を確定できていない」と言うので
流量では偽になる。

## 2. 判定基準（ADR-0013 に明文化する案）

- **blocking**: その注記を無視して比較・集計・解釈すると**結論が誤る**もの。「読んではいけない」と言える範囲に限る。
- **warning**: 無視すると誤解釈しうるが、比較そのものが無効になるわけではないもの（値の出自・補完・誤読しやすい癖）。
- **info**: 処理規則や由来の説明。知っておくと良いが、無視しても数値の解釈は変わらないもの。
- 「文面に禁止表現があるか」では決めない（機械分類の誤りの原因）。**数値・系列に実際に効く範囲**で決める。
- 同じ危険を2つの blocking が重複して言わない（例: effort が危険の本体、share は方法の説明）。
- **kind**: 危険の性質を表す。ADR の enum は「版・時間・方法をまたぐ変化」が中心なので、
  単一時点の加工規則や出自の説明には付けず **null を「該当なし」という判断として明示**する
  （無理に当てはめると誤分類。レビュー記録に `kind: 該当なし` と書く）。
- `cells.notes` 由来207件: severity は原本の `blocks_timeseries` フラグ（人が付けた区分）をそのまま使っており機械分類ではない。
  `kind` の `footnote`/`comparability`/`survey_scope`（127件）は enum 外のまま ADR の enum に**3値を追記**して正式化する
  （行ごとの丸めはしない）。

## 3. レビュー表（`registry/caveat.yaml` に各注記の `review:` として記録する）

記録の形: `review: {reviewed_on: 2026-10-06, reviewer: "claude（オーナー委任）", owner_confirmed_on: 2026-10-07, reason: "…1〜2文", changed: [severity, kind, scope, body] または false}`。

| key | 現 severity/kind | 判定 severity/kind | 変更 | 理由 |
|---|---|---|---|---|
| measuredOn | null/null | info/null | sev | 年度集計値と検体値は grain で構造的に分離済み。無視しても数値は誤らない。本文の件数が古いので直す |
| censoredLod | blocking/censoring | 同左 | なし | ND を観測値と読むと過大評価（上限側の見積もり）になる。23.6% に効く |
| aboveLod | blocking/censoring | 同左（scope を狭める） | scope | 26 行すべて透明度。比較すると高透明度が落ちて偏る。scope を dataset=measurements 全体から **variable=water.transparency** に狭める（他の指標には無関係） |
| duplicates | null/null | info/null | sev | 日平均にまとめた規則の説明。値の解釈は変わらない（重複グループ 71,356） |
| zone | null/null | info/null | sev | 操作的定義であることの断り。比較は成立する |
| organismSite | null/null | warning/null | sev | 流域・地点への割り当ては推定で、流域外 10.2% がある。誤読しうるが比較は成立する |
| effort | blocking/null | blocking/null | body | 件数の増加を実体の増加と読むと結論が誤る。「記録した人の数」を測れる事実に置き換える |
| synthetic | blocking/synthetic | 同左（scope の表し方を変更） | scope | 現行の配信経路に合成データは載らない（b03 が 2,265 行を除外）。休眠の注記として維持し、scope は `dataset=synthetic`（偽の dataset 値）→ **observation_set `is_synthetic=1`**。本文の「観測者・介入…」は現 D1 に表が無いので要確認（§7） |
| regimes | blocking/time_series_break | 同左 | なし | 年代で中身が入れ替わる。分類群をまたぐ比較は誤り。実データで確認済み |
| gbifCutoff | blocking/coverage_gap | 同左 | body | 2025 年以降の鳥類の減少をデータの都合と明記する意義は変わらない。数値を実測に直す |
| share | blocking/null | warning/null | sev・scope | 方法の説明（危険の本体は effort）。重複 blocking を避ける。scope を dataset=organism_records から **place=grid01 のみ**へ |
| inatBackfill | null/method_change | info/null | sev・kind | 当プロジェクトの補完規則で、時間をまたぐ方法変化ではない。本文の「96%」を実測に直す |
| fishClass | null/definition_change | info/null | sev・kind | 当プロジェクトの分類規則で、定義の時間変化ではない |
| isAlien | blocking/known_error | 同左 | なし | 原本フラグで外来種を数えると結論が誤る（102 二名法で混在、オオクチバス 0 件）。環境省リスト結合へ置換済みの旨も本文にある |
| municipality | null/null | info/null | sev | 列名と中身の不一致の説明。表示名の問題 |
| landuseDefinitionChange | null/definition_change | **blocking**/definition_change | sev | 無視すると 2006→2016 の「全減・全増」を実変化と読む。blocking の定義に該当するのに禁止表現が無く機械分類が漏らした。scope は theme=landuse 全体のまま（§7 に狭められるか要確認の点） |
| unitUnknown | blocking/null | blocking/**unit_change** | kind | 単位が既知の出典と混ぜると桁がずれる。出典間の単位差なので unit_change が当たる。流量の不整合は §7 |
| （新）flowTidalBackflow | — | warning/null | 新規 | 感潮域の逆流の負値（180 行・14 地点）を欠測・誤りと読むと平均が偏る。比較は成立するので blocking でない |

blocking は9→9件（share が外れ、landuseDefinitionChange が入る）。warning 3件（organismSite・share・流量）。
severity null は0件になる。`kind` の null は「該当なし」として明示する。

## 4. 語彙の対応（`scope_kind` を ADR-0013 の6種に寄せる）

ADR-0013 の `scope_kind`: variable / place / source_edition / observation_set / dataset / taxon。
`scope_ref` は「対象の ID（範囲指定も可）」なので、**ID そのもの、または `キー=値`（`&` で連結）の選択式**とする。
実行時の照合は今と同じ**文字列の完全一致**（選択式を解釈しない。`facetsForSeries` が同じ文字列を作る）。

| 現行 (kind, ref) | 新 (kind, ref) | 備考 |
|---|---|---|
| table:`sites` | dataset:`sites` | 配信表 `sites` を dataset とみなす（`sites` は地点台帳。v1 の表名で引く経路を廃止） |
| table_prefix（行0） | 廃止 | `mesh_` の行は PR-5 で消滅済み。語彙から外す |
| place_kind:site/zone/grid01 | place:`place_kind=site` 等 | place_id そのものではなく種別の選択式 |
| dataset:measurements/organism_records | dataset: 同じ | |
| dataset:`synthetic`（偽の値） | observation_set:`is_synthetic=1` | 実在しない dataset 値をやめる |
| source_id:moe_ias_list | source_edition:`source_id=moe_ias_list` | 出典の版の集合（ADR-0005）。版を特定できないので出典 ID の選択式 |
| variable_theme:landuse | variable:`theme=landuse` | |
| variable:`<variable_id>` | variable:`<variable_id>` | 変わらない（unitUnknown→observation_set へ移す。下） |
| unitUnknown の variable:`<id>`（unit_id=null の系列だけ） | observation_set:`variable=<id>&unit_id=null` | 「その変数かつ単位不明の系列の集合」。variable ref は流量の注記と衝突するので分ける |
| cell:`doc_id` | source_edition:`doc_id=<doc>` | 行政文書 = 出典の版 |
| cell_table:`doc#table` | observation_set:`doc_table=<doc>#<table>` | 文書内の表 = 観測値の集合 |
| （新）flowTidalBackflow | variable:`common:variable:hydro.flow` | 独立した注記。`description_ja` の埋め込みを外す |
| （新）aboveLod | variable:`common:variable:water.transparency` | dataset から狭める |
| （新）share | place:`place_kind=grid01` のみ | dataset=organism_records から外す |

TypeScript 側: `FacetKind` を6種に置き換え、`facetsForSeries` は系列ごとに
variable:`<id>` を**常に**積み、`unitId===null` の系列にだけ observation_set:`variable=<id>&unit_id=null` を積む。
`caveatsForTables`・`ai/caveats.ts` のテーブル経路・`TABLE_SCOPES` を削除し、
`tools.ts` の `sites` を含む3呼び出しは dataset:`sites` の facet で引く。
照合規則（priority 降順・初出順・sortOrder・key 重複排除）は `resolveCaveatRefs` のまま。

## 5. 宣言ファイル（表→注記の対応を `registry/` へ）

`registry/caveat_scope.yaml`（新設）。形:

```yaml
vocabulary: [variable, place, source_edition, observation_set, dataset, taxon]
scopes:
  - {kind: dataset, ref: sites, caveats: [zone, municipality]}
  - {kind: dataset, ref: measurements, caveats: [measuredOn, censoredLod, duplicates]}
  - {kind: observation_set, ref_from: unit_unknown_variables, caveats: [unitUnknown]}  # variable_alias.csv の unit_id 空行から導出
  - {kind: observation_set, ref: "is_synthetic=1", priority: 1, caveats: [synthetic]}
  ...
```

`sort_order` = 同じ (kind, ref) の中での宣言順（現行と同値になる）。`priority` は scope 単位の宣言。
`build_caveat.py` は読むだけにする: Python 定数（`*_CAVEATS` リスト・`add_*_group`）を削除。
`ref_from` は名前付きの導出器（今の `_unit_unknown_variable_refs()`）に限る。
ビルド時の検査（失敗で止める）: `kind` が vocabulary 内／`caveats` の key が `caveat.yaml` に存在／
`variable:` の ID が `variable.yaml` に存在／(kind, ref, caveat) の重複なし／`review:` が全注記にある。
`web/scripts/build-registry-ts.mjs` の既知 kind リストは vocabulary を yaml から読む（二重管理をやめる）。

D1 スキーマ（`schema-registry.ts`）: 列は変わらない（`scope_kind`/`scope_ref` は text）。コメントだけ更新し、
`pnpm run db:generate` が「No schema changes」になることを確認する（SQL は書かない）。

## 6. 変更ファイル一覧・検証・スナップショット

変更: `registry/caveat.yaml`（review・severity/kind・本文4件〔measuredOn・effort・gbifCutoff・inatBackfill〕・新注記 flowTidalBackflow）、
`registry/caveat_scope.yaml`（新）、`registry/variable.yaml`（hydro.flow の `description_ja` から感潮域の逆流を外す。
`web/` の `VARIABLE_NOTE` 経由の表示は注記側が出す）、`registry/README.md`、
`scripts/registry/build_caveat.py`（読むだけ化・検査）、`scripts/tests/`（検査と「わざと壊すと止まる」）、
`web/src/lib/cube/caveats.ts`・`caveats.test.ts`、`web/src/lib/registry/lookup-client.ts`・`lookup.test.ts`・`generated.test.ts`・`index.ts`
（`getCaveatsForDocument`）、`web/src/lib/ai/caveats.ts`・`caveats.test.ts`・`tools.ts`、`web/scripts/build-registry-ts.mjs`、
再生成物 `generated.ts`・`generated-client.ts`（手で触らない）、`web/src/db/schema-registry.ts`（コメント）、
`docs/adr/0013-caveats.md`（severity/kind の基準・scope の語彙・enum 3値・cells 注記・レビュー結果の節を追記）、
`docs/plans/PHASE_B_INTAKE.md`（#2・#3 を解決済みに）、本書に検証した数値を残す。

宣言済みの意図的な差分（テストで列挙して固定する）:
1. `get_overview` は流域だけを読むので `facetsForOccurrence({places:["watershed"]})` にし、`share` が付かなくなる。
   `BIOTA_CAVEATS`（grid01）は `share` を保つ（並びは organismSite・effort・regimes・gbifCutoff・share のまま）。
2. aboveLod は透明度以外の系列に付かなくなる。
3. flowTidalBackflow が hydro.flow の系列に付く。`hydro.flow` の説明文（`VARIABLE_NOTE`）は注記へ移る。
4. unitUnknown は hydro.flow から外すかどうかは §7（外すなら 8→7 変数）。
5. 他の `caveatsForTables`・`caveatsForFacets` の結果（`caveats.test.ts` の34ケース・cube のケース）は、
   上記以外を新語彙の期待値に書き換えるだけで**同じ注記・同じ順序**であることを確かめる。

検証（軽い順）: `python -m pytest scripts/tests -k caveat`（review 欠落・未知 kind・未知 key・未知 variable・重複で止まる）、
`r01_build_registry.py` の `--files-only` と通常ビルド、`cd web && pnpm run build:registry`（再生成）と
`pnpm vitest run src/lib/cube/caveats.test.ts src/lib/ai src/lib/registry`、`pnpm run db:generate`（差分なし）。
更新される vitest スナップショット: `web/src/lib/ai/__snapshots__/prompt.test.ts.snap`（全注記の本文がプロンプトに入るため、本文4件と新注記が差分に出る。宣言済み）。

**serving スナップショット（`data/sample/serving_snapshot.json`）は動かない**（caveat を含まない。実測 0 件）。
ただし `registry/` と `web/src/lib/registry` は `b00` の PIPELINE ディレクトリなので、
`registry.input_fingerprint` が変わり **v2 が「古い」判定**になる（`build:v2` の作り直し）。
メインが最後に回すもの: `build:v2`、`scripts/b00_run_full_gate.py`（`reports/serving_fingerprint.json` を更新してコミット）、
`serving:snapshot -- --mode snapshot`（一致を確認）。

## 7. 要判断（オーナー・メイン）

1. **unitUnknown と hydro.flow**: 注記が流量で偽になっている（§1）。推奨: refs の導出に「`variable.yaml` に `unit_id` がある変数は外す」を足す（8→7 変数）。
   ただしキューブ側で流量の `unit_id` が NULL なのは別問題（b03 が variable.unit_id にフォールバックしない）で、本 PR では直さず申し送る。
2. **synthetic の本文**（「観測者・介入・意思決定・品質段階の遷移」）: 該当する表は現 D1 に無い。休眠の注記として維持するが、本文を「合成データ（デモ用に生成）。実在の公開データではない。」に縮める案は未実施（プロンプトに出る文面なので承認が要る）。
3. **landuseDefinitionChange の scope**: 本文が言うのは3区分（幹線交通用地・道路・鉄道）だけで、他10区分は日本語名が一致する（PHASE_B_LANDUSE.md:81）。
   名称一致は定義一致の証明ではないので、**今は theme 全体のまま**にする（推測で狭めない）。狭めるなら一次資料の確認が要る。
4. **organismSite に流域外 10.2% を追記するか**: 本文の事実は正しいので今回は変えない案（変えるなら本文変更が1件増える）。
5. #33-5 の残り（#33 の 3・4・6）はこの担当の範囲外。

## 8. 実装後の決定（2026-10-06、メインの承認）

- §7-1: hydro.flow は unitUnknown の対象を機械導出（`variable_alias.csv` の `unit_id` 空行）のままにし、
  #31 が流量の alias に m3/s を入れれば自動で外れる（本 PR は `variable_alias.csv` に触れない）。
  本文は元のまま（事実どおり）。
- §7-2: synthetic の本文を縮めた。§7-3: landuse は theme 全体のまま、理由を `caveat_scope.yaml` と review に1文。
- §7-4: organismSite に流域外・未解決 10.2%（83,515/816,856件）を追記した。
- 実装で足したもの: `unscoped`（意図して範囲に付けない `fishClass`/`inatBackfill` の宣言）、
  画面の変数説明に変数スコープの注記を添える `variableNote()`（TimeseriesExplorer・SiteDetail）。
- `facetsForTables` は配信表 `sites` だけを dataset として引く（`measurements` 等の論理名は D1 の表ではない）。
