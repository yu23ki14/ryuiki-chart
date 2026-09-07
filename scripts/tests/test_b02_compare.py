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


def _run_cli(baseline_json, baseline_data, candidate, out_md, tolerance=0.0):
    return subprocess.run(
        [
            sys.executable,
            str(B02_SCRIPT),
            "--baseline-json",
            str(baseline_json),
            "--baseline-data",
            str(baseline_data),
            "--candidate",
            str(candidate),
            "--tolerance",
            str(tolerance),
            "--out-md",
            str(out_md),
        ],
        capture_output=True,
        text=True,
    )


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

    result = subprocess.run(
        [
            sys.executable,
            str(B02_SCRIPT),
            "--baseline-json",
            str(baseline_json),
            "--reduced",
            "--candidate",
            str(candidate_db),
            "--tolerance",
            "1e-6",
            "--out-md",
            str(out_md),
        ],
        capture_output=True,
        text=True,
    )

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
