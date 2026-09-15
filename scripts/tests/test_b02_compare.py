"""scripts/b02_derived_compare.py の突合テスト。

「一致する候補は0で通り、値が1つ変わった・行が増えた・減った候補は検出して
非0で落ちる」ことを、CLI（サブプロセス呼び出し）で確認する
（docs/plans/PHASE_B_RECONCILIATION.md のゲートそのものが正しく動くことの証明）。
"""
import copy
import json
import subprocess
import sys

import b01_derived_baseline as b01
import b02_derived_compare as b02

from .fixtures import dump_all_tables_as_json, make_fixture_db, make_null_key_fixture_db

ROOT = b01.ROOT
B02_SCRIPT = ROOT / "scripts" / "b02_derived_compare.py"


def _make_baseline(tmp_path, *, include_dupe=False):
    db_path = tmp_path / "baseline.sqlite"
    make_fixture_db(db_path, include_dupe=include_dupe)
    keys_yaml = tmp_path / "derived_keys.yaml"
    keys_yaml.write_text("{}\n", encoding="utf-8")
    baseline, _ = b01.build_baseline(db_path, keys_yaml)
    baseline_json = tmp_path / "derived_baseline.json"
    b01.write_json(baseline, baseline_json)
    return db_path, baseline_json, baseline


def _run_cli(
    baseline_json, baseline_data, candidate, out_md, tolerance=0.0, reduced=False, tables=None,
    expected_diffs=None, no_expected_diffs=None,
):
    """b02 の CLI を起動する。`baseline_data=None` なら `--baseline-data` を
    渡さない（`reduced=True` と組み合わせて縮退モードのテストに使う。
    レビュー指摘 A-6: 以前はこのためだけに `subprocess.run` を呼び出し側で
    再実装していた）。`tables` を渡すと `--tables` を付ける。

    `expected_diffs`/`no_expected_diffs` を両方省略すると既定で `--no-expected-diffs`
    を付ける（既定の `--expected-diffs` は本物のプロジェクトの
    `scripts/reconcile/expected_diffs.yaml` を指しており、そこに宣言された
    テーブル名（`meas_daily` 等）はこのフィクスチャの `baseline_json`
    （`t_pk`/`t_dims` 等）には存在しないため、放っておくと『宣言のテーブル名が
    ベースラインに無い』で無関係なテストまで落ちる）。`expected_diffs=<path>` を
    渡すとそのファイルを読む（`--no-expected-diffs` は付けない）。宣言済み差分の
    機構そのものを「`--no-expected-diffs` が本当に無効化するか」までテストしたい
    ときは、`expected_diffs` と `no_expected_diffs=True` を両方明示的に渡す
    （その場合は上書きせずそのまま両方の引数を CLI に渡す）。
    """
    if no_expected_diffs is None:
        no_expected_diffs = expected_diffs is None
    args = [sys.executable, str(B02_SCRIPT), "--baseline-json", str(baseline_json)]
    if baseline_data is not None:
        args += ["--baseline-data", str(baseline_data)]
    if reduced:
        args.append("--reduced")
    if tables is not None:
        args += ["--tables", tables]
    if expected_diffs is not None:
        args += ["--expected-diffs", str(expected_diffs)]
    if no_expected_diffs:
        args.append("--no-expected-diffs")
    args += ["--candidate", str(candidate), "--tolerance", str(tolerance), "--out-md", str(out_md)]
    return subprocess.run(args, capture_output=True, text=True)


def _write_expected_diffs_yaml(tmp_path, data, name="expected_diffs.yaml"):
    """テスト用の宣言済み差分 YAML を書く（`data` はテーブル名 -> [宣言, ...] の辞書）。"""
    import yaml

    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_identical_candidate_matches_and_exits_zero(tmp_path):
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    # 候補側 = ベースラインの完全なコピー(バイト同一である必要は無い。同じ値であればよい)。
    candidate_db = tmp_path / "candidate.sqlite"
    make_fixture_db(candidate_db, include_dupe=False)

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_db, out_md)

    assert result.returncode == 0, result.stdout + result.stderr
    text = out_md.read_text(encoding="utf-8")
    assert "一致: 2" in result.stdout or "一致" in text


def test_changed_value_is_detected_and_exits_nonzero(tmp_path):
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate = dump_all_tables_as_json(db_path)

    # t_dims の1行だけ avg を書き換える。
    for row in candidate["t_dims"]["rows"]:
        if row[0] == "s1" and row[1] == 2020 and row[2] == "daily":
            row[4] = 9.99
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_path, out_md)

    assert result.returncode != 0, result.stdout + result.stderr
    text = out_md.read_text(encoding="utf-8")
    assert "t_dims" in text
    assert "不一致" in text


def test_added_row_is_detected_and_exits_nonzero(tmp_path):
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate = dump_all_tables_as_json(db_path)
    candidate["t_dims"]["rows"].append(["s3", 2022, "daily", 1, 4.0])
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_path, out_md)

    assert result.returncode != 0
    text = out_md.read_text(encoding="utf-8")
    assert "候補にしか無い行: 1件" in text


def test_removed_row_is_detected_and_exits_nonzero(tmp_path):
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate = dump_all_tables_as_json(db_path)
    candidate["t_dims"]["rows"] = [
        r for r in candidate["t_dims"]["rows"] if not (r[0] == "s2" and r[1] == 2020)
    ]
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_path, out_md)

    assert result.returncode != 0
    text = out_md.read_text(encoding="utf-8")
    assert "ベースラインにしか無い行: 1件" in text


def test_changed_text_column_is_detected_even_without_numeric_change(tmp_path):
    """数値列が1つも変わらなくても、非数値列（キー以外）の値の変化を検出できること。"""
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate = dump_all_tables_as_json(db_path)
    for row in candidate["t_pk"]["rows"]:
        if row[0] == "b":
            row[1] = "Beta-changed"
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_path, out_md)

    assert result.returncode != 0, result.stdout + result.stderr
    text = out_md.read_text(encoding="utf-8")
    assert "t_pk" in text
    assert "label" in text


def test_missing_table_in_candidate_is_detected(tmp_path):
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate = dump_all_tables_as_json(db_path)
    del candidate["t_dims"]
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_path, out_md)

    assert result.returncode != 0
    text = out_md.read_text(encoding="utf-8")
    assert "候補側に無い" in text


def test_tolerance_absorbs_tiny_float_difference(tmp_path):
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate = dump_all_tables_as_json(db_path)
    for row in candidate["t_dims"]["rows"]:
        if row[0] == "s1" and row[1] == 2020 and row[2] == "daily":
            row[4] = row[4] + 1e-9  # 表現差程度のごく小さいずれ
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    out_md = tmp_path / "reconciliation.md"
    # 既定(完全一致)では落ちる。
    result_exact = _run_cli(baseline_json, db_path, candidate_path, out_md, tolerance=0.0)
    assert result_exact.returncode != 0

    # 許容誤差を与えれば通る。
    result_tolerant = _run_cli(baseline_json, db_path, candidate_path, out_md, tolerance=1e-6)
    assert result_tolerant.returncode == 0, result_tolerant.stdout + result_tolerant.stderr


def test_reduced_mode_matches_on_identical_data_without_baseline_source():
    """完全モードではなく縮退モード（実データ無し）でも、ハッシュが一致すれば
    'match' になることを関数レベルで確認する（CLI の既定パス解決に依存しないよう、
    compare_all を直接呼ぶ）。
    """
    import pathlib
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        tmp_path = pathlib.Path(d)
        db_path, baseline_json_path, baseline = _make_baseline(tmp_path)
        baseline_json = json.loads(baseline_json_path.read_text(encoding="utf-8"))

        from reconcile import datasource

        candidate_source = datasource.open_sqlite_source(db_path)
        results, _extra = b02.compare_all(baseline_json, None, candidate_source, tolerance=0.0)
        assert all(r["status"] == "match" for r in results.values()), results


def test_reduced_mode_detects_hash_mismatch_without_baseline_source():
    import pathlib
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        tmp_path = pathlib.Path(d)
        db_path, baseline_json_path, _ = _make_baseline(tmp_path)
        baseline_json = json.loads(baseline_json_path.read_text(encoding="utf-8"))

        candidate = dump_all_tables_as_json(db_path)
        candidate["t_dims"]["rows"][0][4] = 12345.0
        candidate_path = tmp_path / "candidate.json"
        candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

        from reconcile import datasource

        candidate_source = datasource.open_source(candidate_path)
        results, _extra = b02.compare_all(baseline_json, None, candidate_source, tolerance=0.0)
        assert results["t_dims"]["status"] == "mismatch"
        assert results["t_dims"]["mode"] == "reduced"
        assert results["t_pk"]["status"] == "match"


def test_stale_baseline_data_is_reported_and_exits_nonzero(tmp_path):
    """derived_baseline.json が実データと食い違う（b01 の再実行忘れ）ケースを検出する。"""
    db_path, baseline_json, baseline = _make_baseline(tmp_path)

    # baseline.json の中身を手で古いままにする(row_countを書き換えて「実データとズレた」状態を作る)。
    stale = copy.deepcopy(baseline)
    stale["tables"]["t_pk"]["row_count"] = 999
    stale_path = tmp_path / "stale_baseline.json"
    b01.write_json(stale, stale_path)

    candidate_db = tmp_path / "candidate.sqlite"
    make_fixture_db(candidate_db, include_dupe=False)

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(stale_path, db_path, candidate_db, out_md)

    assert result.returncode != 0
    assert "食い違う" in result.stderr or "整合性" in out_md.read_text(encoding="utf-8")


def test_unsupported_schema_version_is_rejected(tmp_path):
    """回帰テスト（レビュー指摘 A-4）。`schema_version` は b01 が書くだけで
    誰も読んでいなかった。b02 が読んで検証し、想定外なら b01 の再実行を
    促して非0で落ちることを確認する。
    """
    db_path, baseline_json_path, baseline = _make_baseline(tmp_path)

    wrong_version = copy.deepcopy(baseline)
    wrong_version["schema_version"] = 999
    wrong_version_path = tmp_path / "wrong_version_baseline.json"
    b01.write_json(wrong_version, wrong_version_path)

    candidate_db = tmp_path / "candidate.sqlite"
    make_fixture_db(candidate_db, include_dupe=False)

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(wrong_version_path, db_path, candidate_db, out_md)

    assert result.returncode != 0
    assert "schema_version" in (result.stdout + result.stderr)


def _make_null_dim_baseline(tmp_path, *, rows=None):
    db_path = tmp_path / "baseline_null.sqlite"
    make_null_key_fixture_db(db_path, rows=rows)
    keys_yaml = tmp_path / "derived_keys.yaml"
    keys_yaml.write_text("{}\n", encoding="utf-8")
    baseline, _ = b01.build_baseline(db_path, keys_yaml)
    baseline_json = tmp_path / "derived_baseline_null.json"
    b01.write_json(baseline, baseline_json)
    return db_path, baseline_json


def test_mismatch_with_null_valued_keys_does_not_crash_sort_and_is_reported(tmp_path):
    """回帰テスト（レビュー指摘 #2）。

    `t_null_dim` は `('g1', None)` と `('g1', 'x')` という、キーの最初の要素が
    等しく2番目が None/str で異なる2つのキーを持つ。候補側でこのテーブルの
    行を全部消すと、両方とも「ベースラインにしか無い行」の集合に入り、
    それを素朴に `sorted()` すると `None` と `str` の比較で `TypeError` に
    なっていた（しかもこれは「不一致を検出する」という、このツールの主目的
    そのものの経路でだけ起きる）。落ちずにレポートへ書けることを確認する。
    """
    db_path, baseline_json = _make_null_dim_baseline(tmp_path)

    candidate_db = tmp_path / "candidate_null.sqlite"
    make_null_key_fixture_db(candidate_db, rows=[])  # 全行消えた候補

    out_md = tmp_path / "reconciliation_null.md"
    result = _run_cli(baseline_json, db_path, candidate_db, out_md)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    text = out_md.read_text(encoding="utf-8")
    assert "t_null_dim" in text
    assert "ベースラインにしか無い行: 3件" in text


def test_reduced_mode_rejects_nonzero_tolerance(tmp_path):
    """回帰テスト（レビュー指摘 #5）。縮退モードは content_hash 同士の完全一致
    しか見ておらず許容誤差を適用する手段が無いので、`--tolerance` を黙って
    無視せず明示的に落とす。

    `--reduced` で縮退モードを強制する（この開発環境には実データへの
    symlink があり、`--baseline-data` を省略するだけでは既定パスの自動検出で
    完全モードになってしまい、このテストが意図と違う経路を通ってしまうため）。
    """
    _db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate_db = tmp_path / "candidate.sqlite"
    make_fixture_db(candidate_db, include_dupe=False)
    out_md = tmp_path / "reconciliation.md"

    result = _run_cli(baseline_json, None, candidate_db, out_md, tolerance=1e-6, reduced=True)

    assert result.returncode != 0
    assert "tolerance" in (result.stdout + result.stderr)


def test_extra_table_in_candidate_does_not_fail_the_gate(tmp_path):
    """回帰テスト（レビュー指摘 #6・前半）。候補側が v1 の33テーブルに無い
    テーブルを余分に持っていても、それだけでゲートを落としてはいけない。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate = dump_all_tables_as_json(db_path)
    candidate["t_extra_only_in_candidate"] = {"columns": ["x"], "rows": [[1], [2]]}
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_path, out_md)

    assert result.returncode == 0, result.stdout + result.stderr
    text = out_md.read_text(encoding="utf-8")
    assert "t_extra_only_in_candidate" in text
    assert "ゲートの合否には含めない" in text


def test_extra_column_in_candidate_table_is_treated_as_mismatch(tmp_path):
    """回帰テスト（レビュー指摘 #6・後半）。比較対象テーブルの中に候補側だけの
    余分な列があれば、「同じ形」という前提が崩れているので不一致として扱う。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate = dump_all_tables_as_json(db_path)
    candidate["t_pk"]["columns"].append("extra_col")
    for row in candidate["t_pk"]["rows"]:
        row.append("z")
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_path, out_md)

    assert result.returncode != 0
    text = out_md.read_text(encoding="utf-8")
    assert "余分な列がある" in text


def test_unparseable_numeric_value_in_candidate_is_counted_not_raised(tmp_path):
    """回帰テスト（レビュー指摘 #10）。候補側が数値列のはずの場所に "N/A" の
    ような非数値を書いてきても、`ValueError` でレポートごと失われず、
    差として数えて非0で終了する。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate = dump_all_tables_as_json(db_path)
    for row in candidate["t_dims"]["rows"]:
        if row[0] == "s1" and row[1] == 2020 and row[2] == "daily":
            row[4] = "N/A"  # avg 列（数値のはず）に非数値
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_path, out_md)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    text = out_md.read_text(encoding="utf-8")
    assert "t_dims" in text


def test_tables_filter_limits_comparison_to_selected_tables(tmp_path):
    """`--tables` で選んだテーブルだけが突合され、選ばなかったテーブルが候補に
    無くても（＝候補が縦に薄い1本しか持たなくても）終了コード0になる。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate = dump_all_tables_as_json(db_path)
    del candidate["t_dims"]  # 選ばないテーブルを候補から消しておく（v2キューブがまだ無い想定）
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_path, out_md, tables="t_pk")

    assert result.returncode == 0, result.stdout + result.stderr
    text = out_md.read_text(encoding="utf-8")
    assert "t_dims" not in text
    assert "t_pk" in text


def test_tables_filter_still_detects_mismatch_in_selected_table(tmp_path):
    """選んだテーブルの1つが不一致なら非0で終わる。"""
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate = dump_all_tables_as_json(db_path)
    for row in candidate["t_pk"]["rows"]:
        if row[0] == "b":
            row[1] = "Beta-changed"
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_path, out_md, tables="t_pk")

    assert result.returncode != 0
    text = out_md.read_text(encoding="utf-8")
    assert "t_pk" in text and "不一致" in text


def test_tables_unknown_name_exits_nonzero_and_names_it(tmp_path):
    """ベースラインに無い名前を渡すと、その名前を含むメッセージで落ちる
    （タイポで『0件を突合して緑』になるのを防ぐ）。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate_db = tmp_path / "candidate.sqlite"
    make_fixture_db(candidate_db, include_dupe=False)
    out_md = tmp_path / "reconciliation.md"

    result = _run_cli(baseline_json, db_path, candidate_db, out_md, tables="t_pk,not_a_real_table")

    assert result.returncode != 0
    assert "not_a_real_table" in (result.stdout + result.stderr)
    assert not out_md.exists()  # 検証で落ちるので、レポートは書かれない


def test_tables_empty_token_is_rejected(tmp_path):
    """カンマの打ち間違い（空トークン）を『0件選択』として黙って通さない。"""
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate_db = tmp_path / "candidate.sqlite"
    make_fixture_db(candidate_db, include_dupe=False)
    out_md = tmp_path / "reconciliation.md"

    result = _run_cli(baseline_json, db_path, candidate_db, out_md, tables="t_pk,,t_dims")

    assert result.returncode != 0


def test_tables_partial_selection_shows_partial_gate_notice(tmp_path):
    """部分指定のとき、レポートと標準出力の両方に部分ゲートの文言が出る。"""
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate = dump_all_tables_as_json(db_path)
    del candidate["t_dims"]
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_path, out_md, tables="t_pk")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "部分ゲート" in result.stdout
    text = out_md.read_text(encoding="utf-8")
    assert "部分ゲート" in text
    assert "t_pk" in text
    assert "全体の合格ではない" in text


def test_tables_full_selection_does_not_show_partial_gate_notice(tmp_path):
    """`--tables` を省略した（＝全テーブルが対象の）ときは、部分ゲートの文言を出さない
    （既存のレポート出力を変えない）。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate_db = tmp_path / "candidate.sqlite"
    make_fixture_db(candidate_db, include_dupe=False)
    out_md = tmp_path / "reconciliation.md"

    result = _run_cli(baseline_json, db_path, candidate_db, out_md)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "部分ゲート" not in result.stdout
    text = out_md.read_text(encoding="utf-8")
    assert "部分ゲート" not in text


def test_tables_filter_does_not_treat_unselected_baseline_tables_as_extra(tmp_path):
    """`--tables` で選ばなかった（が v1 のベースラインには実在する）テーブルを
    候補が持っていても、それを『候補側にしか無いテーブル（extra_tables）』に
    混ぜてはいけない（選ばなかっただけで、v1に実在しないわけではないため）。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate_db = tmp_path / "candidate.sqlite"
    make_fixture_db(candidate_db, include_dupe=False)  # t_pk, t_dims 両方を持つ候補
    out_md = tmp_path / "reconciliation.md"

    result = _run_cli(baseline_json, db_path, candidate_db, out_md, tables="t_pk")

    assert result.returncode == 0, result.stdout + result.stderr
    text = out_md.read_text(encoding="utf-8")
    assert "候補側にしか無いテーブル" not in text


# ---------------------------------------------------------------------------
# 宣言済み差分（scripts/reconcile/expected_diffs.yaml の機構そのもの）
#
# 本物の data/db/*.sqlite は要らない——`_make_baseline`（t_pk/t_dims の
# フィクスチャ）と、この節専用に書く小さな expected_diffs.yaml だけで完結する。
# t_dims のキーは (site, year, kind)（`_make_baseline` 直下の docstring参照）。
# ---------------------------------------------------------------------------

_REASON = "テスト用の宣言（本物の理由ではない）"
_FOUND_ON = "2026-09-08"
_RECORD = "docs/plans/PHASE_B_RECONCILIATION.md 「再現できなかった箇所の記録」"


def test_expected_diff_row_only_in_candidate_is_applied_and_gate_passes(tmp_path):
    """`row_only_in_candidate` の宣言が、実際にその通りの差分（候補にしか無い行）を
    説明できるときは、そのテーブルの状態が『宣言済み差分のみ』になりゲートは0で通る。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate = dump_all_tables_as_json(db_path)
    candidate["t_dims"]["rows"].append(["s3", 2022, "daily", 1, 4.0])
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    expected_diffs = _write_expected_diffs_yaml(tmp_path, {
        "t_dims": [
            {
                "key": ["s3", 2022, "daily"],
                "kind": "row_only_in_candidate",
                "reason": _REASON,
                "found_on": _FOUND_ON,
                "record": _RECORD,
            },
        ],
    })

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_path, out_md, expected_diffs=expected_diffs)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "不一致: 0" in result.stdout
    text = out_md.read_text(encoding="utf-8")
    assert "### `t_dims` — 宣言済み差分のみ" in text
    assert "expected_diffs.yaml で適用したもの" in text
    assert "['s3', 2022, 'daily']" in text or "[\"s3\", 2022, \"daily\"]" in text


def test_expected_diff_value_diff_is_applied_and_gate_passes(tmp_path):
    """`value_diff` の宣言が、実際に値が変わっている共通キーを説明できるときも
    同様にゲートが0で通る。"""
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate = dump_all_tables_as_json(db_path)
    for row in candidate["t_dims"]["rows"]:
        if row[0] == "s1" and row[1] == 2020 and row[2] == "daily":
            row[4] = 9.99
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    expected_diffs = _write_expected_diffs_yaml(tmp_path, {
        "t_dims": [
            {
                "key": ["s1", 2020, "daily"],
                "kind": "value_diff",
                "reason": _REASON,
                "found_on": _FOUND_ON,
                "record": _RECORD,
            },
        ],
    })

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_path, out_md, expected_diffs=expected_diffs)

    assert result.returncode == 0, result.stdout + result.stderr
    text = out_md.read_text(encoding="utf-8")
    assert "宣言済み差分のみ" in text


def test_expected_diff_rotten_declaration_exits_nonzero(tmp_path):
    """宣言したキーが実際には差分になっていない（腐った宣言）と非0で落ちる。
    これが宣言済み差分の機構でいちばん重要な検証——免除が残り続けて他の
    退行を隠すのを防ぐ。"""
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate_db = tmp_path / "candidate.sqlite"
    make_fixture_db(candidate_db, include_dupe=False)  # ベースラインと同一（差分0件）

    expected_diffs = _write_expected_diffs_yaml(tmp_path, {
        "t_pk": [
            {
                "key": ["b"],
                "kind": "row_only_in_candidate",
                "reason": _REASON,
                "found_on": _FOUND_ON,
                "record": _RECORD,
            },
        ],
    })

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_db, out_md, expected_diffs=expected_diffs)

    assert result.returncode != 0
    assert "腐った宣言" in (result.stdout + result.stderr)
    assert not out_md.exists()


def test_expected_diff_kind_mismatch_exits_nonzero(tmp_path):
    """宣言した kind と実際の差分の種類が食い違うと非0で落ちる
    （実際は候補にしか無い行なのに `value_diff` と宣言した場合）。"""
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate = dump_all_tables_as_json(db_path)
    candidate["t_dims"]["rows"].append(["s3", 2022, "daily", 1, 4.0])
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    expected_diffs = _write_expected_diffs_yaml(tmp_path, {
        "t_dims": [
            {
                "key": ["s3", 2022, "daily"],
                "kind": "value_diff",  # 実際は row_only_in_candidate
                "reason": _REASON,
                "found_on": _FOUND_ON,
                "record": _RECORD,
            },
        ],
    })

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_path, out_md, expected_diffs=expected_diffs)

    assert result.returncode != 0
    assert "食い違う" in (result.stdout + result.stderr)


def test_expected_diff_bad_key_length_exits_nonzero(tmp_path):
    """`key` の要素数がそのテーブルのキー列数（t_dims は3）と違うと非0で落ちる。"""
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate_db = tmp_path / "candidate.sqlite"
    make_fixture_db(candidate_db, include_dupe=False)

    expected_diffs = _write_expected_diffs_yaml(tmp_path, {
        "t_dims": [
            {
                "key": ["s1", 2020],  # 2要素（本来3要素: site, year, kind）
                "kind": "value_diff",
                "reason": _REASON,
                "found_on": _FOUND_ON,
                "record": _RECORD,
            },
        ],
    })

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_db, out_md, expected_diffs=expected_diffs)

    assert result.returncode != 0
    assert "要素数" in (result.stdout + result.stderr)
    assert not out_md.exists()


def test_expected_diff_missing_required_key_exits_nonzero(tmp_path):
    """B-2: `reason`/`found_on`/`record` のいずれかが欠けている宣言は非0で落ちる。
    `scripts/migrate/period_exceptions.yaml` の `REQUIRED_EXCEPTION_KEYS` 検証と
    対称にする（免除ゲート自体を免除するこちらの宣言に検証が無かった非対称の是正）。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate_db = tmp_path / "candidate.sqlite"
    make_fixture_db(candidate_db, include_dupe=False)

    expected_diffs = _write_expected_diffs_yaml(tmp_path, {
        "t_pk": [
            {
                "key": ["b"],
                "kind": "row_only_in_candidate",
                # reason/found_on/record が無い。
            },
        ],
    })

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_db, out_md, expected_diffs=expected_diffs)

    assert result.returncode != 0
    assert "必須項目が欠けている" in (result.stdout + result.stderr)
    assert not out_md.exists()


def test_expected_diff_empty_required_value_exits_nonzero(tmp_path):
    """`reason: ""` のように項目はあっても空文字なら、欠けているのと同じ扱いで
    非0で落ちる（空文字1つで免除の説明義務を骨抜きにできないように）。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate_db = tmp_path / "candidate.sqlite"
    make_fixture_db(candidate_db, include_dupe=False)

    expected_diffs = _write_expected_diffs_yaml(tmp_path, {
        "t_pk": [
            {
                "key": ["b"],
                "kind": "row_only_in_candidate",
                "reason": "",
                "found_on": _FOUND_ON,
                "record": _RECORD,
            },
        ],
    })

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_db, out_md, expected_diffs=expected_diffs)

    assert result.returncode != 0
    assert "必須項目が欠けている" in (result.stdout + result.stderr)
    assert not out_md.exists()


def test_expected_diff_unknown_table_name_exits_nonzero(tmp_path):
    """宣言のテーブル名がベースラインに無いと、その名前を挙げて非0で落ちる。"""
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate_db = tmp_path / "candidate.sqlite"
    make_fixture_db(candidate_db, include_dupe=False)

    expected_diffs = _write_expected_diffs_yaml(tmp_path, {
        "no_such_table": [
            {
                "key": ["x"],
                "kind": "row_only_in_candidate",
                "reason": _REASON,
                "found_on": _FOUND_ON,
                "record": _RECORD,
            },
        ],
    })

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_db, out_md, expected_diffs=expected_diffs)

    assert result.returncode != 0
    assert "no_such_table" in (result.stdout + result.stderr)
    assert not out_md.exists()


def test_expected_diff_reduced_mode_with_declared_diff_in_scope_exits_nonzero(tmp_path):
    """縮退モード（ベースライン実データ無し）では、対象テーブルに宣言が1件でも
    あると、行レベルで検証できないため黙って無視せず非0で落ちる。"""
    _db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate_db = tmp_path / "candidate.sqlite"
    make_fixture_db(candidate_db, include_dupe=False)

    expected_diffs = _write_expected_diffs_yaml(tmp_path, {
        "t_pk": [
            {
                "key": ["b"],
                "kind": "row_only_in_candidate",
                "reason": _REASON,
                "found_on": _FOUND_ON,
                "record": _RECORD,
            },
        ],
    })

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(
        baseline_json, None, candidate_db, out_md, reduced=True, expected_diffs=expected_diffs
    )

    assert result.returncode != 0
    assert "縮退モード" in (result.stdout + result.stderr)


def test_no_expected_diffs_flag_ignores_declarations_even_if_rotten(tmp_path):
    """`--no-expected-diffs` を付けると、宣言ファイルを一切読まない。腐った宣言
    （実際には差分ではないキー）が書いてあっても、検証自体が起きずゲートは
    通常どおり（差分0件なので）0で通る。"""
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate_db = tmp_path / "candidate.sqlite"
    make_fixture_db(candidate_db, include_dupe=False)  # 差分0件

    expected_diffs = _write_expected_diffs_yaml(tmp_path, {
        "t_pk": [
            {
                "key": ["b"],
                "kind": "row_only_in_candidate",  # 腐った宣言（実際には差分が無い）
                "reason": _REASON,
                "found_on": _FOUND_ON,
                "record": _RECORD,
            },
        ],
    })

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(
        baseline_json, db_path, candidate_db, out_md,
        expected_diffs=expected_diffs, no_expected_diffs=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    text = out_md.read_text(encoding="utf-8")
    assert "宣言済み差分のみ: 0テーブル" in text
    assert "expected_diffs.yaml で適用したもの" not in text
    assert "### `t_pk` — 一致" in text


def test_expected_diffs_yaml_wrong_shape_exits_cleanly_not_with_traceback(tmp_path):
    """変更9: `meas_daily:` 相当のテーブル名の直下に `key:`/`kind:` を書いてしまう
    （宣言のリストではなくマッピングにしてしまう）と、以前は
    `for d in diffs: d.get(...)` が文字列キーを回して
    `AttributeError: 'str' object has no attribute 'get'` という生のトレースバックに
    なっていた。テーブル名を含む説明的なエラーで止まり、トレースバックが出ないことを
    確認する。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate_db = tmp_path / "candidate.sqlite"
    make_fixture_db(candidate_db, include_dupe=False)

    expected_diffs = tmp_path / "expected_diffs.yaml"
    expected_diffs.write_text(
        "t_pk:\n"
        "  key: [\"a\"]\n"
        "  kind: row_only_in_candidate\n",
        encoding="utf-8",
    )

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_db, out_md, expected_diffs=expected_diffs)

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "AttributeError" not in output
    assert "Traceback" not in output
    assert "t_pk" in output
    assert not out_md.exists()


def test_expected_diff_multiple_bad_declarations_in_one_table_are_reported_together(tmp_path):
    """変更10: 同じテーブルに複数の不正な宣言（腐った宣言・kind の食い違い）が
    あるとき、最初の1件で止まらず、そのテーブルの不正な宣言を全部集めて
    1回でまとめて報告する（上流のバグを1つ直すと同じテーブルの宣言がまとめて
    腐るのが普通なので、1件ずつ知らされると完全モードで何度も待たされる）。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    candidate = dump_all_tables_as_json(db_path)
    candidate["t_dims"]["rows"].append(["s3", 2022, "daily", 1, 4.0])  # 候補にしか無い行
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    expected_diffs = _write_expected_diffs_yaml(tmp_path, {
        "t_dims": [
            {  # 腐った宣言（実際には両側に同じ値で存在し、差分になっていない）
                "key": ["s1", 2020, "daily"],
                "kind": "row_only_in_candidate",
                "reason": _REASON,
                "found_on": _FOUND_ON,
                "record": _RECORD,
            },
            {  # kind の食い違い（実際は row_only_in_candidate）
                "key": ["s3", 2022, "daily"],
                "kind": "value_diff",
                "reason": _REASON,
                "found_on": _FOUND_ON,
                "record": _RECORD,
            },
        ],
    })

    out_md = tmp_path / "reconciliation.md"
    result = _run_cli(baseline_json, db_path, candidate_path, out_md, expected_diffs=expected_diffs)

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "2件ある" in output
    assert "['s1', 2020, 'daily']" in output  # 腐った宣言
    assert "['s3', 2022, 'daily']" in output  # kind の食い違い
    assert "腐った宣言" in output
    assert "食い違う" in output
    assert not out_md.exists()
