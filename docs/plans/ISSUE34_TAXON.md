# Issue #34 分類群・レッドリスト・外来種の整備（設計）

状態: 実装済み（設計承認後）。実測と結果は ADR-0019「Issue #34 追記」・`reports/phase_b_taxon_assessment.md`。実装時の差分: 弱い一致の採用は 0 件、`accepted_taxon_id` は 81 件、`n_alien` は 3,721→19,237（レビュー後。原本の `is_alien` 旗ではなく registry から導く定義に変更。ADR-0019 の表が正）、10 種の件数は `occurrence` 上の値（モツゴ 180・ヒキガエル 37）に確定。v1 は #48 PR-5 で撤去済みなので、Issue 本文の行番号と
`b08_project_occurrence_v1.py` は存在しない。現行の入口は `docs/PIPELINE.md`「取り込み・レジストリ」。

## 1. 各項目の現状の実測（2026-10-06、読み取り専用で計測）

### 項目1 外来種の除外規則

- `moe_ias_list.csv` は 429 行・distinct binom 424。`origin_ja` は「国外由来の外来種」399・
  「国内由来の外来種、国内に自然分布域を持つ国外由来の外来種」20・同「・」区切り 10。
  「国内由来」を含む行は 30（`国内由来` を含まない行が 399）。
- binom 単位の判定:
  - 全掲載が「国内由来」を含む binom: **27**。同じ binom に「国外由来の外来種」が1件でもある
    Pelodiscus sinensis・Sus scrofa・Cuora flavomarginata は 27 に入らない（外来として数える）。
  - 現行の固定7種: 27 のうち **6種**（Nyctereutes procyonoides・Plantago asiatica・Trypoxylus dichotomus・
    Morus australis・Cervus nippon・Rumex japonicus）が含まれる。**Apis mellifera は含まれない**
    （`origin_ja` は国外由来。理由は `subspecies_binomial_contraction` のみ）。
  - 新たに外れる binom は 27-6 = **21**（moe リスト上）。うち `organism_records` に記録のあるものが **10**
    （他の11種は記録0。レポート `reports/phase_b_taxon_assessment.md` の「10種」と一致）。
- 10種の記録数（`organism_records.scientific_name` の二名法で集計、うち `is_alien=1` の件数）:

| binom | 記録数 | うち is_alien=1 |
|---|---:|---:|
| Pseudorasbora parva（モツゴ） | 180 | 10 |
| Plestiodon japonicus（ニホントカゲ） | 43 | 0 |
| Bufo japonicus（ニホンヒキガエル） | 37 | 0 |
| Fejervarya kawamurai | 12 | 7 |
| Mustela itatsi | 9 | 6 |
| Martes melampus | 5 | 3 |
| Ficus microcarpa | 2 | 1 |
| Coreoperca kawamebari / Dicentra peregrina / Tachysurus nudiceps | 各1 | 0 / 1 / 1 |
| 計 | 291 | **29** |

  （レポートの 179/36 とは Pseudorasbora・Bufo で1件ずつ差がある。実装時に binom の取り方の差を確認し、
  正にする方を1つ決めて表を作り直す。）
- **重要な実測**: `n_alien` は b06 が `organism_records.is_alien`（m03 が taxa.ias_category の学名一致で付けた旗）
  をそのまま運び、b07 が `SUM(is_alien)` するだけ。**`in_scope` は `n_alien` に一度も効いていない**
  （`in_scope` を読むのは `catalog.ts` の `iasSpecies` と table-meta のサンプルSQLだけ）。つまり現行の
  `n_alien`（全体 3,721）は**固定7種の is_alien=1 の 351 件も含んでいる**。新しい規則を `n_alien` に効かせると
  動くのは新10種の 29 件ではなく、固定7種 351 件＋新10種 29 件＝**380 件（3,721→3,341、-10.2%）**。
  `Σn_alien` を使う `summary_species_catalog`・`summary_watershed_occurrence`・スナップショットも同じ分だけ動く。
- `in_scope=0` になる moe 行: 現行 binom 一致で7種ぶん → 規則適用後 28 binom（27＋Apis mellifera）ぶん。

### 項目2 accepted_taxon_id

`taxon.accepted_taxon_id` は全行 NULL（`build_taxon.py` 方針6）。`taxon_crosswalk.csv`（2,677行）の
`accepted_scientific_name` は一致ノード自身の学名で受理名ではない。status 内訳: ACCEPTED 2,242・
SYNONYM 376・DOUBTFUL 25・空 34。GBIF `species/match` は SYNONYM のとき `acceptedUsageKey` を返す。
ネットワーク（api.gbif.org）は手元から到達可（`species/match` で応答確認）。

### 項目3 弱い一致 300 件

HIGHERRANK 240（GENUS 139・SPECIES 80・KINGDOM 12・FAMILY 5・ORDER 2・PHYLUM 1・CLASS 1）／FUZZY 60
（SPECIES 50・SUBSPECIES 7・VARIETY 2・FORM 1）。出典は神奈川RL 178・環境省RL 80・外来種 42。全件
`query_variant=verbatim`。HIGHERRANK/SPECIES の80件の中身は「亜種・変種名で聞いて種に丸められた」もの
（例: `Hirasea planulata planulata`→`Hirasea planulata`）で、学名の正規形は一致しない。FUZZY は定義上
綴りが違う（`Mungos mungos`→`Mungos mungo`）。したがって**自動採用の規則（正規形完全一致・種以下・候補1つ）を
満たす行はほとんど無い見込み**（実施件数は収集後に数える）。

### 項目4 DwC-A の taxonID

`scripts/x01_dwca.py:219` が `"taxonID": r["taxon_key"] or ""`。`organism_records.source_id` は同じ行で読めており
（`sid = r["source_id"]`）、`taxon_namespaces.TAXON_KEY_SOURCE_NAMESPACE`（gbif/inat）がそのまま使える。
`x03_verify_dwca.py` は taxonID を検査していない。

### 項目5 place_kind='grid01'

**ADR-0006 のコードリストに追記済み**（`docs/adr/0006-place-registry.md` の place_kind 列挙、2026-09-23 追記。
ADR-0026 D3-6 の履行）。`registry/README.md` にも逸脱の節がある。残りは `PHASE_B_INTAKE.md` の #11 を
解決済みにする記述の整理だけ。

### 項目6・7

実装しない。着手条件を ADR-0019 末尾と `PHASE_B_INTAKE.md` に書く（4節）。

## 2. 決定

### D1 外来種の除外規則を出典の属性ベースにする（行は消さない）

- `registry/taxon/assessment_scope_exclusions.yaml` に **`rules:`** を足す。1規則:
  `rule_id: domestic_origin_only`・`list_id: moe_ias_2015`・「その binom の掲載行がすべて `origin_ja` に『国内由来』を
  含む」・理由コード `domestic_origin`。種名はコードに書かず、規則は宣言から読む。
- 既存 `exclusions:`（固定7種）は**残して併用**する。7種それぞれの確認結果:
  6種は `domestic_origin`（規則に含まれる。規則との一致を機械検証して宣言のずれを止める）、
  Apis mellifera は `subspecies_binomial_contraction` のみ（規則に含まれない。宣言が唯一の根拠）。
  Trypoxylus は両理由。
- 除外の集合 = 規則が選ぶ binom ∪ 宣言の binom（28）。`taxon_assessment` に列 **`scope_reason`**（TEXT NULL、
  `domestic_origin` / `subspecies_binomial_contraction` / 両方を `,` 連結。`in_scope=1` は NULL）を足す。
  `in_scope` は従来どおり 0/1。行は1件も消さない。
- 規則の判定は `origin_ja` の部分文字列（「国内由来」）。実測の揺れ（区切りが `、` と `・`）は部分一致で吸収し、
  `origin_ja` の値の集合（3種）をビルドで検査して、未知の値が増えたら止める。
- **`n_alien` に効かせる**: b06 が `occurrence.is_alien`（原表記の旗。F6 のとおり変えない）に加えて
  **`is_alien_in_scope`**（`is_alien=1` かつ binom が除外集合に無い）を持ち、b07 は `SUM(is_alien_in_scope)` を
  `n_alien` にする（列名・測度名は変えない）。binom は `build_taxon_assessment.binom_of()` を共有し、除外集合は
  registry の `taxon_assessment` から（`list_id='moe_ias_2015' AND in_scope=0` の `binom`）読む（b06 は registry を
  既に読んでいる）。occurrence と cube のスキーマ変更なので b06/b07 の `spec_version` を上げる。
- docs/PR 用の表: 上の実測表（10種）＋ `n_alien` 3,721→3,341、`in_scope=0` の moe 行数、
  `summary_species_catalog`・`summary_watershed_occurrence` の n_alien 合計の前後、スナップショットの差分を
  `serving:snapshot --mode diff` の出力として貼る。

### D2 accepted_taxon_id（GBIF API から収集し直す）

- 新スクリプト `scripts/c26_taxon_gbif_accepted.py`（c24 は触らない。User-Agent は `scripts/common.py` の `get_json`
  経由＝個人名を入れない）。入力 `taxon_crosswalk.csv`（読むだけ）。`taxon_key` が空でない行のうち status が
  ACCEPTED 以外（SYNONYM/DOUBTFUL）について `GET /v1/species/{key}` を引き、`acceptedKey` と受理名の canonicalName・
  status を取る。ACCEPTED 行は受理名＝自分自身として機械的に書く（API を引かない）。約 400 件×1.5秒≒10分。
  途中再開できるように既存の出力を読み込む（c24 と同じ増分方式）。
- 出力 **`data/processed/taxon_gbif_accepted.csv`**（新規。列: `taxon_id`〔taxa.taxon_id〕・`gbif_key`・`status`・
  `accepted_key`・`accepted_canonical_name`・`accepted_basis`〔`self`/`api`/`api_failed`〕・`fetched_at`）。
  `taxon_crosswalk.csv` は書き換えない。
- r01（`build_taxon.py`）が読む。`accepted_taxon_id` は、`accepted_key` が `common:taxon:gbif.<accepted_key>` として
  レジストリに**実在する**ときだけ埋める（新しい taxon 行は作らない）。実在しない／API 失敗は NULL のまま、
  数は `taxon_assessment`〔ビルドログ〕に出す。自分自身が受理名のとき NULL か自己参照かは実装時に決めず、
  **自己参照は入れず NULL**（「別 taxon の受理名」だけを意味する列にする）。
- r01 の `--check-fresh` の指紋に新 CSV を足す（`_hash_*` の入力。`--files-only` にも同様）。
- **CI サンプル**: `data/sample/processed/` は `coverage.yaml` の `wholesale_processed_files` を丸ごとコピーする方式
  （`taxon_crosswalk.csv`・`moe_ias_list.csv` と同じ）。新 CSV も同じ列に追加すれば足りる（約 2.7k 行、サイズ問題なし）。
  `s01_build_sample.py` で再生成して `manifest.json` の sha を更新する。
- 収集が実行できない場合は、理由を書いて項目2をやらない判断に倒す（現時点で到達可なので実行する）。

### D3 弱い一致 300 件

- c26 が弱い一致 300 行について `species/match?name=<canonical>&verbose=true` を再度引く。**自動採用は次の3条件をすべて
  満たすときだけ**: (a) 問い合わせ名の正規形（著者・年を除いた小文字の `c24.canonical()`）と GBIF の
  `canonicalName` が完全一致、(b) 返ったランクが SPECIES/SUBSPECIES/VARIETY/FORM、(c) `alternatives` に同じ正規形で
  ランクが種以下の別候補が無い（候補1つ）。採用した行は `taxon_gbif_accepted.csv` ではなく別列
  `weak_resolution`（`adopted`）で記録し、`build_taxon.py` の「EXACT のみ」規則を `adopted` 行も通すよう広げる。
- それ以外は unresolved のまま、理由区分を残す: `fuzzy_spelling`（綴り違い）・`infraspecific_collapsed`
  （亜種以下を種に丸めた）・`genus_or_higher`（属以上）・`ambiguous`（候補が複数）・`no_candidate`。
  区分は出力 CSV の `weak_reason` 列に持つ。
- 採用件数は収集後に実測して報告（見込み: ごく少数。0件でも「理由区分つきで unresolved」が成果）。
  採用が出た場合のみ taxon 行の ID が `ryuiki-taxa.*`→`gbif.*` に動くので、その件数と影響を表にする。

### D4 DwC-A の taxonID に名前空間を前置

- `x01_dwca.py` の taxonID を `f"{TAXON_KEY_SOURCE_NAMESPACE[sid]}:{taxon_key}"`（taxon_key が空なら空文字。
  未知の source_id は `assert_known_source_ids` で止める）にする。レジストリの `taxon_id` 形式
  （`common:taxon:gbif.8026`）ではなく `gbif:8026`／`inat:8026`（Issue 本文どおり。短く、GBIF 側が読みやすい）。
- `x03_verify_dwca.py` に検査を足す: 非空の taxonID は `^(gbif|inat):\d+$`、かつ `occurrenceID` の接頭辞
  （`<source_id>__`）と名前空間が対応すること。わざと壊すテスト（前置なし・名前空間の取り違え）で止まることを固定する。
- これは公開物の意図的な変更。ここでは書き出しのコードと検証だけを直し、`data/dwca` の再公開は行わない
  （公開の段取りと合わせる旨を PR に書く）。

### D5 grid01

ADR-0006 は追記済み。やることは `docs/plans/PHASE_B_INTAKE.md` の #11 を取り消し線＋解決済み（根拠: ADR-0006
コードリスト・ADR-0026 D3-6）にし、`registry/README.md` の逸脱の節の見出しを「逸脱」から「追加済み」に直すだけ。

### D6・D7 着手条件（実装しない）

- #6 `parent_taxon_id`: 着手条件 = 上位分類のツリーを要る消費者（分類群の階層で集計する画面・AIツール、または
  「科に属する種を全部」を引く API）が issue になったとき。ADR-0019 の末尾に追記。
- #7 評価の `taxon_id` 解決率（60.6%）: 着手条件 = `taxon_assessment.taxon_id` を結合キーに使う画面・クエリが出たとき
  （現状は `binom` 結合で足りており、消費者が無い）。その時点で規則を見直す。`PHASE_B_INTAKE.md` に追記。

## 3. 変更ファイル一覧（予定）

| 項目 | ファイル |
|---|---|
| D1 | `registry/taxon/assessment_scope_exclusions.yaml`、`scripts/registry/build_taxon_assessment.py`（規則の読み込み・`scope_reason`・検証）、`scripts/schema_registry.sql`・`web/src/db/schema-registry.ts`・`pnpm run db:generate`（`scope_reason` 列。`web/drizzle/migrations/` は生成）、`web/src/lib/table-meta.ts`（列の説明）、`scripts/b06_build_occurrence.py`・`scripts/b07_build_occurrence_cube.py`（`is_alien_in_scope`・`spec_version`）、`web/src/db/schema-cube.ts` は変更なし（列名維持）、`scripts/tests/test_registry_taxon_assessment.py`・b06/b07 のテスト、`reports/phase_b_taxon_assessment.md`・`docs/plans/PHASE_B_TAXON_ASSESSMENT.md`・`registry/README.md`・`docs/PIPELINE.md` |
| D2・D3 | 新規 `scripts/c26_taxon_gbif_accepted.py`、`data/processed/taxon_gbif_accepted.csv`（生成物・gitignore）、`scripts/registry/build_taxon.py`、`scripts/r01_build_registry.py`（指紋）、`data/sample/coverage.yaml`・`data/sample/processed/taxon_gbif_accepted.csv`・`manifest.json`（`s01` で再生成）、`scripts/tests/test_registry_taxon.py`、`registry/README.md`、`docs/adr/0019-taxon-registry.md` |
| D4 | `scripts/x01_dwca.py`、`scripts/x03_verify_dwca.py`、`scripts/taxon_namespaces.py`（docstring の「まだ経由していない」を更新）、テスト新設 |
| D5-D7 | `docs/plans/PHASE_B_INTAKE.md`（#8・#10・#11・#17 の解決済み化と #6/#7 の着手条件）、`docs/adr/0006-place-registry.md`（変更なし）、`docs/adr/0019-taxon-registry.md` |

パイプラインのパス（`scripts/registry/`・`b06`・`b07`）に触るので、PR 直前にメインが `b00` 全量ゲートを1回回して
`reports/serving_fingerprint.json` を更新する。

## 4. 検証方法

- 速い検証のみ（担当）: `scripts/tests/test_registry_taxon_assessment.py`・`test_registry_taxon.py`・b06/b07 の
  テスト・x01/x03 のテスト。規則の機械検証（27 binom・固定7種との整合・`origin_ja` 値集合）、「宣言の
  `domestic_origin` を壊すと止まる」「`origin_ja` に未知の値を足すと止まる」「`is_alien_in_scope` を `is_alien` に
  戻すと n_alien のテストが落ちる」を変異テストで固定。x03 は taxonID の名前空間なし・取り違えで落ちること。
- c26 は小件数（`--limit`）でスモーク実行し、ネットワーク失敗時に `api_failed` を残して続行することを確認。
  全量（約10分）の収集はメインの指示後に1回。
- 重い検証（メイン）: `b00` 全量ゲート、`serving:snapshot --mode diff`（before/after 表を PR に貼る）、CI の clone 再現。

## 5. スナップショットが動くか

- **動く**（D1）: `n_alien` を使うキューブ・`summary_species_catalog`・`summary_watershed_occurrence`、
  `iasSpecies` の行（in_scope が 7→28 binom）。`data/sample/serving_snapshot.json` はサンプルに該当種
  （Pseudorasbora parva 等・固定7種）の記録が入っている範囲で動く。`--mode diff` で確定し、更新自体を宣言とする。
  `reports/serving_fingerprint.json` も動く（b06/b07 の spec_version とパイプラインのパスの変更）。
- 動かない見込み: D2（`accepted_taxon_id` は配信クエリが読まない）・D4・D5。ただし D3 で自動採用が1件でも出ると
  taxon_id が動き、occurrence の `taxon_id` を経由して動く可能性がある（採用件数が確定してから判断。0件なら動かない）。
- 要確認: 現行の `n_alien` が固定7種を既に除いていない（351件含む）という実測は事実だが、v1 で `alien_n` が除外していたかは未確認（v1 は撤去済み。除外していたのは
  `ias_species` の宣言だけ、という経緯からの推測）。規則を `n_alien` にも効かせるのは挙動変更である。
