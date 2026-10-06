"""ADR-0016 Phase B「ファクトとキューブ」— measurements を単一の縦持ちファクト
`observation`（ADR-0007）に集約し、キューブ（ADR-0011）にするパッケージ。
（v1 の派生テーブル形への射影 b05 などは Issue #48 PR-5 で撤去した。）

`scripts/b03_build_observation.py` / `scripts/b04_build_cube.py` ほか
b06/b07/b09/b13 が薄いオーケストレータで、実際の変換ロジックは
このパッケージに置く（`scripts/registry/` が build_*.py 群を持つのと同じ構成）。

- `common.py`   — 読み取り専用オープン・出力 sqlite の作り直し・タイミング表示
- `censoring.py`— ADR-0009 の検閲マッピング（design.md D2）
- `period.py`   — ADR-0008 の期間展開と value_grain/period_grain の食い違い検出（design.md D4）
"""
