"""Phase B 突合ハーネス（docs/adr/0016-migration-plan.md の Phase B 受け入れゲート）。

scripts/b01_derived_baseline.py（v1 派生33テーブルの指紋を作る）と
scripts/b02_derived_compare.py（指紋と候補側を突き合わせる）が共有するロジックを
このパッケージに置く。scripts/registry/ が build_*.py 群のオーケストレータ（r01）と
共通処理（registry/common.py）を分けているのと同じ構成。

このパッケージのどの関数も、渡された sqlite ファイルを読み取り専用でしか開かない
（`fingerprint.py` の `open_readonly` 参照）。
"""
