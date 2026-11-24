"""縮小サンプル（Issue #29「縮小サンプル＋実行証明」）の成果物
（`data/sample/coverage.yaml`・`declaration_counts.yaml`・`manifest.json`）の構造検証と、
コミット済みのサンプル本体（`data/sample/ryuiki/*.sql`・`cells/*.sql`）に対する
「宣言どおりに入っているか」の検証（A-1「pytest は検証として使う」）。
（Issue #48 PR-5 で v1 との突合〔`derived_keys.yaml`・`derived_baseline.json`・
`expected_diffs.yaml`〕は無くなった。）

**原本DB（data/db/*.sqlite、14GB）は一切使わない**——ここで使うのはすべて
コミット済みのテキスト（`data/sample/`）と、`scripts/migrate/*.yaml`
（正本の宣言。小さい・原本を必要としない）だけ。
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
from ingest import manifest as manifest_lib  # noqa: E402
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
    s01.register_dedup_functions(c)   # coverage.yaml の重複ペアの述語（Issue #125）
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


# 6つの宣言ファイルのパス。以前はファイルごとに手で書き写した
# `_flat_keys_for_*`（7個）を個別に持っており、キーの有効性判定
# （`expected_row_count`/`expected_count`/`breakdown` の見方）を
# `scripts/migrate/period.py` の `apply_count_overlay()` と2箇所で
# 重複させていた——正本にキーの種類が増えても追従し忘れる余地があった
# （code-review 指摘対応）。今は判定条件そのものを持つ
# `period.declared_overlay_keys()` を呼ぶだけにし、ここではファイルの
# パスと「どこが entries か」（`manifests` だけ `manifests/*.yml` から
# `expected_row_count` を持つ出典を集める。Issue #40 Phase D）だけを持つ。
_DECLARATION_FILE_PATHS = {
    name: ROOT / "scripts" / "migrate" / name
    for name in (
        "period_exceptions.yaml",
        "time_label_conventions.yaml",
        "occurrence_period_shapes.yaml",
        "occurrence_cube_declarations.yaml",
        "occurrence_place_declarations.yaml",
    )
}


def _declared_entries_for(filename: str) -> dict:
    if filename == "manifests":
        return {
            sid: {
                "expected_row_count": m.expected_row_count,
                **({"breakdown": m.count_breakdown} if m.count_breakdown else {}),
            }
            for sid, m in manifest_lib.load_manifests().items() if m.expected_row_count is not None
        }
    return load_yaml(_DECLARATION_FILE_PATHS[filename])


@pytest.mark.parametrize("filename", sorted(_DECLARATION_FILE_PATHS) + ["manifests"])
def test_declaration_counts_keys_match_declared_entries_exactly(filename):
    grouped = period.load_count_overlay_file(SAMPLE_DIR / "declaration_counts.yaml")
    overlay_keys = set(grouped.get(filename, {}))
    declared_keys = period.declared_overlay_keys(_declared_entries_for(filename))
    if filename == "manifests":   # builtin × occurrence の manifest の expected も overlay が差し替える
        declared_keys |= manifest_lib.expected_overlay_keys(manifest_lib.load_manifests())
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


def test_sample_contains_duplicate_pairs_that_b06_excludes(conn):
    """Issue #125: サンプルに、GBIF 経由の iNaturalist 観察と直取得の重複ペアが神奈川・奄美とも入っている
    （CI の sample-gate が b06 の除外の経路を通る）。"""
    for gbif, direct in (("gbif_kanagawa_occurrences", "inaturalist_kanagawa"), ("gbif_amami_occurrences", "inaturalist_amami")):
        n = conn.execute(
            "SELECT COUNT(*) FROM organism_records g WHERE g.source_id = ? AND g.source_ref IN "
            "(SELECT source_ref FROM organism_records WHERE source_id = ?)", (gbif, direct),
        ).fetchone()[0]
        assert n >= 2, f"{gbif}: 直取得と source_ref が一致する行が {n} 件"


def test_s01_dup_rows_agree_with_b06_independent_join_on_sample(materialized_db, conn):
    """s01 が宣言件数から除く重複行（`is_dup_row`。サンプルの選択行の中での判定）が、サンプルに b06 を当てたときの除外件数
    （b06 が結合で独立に数える重複件数）と出典ごとに一致する。一致しないと sample-gate の件数宣言が合わない。"""
    import b06_build_occurrence as b06
    from migrate import source_regions

    sources, _regions = source_regions.load_source_regions(consumer="occurrence")
    pairs = b06._dedup_pairs(sources)
    assert pairs, "dedup_against を宣言した出典が無い"
    s01.register_dedup_functions(conn, from_sql="organism_records")
    s01_counts = {
        sid: conn.execute(
            "SELECT COUNT(*) FROM organism_records WHERE source_id = ? AND is_dup_row(source_id, source_ref) "
            "AND COALESCE(is_synthetic, 0) <> 1 AND occurrence_status IS NOT 'ABSENT'", (sid,),
        ).fetchone()[0]
        for sid in pairs
    }
    work = sqlite3.connect("file::memory:", uri=True)
    work.execute("ATTACH DATABASE ? AS src", (f"file:{materialized_db}?mode=ro",))
    b06_counts = b06._count_duplicates_by_join(work, pairs)
    work.close()
    assert s01_counts == b06_counts
    assert all(n >= 2 for n in b06_counts.values()), b06_counts
