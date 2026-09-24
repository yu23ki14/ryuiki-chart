#!/usr/bin/env python3
"""v1 派生33テーブルすべてを1コマンドで突き合わせる統合ゲート（ADR-0016
Phase B の「v1 の33テーブルすべてを v2 から再現できる」ことの全体の合格。
docs/plans/PHASE_B_RECONCILIATION.md「全体の合格」参照）。

    .venv/bin/python3 scripts/b02_run_all_gates.py

`scripts/reconcile/projection_manifest.yaml`（テーブル名 -> (射影スクリプト,
candidate ファイル) の宣言的な対応表。5つの candidate ファイルに分かれている）
を読み、candidate ファイルごとに `scripts/b02_derived_compare.py` の突合ロジック
（`compare_all`）を1回ずつ呼んで結果をマージし、1つのレポート（既定
`reports/derived_reconciliation_all.md`）にまとめる。

**`scripts/b02_derived_compare.py` 自身は1行も変更していない**——このスクリプトは
`compare_all`/`render_markdown`/宣言済み差分の読み込み・検証を import して
呼ぶだけの薄いオーケストレータ（新しい入口 vs `b02` への `--manifest` 追加、
どちらにするかの判断は PR 説明参照）。5系統の個別ゲート
（`b02_derived_compare.py --candidate <1つ> --tables <その candidate の分だけ>`）
はこれまでどおり単独で動く。

**射影スクリプトは自動実行しない**（原本DBが要るので CI では動かない。この
ゲートは「既にある candidate を突き合わせる」だけ）。candidate ファイルが
1つでも無ければ、`projection_manifest.yaml` の `script` を名指しして即座に
止める（どれか1つが古くても、それ以外の candidate は普通に読めてしまうため、
「一部だけ古い状態で緑になる」事故を避ける——`derived_baseline.json` 自体の
鮮度チェックは `compare_all` が完全モードで自動的に行う）。

出力レポートを、個別ゲート（`b02_derived_compare.py --tables ...`）の既定出力
`reports/derived_reconciliation.md` とは別のファイル名にしている
（`reports/derived_reconciliation_all.md`）。理由: 個別ゲートをこの統合ゲートの
前後どちらで実行しても、互いの結果を上書きし合わないようにするため
（「5本のゲートを同時に回すと既存レポートが上書きされ合う」という /simplify
指摘と同根の問題を、ファイル名を分けることで避ける。docs/plans/
PHASE_B_RECONCILIATION.md 参照）。どちらのファイルも `.gitignore` 済み
（実行するたびに書き直す成果物であり、コミット対象ではない）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import b02_derived_compare as b02  # noqa: E402
from reconcile import common, datasource  # noqa: E402

DEFAULT_MANIFEST = ROOT / "scripts" / "reconcile" / "projection_manifest.yaml"
DEFAULT_DATA_DIR = ROOT / "data" / "db"
DEFAULT_OUT_MD = ROOT / "reports" / "derived_reconciliation_all.md"


def _assert_manifest_matches_baseline(manifest: dict, baseline_tables: dict) -> dict[str, str]:
    """`projection_manifest.yaml` のテーブル名の集合が `derived_baseline.json`
    の33テーブルと過不足なく一致することを検証する（`scripts/reconcile/
    adr0011_destinations.yaml` と同じ流儀の実行時チェック。機械検証の本体は
    `scripts/tests/test_common.py` の pytest テストだが、実行のたびにも
    同じ検証を通す——古い manifest とベースラインの組み合わせで実行される
    事故を防ぐ）。戻り値はテーブル名 -> candidate ファイル名のフラット辞書
    （`common.flatten_projection_manifest` がテーブル名の重複も検出する）。
    """
    flat = common.flatten_projection_manifest(manifest)
    manifest_tables = set(flat)
    baseline_table_set = set(baseline_tables)
    missing = sorted(baseline_table_set - manifest_tables)
    extra = sorted(manifest_tables - baseline_table_set)
    if missing or extra:
        sys.exit(
            "scripts/reconcile/projection_manifest.yaml のテーブル名の集合が "
            "reports/derived_baseline.json の33テーブルと一致しない"
            f"（不足: {missing}、余分: {extra}）。"
        )
    return flat


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument(
        "--data-dir", default=str(DEFAULT_DATA_DIR),
        help="candidate ファイル（projection_manifest.yaml のキー）を探すディレクトリ",
    )
    parser.add_argument("--baseline-json", default=str(b02.DEFAULT_BASELINE_JSON))
    parser.add_argument(
        "--baseline-data", default=None,
        help=f"既定は {b02.DEFAULT_BASELINE_DB} があれば使い、無ければ縮退モードにする。",
    )
    parser.add_argument("--tolerance", type=float, default=0.0)
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    parser.add_argument(
        "--reduced", action="store_true",
        help="縮退モードを強制する（scripts/b02_derived_compare.py と同じ意味）。",
    )
    parser.add_argument("--expected-diffs", default=str(b02.DEFAULT_EXPECTED_DIFFS))
    parser.add_argument("--no-expected-diffs", action="store_true")
    args = parser.parse_args()

    baseline_json_path = pathlib.Path(args.baseline_json)
    if not baseline_json_path.exists():
        sys.exit(
            f"ベースラインが無い: {baseline_json_path}\n"
            "先に `.venv/bin/python3 scripts/b01_derived_baseline.py` を実行すること。"
        )
    baseline_json = json.loads(baseline_json_path.read_text(encoding="utf-8"))
    if baseline_json.get("schema_version") != common.SCHEMA_VERSION:
        sys.exit(
            f"{baseline_json_path} の schema_version が想定と異なる"
            f"（期待 {common.SCHEMA_VERSION}、実際 {baseline_json.get('schema_version')!r}）。"
            "scripts/b01_derived_baseline.py を実行して作り直すこと。"
        )

    manifest = common.load_projection_manifest(args.manifest)
    _assert_manifest_matches_baseline(manifest, baseline_json["tables"])

    if args.no_expected_diffs:
        expected_diffs_by_table: dict[str, list[dict]] = {}
    else:
        expected_diffs_by_table = common.load_expected_diffs(args.expected_diffs)
        common.validate_expected_diffs(
            expected_diffs_by_table, baseline_json["tables"], str(args.expected_diffs)
        )

    if args.reduced:
        baseline_data_path = None
    else:
        baseline_data_path = args.baseline_data
        if baseline_data_path is None and b02.DEFAULT_BASELINE_DB.exists():
            baseline_data_path = str(b02.DEFAULT_BASELINE_DB)

    # このゲートは常に全33テーブルが対象（`--tables` に相当する絞り込みが無い）
    # ので、b02_derived_compare.py の main() と同じ「縮退モードでは宣言済み
    # 差分/許容誤差を扱えない」検証をそのまま適用する。
    tables_with_declared_diffs = sorted(t for t, diffs in expected_diffs_by_table.items() if diffs)
    if baseline_data_path is None and tables_with_declared_diffs:
        sys.exit(
            "縮退モード（--baseline-data 無し・ベースライン実データ無し）では宣言済み差分"
            "（expected_diffs.yaml）を適用できない（行レベルの差分を見られないので、宣言が"
            f"実際に差分になっているか検証できない）。宣言があるテーブル: {tables_with_declared_diffs}\n"
            "縮退モードで動かしたいなら --no-expected-diffs を付けること。"
        )
    if baseline_data_path is None and args.tolerance > 0:
        sys.exit(
            "縮退モード（--baseline-data 無し）では --tolerance は使えない。"
            "content_hash 同士の比較に許容誤差の概念が無く、適用したふりをしない。"
        )

    if baseline_data_path is not None:
        baseline_source = datasource.open_source(baseline_data_path)
        mode = "full"
    else:
        baseline_source = None
        mode = "reduced"
        print(
            "▶ ベースラインの実データが無いので縮退モードで実行する"
            "（行レベルの内訳は出せない。docs/plans/PHASE_B_RECONCILIATION.md 参照）"
        )

    data_dir = pathlib.Path(args.data_dir)
    combined_results: dict[str, dict] = {}
    combined_extra_tables: set[str] = set()

    try:
        for candidate_name in sorted(manifest):
            spec = manifest[candidate_name]
            candidate_path = data_dir / candidate_name
            if not candidate_path.exists():
                sys.exit(
                    f"{candidate_path} が無い。先に {spec['script']} を実行すること。"
                )
            candidate_source = datasource.open_source(candidate_path)
            try:
                results, extra_tables = b02.compare_all(
                    baseline_json,
                    baseline_source,
                    candidate_source,
                    args.tolerance,
                    set(spec["tables"]),
                    expected_diffs_by_table,
                )
            except b02.ExpectedDiffError as e:
                sys.exit(str(e))
            combined_results.update(results)
            combined_extra_tables.update(extra_tables)
            candidate_source.close()
    finally:
        if baseline_source is not None:
            baseline_source.close()

    stale_tables = sorted(t for t, r in combined_results.items() if r.get("baseline_stale"))

    md = b02.render_markdown(
        combined_results,
        mode,
        args.tolerance,
        stale_tables,
        sorted(combined_extra_tables),
        partial_tables=None,
        total_baseline_tables=None,
    )
    out_md = pathlib.Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md, encoding="utf-8")
    print(f"→ {out_md}")

    total = len(baseline_json["tables"])
    n_mismatch = sum(
        1 for r in combined_results.values() if r["status"] not in ("match", "declared_diffs_only")
    )
    n_declared_only = sum(1 for r in combined_results.values() if r["status"] == "declared_diffs_only")
    n_match = len(combined_results) - n_mismatch - n_declared_only
    n_excluded = total - len(combined_results)
    print(
        f"{total}表中 一致: {n_match} / 宣言済み差分のみ: {n_declared_only} / "
        f"不一致: {n_mismatch} / 対象外: {n_excluded}"
    )
    n_applied = sum(len(r.get("declared_diffs_applied", [])) for r in combined_results.values())
    if n_applied:
        print(f"適用した宣言済み差分: {n_applied}件")

    if stale_tables:
        print(f"ベースラインが実データと食い違うテーブル: {stale_tables}", file=sys.stderr)
        return 1
    return 1 if (n_mismatch > 0 or n_excluded > 0) else 0


if __name__ == "__main__":
    sys.exit(main())
