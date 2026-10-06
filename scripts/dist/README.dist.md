# 流域カルテ 配布データ（dist）

`scripts/d01_build_dist.py` が `v2.sqlite` と `registry.sqlite` から決定的に作る Parquet の配布物です
（ADR-0001）。記述子は `datapackage.json`（Frictionless Data Package）。

## 中身

| パス | 内容 |
|---|---|
| `observation/source_table=<出典テーブル>/part-0.parquet` | 観測（数値）。公開 ID `observation_id`・`source_edition_id` 付き |
| `occurrence/source_id=<出典>/part-0.parquet` | 出現（種の記録）。公開 ID `occurrence_id`・`source_edition_id` 付き。座標は原本のまま |
| `occurrence_place.parquet` | 出現と場所（流域など）の対応 |
| `observation_agg.parquet` / `occurrence_agg.parquet` | 集計キューブ |
| `registry/*.parquet` | place・taxon・variable・unit・source・source_edition・license・caveat など |

パーティション列（`source_table` / `source_id`）はファイルの中には持たず、パス（hive 形式）が持ちます。

## 読み方（DuckDB の例）

```sql
SELECT * FROM read_parquet('dist/observation/*/*.parquet', hive_partitioning = true) LIMIT 10;
SELECT * FROM read_parquet('dist/occurrence/*/*.parquet', hive_partitioning = true) WHERE taxon_id = '...';
SELECT * FROM 'dist/registry/source_edition.parquet';
```

## 読むときの注意

- **時間（3点セット）**: `period_start` / `period_end` / `period_raw` を持ちます。時刻帯なしのローカル時刻の
  **文字列**です（ADR-0024）。timestamp 型にして UTC に直さないでください。
- **検閲**: 定量下限未満の値は `censoring`（`below_lod` / `not_detected` 等）と `censoring_limit` に残っています。
  `value_num` を 0 や定量下限で埋めた値としてそのまま平均しないでください。キューブは `value_zero`（0 を代入）と
  `value_lod`（下限値を代入）の両方を持ちます（ADR-0009）。
- **出力を絞っていません**（ADR-0028）。`redistributable=0` の出典の行も含みます。旗（`redistributable`・
  `license_class`）は出典の性質を示す情報で、行を除外する条件ではありません。再利用の条件は `datapackage.json` の
  `sources[]`（`license_id`・`license_class`・`attribution`）で確かめてください。
- **座標は原本のまま**です。ぼかし・丸めはしていません。
- 合成データ（`synthetic_*` の出典）は含みません。
- 利用条件が確定していない出典（`license_class` が `unknown`（写像漏れ）または `unconfirmed`（未確認））の件数と
  版 ID は `datapackage.json` の `license_summary.unresolved_license_class` に出しています。

## 同一性の確かめ方

`datapackage.json` の各リソースが `sha256`（ファイルのバイト）と `rows_sha256`（行集合のダイジェスト。行の順序に
依らない）を持ちます。同じ入力から作り直すとバイトまで一致します。ライブラリの版が変わってバイトが揺れても、
`rows_sha256` が一致すれば内容は同一です。時刻は `datapackage.json` に入れていません。
