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

**`scripts/b02_derived_compare.py` 自身の振る舞いは1ビットも変えていない**
——CLI から呼んだときの出力は従来どおり（`scripts/tests/test_b02_compare.py`
で確認済み）。このスクリプトは、`main()` が持っていた「ベースラインの読み込み・
`schema_version` 検証・宣言済み差分の読み込みと検証・縮退モードの判定・
要約の集計」を `b02_derived_compare.py` 側に切り出した共有ヘルパ
（`load_baseline_json`/`resolve_expected_diffs`/`resolve_baseline_data_path`/
`guard_reduced_mode_restrictions`/`open_baseline_source_for_mode`/
`summarize_results`）と、`compare_all`/`render_markdown` を import して呼ぶだけの
薄いオーケストレータ（コードレビュー指摘: 以前は約60行がそのままコピーされ、
文言だけ微妙に違っていた）。5系統の個別ゲート
（`b02_derived_compare.py --candidate <1つ> --tables <その candidate の分だけ>`）
はこれまでどおり単独で動く。

**射影スクリプトは自動実行しない**（原本DBが要るので CI では動かない。この
ゲートは「既にある candidate を突き合わせる」だけ）。candidate ファイルが
1つでも無ければ、**比較を1件も始める前に**5ファイルの存在をまとめて確認し、
足りないものを `projection_manifest.yaml` の `script`付きで全部並べて止める
（コードレビュー指摘: 以前は比較の途中で1つ見つからないことに気づき、それまでの
1分超の比較が無駄になっていた）。

出力レポートを、個別ゲート（`b02_derived_compare.py --tables ...`）の既定出力
`reports/derived_reconciliation.md` とは別のファイル名にしている
（`reports/derived_reconciliation_all.md`）。理由: 個別ゲートをこの統合ゲートの
前後どちらで実行しても、互いの結果を上書きし合わないようにするため
（「5本のゲートを同時に回すと既存レポートが上書きされ合う」という /simplify
指摘と同根の問題を、ファイル名を分けることで避ける。docs/plans/
PHASE_B_RECONCILIATION.md 参照）。どちらのファイルも `.gitignore` 済み
（実行するたびに書き直す成果物であり、コミット対象ではない）。レポート自体にも
「統合ゲートである・33表を5ファイルで見た」ことと、テーブルごとの candidate
ファイル（不一致なら再実行すべきスクリプトも）を明記する（コードレビュー指摘:
以前は個別ゲートのレポートと見分けがつかなかった）。
"""
from __future__ import annotations

import argparse
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
    （`common.flatten_projection_manifest` がテーブル名の重複も検出する。
    `main()` がこの戻り値を、統合レポートに「各表がどの candidate ファイルの
    分か」を出すのに使う——コードレビュー指摘: 以前は戻り値を捨てていた）。
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


def _assert_all_candidates_exist(manifest: dict, data_dir: pathlib.Path) -> None:
    """比較を1件も始める前に、manifest が指す全 candidate ファイルの存在を
    まとめて確認する。1つでも無ければ、足りないものを全部（`script` 付きで）
    並べて即座に止める（コードレビュー指摘: 以前は比較ループの中で1つずつ
    確かめており、5ファイル中4番目が無いようなケースで、既に終えた3ファイル分
    〔完全モードで実測1分超〕の比較が無駄になっていた）。
    """
    missing = [
        (name, manifest[name]["script"])
        for name in sorted(manifest)
        if not (data_dir / name).exists()
    ]
    if missing:
        lines = [f"  - {name}: 先に {script} を実行すること" for name, script in missing]
        sys.exit(
            f"candidate ファイルが{len(missing)}件無い（{data_dir}）:\n" + "\n".join(lines)
        )


def _candidate_note(candidate_name: str, script: str) -> str:
    return f"candidate ファイル: `{candidate_name}`（射影スクリプト: `{script}`）"


def _compare_one_candidate(
    candidate_path, baseline_json, baseline_source, tolerance, tables, expected_diffs_by_table,
):
    """1つの candidate ファイルを開いて `compare_all` で突き合わせ、必ず閉じる
    （`compare_all` が `ExpectedDiffError` を投げても、ここで確実に
    `candidate_source.close()` する。宣言の例外そのものの捕捉・`sys.exit` は
    呼び出し側〔ループ〕の責務のまま——コードレビュー指摘: ループの入れ子を
    1段減らす）。
    """
    candidate_source = datasource.open_source(candidate_path)
    try:
        return b02.compare_all(
            baseline_json, baseline_source, candidate_source, tolerance, tables, expected_diffs_by_table,
        )
    finally:
        candidate_source.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument(
        "--data-dir", default=str(DEFAULT_DATA_DIR),
        help="candidate ファイル（projection_manifest.yaml のキー）を探すディレクトリ",
    )
    b02._add_shared_compare_args(parser, default_out_md=DEFAULT_OUT_MD)
    args = parser.parse_args()

    baseline_json = b02.load_baseline_json(args.baseline_json)

    manifest = common.load_projection_manifest(args.manifest)
    table_to_candidate = _assert_manifest_matches_baseline(manifest, baseline_json["tables"])

    data_dir = pathlib.Path(args.data_dir)
    _assert_all_candidates_exist(manifest, data_dir)

    expected_diffs_by_table = b02.resolve_expected_diffs(
        args.expected_diffs, baseline_json["tables"], skip=args.no_expected_diffs
    )

    baseline_data_path = b02.resolve_baseline_data_path(
        reduced=args.reduced, baseline_data=args.baseline_data, default_baseline_db=b02.DEFAULT_BASELINE_DB
    )

    # このゲートは常に全33テーブルが対象（`--tables` に相当する絞り込みが無い）。
    target_tables = set(baseline_json["tables"].keys())
    b02.guard_reduced_mode_restrictions(baseline_data_path, expected_diffs_by_table, target_tables, args.tolerance)

    baseline_source, mode = b02.open_baseline_source_for_mode(baseline_data_path)

    combined_results: dict[str, dict] = {}
    combined_extra_tables: set[str] = set()

    try:
        for candidate_name in sorted(manifest):
            spec = manifest[candidate_name]
            candidate_path = data_dir / candidate_name  # 存在は _assert_all_candidates_exist で確認済み
            try:
                results, extra_tables = _compare_one_candidate(
                    candidate_path, baseline_json, baseline_source, args.tolerance,
                    set(spec["tables"]), expected_diffs_by_table,
                )
            except b02.ExpectedDiffError as e:
                sys.exit(str(e))

            note = _candidate_note(candidate_name, spec["script"])
            for table in results:
                results[table]["notes"].append(note)
            combined_results.update(results)
            combined_extra_tables.update(extra_tables)
    finally:
        if baseline_source is not None:
            baseline_source.close()

    stale_tables = sorted(t for t, r in combined_results.items() if r.get("baseline_stale"))

    integrated_note = (
        "**統合ゲート**（`scripts/b02_run_all_gates.py`）: v1 派生33テーブルすべてを、"
        "5つの candidate ファイル（`scripts/reconcile/projection_manifest.yaml` の対応表、"
        f"実際に読んだのは `{pathlib.Path(args.manifest).name}`）に対してまとめて"
        "突き合わせた結果。個別ゲート（`scripts/b02_derived_compare.py --tables ...`）の"
        "レポートとは別物。"
    )
    # 不一致のテーブルで「candidate ファイル（再実行すべきスクリプト）」を
    # 1セルで分かるようにする（コードレビュー指摘）。
    table_candidate_display = {
        t: f"`{c}`（{manifest[c]['script']}）" for t, c in table_to_candidate.items()
    }

    md = b02.render_markdown(
        combined_results,
        mode,
        args.tolerance,
        stale_tables,
        sorted(combined_extra_tables),
        partial_tables=None,
        total_baseline_tables=None,
        integrated_note=integrated_note,
        table_candidate=table_candidate_display,
    )
    out_md = pathlib.Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md, encoding="utf-8")
    print(f"→ {out_md}")

    total = len(baseline_json["tables"])
    summary = b02.summarize_results(combined_results)
    n_excluded = total - len(combined_results)
    print(
        f"{total}表中 一致: {summary['n_match']} / 宣言済み差分のみ: {summary['n_declared_only']} / "
        f"不一致: {summary['n_mismatch']} / 対象外: {n_excluded}"
    )
    if summary["n_applied"]:
        print(f"適用した宣言済み差分: {summary['n_applied']}件")

    if stale_tables:
        print(f"ベースラインが実データと食い違うテーブル: {stale_tables}", file=sys.stderr)
        return 1
    return 1 if (summary["n_mismatch"] > 0 or n_excluded > 0) else 0


if __name__ == "__main__":
    sys.exit(main())
