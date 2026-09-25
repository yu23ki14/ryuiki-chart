"""縮小サンプル（Issue #29「縮小サンプル＋実行証明」）の成果物
（`data/sample/coverage.yaml`・`declaration_counts.yaml`・`derived_keys.yaml`・
`manifest.json`）の構造検証と、コミット済みのサンプル本体
（`data/sample/ryuiki/*.sql`・`cells/*.sql`）に対する「宣言どおりに入っているか」
の検証（A-1「pytest は検証として使う」）。宣言済み差分（`expected_diffs.yaml`）は
サンプル専用ファイルを持たず、正本（`scripts/reconcile/expected_diffs.yaml`）を
そのまま使う（下の該当節参照）。

**原本DB（data/db/*.sqlite、14GB）は一切使わない**——ここで使うのはすべて
コミット済みのテキスト（`data/sample/`）と、`scripts/reconcile/*.yaml`/
`scripts/migrate/*.yaml`（正本の宣言。小さい・原本を必要としない）だけ。
`s02_materialize_sample.py` で一時ディレクトリに材料化した sqlite に対して
実際に SQL を投げて検証する。
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SAMPLE_DIR = ROOT / "data" / "sample"

sys.path.insert(0, str(ROOT / "scripts"))

import pipeline_inputs  # noqa: E402
import s01_build_sample as s01  # noqa: E402
import s02_materialize_sample as s02  # noqa: E402
from migrate import period  # noqa: E402
from reconcile.common import load_yaml  # noqa: E402


pytestmark = pytest.mark.skipif(
    not (SAMPLE_DIR / "coverage.yaml").exists(),
    reason="data/sample/ が無い（まだ scripts/s01_build_sample.py を実行していない環境）",
)


@pytest.fixture(scope="module")
def coverage() -> dict:
    return load_yaml(SAMPLE_DIR / "coverage.yaml")


@pytest.fixture(scope="module")
def materialized_db(tmp_path_factory) -> pathlib.Path:
    """`data/sample/` をコミット済みのまま一時ディレクトリに材料化する
    （module スコープ: このファイル内の全テストで1回だけ作る。原本は使わない）。
    """
    tmp_dir = tmp_path_factory.mktemp("sample_materialize")
    data_db_dir = tmp_dir / "data" / "db"
    processed_dir = tmp_dir / "data" / "processed"
    s02.materialize(SAMPLE_DIR, data_db_dir, processed_dir)
    return data_db_dir / "ryuiki.sqlite"


@pytest.fixture(scope="module")
def conn(materialized_db) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{materialized_db}?mode=ro", uri=True)
    # coverage.yaml の occurrence_shape_* predicate が classify_shape(observed_on)
    # を使う（s01_build_sample._open_ro が本番で登録するのと同じ関数。
    # code-review 指摘対応: length(observed_on) の近似をやめて実際の
    # 分類関数に揃えた）。
    s01.register_classify_shape(c)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# coverage.yaml の構造
# ---------------------------------------------------------------------------


def test_predicates_have_required_fields(coverage):
    for pred in coverage["predicates"]:
        assert set(pred) >= {"name", "table", "where", "min_rows"}
        assert isinstance(pred["min_rows"], int) and pred["min_rows"] > 0
        assert pred["table"] in ("measurements", "sensor_timeseries", "organism_records")


def test_predicate_names_are_unique(coverage):
    names = [p["name"] for p in coverage["predicates"]]
    assert len(names) == len(set(names))


def test_full_closures_have_required_fields(coverage):
    for closure in coverage["full_closures"]:
        assert set(closure) >= {"name", "table", "where", "reason"}


def test_document_closure_meets_min_documents(coverage):
    dc = coverage["document_closure"]
    assert len(dc["doc_ids"]) >= dc["min_documents"]
    assert len(dc["doc_ids"]) == len(set(dc["doc_ids"]))


def test_wholesale_lists_are_non_empty(coverage):
    assert coverage["wholesale_ryuiki_tables"]
    assert coverage["wholesale_cells_tables"]
    assert coverage["wholesale_processed_files"]


# ---------------------------------------------------------------------------
# 「入れたつもりが入っていない」が起きないことの検証（A-1）:
# coverage.yaml の predicates/full_closures を、材料化したサンプルに対して
# 実際に評価し、min_rows 以上（full_closures は1件以上）あることを確認する。
# ---------------------------------------------------------------------------


def test_predicates_are_satisfied_in_materialized_sample(conn, coverage):
    problems = []
    for pred in coverage["predicates"]:
        n = conn.execute(f'SELECT COUNT(*) FROM "{pred["table"]}" WHERE {pred["where"]}').fetchone()[0]
        if n < pred["min_rows"]:
            problems.append(f"{pred['name']}: {n}行（min_rows={pred['min_rows']}）")
    assert not problems, "predicate が min_rows を満たさない:\n" + "\n".join(problems)


def test_full_closures_are_non_empty_in_materialized_sample(conn, coverage):
    problems = []
    for closure in coverage["full_closures"]:
        n = conn.execute(f'SELECT COUNT(*) FROM "{closure["table"]}" WHERE {closure["where"]}').fetchone()[0]
        if n < 1:
            problems.append(closure["name"])
    assert not problems, "full_closures が1件も無い:\n" + "\n".join(problems)


def test_wholesale_ryuiki_tables_have_rows(conn, coverage):
    for table in coverage["wholesale_ryuiki_tables"]:
        n = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        assert n > 0, f"{table} が0行（丸ごと入れるはずのテーブル）"


# ---------------------------------------------------------------------------
# declaration_counts.yaml: 上書きのキーの集合が正本のエントリの集合と
# 過不足なく一致すること（A-2 のオーナー要件）。
# ---------------------------------------------------------------------------


# 7つの宣言ファイルのパス。以前はファイルごとに手で書き写した
# `_flat_keys_for_*`（7個）を個別に持っており、キーの有効性判定
# （`expected_row_count`/`expected_count`/`breakdown` の見方）を
# `scripts/migrate/period.py` の `apply_count_overlay()` と2箇所で
# 重複させていた——正本にキーの種類が増えても追従し忘れる余地があった
# （code-review 指摘対応）。今は判定条件そのものを持つ
# `period.declared_overlay_keys()` を呼ぶだけにし、ここではファイルの
# パスと「YAML のどこが entries か」（`source_regions.yaml` だけ
# `raw["sources"]`）だけを持つ。
_DECLARATION_FILE_PATHS = {
    name: ROOT / "scripts" / "migrate" / name
    for name in (
        "period_exceptions.yaml",
        "time_label_conventions.yaml",
        "source_regions.yaml",
        "occurrence_period_shapes.yaml",
        "occurrence_cube_declarations.yaml",
        "occurrence_place_declarations.yaml",
        "occurrence_watershed_v1_declarations.yaml",
    )
}


def _declared_entries_for(filename: str) -> dict:
    raw = load_yaml(_DECLARATION_FILE_PATHS[filename])
    if filename == "source_regions.yaml":
        return raw.get("sources") or {}
    return raw


@pytest.mark.parametrize("filename", sorted(_DECLARATION_FILE_PATHS))
def test_declaration_counts_keys_match_declared_entries_exactly(filename):
    grouped = period.load_count_overlay_file(SAMPLE_DIR / "declaration_counts.yaml")
    overlay_keys = set(grouped.get(filename, {}))
    declared_keys = period.declared_overlay_keys(_declared_entries_for(filename))
    missing = declared_keys - overlay_keys
    extra = overlay_keys - declared_keys
    assert not missing and not extra, (
        f"{filename}: declaration_counts.yaml のキーが正本のエントリと一致しない"
        f"（不足: {sorted(missing)} / 余分: {sorted(extra)}）"
    )


def test_declaration_counts_values_are_non_negative_ints():
    grouped = period.load_count_overlay_file(SAMPLE_DIR / "declaration_counts.yaml")
    for filename, entries in grouped.items():
        for name, value in entries.items():
            assert isinstance(value, int) and not isinstance(value, bool) and value >= 0, (
                f"{filename}:{name} の値が非負整数でない: {value!r}"
            )


# ---------------------------------------------------------------------------
# derived_keys.yaml: サンプルのキーが全量ベースラインの33表と過不足なく一致すること（A-3）。
# ---------------------------------------------------------------------------


def test_derived_keys_yaml_matches_full_baseline_exactly():
    baseline_path = ROOT / "reports" / "derived_baseline.json"
    if not baseline_path.exists():
        pytest.skip("reports/derived_baseline.json が無い")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    sample_keys = load_yaml(SAMPLE_DIR / "derived_keys.yaml")

    missing = set(baseline["tables"]) - set(sample_keys)
    extra = set(sample_keys) - set(baseline["tables"])
    assert not missing and not extra, (
        f"derived_keys.yaml のテーブル集合が derived_baseline.json と一致しない"
        f"（不足: {sorted(missing)} / 余分: {sorted(extra)}）"
    )
    mismatched = {
        table: (baseline["tables"][table]["key"], sample_keys[table]["key"])
        for table in baseline["tables"]
        if baseline["tables"][table]["key"] != sample_keys[table]["key"]
    }
    assert not mismatched, f"key が全量ベースラインと食い違うテーブル: {mismatched}"


# ---------------------------------------------------------------------------
# derived_baseline.json（サンプル自身のベースライン。s03 が原本無しで作り直せる）
# ---------------------------------------------------------------------------


def test_sample_derived_baseline_json_has_33_tables():
    path = SAMPLE_DIR / "derived_baseline.json"
    if not path.exists():
        pytest.skip("data/sample/derived_baseline.json が無い")
    baseline = json.loads(path.read_text(encoding="utf-8"))
    assert baseline["table_count"] == 33
    assert len(baseline["tables"]) == 33


# ---------------------------------------------------------------------------
# manifest.json
# ---------------------------------------------------------------------------


def test_manifest_json_has_required_fields():
    manifest = json.loads((SAMPLE_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest) >= {"source_files", "row_counts"}
    # キーの形は pipeline_inputs.SOURCE_FILE_KEYS（"data/db/ryuiki.sqlite" 形）で
    # 統一する（scripts/b00_run_full_gate.py の source_hashes() と共通。
    # レビュー指摘: 以前はここだけ "ryuiki.sqlite" 形で、証明側と食い違っていた）。
    assert set(manifest["source_files"]) == set(pipeline_inputs.SOURCE_FILE_KEYS)
    for name, digest in manifest["source_files"].items():
        assert len(digest) == 64, f"{name} の sha256 の桁数が64でない: {digest!r}"


# ---------------------------------------------------------------------------
# expected_diffs.yaml: サンプルは正本（scripts/reconcile/expected_diffs.yaml）を
# そのまま使う（レビュー対応で sample 専用ファイルを廃止した——閉包の取り方
# （Sirosporium の投票元3行）を直した結果、正本の20キー全部がサンプル規模でも
# 再現するようになったため、免除を維持する理由が無くなった。宣言済み差分>
# データを曲げる、の原則どおり「サンプルに合わせて宣言を弱める」のではなく
# 「サンプル側を正しく作る」を選んだ）。
# ---------------------------------------------------------------------------


def test_no_sample_specific_expected_diffs_file_exists():
    """`data/sample/expected_diffs.yaml` を復活させていないことを確認する
    （復活させたくなったら、まずこのテストと本ファイルの上のコメントを読むこと）。
    """
    assert not (SAMPLE_DIR / "expected_diffs.yaml").exists()
