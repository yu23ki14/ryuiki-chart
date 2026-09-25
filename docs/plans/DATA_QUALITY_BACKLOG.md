# データ品質バックログ（収集とデータ品質、Issue #38・親 #27）

対象は Phase B（ADR-0016）の対象外と明記されていた、収集・データ品質の8項目。

**このドキュメントは調査と記録が主で、原本と値は動かさない。** 実装が要る項目も、方針と
着手条件をここに書くだけで留める（理由: 値を動かす変更は「再現してから変える」原則により、
突合ゲートの継続実行（#29）が入ってから、差分を数えながら入れる）。原則:

- 推測で埋めない。黙って直さない。
- 一次資料が無いものは空のままにして、空である理由を書く。
- 宣言済み差分 > データを曲げる。差分は列挙して機械検証する。

1項目1節。各節に現状の実測・根拠（ファイル:行、SQL と結果）・判断・着手条件を書く。

すべての実測は `ryuiki.sqlite`/`cells.sqlite` を `file:...?mode=ro` の読み取り専用で開いて行った。
調査は全体を通じて原本を読み取り専用でのみ開き、作業前後で sha256・mtime が一致した
（変更なし。ハッシュ値そのものは本PRの本文に記載する）。

---

## 1. 地盤沈下（`kanagawa_jiban_chinka`）の年次 n=2 グループ 1,625件

### 実測

`measurements`（`ryuiki.sqlite`、`m05_tier1.py` が書く。原本は読み取り専用で開いた）を
`source_id='kanagawa_jiban_chinka'` で見ると、全3,286行・`measured_on` は 1973〜2024。

```sql
select site_id, variable, measured_on, count(*) n
from measurements
where source_id='kanagawa_jiban_chinka'
group by site_id, variable, measured_on
```

`(site_id, variable, measured_on)` でグルーピングした結果、グループサイズの分布は
**n=1: 36件 / n=2: 1,625件 / n=3以上: 0件**（36×1 + 1,625×2 = 3,286 と一致）。

n=2 の1,625グループ全件を実際に突き合わせた結果（例外なし）:

- **全1,625組で `value` が完全一致**（`min=max`）。
- **全1,625組で `value_raw` も完全一致**（文字列レベルで同一）。
- **全1,625組で、2件のうち片方が `source_ref` に `r5table.xlsx`、もう片方が
  `r6table.xlsx` を含む**（`(r5table.xlsx, r6table.xlsx)` 以外の組み合わせは0件。
  同一ファイル内での重複も0件）。
- 内訳（variable別、n=2グループ数）: `地下水位(年平均)` 1,270 / `有効水準点数` 51 /
  `沈下水準点数(1cm以上2cm未満)` 51 / `沈下水準点数(2cm以上)` 51 / `調査面積` 51 /
  `沈下面積(1cm以上2cm未満)` 50 / `沈下面積(2cm以上)` 50 / `最大沈下量(基準点)` 51。

n=1 の36グループは**全件 `measured_on='2024'`**で、**全件 `source_ref` が `r6table.xlsx`
のみ**（`r5table.xlsx` 側にまだ存在しない、令和6年度報告書で新規に追加された最新年度の行）。

これは `docs/plans/PHASE_B_FACT_SLICE.md:330-336` の実測（`site_id='kanagawa_jiban_chinka__1'`・
`measured_on='1980'` の1例）を全数で裏付ける結果であり、**「同じ年の値が、異なる年度の
報告書（過去分の再掲）から重複して収集されている」という仮説を実証できた**。値が食い違う
ペア・3件以上のグループ・r5/r6以外の組み合わせは1件も無く、例外は無い。

収集スクリプト `scripts/c84_jiban_chinka.py:20-26` 自身がこの重複を予期して設計されている
——r5/r6を両方処理し、重複除去は「ローダー側の仕事」という方針で意図的にしないと明記
している（要旨。原文は同ファイル参照）。

続く「L2化」の `scripts/m05_tier1.py:295-336`（`load_measurements_csv`、厚木市・横浜市など
複数ソースが共有する汎用ローダー）も重複排除をしない。`measurement_id` は
`f"{source_id}__{i:06d}"`（CSV内の行連番）で作られる（`m05_tier1.py:327`）ため、r5由来行と
r6由来行は別々の `measurement_id` を持ち、`INSERT OR REPLACE` で衝突せず両方とも残る。

### 判断

**根本は「同じ出典に複数の版（報告年度）が同居する」問題そのものであり、これは
ADR-0005（`source`/`source_edition`＋`superseded_by`、Phase C）が扱う領域。本筋は
Phase C で解く。** 同型の実例は他に2つある: 土地利用 L03-b（2006年版/2016年版、
`docs/plans/PHASE_B_LANDUSE.md`。ADR-0005 の2026-09-24追記が最初の実例として記録済み）と、
GBIF の再取得（本書§2。ADR-0005 自身の「背景」節が `gbif_kanagawa`→`gbif_kanagawa_occurrences`
の例で既に挙げている）。地盤沈下の r5/r6 重複は3件目の実例であり、Phase C で
`source_edition.superseded_by` により「新しい版が古い版を置き換える」ことを構造的に
表現すれば、この種の問題全てが同じ仕組みで解ける（ADR-0005 本体に追記済み。後述）。

以下は候補の比較（収集 c8*／L2化 m0x／b03 の宣言的除外／Phase C）と、Phase C 以前に
手を付ける場合の実装形の検討:

- **収集（`c84_jiban_chinka.py`）で除外しない。** 重複排除をしないことは、このスクリプト
  自身が明言している設計判断（「重複判定・優先順位付けはローダー側の仕事」）。この方針を
  ひっくり返すのはコレクタの責務の再定義であり、影響範囲も大きい（`ryuiki.sqlite` の
  `measurements` を直接変えるため、v1（`web/scripts/build-derived.mjs`）を含む**全ての
  下流消費者**の集計値が無条件に動く。Phase B の「まず v1 を再現できることを確認する」
  という受け入れ基準と衝突し、影響を宣言済み差分として区切れない）。
- **L2化（`m05_tier1.py` の `load_measurements_csv`）で除外しない。** このローダーは
  厚木市水質・横浜市水位など**他の複数ソースが共有する汎用コード**。地盤沈下1ソースだけの
  重複判定ロジックを汎用ローダーに埋め込むと、単一責任が崩れるうえ、他ソースへの
  意図しない副作用のリスクを持つ。また、ここで除外すると上記と同じく `measurements`
  自体が変わり、v1 の再現に影響する。
- **Phase C より前に暫定でやる場合の除外の形**: `(site_id, variable, measured_on)` を
  1,625件並べるのではなく、`scripts/migrate/period_exceptions.yaml`（仕組みは
  `docs/adr/0021-observation-grain-and-cube-key.md` 参照。`source_id` ごとに1ルール＋
  `expected_row_count` を実測件数と突き合わせる）や
  `registry/taxon/assessment_scope_exclusions.yaml`（仕組みは
  `docs/plans/PHASE_B_TAXON_ASSESSMENT.md:76-83` 参照）と同型の
  **`source_id` 単位の1ルール**にする: 「`kanagawa_jiban_chinka` は自然キー
  `(site_id, variable, measured_on)` が衝突したら `source_ref` のファイル名が新しい方
  （`r6table.xlsx`）を残す」＋件数検証（現在1,625件、食い違えば `MigrationError` で
  止める）。`(well_id, variable_ja, fiscal_year)` は
  `data/processed/kanagawa_jiban_chinka.csv`（`c84_jiban_chinka.py:375` の `fields`）の
  列名で、b03 が読む `measurements` には存在しない（`m05_tier1.py` を経た後は
  `site_id`/`variable`/`measured_on`）。

- **この暫定策には規模の問題がある。** 1,625組は全て `value`/`value_raw` が完全一致する
  ペアなので、r5側の1行を除外しても r6側の1行は残り、**`meas_year` 等の行そのものは
  消えない**（`row_only_in_baseline` ではない）。動くのは「重複していた分の件数（n）」
  だけで、`avg`/`min`/`max` は変わらない。`web/scripts/build-derived.mjs` と
  `scripts/b05_project_v1.py` の実際の式を読み、v1派生33表への影響を実測した
  （判断材料として残す）:

  | v1テーブル | 影響列 | 影響行数 | 根拠 |
  |---|---|---:|---|
  | `meas_year`（`build-derived.mjs:72-77` の annual 分岐／`b05` の `_MEAS_YEAR_SQL`、`b05_project_v1.py:293-300`） | `n`（`COUNT(*)`、`build-derived.mjs:73`）のみ | **1,625行**（`kind='annual'` の重複年グループ全て） | `avg`/`min`/`max`（同じく73行目）は value 完全一致のため不変。`n_censored`（74行目）も対象1,625組の `value_raw` に `LIKE '<%'` が0件（実測）のため不変 |
  | `site_var`（`build-derived.mjs:143-149`／`b05` の `_SITE_VAR_SQL`、`b05_project_v1.py:323-328`。`meas_year` から `SUM(n)`） | `n`（`build-derived.mjs:145`）のみ | **82行**（影響を受ける `(site_id, variable, kind='annual')` の組。1,625件の年グループがこの82行に配分される。実測: `site_id,variable` の distinct 組数） | `avg`（146行目、`AVG(y.avg)`=年ごとの平均の単純平均）は各年の avg 自体が不変なので不変 |
  | `var_catalog`（`build-derived.mjs:127-138`／`b05` の `_VAR_CATALOG_SQL`、`b05_project_v1.py:310-319`。`meas_year` から `SUM(n)`） | `n`（132行目）・`n_annual`（136行目） | **8行**（影響を受ける8変数全て。実測: `地下水位(年平均)`等8変数はいずれも `source_id='kanagawa_jiban_chinka'` からしか出現しない＝他ソースと混ざらない） | `n_sites`（133行目）/`y_from`/`y_to`（134行目）/`n_daily`（135行目）/`n_censored`（137行目）は不変（対象 site_id は行ごと消えず、年の範囲も変わらず、daily側は無関係、below_lod行は0件） |
  | `meas_daily`/`meas_month`/`meas_clim` | 影響なし | 0 | `kanagawa_jiban_chinka` の `measured_on` は全行 `LENGTH=4`（年度番号）で、`LENGTH(measured_on)=10` を要求する `meas_daily`（`build-derived.mjs:47-61`、条件は57行目）に入らない。`meas_month`/`meas_clim` は `meas_daily` から作るため連動して無関係 |
  | `zone_year`/`zone_clim` | 影響なし | 0 | `kanagawa_jiban_chinka` の site_id は `sites` テーブルに1件も存在しない（実測: `select count(*) from sites where site_id like 'kanagawa_jiban_chinka%'` → 0件）。`zone_year`/`zone_clim` は `meas_year`/`meas_month` を `sites` と `JOIN` するため、この JOIN で最初から除外される |
  | `sensor_daily`/`rain_daily`/`sensor_hour_month`/`landuse_watershed`/`landuse_change` | 影響なし | 0 | `measurements` ではなく `sensor_timeseries`／土地利用CSV由来で無関係 |

  `b05_project_v1.py` の `_SITE_VAR_SQL`/`_VAR_CATALOG_SQL`（310-328行）は
  `build-derived.mjs` の `var_catalog`/`site_var` と SQL が実質一致するため、v1
  （`derived.sqlite`）と v2射影（`v1_projection.sqlite`）のどちらでも同じ影響になる。

  b03 だけを直した場合、v1（`derived.sqlite`）は重複を含んだまま・v2は含まないまま
  になるため、`scripts/reconcile/expected_diffs.yaml` に `value_diff`（`row_only_in_baseline`
  ではない。`columns: [n]` 等）を `meas_year` 1,625キー・`site_var` 82キー・
  `var_catalog` 8キー、**計1,715キー**宣言する必要が生じる。だが
  `docs/plans/PHASE_B_RECONCILIATION.md`「危うさ」節は、既存の宣言済み差分が
  現状「6テーブルで18キー（1つの原因）」の規模であることを踏まえ、「この件数が増え続ける
  ようなら、免除ではなく v1/v2 双方の是正を優先すべき兆候として扱う」と明記している。
  1,715キーは18キーの約95倍であり、この基準に照らして**宣言では対応しない**。

  **推奨: b03 だけでなく `build-derived.mjs` にも同じ `source_id` 単位のルールを入れ、
  `derived.sqlite` を作り直してゲートの差分をゼロに保つ。** 比較した代替案:
  - **（推奨）v1（`build-derived.mjs`）にも同じルールを入れる**: 現在の本番は
    `derived.sqlite`（v1パイプライン）をそのまま D1 に流している（#28 未着手のため）。
    v2側だけ直しても本番の重複カウントは直らない。両方に同じルールを入れれば
    本番のバグも直り、ゲートは宣言なしでゼロ差分のまま保てる。コストは v1側
    （まもなく廃止予定のコード）に手を入れることだが、`meas_year`/`site_var`/
    `var_catalog` の該当 `FROM r.measurements` に同じ重複排除の CTE を足すだけの
    小さな変更で足りる。
  - **（見送り）v1 の廃止（#41）後に入れる**: v1 に触れずに済むが、#41 は #28（本番の
    v2 接続）に依存しており、本番の重複カウントが直るまでの期間が長い（#29→#28→#41
    の順）。**Phase C（本筋）が先に来る可能性もあり、その場合はこの暫定策自体が
    不要になる**ため、v1 側を直す投資すら不要になりうる。
  - 選定理由: 本番影響（重複カウントされたままの `n`/`地下水位` 等の件数表示）を
    早く止めたいなら前者、Phase C を待てるなら後者もしくは何もしない、という
    トレードオフ。今回は**「本筋は Phase C」を最優先の推奨とし、それより前に何かを
    急ぐ理由（本番影響の大きさ）が無ければ、暫定策そのものを実施しない**ことを
    合わせて推奨する（`kanagawa_jiban_chinka` は地点あたりの件数表示に影響するのみで、
    集計値・平均値は変わらないため、緊急性は低いと判断）。

### 着手条件

**Phase C（ADR-0005 の `source_edition`＋`superseded_by` の実装）。** それより前に
暫定策（v1/v2 双方への `source_id` 単位ルールの追加）を急ぐ必要が生じた場合のみ、
#29（33表突合ゲートの継続実行）が入った後、ゲート差分がゼロのままであることを
確認しながら実施する。**このIssueでは実装しない。**

---

## 2. GBIF の未取得1,039件

### 実測

`data/logs/gbif_partition_report.csv`（1,119データ行、`scripts/c02_gbif_repair.py:286-309`
が書く。全区画完了後に一度だけ書き出される「最終確定版」）を読んだ。

```
note列の分布:
  ''（空、フルマッチ）                                                        1,109行  diff合計 0
  '時間予算超過のため未着手(取れなかった)'                                          4行  diff合計 93
  '検索APIに『フィールド欠損』を問い合わせる手段がなく分離取得不可(...)'              6行  diff合計 958
sum(expect) - sum(got) = 898,776 - 897,725 = 1,051  (= 93 + 958、負のdiffは無し)
```

内訳は issue の記述（区画不明93・日付欠損958）と一致する。区画不明93件は
`scripts/c02_gbif_repair.py` の `TIME_BUDGET_SEC`（65分）超過で未着手のまま残った4区画
（`gbif_repair_run3.log` 末尾で `TIME BUDGET SKIP` として実際に確認できる）。日付欠損958件は
`scripts/c02_gbif.py:106-142`（`build_dataset_leaves`/`add_gap`）が、year→month→day で
区画分割するときに facet 集計の合計が親区画の総数に届かない差分として記録したもの
（`c02_gbif.py:24-30` のdocstringが理由を説明: 「year/month/day は解釈済みフィールドで
欠損があり得る…検索APIには『フィールドが無い』ことを直接問い合わせる方法が無く」）。

**気付いた不整合（記録のみ、原因追及はこのタスクのスコープ外）**: `gbif_repair_run3.log`
末尾に

```
[repair] final jsonl lines=658360  GBIF top-level count=659399  diff=1039
[repair] 内訳: 区画取得不能による欠落=93件, 日付フィールド欠損による分割不能ぶん=958件
```

とあり、スクリプト自身が「diff=1039」と「内訳93+958」を並べて書いているが、
**93+958=1,051 であり 1,039 とは一致しない（12件の差）**。`scripts/m99_validate.py:163-164`
（およびこのIssue本文）の「1,039件（93+958）」という記述は、このログの矛盾をそのまま
引き継いだもの。`data/logs/gbif_partition_report.csv` 自体の実測（上記）は一貫して
1,051件（93+958）を示しており、1,039 という数字は「jsonl行数(658,360) と GBIF側の
region全体カウント(659,399) の差」という**別の集計方法**から来ている。この2つの数え方が
12件だけ食い違う理由は、今回のログ・コードからは特定できなかった（facetLimit
による打ち切り深さ違いなどが疑われるが未確認）。**記録として残すのみで、実装・再収集は
しない。**

GBIF API で日付なし記録を別条件で取れるかの調査（WebSearch、2026-09-25）: GBIF の
**ダウンロードAPI**（`occurrence/download`、predicate方式）は `{"type": "isNull",
"parameter": "YEAR"}` のような「フィールドが無い」ことを直接問い合わせる述語
（`IsNullPredicate`）をサポートしている
（[GBIF API Reference](https://techdocs.gbif.org/en/openapi/)、
[gbif/occurrence#585](https://github.com/gbif/occurrence/issues/585)）。したがって
技術的には `datasetKey=X AND YEAR IS NULL` のような条件で958件の一部を分離取得できる
可能性がある。ただしこのAPIは無料とはいえ**登録アカウントと非同期ジョブ待ちが必要**で、
`scripts/c02_gbif.py:26-27`・`scripts/c02_gbif_repair.py` のdocstringが明記するとおり
このプロジェクトはこれまで意図的に使っていない。

**再取得が旧登録を上書きする実例（ADR-0005 の問題そのもの）**: `scripts/common.py:72-76`
の `register()` は `source_registry`（`source_id` が主キー、
`web/drizzle/migrations/0000_init.sql:565-578` で確認）へ `INSERT OR REPLACE` するだけで、
版の概念が無い。実際に `c02_gbif.py`（初回取得）と `c02_gbif_repair.py`（429対策の再取得）
は両方とも `source_id="gbif_kanagawa_occurrences"` で `register()` を呼んでおり
（`c02_gbif.py:391`・`c02_gbif_repair.py:404`）、`ryuiki.sqlite` を実測すると
`source_registry` にはこの `source_id` の行が1件（`fetched_at='2026-08-29T18:46:34'`、
`access_method` に「429対策で再取得済み」の文言、`record_count=658360`）しか無く、
初回取得時の `access_method`/`record_count`/`fetched_at` は**復元不能な形で消えている**。
ADR-0005 が挙げる「同一出典の再取得が旧行を上書きするか、別IDの行として増えるかが
一貫しない」「数値の再現ができない」という問題の実例そのもの。

### 判断

**現時点では再収集しない。** 理由:

- 958件（日付欠損）はダウンロードAPI（アカウント登録・非同期ジョブという新しい依存）が
  要る一方、対象は取得済み658,360件の0.15%程度に留まり、費用対効果が低い。加えて
  「日付が無い」という性質上、このプロジェクトの主要な使い方（年次・月次集計）には
  そもそも使いにくいレコード群である可能性が高い。
- 93件（区画取得不能）は技術的には `c02_gbif_repair.py` の再実行（時間予算を延ばすだけ）
  で解決できる可能性が高いが、0.014%と極小で、単独タスクとして起票するほどではない。
  将来 GBIF まわりを触る別の理由（例: ダウンロードAPI導入）が生じた際に、ついでに
  拾えば十分。
- 上記の「1,039 vs 1,051」の不整合も、値そのものより「内訳の記録が正確かどうか」の
  問題であり、実害（データの欠落量）を変えるものではない。

### 着手条件

なし（この判断で一旦クローズしてよい）。将来ダウンロードAPIを別目的で導入する場合に
958件の再取得を検討する。

---

## 3. 緯度経度が無くて `sites` に登録できない地点（そらまめ君・相模原市大気局）

### 実測・調査（WebSearch/WebFetch、2026-09-25）

既存の記録（`scripts/m99_validate.py:169-175`）は「そらまめ君の公開CSVに緯度経度は
含まれない」という収集エージェントのコード上のコメントのみを根拠にしている。今回、
独立した一次資料・第三者資料で裏付けを試みた:

- そらまめ君公式サイト（`https://soramame.env.go.jp/`、`https://soramame.env.go.jp/apiManual`
  等）はJavaScriptで描画するSPAで、WebFetch（静的HTML取得）ではAPI仕様の本文が
  読めなかった。
- 代わりに、そらまめ君の公開データ形式を独自に解析した第三者パーサー
  [`c9s/soramame`](https://github.com/c9s/soramame)（PHP、GitHub）を確認した。
  README記載の `fetchCountyStations()`（測定局一覧を取得するAPI）が返すフィールドは
  `code`/`name`/`address`/`attributes` のみで、**緯度経度フィールドは無い**。これは
  既存コメントの内容と独立に一致する状況証拠になる（ただし政府の一次資料そのものではない）。
- 相模原市公式ページ（「大気の状況」
  `https://www.city.sagamihara.kanagawa.jp/kurashi/1026489/kankyo/1026503/jyokyo/1008122/index.html`、
  年次報告書「さがみはらの環境」令和5年度版PDF）を確認したが、測定局（市役所・相模台・
  橋本・田名・津久井・古淵・上溝）の緯度経度・住所一覧は見つからなかった
  （PDFは `pdftotext` でテキスト化して "緯度"/"経度"/"測定局" を検索したが該当なし）。
- 神奈川県の大気汚染常時監視ページ群（`pref.kanagawa.jp/sys/taikikanshi/...`）も
  トップページ・検索結果からは座標一覧を確認できなかった。

### 判断

**一次資料で座標を確認できなかった。空のままにする。** 探した場所: そらまめ君公式サイト
（トップ・apiManual）、そらまめ君の第三者パーサー（GitHub c9s/soramame）、相模原市
「大気の状況」ページ、相模原市年次報告書「さがみはらの環境」令和5年度版PDF、神奈川県
大気汚染常時監視ページ。設計（`sites` に緯度経度が判明すれば
追加登録できる構造、`m99_validate.py:175`）は変更不要。

### 着手条件

一次資料（環境省または相模原市の公式な測定局台帳）で緯度経度が判明した時点。

---

## 4. 相模原市の大気データの単位が不明

### 実測・調査（WebSearch/WebFetch、2026-09-25）

`scripts/m02_measurements.py:12`「相模原市大気データは unit=NULL のまま」、
`scripts/m99_validate.py:177`「公開元に単位の記載が無いため `unit=NULL` のまま。
推測していない。」という既存の扱いに対し、追加の一次資料を探した。

- 相模原市「大気の状況」ページ: 測定局数（7局、一般環境大気5・自動車排出ガス2）は
  書かれているが、測定値そのものの単位表記は無い。
- 相模原市 環境基本計画年次報告書「さがみはらの環境」令和5年度版PDF
  （`https://www.ecopark-sagamihara.com/c7abd7d95caf9f639007c76cd47e2aa0.pdf`、
  `pdftotext -layout` でテキスト化し `ppm`/`μg`/`µg`/`mg/m`/`単位` を検索）:
  この報告書は「環境基準の達成率（%）」のような指標中心の記載で、汚染物質の**生の
  測定値と単位を並記した表が無い**（達成・非達成の判定結果のみ）。
- 環境省・相模原市とも、市の生データ自体は「神奈川県ホームページの『項目別日報』」
  経由で公開されているとの案内があった（相模原市ページの記載）が、その日報ページ
  自体（実際の数値表）までは今回のスコープでは到達・確認していない（次に確認すべき
  候補として記録）。

### 判断

**今回追加で確認できる一次資料は見つからなかった。`unit=NULL` のまま空欄を維持する
（推測しない）。** 次に確認する価値がある未踏の資料: 神奈川県の「項目別日報」ページ
（相模原市分の生値が実際に載っている可能性がある。今回は時間の制約で実データ表までは
未確認）。

### 着手条件

「項目別日報」等、相模原市の生データを直接掲載する一次資料に単位表記が見つかった時点。

---

## 5. 統計量が埋められない項目

### 5a. 全シアン（`cn`）の統計量

`docs/plans/PHASE_B_INTAKE.md:108-116` の記述どおり、環境基準の評価方法（全シアンだけ
年間最高値、他26項目は年間平均値）は国立環境研究所の一次資料（`kan_w.html`）で確定して
いるが、`zip_create` API のCSV1列がどちらの統計量を実際に格納しているかを記載した資料は
見つかっていない。今回 `water-pub.env.go.jp`（水環境総合情報サイト）を再確認したが、
文字コードの問題でページ内容を読めず（Shift_JIS想定、WebFetchの変換に失敗）、`zip_create`
APIの列レイアウト説明書には到達できなかった。**新しい一次資料は見つからなかった。stat は
空のまま維持する。**（検索日: 2026-09-25）

### 5b. 大腸菌数（素の値）の統計量

`docs/plans/PHASE_B_ALIAS_STAT_SOURCES.md:206-211`（§2.6）のとおり、90%値の定義は
確定しているが「素の値」列が何かは未確認。今回追加で「大腸菌群数→大腸菌数」への
環境基準改正の経緯資料（環境省 令和3年3月報告書、`env.go.jp/press/files/jp/115868.pdf`）を
確認したが、90%値の定義の再確認に留まり、「素の値」列の定義に触れた記載は見つからな
かった。**新しい一次資料は見つからなかった。stat は空のまま維持する。**（検索日:
2026-09-25）

### 5c. 底層溶存酸素量の統計量 — 新しい一次資料を発見（未反映）

`docs/plans/PHASE_B_ALIAS_STAT_SOURCES.md:206-211` は「Web検索では言及があったが
環境省の一次資料から原文を直接確認できなかった」としていたが、今回、環境省
中央環境審議会 水環境部会 生活環境項目環境基準専門委員会（第8回、開催日
平成28年9月9日）の配付資料「参考資料２ 資料５ 底層溶存酸素量及び沿岸透明度の
評価方法等について」の写し
（[長野県が公開しているPDF](https://www.pref.nagano.lg.jp/mizutaiki/kurashi/shizen/suishitsu/7kisuwakokeikaku/documents/09-02_ruikeisitei.pdf)、
20-27行目付近）で原文を確認できた:

> 底層溶存酸素量の年間における評価について、連続測定を実施する場合は、目標値を
> 下回る観測結果（日間平均値）が2日以上続いた場合は「非達成」、そうでない場合は
> 「達成」と評価する。連続測定を実施しない場合は日間平均値の年間最低値により評価する。
>
> （中略）このため、底層溶存酸素量の年間における評価は、保全対象種の保全に対して
> 安全側の評価となるように、日間平均値の年間最低値とすることが適当と考えられる。

環境省自身のcouncilページ（`https://www.env.go.jp/council/09water/y0916-08a.html`、
同委員会の議事録）を確認したが、この資料5への直接リンクは確認できず、`env.go.jp`
ドメイン上の原本URLへは到達できていない（長野県のミラーコピーのみ確認）。

**留保**: `docs/plans/PHASE_B_ALIAS_STAT_SOURCES.md` §2.3（水生生物保全項目）と同じ理由
（環境基準の「評価方法」の確定であって、`zip_create` API の実CSV列が同一のものを
格納していると直接記載した資料ではない）。「高確度の一致」候補として記録するに留め、
レジストリへの反映（`stat='min'` の記入）は今回は行わない。

### 判断

5a・5b は探索したが一次資料が見つからず、空のまま維持が正しい。5c は将来の
`variable_alias` 更新（別タスク）で `stat='min'` を検討する材料として、上記URL・引用を
記録した。

### 着手条件

5a・5b: 追加の一次資料（`zip_create` APIの列レイアウト説明書、または大腸菌数「素の値」の
定義資料）が見つかった時点。5c: レジストリ（`variable_alias.csv`）を次に触るタスクで、
この記録を根拠に `stat='min'`（高確度の一致、水生生物保全項目と同水準の留保付き）を
検討する。

---

## 6. 検体値の調査区分の区別情報が原本に無い

### 実測

背景（一次資料での確認済み事項）は `docs/plans/PHASE_B_INTAKE.md:99-106` と
`docs/plans/PHASE_B_ALIAS_STAT_SOURCES.md` §3.2（232-249行）参照——検体値ファイルは
仕様上、調査区分コード5/6（水質自動モニターの日間平均値）が通常の点観測と同じレコード
形式で混在しうるが、実際に収集した生CSV列には調査区分コードに相当する列が存在しない、
という既存の結論。

今回追加で `water-pub.env.go.jp`（水環境総合情報サイト、`zip_create` APIの配布元）を
再確認したが、文字コードの問題（Shift_JIS想定）でページ本文が読めず、調査区分列の
有無を更新する資料には到達できなかった（検索日: 2026-09-25）。

### 判断

**新しい一次資料は見つからなかった。既存の結論（原本に区別情報が無い）を維持する。**
収集を直しても解決しない可能性が高いという既存の記述（`PHASE_B_INTAKE.md:106`）は
そのまま。

### 着手条件

`zip_create` APIが調査区分コード列を含む新しい配布形式に変わった時点（可能性は低い）。

---

## 7. 文字列の観測が落ちている件（天気概況・風向など4系列・各971行）

### 実測

`sensor_timeseries`（`source_id='jma_daily_yokohama'`）で該当4系列を確認した。

```sql
select datastream, count(*), sum(case when result is null then 1 else 0 end)
from sensor_timeseries
where source_id='jma_daily_yokohama'
  and datastream in (
    '天気概況_昼 (06:00-18:00)', '天気概況_夜 (18:00-翌日06:00)',
    '風向・風速_最大風速_風向', '風向・風速_最大瞬間風速_風向')
group by datastream
```

結果: 4系列とも **971行・全行 `result IS NULL`**（`docs/plans/PHASE_B_FACT_SLICE.md:409-413`
の実測と一致）。

**上流の特定（2段階）**:

1. **`scripts/c10_jma.py:161-180`（`parse_cell`）** — セルの値が数値としてパースできない
   場合（天気概況の「晴後曇」、風向の「北」など）、`to_number(body)` が失敗し
   `return None, s, flag, 0` を返す（180行目）。つまり **収集の時点で `value=None` に
   なり、元の文字列は `value_raw` にしか残らない**。`melt_table()`（182-219行目）は
   これを認識してはいるが、202-203行目で `pass  # 風向・天気概況などの文字列値` と
   何もせず、`"value": v`（None）・`"value_raw": vraw`（文字列）のまま `data/processed/
   jma_daily_yokohama.jsonl` に書き出す。
2. **`scripts/m02_measurements.py:38-67`（`load_sensor_timeseries`）** — jsonlを
   `sensor_timeseries` に流し込むこの関数の48行目 `r.get("value")` が、`result` カラム
   （スキーマは `REAL`、文字列を持つ姉妹カラムは無い）に入れる値。**`r.get("value_raw")`
   はここで一切読まれず、jsonlの中には残っている文字列がアプリDB到達時点で完全に
   失われる。** これが `sensor_timeseries.result IS NULL` として観測される最終形。

つまり「文字列が消える」は2段階で起きている: c10で `value` が失われ（`value_raw`には
残る）、m02で `value_raw` を伝播する経路が無いため最終的に消える。`sensor_timeseries`
のスキーマ自体に文字列用のカラムが無いことが、m02側で直せない構造的な理由。

**受け皿は既にある**: `observation`（ADR-0007、`docs/adr/0007-observation-fact.md:32`）は
`value_text` 列を最初から持っている。`b03_build_observation.py:117-119` が埋めない理由は
「どちらの出典も値は常に量的でテキスト値を持つ観測が無い」と書いているが、これは
`sensor_timeseries` 自体に文字列を運ぶ列が無い（本節の実測どおり）ことの帰結であり、
`observation.value_text` という設計が無いわけではない。したがって将来の対応は**新しい
設計を要らない**——`sensor_timeseries` にテキスト列を足し、`m02` がそこに `value_raw`
（文字列側）を流し、`b03` がそれを `observation.value_text` に流す、という**配管を戻す**
だけで済む。

### 判断

修正しない（`sensor_timeseries` にテキスト用カラムを足す、または `m02` が `value_raw` を
別テーブルに書く、などの対応が要るが、いずれもスキーマ変更を伴う実装であり、今回のタスク
（調査のみ）の範囲外）。

### 着手条件

文字列の観測（天気概況・風向）を実際に使う消費者（画面・API）が現れたら、
`c10_jma.py`/`m02_measurements.py`/`sensor_timeseries` スキーマの対応を検討する。

---

## 8. e-Stat の小地域境界の配信形式

### 実測

`scripts/c90_estat_shozaiki.py:20`（simplifyについてのdocstring）に既に記載がある:

> 原形は data/raw/ の Shapefile に残るので、後で PMTiles に切り替えるときはそちらから
> 作る。

現状は `data/processed/estat_shozaiki_kanagawa.geojson`（simplify済みGeoJSON）を
配信しており、PMTiles化するかどうかは未決。

### 判断

このIssueでは判断しない（着手条件のみを書く）。

### 着手条件

ジオメトリ配信形式の判断は、Phase D（マニフェスト・配布物・公開、Issue #40）の
ジオメトリ配信形式ADRで行う。

