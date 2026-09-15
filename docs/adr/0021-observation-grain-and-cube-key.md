# ADR-0021: 粒度は「値の粒度」と「日付の精度」に分け、キューブは入力の統計量と粒度を鍵に含める

- 状態: 提案中 / 日付: 2026-09-08
- 関連: ADR-0007（observation）, ADR-0008（時間）, ADR-0010（指標）, ADR-0011（キューブ）, ADR-0016（移行計画）

## 背景（実測。Phase B 縦に薄い1本 `measurements`→`observation`→`meas_daily`/`meas_month`/`meas_year` で判明）

ADR-0008 は時間を `period_start` / `period_end` / `grain` の3点セットで表すと決めた。しかし
`atsugi_river_water_quality`（厚木市の河川水質。相模川・中津川・小鮎川・玉川の4地点）の実装（`scripts/b03_build_observation.py`）で、
この3点セットが**1本の軸では表せない**ケースが実測で見つかった。

```
atsugi_river_water_quality の測定 3,840 行（全 323,164 行中）
  - variable_alias（レジストリ、実データで確認: alias='pH' 等, source_id='atsugi_river_water_quality'）
    は grain='day', stat='mean' を宣言している（原本xlsx全19本のB3セル
    「※数値は日間平均値です。」が一次資料。docs/plans/PHASE_B_INTAKE.md の
    「#1・#7を解決した本PR」節に記録済み）。
  - しかし measured_on はこの3,840行に限り4桁の年度番号しか持たない
    （scripts/m05_tier1.py:312 の `measured_on = sampled_on or fiscal_year` の副作用。
    `sampled_on`（採水日）が無い行だけがこの経路に落ちる）。
```

`grain` を `day`（alias が言う値の粒度）のままにすると、`period_start`/`period_end` を
日付から特定できない（4桁は「年度」であって「日」ではない）。逆に `grain` を
`fiscal_year` に倒すと期間は言えるが、「この値は日間平均値である」という情報
（`value_grain='day'`）が消える。**「値が代表する統計期間」と「日付から確実に言える期間」は
別の実測結果であり、同じ列に収まらない。**

ADR-0011 のキューブの鍵は `(..., grain, stat, imputation)` だが、これも実データで衝突する。
`variable_alias` を実測すると、`env_kousui_annual_kanagawa`（神奈川県公共用水域水質年報）は
同じ `variable_id='common:variable:water.ph'` を、`stat` だけを変えて2つの alias で配っている。

```
alias='pH（最大値）' source_id='env_kousui_annual_kanagawa' -> variable_id=water.ph, grain='fiscal_year', stat='max'
alias='pH（最小値）' source_id='env_kousui_annual_kanagawa' -> variable_id=water.ph, grain='fiscal_year', stat='min'
```

ADR-0011 の `stat` はキューブ**自身**が入力に対して行う集計関数（mean/min/max/…）を表す列であり、
「入力（`observation`）側が既にどの統計量として配られてきたか」を表す列ではない。この区別が
無いと、`env_kousui_annual_kanagawa` の「pH 最大値」系列と「pH 最小値」系列は
`(variable_id=water.ph, grain='fiscal_year', 期間)` が完全に一致するため、キューブが同じ期間の
`AVG(v)`/`MIN(v)`/`MAX(v)` を計算するときに**両系列の値が同じグループに混ざり**、
「最大値の系列の最小値」のような意味を持たない集計を機械的に作ってしまう。

`kanagawa_jiban_chinka`（地盤沈下報告書）も同様の実測結果を持つ。この出典の `variable_alias`
は `grain='year'`（暦年）を宣言している（実データで確認）。v1 (`meas_year.kind`) は
「出典が直接配った暦年値」（`kind='annual'`）と「日次観測を積み上げた暦年値」（`kind='daily'`）を
区別しており、実測では前者が **100,240 行**、後者が **15,836 行**（前者は後者の約6.3倍。
`data/db/v1_projection.sqlite` の `meas_year` を実測）。`(place, variable_id, period, grain)` だけを
鍵にすると、この2種類は同じ格に落ちて区別できなくなる——出典が公開した値と、当方が積み上げた値では
「その数字が何をどう集計したものか」の系譜が違うため、混ぜてよいものではない。

## 決定（3つ）

### 1. observation は「値の粒度」と「日付の精度」を2本の軸として持つ

`value_grain`（統計量が代表する期間の粒度。**`variable_alias` から取る。`measured_on` の桁数から
再導出しない**）と、`period_grain` / `period_start` / `period_end`（日付から確実に言える区間。
`measured_on` の桁数と `value_grain` から導出する。`scripts/migrate/period.py`）を分けて持つ。
通常は一致する。

**食い違いは宣言的な例外表（`scripts/migrate/period_exceptions.yaml`）に載っているものだけ許し、
宣言に無い食い違いはビルド（`scripts/b03_build_observation.py`）を止める。宣言が1件も
該当しない場合、および実測件数が宣言の `expected_row_count` と食い違う場合も止める**
（腐った例外表が残らないように。`scripts/migrate/period.py` の `PeriodExceptionUsage`）。
例外エントリには `reason`（なぜ起きるか）と `restoration_plan`（いつ・どう解消するか）を必須にする。

実測: この縦線で `value_grain != period_grain` になる行は**ちょうど3,840行**（すべて
`atsugi_river_water_quality` の4桁日付行。`reports/phase_b_fact_slice.md`）で、宣言表の
`expected_row_count: 3840` と一致している。

### 2. キューブの次元キーに `obs_stat` ・ `value_grain` ・ `input_grain` を足す

`scripts/b04_build_cube.py` の `observation_agg` の次元キー:

```
region_id, place_id, place_kind, variable_id, obs_stat, unit_id,
value_grain, period_start, period_end, grain, input_grain, stat, imputation
```

- `obs_stat`: **入力（`observation`）側の統計量**（alias が言う。`pH（最大値）`/`pH（最小値）`は
  ここが `max`/`min` に分かれ、同じ格に混ざらなくなる）。
- `stat`: **キューブ自身**が観測の集合に対して行う集計関数（`mean`/`min`/`max`）。`obs_stat` とは
  別の軸。日次・月次セルは常に `stat='mean'`（v1 の `meas_daily.value`/`meas_month.avg` が
  `AVG(value)` なので、min/max は作らない）。年次セルだけ `stat` ごとに別行になる
  （`meas_year` の `avg`/`min`/`max` を再現するため。射影側 `scripts/b05_project_v1.py` が
  3行を1行にピボットし直す）。
- `input_grain`: 積み上げの**途中で経由した格ではなく、葉の observation（積み上げの末端にある
  生の観測行）の `period_grain`** と定義する。日次セルから積み上げた月次・年次セルは、
  日→月→年のどの段を経由しても常に `input_grain='day'`（値は変わらない定義）。出典が直接
  配った年次値（`period_grain <> 'day'`）は、観測から直接作り、その `period_grain` を
  そのまま `input_grain` として使う（日次セルを経由しない）。`meas_year.kind` は
  `input_grain='day'` なら `'daily'`、そうでなければ `'annual'`（`scripts/b05_project_v1.py` の
  `_MEAS_YEAR_SQL`）。

### 3. 平均は SQLite の `AVG()` で計算し、`sqlite3.sqlite_version_info >= (3, 43, 0)` を検証する

SQLite 3.43 で `SUM()`/`AVG()` の加算アルゴリズムが Kahan-Babuška-Neumaier（丸め誤差を補正しながら
足す）に変わった。それより前のバージョン、または pandas/numpy 等の素朴な左→右加算に計算し直すと、
`meas_year(kind='daily')` の **3,176/15,836 グループ（20%）**で平均値がベースラインと食い違う
（アドバイザーが実データで実測。`scripts/b04_build_cube.py` の docstring と起動時のガードに
そのまま記録されている）。

`scripts/b02_derived_compare.py` の既定（完全モード・`--tolerance 0`）は `_exceeds_tolerance` が
`abs_diff != 0` で**生の double を直接比較**しており、`scripts/reconcile/common.py` の
`format_number`（6桁固定小数点。content_hash の正準化用）はこの行レベル比較には使われない。
したがって「6桁に丸めれば小さな誤差は吸収される」という期待はこのゲートの実際の比較方法に対する
安全網にならない。

この環境の `sqlite3` **CLI** は **3.37.2**（条件を満たさない。`sqlite3 --version` で確認）だが、
b03/b04/b05 が実際に使うのは **Python 同梱の `sqlite3` モジュール**（**3.49.1**、条件を満たす。
`python3 -c "import sqlite3; print(sqlite3.sqlite_version)"` で確認）であり、CLI とは別物。
「たまたま今の Python が新しいから通っている」を黙って信用せず、`scripts/b04_build_cube.py` は
モジュール読み込み時点で `sqlite3.sqlite_version_info >= (3, 43, 0)` を検証し、満たさなければ
理由を示して `raise SystemExit` で止まる（`assert` にしない——`python -O`/
`PYTHONOPTIMIZE=1` では `assert` が丸ごと消え、まさにこのガードが要る場面で無効化されてしまう。
レビュー指摘）。`observation_agg.built_from` にも版を記録し
（例: `observation (sqlite=3.49.1)`）、後から「どの SQLite で計算されたキューブか」を追跡できる
ようにする。

## 影響

- **良い**: v1 の `meas_year.kind`（どの経路で作った値か）がモデルに載る。出典が直接配った集計値と
  当方が積み上げた集計値が混ざらない。`pH（最大値）`/`pH（最小値）`が1つの格に潰れず、
  意味の異なる系列を機械的に混ぜる事故が構造的に起きなくなる。日付精度が落ちた出典
  （`atsugi_river_water_quality`）を「無かったこと」にせず、復元計画付きの負債として持てる。
- **コスト**: `observation` の列（`value_grain`/`period_grain` の2本立て）と `observation_agg` の
  次元キー（`obs_stat`/`value_grain`/`input_grain`）が増える。ADR-0008・ADR-0011 が示した図と
  文字どおりには一致しなくなる（本 ADR による拡張として両 ADR に参照だけ追記した）。
- **注意**: `period_exceptions.yaml` は**直すべき負債の一覧**であって恒久的な逃げ道ではない。
  `atsugi_river_water_quality` のエントリは `restoration_plan` に「`source_ref` の月ラベルから
  復元できる。Phase B のゲートが緑になった後に対応する」と明記してあり、無期限に残す前提ではない。

## 検討した代替案（却下理由まで書く）

- **統計量を `variable_id` に埋める（`water.ph_annual_max` のような ID にする）**: ADR-0007 決定2
  「出典が既に集計値を配っている場合（`河川水位_日平均`）、名前に埋めず `variable_id=水位, grain=day,
  stat=mean` と分解する」に正面から反する。指標をまたいだ比較（ADR-0007 の目的そのもの）ができなく
  なる。却下。
- **キューブの `stat` を合成文字列にする（`'max/mean'` のような値にする）**: 人は読めるが、
  「入力側の統計量」と「キュープ自身の集計」を機械的に分解できず、集計ロジックの分岐に文字列
  パースが要る。却下。
- **`atsugi_river_water_quality` を `grain='fiscal_year'` に倒して1軸で済ませる**: 「日間平均値
  である」という一次資料（原本xlsxのB3セル）の情報を失う。加えて、`source_ref` に残る月ラベル
  （19年度×12ヶ月ぶん欠落なく残っている）からの復元計画が書けなくなる。却下。
- **`built_from` に入力の粒度を書いてキーには含めない**: `built_from` は版・出所を記録する列で
  あり、次元（グループ化の単位）ではない。次元をここに逃がすと「同じ `built_from` でも実は違う
  グループ化がされている」状態を許してしまい、意味が二重になる。却下。
