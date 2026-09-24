"""scripts/reconcile/common.py の単体テスト（キー自動導出・指紋計算）。"""
import json
import pathlib

import pytest

from reconcile import common, datasource

from .fixtures import make_fixture_db, make_null_key_fixture_db

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DESTINATIONS_YAML = _REPO_ROOT / "scripts" / "reconcile" / "adr0011_destinations.yaml"
_DERIVED_BASELINE_JSON = _REPO_ROOT / "reports" / "derived_baseline.json"
_PROJECTION_MANIFEST_YAML = _REPO_ROOT / "scripts" / "reconcile" / "projection_manifest.yaml"


@pytest.fixture()
def fixture_db(tmp_path):
    path = tmp_path / "fixture.sqlite"
    make_fixture_db(path)
    return path


def test_derive_key_uses_declared_primary_key(fixture_db):
    conn = common.open_readonly(fixture_db)
    try:
        key, source, note = common.derive_key(conn, "t_pk", overrides={})
    finally:
        conn.close()
    assert key == ["raw"]
    assert source == "pk"
    assert note is None


def test_derive_key_auto_two_phase_needs_untyped_column(fixture_db):
    """t_dims は (site, year) だけでは一意にならず、宣言型の無い 'kind' が要る
    （meas_year の 'kind' と同じ形）。Phase A だけで見つからず Phase B に落ちることを確認する。
    """
    conn = common.open_readonly(fixture_db)
    try:
        key, source, note = common.derive_key(conn, "t_dims", overrides={})
    finally:
        conn.close()
    assert key == ["site", "year", "kind"]
    assert source == "auto"
    assert note is None


def test_derive_key_null_in_typed_dimension_column_is_not_pruned_away(tmp_path):
    """回帰テスト（レビュー指摘 #1）。

    `t_null_dim` は `(grp, sub)` が一意な次元列だけの組み合わせ（`sub` に
    NULL を含む）。`_DistinctCache` が `COUNT(DISTINCT sub)`（NULL を数えない）
    だけを見ていると、鳩の巣原理の枝刈りが `(grp,sub)` を「一意になり得ない」と
    誤判定し、探索Aで見つからず探索Bに落ちて、宣言型を持たない集計列もどきの
    `val` がキーに紛れ込んでいた。修正後は探索Aだけで `(grp, sub)` が
    見つかり、`val` は絶対にキーに入らないことを確認する。
    """
    path = tmp_path / "null_dim.sqlite"
    make_null_key_fixture_db(path)
    conn = common.open_readonly(path)
    try:
        key, source, note = common.derive_key(conn, "t_null_dim", overrides={})
    finally:
        conn.close()
    assert key == ["grp", "sub"]
    assert source == "auto"
    assert note is None
    assert "val" not in key


def test_derive_key_declared_override_takes_precedence(fixture_db):
    """derived_keys.yaml に宣言があれば、自動探索を待たずにそれを使う。"""
    overrides = {
        "t_dims": {
            "key": ["site", "year", "kind"],
            "reason": "テスト: 宣言があれば自動探索より優先されることの確認",
        }
    }
    conn = common.open_readonly(fixture_db)
    try:
        key, source, note = common.derive_key(conn, "t_dims", overrides=overrides)
    finally:
        conn.close()
    assert key == ["site", "year", "kind"]
    assert source == "declared"
    assert "テスト" in note


def test_derive_key_raises_when_no_key_exists_and_no_override(fixture_db):
    """t_dupe は全列を使っても一意にならない（完全重複行がある）。
    宣言も無ければ、黙って全列をキーにせず例外で止まる。
    """
    conn = common.open_readonly(fixture_db)
    try:
        with pytest.raises(RuntimeError, match="derived_keys.yaml"):
            common.derive_key(conn, "t_dupe", overrides={})
    finally:
        conn.close()


def test_derive_key_declared_override_must_itself_be_unique(fixture_db):
    """宣言されたキーであっても一意性は検証する（宣言だから無条件で信用しない）。"""
    overrides = {"t_dupe": {"key": ["a", "b"], "reason": "テスト: わざと一意にならない宣言"}}
    conn = common.open_readonly(fixture_db)
    try:
        with pytest.raises(AssertionError):
            common.derive_key(conn, "t_dupe", overrides=overrides)
    finally:
        conn.close()


def test_format_number_fixed_six_decimals():
    assert common.format_number(1) == "1.000000"
    assert common.format_number(1.23456789) == "1.234568"
    assert common.format_number(0) == "0.000000"


def test_numeric_columns_of(fixture_db):
    """回帰テスト（レビュー指摘 B-3）。列ごとに別クエリを打っていたのを
    1テーブル1クエリにまとめた後も、判定結果自体は変わらないこと。
    """
    conn = common.open_readonly(fixture_db)
    try:
        columns = common.get_columns(conn, "t_dims")
        numeric = common.numeric_columns_of(conn, "t_dims", columns)
    finally:
        conn.close()
    assert numeric == ["year", "n", "avg"]


def test_numeric_columns_of_empty_columns_list(fixture_db):
    conn = common.open_readonly(fixture_db)
    try:
        assert common.numeric_columns_of(conn, "t_dims", []) == []
    finally:
        conn.close()


def test_compute_fingerprint_is_deterministic_across_two_runs(fixture_db):
    columns = ["site", "year", "kind", "n", "avg"]
    key = ["site", "year", "kind"]
    numeric = ["year", "n", "avg"]

    conn1 = common.open_readonly(fixture_db)
    fp1 = common.compute_fingerprint(datasource.SqliteSource(conn1), "t_dims", columns, key, numeric)
    conn1.close()

    conn2 = common.open_readonly(fixture_db)
    fp2 = common.compute_fingerprint(datasource.SqliteSource(conn2), "t_dims", columns, key, numeric)
    conn2.close()

    assert fp1 == fp2
    assert fp1["row_count"] == 4


def test_compute_fingerprint_detects_a_single_changed_value(fixture_db, tmp_path):
    import sqlite3

    columns = ["site", "year", "kind", "n", "avg"]
    key = ["site", "year", "kind"]
    numeric = ["year", "n", "avg"]

    conn = common.open_readonly(fixture_db)
    baseline_fp = common.compute_fingerprint(datasource.SqliteSource(conn), "t_dims", columns, key, numeric)
    conn.close()

    changed_path = tmp_path / "changed.sqlite"
    make_fixture_db(changed_path)
    edit_conn = sqlite3.connect(str(changed_path))
    edit_conn.execute("UPDATE t_dims SET avg = 9.99 WHERE site='s1' AND year=2020 AND kind='daily'")
    edit_conn.commit()
    edit_conn.close()

    conn2 = common.open_readonly(changed_path)
    changed_fp = common.compute_fingerprint(datasource.SqliteSource(conn2), "t_dims", columns, key, numeric)
    conn2.close()

    assert changed_fp["content_hash"] != baseline_fp["content_hash"]
    assert changed_fp["row_count"] == baseline_fp["row_count"]
    assert changed_fp["numeric_stats"]["avg"] != baseline_fp["numeric_stats"]["avg"]


# ---------------------------------------------------------------------------
# load_expected_diffs / validate_expected_diffs（変更9・CI 構造検証）
# ---------------------------------------------------------------------------

def test_load_expected_diffs_rejects_mapping_instead_of_list(tmp_path):
    """`meas_daily:` の直下に `key:`/`kind:` を書いてしまう（宣言のリストでは
    なくマッピングにしてしまう）と、以前はここでは何も検証しておらず、
    呼び出し側の `for d in diffs: d.get(...)` が文字列キーを回して
    `AttributeError: 'str' object has no attribute 'get'` という生のトレースバックに
    なっていた（レビュー指摘）。テーブル名を含む説明的なエラーで止まることを確認する。
    """
    path = tmp_path / "expected_diffs.yaml"
    path.write_text(
        "meas_daily:\n"
        "  key: [\"a\"]\n"
        "  kind: row_only_in_candidate\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="meas_daily"):
        common.load_expected_diffs(path)


def test_load_expected_diffs_accepts_well_formed_list(tmp_path):
    path = tmp_path / "expected_diffs.yaml"
    path.write_text(
        "meas_daily:\n"
        "  - key: [\"a\"]\n"
        "    kind: row_only_in_candidate\n",
        encoding="utf-8",
    )
    diffs = common.load_expected_diffs(path)
    assert diffs == {"meas_daily": [{"key": ["a"], "kind": "row_only_in_candidate"}]}


def test_load_expected_diffs_missing_file_returns_empty(tmp_path):
    assert common.load_expected_diffs(tmp_path / "does_not_exist.yaml") == {}


# `REQUIRED_DIFF_KEYS`（B-2）を満たす宣言の共通部分。`key`/`kind` 以外の必須項目
# （非空であること自体を検証する側の対象）を毎回書かずに済ませる。
_REQUIRED_EXTRAS = {"reason": "テスト用の理由", "found_on": "2026-09-08", "record": "テスト"}


def test_validate_expected_diffs_unknown_table_name_raises(tmp_path):
    with pytest.raises(SystemExit, match="no_such_table"):
        common.validate_expected_diffs(
            {"no_such_table": [{"key": ["a"], "kind": "row_only_in_candidate", **_REQUIRED_EXTRAS}]},
            {"t_pk": {"key": ["raw"]}},
            "expected_diffs.yaml",
        )


def test_validate_expected_diffs_bad_kind_raises():
    with pytest.raises(SystemExit, match="kind が不正"):
        common.validate_expected_diffs(
            {"t_pk": [{"key": ["a"], "kind": "not_a_real_kind", **_REQUIRED_EXTRAS}]},
            {"t_pk": {"key": ["raw"]}},
            "expected_diffs.yaml",
        )


def test_validate_expected_diffs_bad_key_length_raises():
    with pytest.raises(SystemExit, match="要素数"):
        common.validate_expected_diffs(
            {"t_dims": [{"key": ["a"], "kind": "row_only_in_candidate", **_REQUIRED_EXTRAS}]},
            {"t_dims": {"key": ["site", "year", "kind"]}},
            "expected_diffs.yaml",
        )


def test_validate_expected_diffs_accepts_well_formed_declaration():
    common.validate_expected_diffs(
        {"t_pk": [{"key": ["a"], "kind": "row_only_in_candidate", **_REQUIRED_EXTRAS}]},
        {"t_pk": {"key": ["raw"]}},
        "expected_diffs.yaml",
    )  # 例外を投げなければ良い


def test_validate_expected_diffs_missing_required_key_raises():
    """B-2: `reason`/`found_on`/`record` のいずれかが欠けていると、免除ゲート自体を
    免除する宣言なのに『なぜ免除するか』が機械可読な形で残らない。`kind`/`key`
    の検証と非対称にならないよう、こちらも欠落を検出して止まる。
    """
    with pytest.raises(SystemExit, match="必須項目が欠けている"):
        common.validate_expected_diffs(
            {"t_pk": [{"key": ["a"], "kind": "row_only_in_candidate"}]},  # reason 等が無い
            {"t_pk": {"key": ["raw"]}},
            "expected_diffs.yaml",
        )


def test_validate_expected_diffs_empty_required_value_raises():
    """`reason: ""` のように項目自体はあっても空文字なら、キーが欠けているのと
    同じ扱いで止まる（空文字1つで免除ゲートの説明義務を骨抜きにできないように）。
    """
    entry = {"key": ["a"], "kind": "row_only_in_candidate", **_REQUIRED_EXTRAS, "reason": ""}
    with pytest.raises(SystemExit, match="必須項目が欠けている"):
        common.validate_expected_diffs(
            {"t_pk": [entry]},
            {"t_pk": {"key": ["raw"]}},
            "expected_diffs.yaml",
        )


def test_load_destinations_covers_exactly_33_tables_with_no_duplicates():
    """ADR-0011「33テーブルの行き先」表の転記（`scripts/reconcile/
    adr0011_destinations.yaml`）が合計33件・重複無しであることを確認する
    （docs/plans/PHASE_B_DOCUMENTS.md の P-3 改訂で document_provenance/
    quality_workflow_log の2カテゴリを新設した後も合計が変わらないことの回帰。
    改訂前はこの合計を確かめる自動テストが無かった）。
    """
    flat = common.load_destinations(_DESTINATIONS_YAML)
    assert len(flat) == 33

    raw = common.load_yaml(_DESTINATIONS_YAML)
    all_tables = [t for spec in raw.values() for t in spec.get("tables", [])]
    assert len(all_tables) == len(set(all_tables)), "同じテーブル名が複数カテゴリに重複している"


def test_load_destinations_document_and_quality_tables_are_not_cube_observation():
    """P-3 決定: doc_series/doc_series_meta/quality_monthly の実際の入力は
    `observation` ではない（cells.sqlite/quality_transitions）ため、
    `cube_observation` から新設カテゴリへ移した（docs/plans/PHASE_B_DOCUMENTS.md）。
    """
    flat = common.load_destinations(_DESTINATIONS_YAML)
    assert flat["doc_series"]["category"] == "document_provenance"
    assert flat["doc_series_meta"]["category"] == "document_provenance"
    assert flat["quality_monthly"]["category"] == "quality_workflow_log"


def test_load_destinations_table_names_match_derived_baseline_exactly():
    """`adr0011_destinations.yaml` のテーブル名の集合が、実データから作った
    `reports/derived_baseline.json`（正）の33テーブルの集合と完全に一致する
    ことを確認する（コードレビュー指摘: 合計が33でも、打ち間違えた名前と
    書き漏らした名前が1対1で相殺すれば `len(flat) == 33` は通ってしまう。
    `b01_derived_baseline.py` の `render_markdown` は宣言に無いテーブルを
    黙って「（未分類）」にするだけで検出しない——このテストが唯一の歯止め）。
    `reports/derived_baseline.json` はコミット済みなので原本DBが無い環境
    （CI）でも読める。
    """
    flat = common.load_destinations(_DESTINATIONS_YAML)
    baseline = json.loads(_DERIVED_BASELINE_JSON.read_text(encoding="utf-8"))
    assert set(flat) == set(baseline["tables"])


def test_load_destinations_category_counts_match_the_declared_breakdown():
    """テーブル名の集合一致（前テスト）だけでは「正しい名前が誤ったカテゴリに
    入っている」事故を検出できない（集合演算はカテゴリをまたいで同じテーブル
    名を数える）。カテゴリごとの件数をヘッダコメントの内訳
    （12+11+1+2+3+1+2+1=33）と突き合わせる（コードレビュー指摘）。
    ラベル文言の一致までは見ない（YAML のヘッダコメントに明記のとおり、
    ADR-0011 の Markdown 本文との一致は対象外）。
    """
    raw = common.load_yaml(_DESTINATIONS_YAML)
    counts = {category: len(spec.get("tables", [])) for category, spec in raw.items()}
    assert counts == {
        "cube_observation": 12,
        "cube_occurrence": 11,
        "variable_registry": 1,
        "place_attribute": 2,
        "taxon_registry": 3,
        "fact_body": 1,
        "document_provenance": 2,
        "quality_workflow_log": 1,
    }


def test_load_projection_manifest_rejects_entry_without_script_or_tables(tmp_path):
    """`load_projection_manifest` は candidate ファイルごとの値が
    `{script, tables}` を持つマッピングになっていることを検証する。
    """
    bad = tmp_path / "bad_manifest.yaml"
    bad.write_text("v1_projection.sqlite:\n  tables: [meas_daily]\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="script/tables を持つマッピング"):
        common.load_projection_manifest(bad)


def test_load_projection_manifest_missing_file_raises_clearly(tmp_path):
    """`--manifest` の打ち間違いで存在しないパスを渡したときは、
    `load_yaml` の「無ければ空を返す」に頼らず、そう言って明示的に止まる
    （コードレビュー指摘: 黙って `{}` を返すと『33表と一致しない』という
    無関係なエラーに化けて原因が分かりにくい）。
    """
    missing = tmp_path / "does-not-exist.yaml"
    with pytest.raises(SystemExit, match=r"does-not-exist\.yaml.*無い"):
        common.load_projection_manifest(missing)


def test_load_projection_manifest_rejects_tables_with_no_value(tmp_path):
    """`tables:`（値が無い、YAML では `None`）だと `flatten_projection_manifest`
    の `for table in spec["tables"]` が生の `TypeError` になる——ここで
    弾いて分かるメッセージにする（コードレビュー指摘）。
    """
    bad = tmp_path / "bad_manifest.yaml"
    bad.write_text("v1_projection.sqlite:\n  script: scripts/b05_project_v1.py\n  tables:\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="tables"):
        common.load_projection_manifest(bad)


def test_load_projection_manifest_rejects_tables_as_a_bare_string(tmp_path):
    """`tables: meas_daily`（リストではなく1つの文字列）だと
    `for table in "meas_daily"` が1文字ずつ回ってしまう——ここで弾く
    （コードレビュー指摘）。
    """
    bad = tmp_path / "bad_manifest.yaml"
    bad.write_text(
        "v1_projection.sqlite:\n  script: scripts/b05_project_v1.py\n  tables: meas_daily\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="tables"):
        common.load_projection_manifest(bad)


def test_flatten_projection_manifest_raises_on_duplicate_table():
    """同じテーブル名が2つの candidate ファイルに重複して宣言されていたら、
    黙って後勝ちにせず例外を投げる（コピペミスの検出。`b02_run_all_gates.py`
    が同じ candidate を2回突き合わせて片方の結果を握りつぶす事故を防ぐ）。
    """
    manifest = {
        "a.sqlite": {"script": "scripts/x.py", "tables": ["t1", "t2"]},
        "b.sqlite": {"script": "scripts/y.py", "tables": ["t2"]},
    }
    with pytest.raises(SystemExit, match="t2.*重複"):
        common.flatten_projection_manifest(manifest)


def test_load_projection_manifest_covers_exactly_33_tables_with_no_duplicates():
    """`scripts/reconcile/projection_manifest.yaml`（33テーブル → (射影
    スクリプト, candidate ファイル) の対応表）が合計33件・重複無しであることを
    確認する（`test_load_destinations_covers_exactly_33_tables_with_no_duplicates`
    と同じ形）。
    """
    manifest = common.load_projection_manifest(_PROJECTION_MANIFEST_YAML)
    flat = common.flatten_projection_manifest(manifest)
    assert len(flat) == 33


def test_load_projection_manifest_table_set_matches_derived_baseline_exactly():
    """`projection_manifest.yaml` のテーブル名の集合が、実データから作った
    `reports/derived_baseline.json`（正）の33テーブルの集合と完全に一致する
    ことを確認する（`test_load_destinations_table_names_match_derived_baseline_exactly`
    と同じ形・同じ理由: 打ち間違えた名前と書き漏らした名前が1対1で相殺すれば
    件数一致だけのテストは通ってしまう）。
    """
    manifest = common.load_projection_manifest(_PROJECTION_MANIFEST_YAML)
    flat = common.flatten_projection_manifest(manifest)
    baseline = json.loads(_DERIVED_BASELINE_JSON.read_text(encoding="utf-8"))
    assert set(flat) == set(baseline["tables"])


def test_load_projection_manifest_candidate_file_counts_match_the_declared_breakdown():
    """candidate ファイルごとのテーブル数を、既知の内訳
    （13+13+3+2+2=33）と突き合わせる（`test_load_destinations_category_counts_
    match_the_declared_breakdown` と同じ考え方。正しいテーブル名が誤った
    candidate ファイルに入っている事故は、集合一致（前テスト）だけでは
    検出できない）。
    """
    manifest = common.load_projection_manifest(_PROJECTION_MANIFEST_YAML)
    counts = {candidate: len(spec.get("tables", [])) for candidate, spec in manifest.items()}
    assert counts == {
        "v1_projection.sqlite": 13,
        "v1_projection_occurrence.sqlite": 13,
        "v1_projection_documents.sqlite": 3,
        "v1_projection_place.sqlite": 2,
        "v1_projection_taxon.sqlite": 2,
    }


def test_load_projection_manifest_watershed_rollup_is_in_place_projection():
    """`watershed_rollup`（Phase B 最後の1表）が `v1_projection_place.sqlite`
    （`scripts/b11_project_place_v1.py`）に宣言されていることの回帰。
    """
    manifest = common.load_projection_manifest(_PROJECTION_MANIFEST_YAML)
    assert manifest["v1_projection_place.sqlite"]["script"] == "scripts/b11_project_place_v1.py"
    assert "watershed_rollup" in manifest["v1_projection_place.sqlite"]["tables"]
