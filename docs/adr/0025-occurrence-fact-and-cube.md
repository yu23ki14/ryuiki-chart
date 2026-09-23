# ADR-0025: occurrence ファクトとキューブの設計（region は出典から・期間は12形の宣言・1ファクト＝1キューブ表）

- 状態: 提案中 / 日付: 2026-09-22
- 関連: ADR-0006（place）, ADR-0007（observation/occurrence の分離）, ADR-0008（時間の3点セット）,
  ADR-0011（キューブ）, ADR-0016（移行計画）, ADR-0019（taxon）, ADR-0021（キューブの鍵）,
  ADR-0022（place.region_id とスコープ）, ADR-0024（時刻帯・時刻ラベル）

## 背景

ADR-0007 決定3は「`observation` と `occurrence` は分ける」と決めていたが、`occurrence`
本体の設計（列・region の決め方・期間の展開）は未着手のまま残っていた
（`docs/plans/PHASE_B_OCCURRENCE.md` §9「再現の壁・申し送り」）。`organism_records`
（823,692行、この基盤最大のファクト）を実データで検証した結果、以下が判明した
（実測はすべて `docs/plans/PHASE_B_OCCURRENCE.md` に記録済み。以下は要点だけ再掲する）。

- `observed_on` は**12種類の文字数・並び**（形）を持つ（4桁の暦年〜35桁の区間まで）。
  一部（1,958行）は `'Z'`（UTC）終端で、GBIF 経由の iNat 観測がすべて該当する。
- `place`（grid01。県境という概念を持たない機械グリッド、ADR-0006/0022）経由では
  `region_id` を決められない——grid01 の `region_id` は常に `NULL`（ADR-0022 決定1）。
- taxon の分類属性（class/kingdom/phylum/order/family/taxon_group/canonical_binomial）は
  taxon レジストリ（ADR-0019、Slice 0 で実装済み）に既に taxon 単位で持っている。
  v1（`web/scripts/build-biota.mjs`）が記録ごとに行っていた COALESCE 補完は、
  taxon 単位に1回だけ適用すれば記録側で再計算する必要が無い（実測で確認: 816,856行中
  binom/kingdom/phylum/order/family は不一致0、class は同数タイブレークが1 taxon
  （*Sirosporium celtidis*）だけ食い違う）。

## 決定

### D1. occurrence は observation と別のファクト（ADR-0007 決定3の実装）

`scripts/b06_build_occurrence.py` が `organism_records` の全823,692行を
`data/db/v2.sqlite` の `occurrence` テーブルにする（`observation`/`observation_agg`
と同じファイルに、表ごとの所有で同居。`scripts/migrate/common.staged_table` で
作り直す）。

- **観測日の無い6,836行も落とさない**（ADR-0007 原則1）。`period_grain`/
  `period_start`/`period_end`/`period_raw` が `NULL` になるだけで、
  `taxon_id`/`place_id`/`region_id` は他の行と同じ規則で解決する。
- `taxon_id`: `scripts/taxon_namespaces.py` の名前空間（`gbif`/`inat`）から、
  `scripts/registry/common.py` の `taxon_id_gbif`/`taxon_id_inat`（taxon
  レジストリのビルドが実際に ID を発行するのと同じ関数）で候補を組み立て、
  `registry.taxon` に実在することを検証する。`taxon_key` の無い853行
  （うち観測日あり775行）は `NULL`。
- `place_id`: 座標のある行は grid01 に**必ず**解決する（`organism_records` は
  実測で座標を全行持つ）。**座標が無い行は `place_id`/`lat`/`lon` を NULL の
  まま保持する**（ADR-0007 原則1。落とさない）。**ADR-0006 規約4の改定
  （F4）**: 機械グリッドには常に解決し、
  `coordinate_uncertainty_m` を occurrence に運ぶ（使う側が精度で絞る。規約4の
  文字どおりの適用——精度不明なら解決しない——は地点等の細かい単位への解決と
  公開時の一般化〔ADR-0018〕に限る）。
- **`region_id` は出典から決める**（ADR-0022 決定3の最初の実装）。宣言は
  `scripts/migrate/source_regions.py`/`source_regions.yaml`（`sources:` に
  `source_id → region_id`/`expected_row_count`/`evidence`、`regions:` に
  `region_id → utc_offset`）。**`sources:` と `regions:` は意味が違う**——
  `sources:` は「occurrence の出典ごとの行数検証」という occurrence 固有の
  宣言だが、`regions:` の `utc_offset` は region そのものの属性（ADR-0024
  「時刻帯は地域の属性」）であり、将来 `observation` 側が同じ経路で
  region を解決するようになれば `regions:` はそちらからも読まれうる。
  未知の出典・使われない宣言・件数不一致は `scripts/b06_build_occurrence.py`
  を止める。`b03`（`observation`）の
  `place_source_ref(source_id='sites.site_id') → place.region_id` という既知の
  結合はそのまま残す（ADR-0022 決定3が明記したとおり、地点に紐づく観測だけを
  扱っているあいだは結果が一致するため。occurrence で先に地域決定の出典依存を
  実装したのは、`place` 経由では原理的に決められない〔grid01 の region_id は
  常に NULL〕ためで、`observation` 側を今すぐ揃える理由は無い）。
- **期間（ADR-0008/0024）は12形を宣言表で持つ**
  （`scripts/migrate/occurrence_period.py`・`occurrence_period_shapes.yaml`。
  形ごとに期待件数を宣言し、未知の形・件数不一致で止める）。展開規則:

  | 形 | 桁数 | period_grain | 展開 |
  |---|---:|---|---|
  | `YYYY` | 4 | `year` | 暦年（01-01〜12-31） |
  | `YYYY-MM` | 7 | `month` | 月初日〜月末日 |
  | `YYYY/YYYY` | 9 | `survey_period` | 開始年-01-01〜終了年-12-31 |
  | `YYYY-MM-DD` | 10 | `day` | そのまま |
  | `YYYY-MM/YYYY-MM` | 15 | `survey_period` | 開始月の月初日〜終了月の月末日 |
  | `YYYY-MM-DDTHH:MM` | 16 | `instant` | 秒を `:00` 補完。時刻帯なし＝すでにローカル時刻なので変換しない |
  | `…THH:MMZ` | 17 | `instant` | 秒を `:00` 補完 → 'Z' をローカル時刻に変換 |
  | `…THH:MM:SS` | 19 | `instant` | そのまま（ローカル時刻） |
  | `…THH:MM:SSZ` | 20 | `instant` | 'Z' をローカル時刻に変換 |
  | `YYYY-MM-DD/YYYY-MM-DD` | 21 | `survey_period` | 両端そのまま |
  | `…THH:MM:SS.sssZ` | 24 | `instant` | ミリ秒切り捨て → 'Z' をローカル時刻に変換 |
  | `…THH:MMZ/…THH:MMZ` | 35 | `survey_period` | 両端とも 'Z' をローカル時刻に変換 |

  **'Z' は「region の属性である utc_offset」で変換する**（`source_regions.yaml`
  の `regions:` から引く。`'+09:00'` を occurrence のビルドスクリプトに直書きしない
  ——ADR-0024 が「時刻帯は地域の属性」と決めた設計を、実際に結線する最初の実装）。
  変換は Python の `datetime` で行い、SQLite の日時関数は使わない（CLAUDE.md）。
  **機械検証**: 変換前後で年が変わったら `YearBoundaryCrossedError` で即座に止まる
  （D3の前提。実測では0件）。日・月が変わった件数はログに出すだけ（実測: 全'Z'
  1,958行中、日が変わる221・月が変わる10）。

### D2. occurrence のキューブは物理的に別の表 `occurrence_agg`（O-1b で実装）

ADR-0011 は入力を `observation` と `occurrence` の2つに決めているが、物理表を
1つに限ってはいない。**「1ファクト＝1キューブ表。鍵の規律（`staged_table`・
`COALESCE(c,'')` の `UNIQUE INDEX`・`built_from`/`spec_version`）は共通」**と
ここで明確化する。`observation` のキューブが `observation_agg` であるのと対称に、
`occurrence` のキューブは `occurrence_agg`（`scripts/b07_build_occurrence_cube.py`、
番号は本 ADR の時点で予約済み・未実装）になる。

- 鍵: `region_id, source_id, place_id, taxon_id, grain, period_start, period_end`。
  値: `n`・`n_red_list`（RL 原表記が空でない記録数）。`n_distinct_taxon` は
  taxon 粒度で非加法なので持たない。`taxon_id` が `NULL` のセルも持つ（データを
  落とさない）。
- **`grain ∈ {year, survey_period}`**（month は使う側が現れるまで後回し。
  ADR-0011 の `biota_by_mesh` も `periods: [year]`）。
  - `year` セル: 期間が1つの暦年に収まる記録（day/instant/month/year と、
    同年内に収まる区間）。
  - `survey_period`（leaf）セル: 年をまたぐ区間（実測1,191行）。
    `period_start`/`period_end` = 区間そのもの（セルの宣言する期間＝メンバーの
    期間なので、ADR-0024 決定3「メンバーの区間がセルの区間をはみ出す集計は
    キューブのセルにしない」を破らない）。
  - この2つの `grain` で、**観測日のある全記録がちょうど1つのセルに入る**
    （キューブ＝L2 の分割）。

### D3. v1 互換の射影（O-1a で `org_norm` を実装。年キー8表・species_month は O-1b）

`scripts/b08_project_occurrence_v1.py` が `occurrence`（L2）から `org_norm` を
作る。**ADR-0011 の `org_norm` の行き先は「L2 のファクト本体に統合」**であり、
射影元は L2（`occurrence`）であって、まだ実装していないキューブ（D2）ではない。

- `binom`/`rank_l`/`cls`/`kdm`/`phy`/`ord`/`family`/`taxon_group` は**taxon の
  属性**（`occurrence.taxon_id` → `registry.taxon` を素直に JOIN するだけで
  足りる。v1 の記録ごとの多数決 COALESCE は Slice 0 で taxon レジストリの
  ビルド時に taxon 単位へ移設済み——実データで検証: 816,856行中不一致は
  `cls` の1件のみ）。`taxon_group` は `COALESCE(taxon.taxon_group,
  registry/taxon/taxon_group.yaml の default_label_ja)`（taxon_id が NULL の
  775行はこの既定に落ちる。リテラルを射影スクリプトに書かない）。
  **`rank_l`**: 初回実装は「taxon の属性」に分類し損ねて `lower(記録の
  taxon_rank)`（F6 の原表記側）から計算していた（独立レビューで指摘）。
  `registry.taxon.rank`（build_taxon.py が組み立て時に小文字化して持つ）と
  `lower(記録の taxon_rank)` が816,856行全件で一致することを実測で確認した
  うえで、`t.rank`（taxon の属性）に修正した——本節の分類どおりになった。
- `scientific_name`/`vernacular_name`/`red_list_category`/`license_class`/
  `is_alien` は**記録の原表記**（occurrence の F6 列。NULLIF 等の正規化は
  しない）。
- `yr`/`mo` は **`period_raw`（原表記）から v1 の式をそのまま**適用する
  （`yr=CAST(substr(period_raw,1,4) AS INT)`、`mo` は `length(period_raw)>=7`
  のとき `CAST(substr(period_raw,6,2) AS INT)`）。`period_start`/`period_end`
  （展開結果）ではなく `period_raw` を使う——`'YYYY/YYYY'` 区間では v1 のこの式が
  「月」ではない値（実測: 18/19/20）を返すが、これは v1 の癖であり直さない
  （v1 の `org_norm` と1ビットも変えないための意図的な再現）。
  **`yr`/`mo`/`mlat`/`mlon` は INTEGER で入れる**（`scripts/b02_derived_compare.py`
  は `typeof()` で数値列を決めて比較するため）。
- **年キーの8表**（`org_group_year`/`effort_year`/`species2`/`species_year2`/
  `mesh_year`/`mesh_all`/`mesh_species`/`species_mesh_year`。O-1b）は
  **キューブ（D2）だけから**作る: v1 の「年」は
  `CAST(substr(period_start,1,4) AS INT)`（`year` セルも `survey_period`
  （leaf）セルも同じ式）。**「開始の年」という v1 の癖は、キューブに焼き込まれた
  値ではなく射影の式**である——`occurrence_agg` のセルは区間そのものを
  `period_start`/`period_end` に持ち（D2）、そこから「年」を取り出す式（＝v1 の
  年キー）は射影（O-1b）側の責務。
- **`species_month`**（O-1b）は `occurrence`（L2）から直接作る——v1 の `mo`
  （月の格）は `grain` の語彙（D2: `year`/`survey_period`）で表せない集計軸
  であり、`docs/plans/PHASE_B_FACT_SLICE.md` D10「climatology 相当の軸は
  キューブのセルにしない」の4例目（`sensor_hour_month` と同じ先例）。
- **宣言済み差分**（`scripts/reconcile/expected_diffs.yaml`）:
  *Sirosporium celtidis* の `org_norm.cls`（属単位の多数決が同数で、v1 の
  実装依存の暗黙順と taxon レジストリの決定論的タイブレークが食い違う。
  `docs/plans/PHASE_B_OCCURRENCE.md` §3「F2: 分類の補完」参照）1キーのみ。
  `species2` 側の同じ由来の宣言は O-1b で追加する。

### D4. 縦線の切り方

- **O-1a = `occurrence`（L2）＋ `org_norm`**（816,856行の行単位ゲート。
  taxon/place/period/region/原表記の旗を全部ここで確定する）＋ 本 ADR。
- **O-1b = `occurrence_agg` ＋ 年キー8表 ＋ `species_month`（L2）**
  （キューブのゲート。別 PR）。

## 影響

- **良い**: `observation` と対称な設計（`staged_table`・宣言表による機械検証・
  L2→キューブ→v1射影という3層）を `occurrence` にも適用できた。region の決め方が
  出典に一本化され、grid01 のような「県境という概念を持たない」space も
  破綻なく扱える。'Z' の変換が region の属性として結線され、`'+09:00'` の
  直書きが1箇所（`source_regions.yaml`）に閉じた。
- **コスト**: `occurrence` の列は observation（ADR-0007）の列挙とは一致しない
  独自の形になった（`quality_stage`/`is_synthetic`/`source_ref`/`event_id` は
  持たない——organism_records 側にこれらを使う v1 派生テーブルが無いため）。
  将来これらの列を使う消費者が現れたら改めて設計する。
- **リスク**: D2（`occurrence_agg`）・D3 の年キー8表・`species_month` は本 ADR の
  時点ではまだ実装が無い（O-1b）。`b07_build_occurrence_cube.py` という番号だけを
  予約してある。

## 検討した代替案

- **`observation.region_id` の決め方（place 経由）を occurrence にも流用する**:
  grid01 の `region_id` は ADR-0022 決定1により常に `NULL`（`common:` スコープ）
  なので、この経路では原理的に地域が決まらない。却下（ADR-0022 決定3がこの
  却下を先に明記済み）。
- **`'Z'` の変換を `'+09:00'` 固定でハードコードする**: 対象地域が神奈川県だけの
  現状では動くが、ADR-0024 が「時刻帯は地域の属性」と決めた設計に反し、
  他地域を足したときに `occurrence_period.py` の書き換えが要る。却下。
- **v1 の記録ごとの分類補完を occurrence 側で再実装する**: taxon レジストリ
  （Slice 0）が既に taxon 単位で計算済みの値を、記録単位でもう一度計算し直す
  ことになり、2つの実装が食い違う余地を生む。taxon への単純な JOIN で
  実データが再現できることを確認済みなので却下。
