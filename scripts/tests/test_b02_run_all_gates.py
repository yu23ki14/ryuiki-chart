"""scripts/b02_run_all_gates.py（33表の統合ゲート）のテスト。

`scripts/tests/test_b02_compare.py` と同じ流儀（フィクスチャ sqlite + CLI を
サブプロセスで起動）で、「複数の candidate ファイルに分かれたテーブルを
1コマンドで突き合わせ、1つのレポートにまとめる」「candidate が無ければ
projection_manifest.yaml の script を名指しして止まる」「manifest のテーブル
集合が baseline と食い違えば即座に止まる」ことを確認する。

フィクスチャは `t_pk`（1つ目の candidate ファイル相当）・`t_dims`（2つ目の
candidate ファイル相当）の2テーブルだけを使う（`t_dupe` はどんな列の組でも
一意なキーが作れないフィクスチャで、`derived_keys.yaml` の宣言無しには
ベースライン自体が作れないため、ここでは使わない——`test_b02_compare.py` も
値の突合テストでは `include_dupe=False` を使っている）。
"""
import json
import subprocess
import sys

import pytest

import b01_derived_baseline as b01
import b02_run_all_gates as run_all

from .fixtures import dump_all_tables_as_json, make_fixture_db

ROOT = b01.ROOT
RUN_ALL_GATES_SCRIPT = ROOT / "scripts" / "b02_run_all_gates.py"


def _make_baseline(tmp_path):
    """`t_pk`/`t_dims` の2テーブルを持つフィクスチャ baseline を作る。"""
    db_path = tmp_path / "baseline.sqlite"
    make_fixture_db(db_path, include_dupe=False)
    keys_yaml = tmp_path / "derived_keys.yaml"
    keys_yaml.write_text("{}\n", encoding="utf-8")
    baseline, _ = b01.build_baseline(db_path, keys_yaml)
    baseline_json = tmp_path / "derived_baseline.json"
    b01.write_json(baseline, baseline_json)
    return db_path, baseline_json, baseline


def _write_split_candidates(tmp_path, dump):
    """`t_pk`/`t_dims` を2つの candidate ファイル（`cand_a.json`/`cand_b.json`）
    に分けて書き出す（`test_b02_compare.py` と同じ JSON 候補の書式。
    `datasource.open_source` は拡張子で自動判定するので candidate ファイルが
    `.sqlite` である必要はない）。
    """
    data_dir = tmp_path / "data_dir"
    data_dir.mkdir()
    (data_dir / "cand_a.json").write_text(json.dumps({"t_pk": dump["t_pk"]}), encoding="utf-8")
    (data_dir / "cand_b.json").write_text(json.dumps({"t_dims": dump["t_dims"]}), encoding="utf-8")
    return data_dir


def _write_manifest(tmp_path, *, tables_a=("t_pk",), tables_b=("t_dims",)):
    manifest_path = tmp_path / "projection_manifest.yaml"
    lines = []
    if tables_a is not None:
        lines.append("cand_a.json:")
        lines.append("  script: scripts/fake_a.py")
        lines.append("  tables:")
        for t in tables_a:
            lines.append(f"    - {t}")
    if tables_b is not None:
        lines.append("cand_b.json:")
        lines.append("  script: scripts/fake_b.py")
        lines.append("  tables:")
        for t in tables_b:
            lines.append(f"    - {t}")
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest_path


def _run_cli(
    baseline_json, baseline_data, manifest, data_dir, out_md,
    *, reduced=False, expected_diffs=None,
):
    args = [
        sys.executable, str(RUN_ALL_GATES_SCRIPT),
        "--baseline-json", str(baseline_json),
        "--manifest", str(manifest),
        "--data-dir", str(data_dir),
        "--out-md", str(out_md),
    ]
    if baseline_data is not None:
        args += ["--baseline-data", str(baseline_data)]
    if reduced:
        args.append("--reduced")
    if expected_diffs is not None:
        args += ["--expected-diffs", str(expected_diffs)]
    else:
        # 既定の expected_diffs.yaml は本物のプロジェクトのファイル
        # （meas_daily 等）を指しており、このフィクスチャの baseline
        # （t_pk/t_dims）には無関係なので、明示しない限り読まない。
        args.append("--no-expected-diffs")
    return subprocess.run(args, capture_output=True, text=True)


def test_matches_across_multiple_candidate_files_exits_zero(tmp_path):
    """2テーブルが2つの candidate ファイルに分かれていても、1回の実行で
    まとめて突き合わせられ、全部一致すれば終了コード0になる。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    dump = dump_all_tables_as_json(db_path)
    data_dir = _write_split_candidates(tmp_path, dump)
    manifest = _write_manifest(tmp_path)
    out_md = tmp_path / "all.md"

    result = _run_cli(baseline_json, db_path, manifest, data_dir, out_md)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "一致: 2" in result.stdout
    assert "対象外: 0" in result.stdout
    text = out_md.read_text(encoding="utf-8")
    assert "t_pk" in text and "t_dims" in text


def test_mismatch_in_one_candidate_file_causes_nonzero_exit_and_reports_it(tmp_path):
    """1つの candidate ファイルだけに値の食い違いがあっても、統合ゲート全体が
    非0で終了し、レポートに不一致テーブルとして出る（もう1つの candidate の
    一致は覆い隠されない）。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    dump = dump_all_tables_as_json(db_path)
    for row in dump["t_dims"]["rows"]:
        if row[0] == "s1" and row[1] == 2020 and row[2] == "daily":
            row[4] = 9.99
    data_dir = _write_split_candidates(tmp_path, dump)
    manifest = _write_manifest(tmp_path)
    out_md = tmp_path / "all.md"

    result = _run_cli(baseline_json, db_path, manifest, data_dir, out_md)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "一致: 1" in result.stdout
    assert "不一致: 1" in result.stdout
    text = out_md.read_text(encoding="utf-8")
    assert "t_dims" in text
    assert "不一致" in text


def test_missing_candidate_file_names_its_script_and_stops(tmp_path):
    """manifest が指す candidate ファイルが無ければ、`script` を名指しして
    即座に非0で終了する（射影スクリプトを自動実行しない）。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    dump = dump_all_tables_as_json(db_path)
    data_dir = _write_split_candidates(tmp_path, dump)
    (data_dir / "cand_b.json").unlink()  # cand_b だけ無い状態にする
    manifest = _write_manifest(tmp_path)
    out_md = tmp_path / "all.md"

    result = _run_cli(baseline_json, db_path, manifest, data_dir, out_md)

    assert result.returncode != 0
    assert "scripts/fake_b.py" in (result.stdout + result.stderr)
    assert not out_md.exists()


def test_manifest_missing_a_baseline_table_fails_fast(tmp_path):
    """manifest がベースラインの1テーブル（`t_dims`）を書き漏らしていたら、
    どの candidate も開かず即座に非0で終了する（黙って一部のテーブルだけ
    緑になる事故を防ぐ）。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    dump = dump_all_tables_as_json(db_path)
    data_dir = _write_split_candidates(tmp_path, dump)
    manifest = _write_manifest(tmp_path, tables_b=None)  # t_dims を書き漏らす
    out_md = tmp_path / "all.md"

    result = _run_cli(baseline_json, db_path, manifest, data_dir, out_md)

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "t_dims" in combined
    assert not out_md.exists()


def test_manifest_with_extra_unknown_table_fails_fast(tmp_path):
    """manifest にベースラインへ無いテーブル名が紛れ込んでいたら（打ち間違い）、
    即座に非0で終了する。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    dump = dump_all_tables_as_json(db_path)
    data_dir = _write_split_candidates(tmp_path, dump)
    manifest = _write_manifest(tmp_path, tables_b=("t_dims", "t_typo"))
    out_md = tmp_path / "all.md"

    result = _run_cli(baseline_json, db_path, manifest, data_dir, out_md)

    assert result.returncode != 0
    assert "t_typo" in (result.stdout + result.stderr)
    assert not out_md.exists()


def test_duplicate_table_declared_in_two_candidates_fails_fast(tmp_path):
    """同じテーブル名が2つの candidate ファイルの両方に宣言されていたら
    （コピペミス）、即座に非0で終了する（`common.flatten_projection_manifest`
    の重複検出。片方の結果がもう片方を静かに上書きする事故を防ぐ）。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    dump = dump_all_tables_as_json(db_path)
    data_dir = _write_split_candidates(tmp_path, dump)
    manifest = _write_manifest(tmp_path, tables_a=("t_pk", "t_dims"), tables_b=("t_dims",))
    out_md = tmp_path / "all.md"

    result = _run_cli(baseline_json, db_path, manifest, data_dir, out_md)

    assert result.returncode != 0
    assert "t_dims" in (result.stdout + result.stderr)
    assert "重複" in (result.stdout + result.stderr)


def test_reduced_mode_without_baseline_data_still_covers_all_candidates(tmp_path):
    """`--baseline-data` を渡さず `--reduced` を指定すると、行レベルの内訳は
    出せないが、複数 candidate ファイルにまたがる縮退モードの突合はそのまま
    動く（ハッシュ・行数・数値集計だけの比較）。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    dump = dump_all_tables_as_json(db_path)
    data_dir = _write_split_candidates(tmp_path, dump)
    manifest = _write_manifest(tmp_path)
    out_md = tmp_path / "all.md"

    result = _run_cli(baseline_json, None, manifest, data_dir, out_md, reduced=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "一致: 2" in result.stdout


def test_declared_diffs_only_table_does_not_count_as_mismatch(tmp_path):
    """宣言済み差分（expected_diffs.yaml）で説明しきれるテーブルは、統合
    ゲートでも「宣言済み差分のみ」として扱われ、終了コードは0のまま
    （既存の `b02_derived_compare.py` の挙動を、複数 candidate に分かれた
    構成でも壊していないことの確認）。
    """
    import yaml

    db_path, baseline_json, _ = _make_baseline(tmp_path)
    dump = dump_all_tables_as_json(db_path)
    for row in dump["t_dims"]["rows"]:
        if row[0] == "s1" and row[1] == 2020 and row[2] == "daily":
            row[4] = 9.99
    data_dir = _write_split_candidates(tmp_path, dump)
    manifest = _write_manifest(tmp_path)

    expected_diffs = {
        "t_dims": [
            {
                "key": ["s1", 2020, "daily"],
                "kind": "value_diff",
                "columns": ["avg"],
                "reason": "テスト用の宣言",
                "found_on": "2026-09-24",
                "record": "test",
            }
        ]
    }
    expected_diffs_path = tmp_path / "expected_diffs.yaml"
    expected_diffs_path.write_text(yaml.safe_dump(expected_diffs, allow_unicode=True), encoding="utf-8")
    out_md = tmp_path / "all.md"

    result = _run_cli(
        baseline_json, db_path, manifest, data_dir, out_md, expected_diffs=expected_diffs_path
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "宣言済み差分のみ: 1" in result.stdout
    assert "一致: 1" in result.stdout


def test_multiple_missing_candidate_files_are_all_named_at_once(tmp_path):
    """candidate ファイルが2つとも無ければ、1つ目が見つからない時点で止まる
    のではなく、比較を1件も始める前に両方まとめて（`script` 付きで）1回の
    エラーで示す（コードレビュー指摘5: 以前は比較ループの中で1つずつ確かめて
    おり、既に終えた分の比較〔完全モードで実測1分超〕が無駄になっていた）。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    dump = dump_all_tables_as_json(db_path)
    data_dir = _write_split_candidates(tmp_path, dump)
    (data_dir / "cand_a.json").unlink()
    (data_dir / "cand_b.json").unlink()
    manifest = _write_manifest(tmp_path)
    out_md = tmp_path / "all.md"

    result = _run_cli(baseline_json, db_path, manifest, data_dir, out_md)

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "scripts/fake_a.py" in combined
    assert "scripts/fake_b.py" in combined
    assert "2件無い" in combined
    assert not out_md.exists()


def test_missing_table_within_an_existing_candidate_file_names_its_script(tmp_path):
    """candidate ファイル自体はあるが、manifest が言うテーブルの一部を
    持たない（古い candidate。`missing_in_candidate` になる、表だけ足りない
    壊れ方）場合、レポートにそのテーブルを作る射影スクリプト名が出る
    （コードレビュー指摘3: 以前はファイルが無い場合だけ名指ししていた。
    表だけ足りない方が起きやすい壊れ方だと指摘された）。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    dump = dump_all_tables_as_json(db_path)
    data_dir = tmp_path / "data_dir"
    data_dir.mkdir()
    # t_dims だけを持つ candidate ファイル（manifest 上は t_pk もこのファイルの
    # 分だと宣言するが、実ファイルには無い——「表だけ足りない」ケース）。
    (data_dir / "cand_b.json").write_text(json.dumps({"t_dims": dump["t_dims"]}), encoding="utf-8")
    manifest = _write_manifest(tmp_path, tables_a=None, tables_b=("t_pk", "t_dims"))
    out_md = tmp_path / "all.md"

    result = _run_cli(baseline_json, db_path, manifest, data_dir, out_md)

    assert result.returncode != 0
    text = out_md.read_text(encoding="utf-8")
    assert "候補側にこのテーブルが無い" in text
    assert "scripts/fake_b.py" in text


def test_integrated_report_is_distinguishable_from_a_single_candidate_report(tmp_path):
    """統合レポートが「統合ゲートである」ことと、各テーブルがどの candidate
    ファイルの分かを明示する（コードレビュー指摘10: 個別ゲートのレポートと
    見分けがつかなかった）。不一致のテーブルには candidate ファイル
    （と再実行すべきスクリプト）が summary の表にも出る。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    dump = dump_all_tables_as_json(db_path)
    for row in dump["t_dims"]["rows"]:
        if row[0] == "s1" and row[1] == 2020 and row[2] == "daily":
            row[4] = 9.99
    data_dir = _write_split_candidates(tmp_path, dump)
    manifest = _write_manifest(tmp_path)
    out_md = tmp_path / "all.md"

    result = _run_cli(baseline_json, db_path, manifest, data_dir, out_md)

    assert result.returncode != 0
    text = out_md.read_text(encoding="utf-8")
    assert "統合ゲート" in text
    assert "scripts/b02_run_all_gates.py" in text
    # 一致した t_pk の詳細節にも candidate ファイルが出る（全テーブル共通）。
    assert "candidate ファイル: `cand_a.json`" in text
    # 不一致の t_dims: サマリの表にも candidate ファイル（＋スクリプト）が出る。
    assert "cand_b.json" in text
    assert "scripts/fake_b.py" in text


def test_candidate_source_is_closed_even_when_expected_diff_error_is_raised(tmp_path, monkeypatch):
    """`compare_all` が `ExpectedDiffError`（腐った宣言）で例外を投げても、
    開いた `candidate_source` が必ず閉じられる（コードレビュー指摘14: 以前は
    `try/finally` の外で開いており、この経路でファイルハンドルが残っていた）。
    """
    db_path, baseline_json, _ = _make_baseline(tmp_path)
    dump = dump_all_tables_as_json(db_path)
    data_dir = _write_split_candidates(tmp_path, dump)
    manifest = _write_manifest(tmp_path)

    # 「腐った宣言」: t_pk は候補と完全一致するのに、value_diff を宣言する
    # ——_apply_expected_diffs が「実際には差分になっていない」として
    # ExpectedDiffError を投げる。
    expected_diffs_path = tmp_path / "expected_diffs.yaml"
    expected_diffs_path.write_text(
        "t_pk:\n"
        "  - key: [a]\n"
        "    kind: value_diff\n"
        "    columns: [label]\n"
        '    reason: "腐った宣言（テスト用）"\n'
        '    found_on: "2026-09-24"\n'
        '    record: "test"\n',
        encoding="utf-8",
    )

    closed_paths: list[str] = []
    real_open_source = run_all.datasource.open_source

    class _SpySource:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def close(self):
            closed_paths.append(True)
            self._inner.close()

    def spy_open_source(path):
        return _SpySource(real_open_source(path))

    monkeypatch.setattr(run_all.datasource, "open_source", spy_open_source)
    monkeypatch.setattr(
        sys, "argv",
        [
            "b02_run_all_gates.py",
            "--baseline-json", str(baseline_json),
            "--baseline-data", str(db_path),
            "--manifest", str(manifest),
            "--data-dir", str(data_dir),
            "--out-md", str(tmp_path / "all.md"),
            "--expected-diffs", str(expected_diffs_path),
        ],
    )

    with pytest.raises(SystemExit):
        run_all.main()

    # cand_a.json（t_pk を含む）を開いたぶんは少なくとも閉じられている。
    assert closed_paths
