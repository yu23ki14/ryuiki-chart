"""Phase B パイプラインの共通処理（読み取り専用オープン・テーブルの指紋・YAML 読み込み）。

`scripts/migrate/common.py` が `common`（`open_readonly`・`load_yaml`・`compute_fingerprint`）を、
`scripts/migrate/` 以外の収集・サンプル系が `datasource` を import する。v1 との突合
（b01/b02）は Issue #48 PR-5 で消えた。

このパッケージのどの関数も、渡された sqlite ファイルを読み取り専用でしか開かない
（`common.open_readonly` 参照）。
"""
