"""scripts/b11_project_place_v1.py の統合テスト（Phase B `phase-b/place-attributes`、
P-1a）。

本物の `data/db/registry.sqlite` を要さない: `registry.common.create_registry_db()`
で空の registry.sqlite を作り、place / place_watershed / place_source_ref に
検証したい行だけを直接 INSERT する（scripts/tests/test_r01_invariants.py と同じ流儀）。
"""
import sqlite3

import pytest

import b11_project_place_v1 as b11
from migrate import common as migrate_common
from registry import common as registry_common

_WATERSHED_ROW = {
    "place_id": "common:place:watershed.nlni-83032-0024",
    "watershed_id": "83032-0024",
    "name_ja": "相模川",
    "lat": 35.1,
    "lon": 139.2,
    "area_km2": 1.2,
    "definition_ref": "https://example.invalid/w12",
    "water_system_code": "83032",
    "water_system_category": "一級河川を含む単一水系域",
    "main_rivers": "相模川|中津川",
    "data_year": 1977,
}


def _insert_watershed_place(conn, row) -> None:
    conn.execute(
        "INSERT INTO place (place_id, region_id, place_kind, name_ja, lat, lon, "
        "elevation_m, area_km2, definition_ref, status) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            row["place_id"], None, "watershed", row.get("name_ja"),
            row.get("lat"), row.get("lon"), None, row.get("area_km2"),
            row.get("definition_ref"), "ok",
        ),
    )
    conn.execute(
        "INSERT INTO place_source_ref (place_id, external_key, source_id) VALUES (?,?,?)",
        (row["place_id"], row["watershed_id"], "watershed_meta.watershed_id"),
    )
    conn.execute(
        "INSERT INTO place_watershed "
        "(place_id, water_system_code, water_system_category, main_rivers, data_year) "
        "VALUES (?,?,?,?,?)",
        (
            row["place_id"], row.get("water_system_code"), row.get("water_system_category"),
            row.get("main_rivers"), row.get("data_year"),
        ),
    )


def _make_registry_db(path, watershed_rows=()) -> None:
    conn = registry_common.create_registry_db(path)
    try:
        for row in watershed_rows:
            _insert_watershed_place(conn, row)
        conn.commit()
    finally:
        conn.close()


# --- watershed_rollup が ATTACH する2つの射影出力の最小フィクスチャ ---------


def _make_v1_projection_db(path, site_var_rows=(), landuse_rows=()) -> None:
    """`site_var`/`landuse_watershed` だけを持つ最小の `v1_projection.sqlite`
    フィクスチャ（`scripts/b05_project_v1.py` の出力の代わり）。列名・列順は
    `scripts/b05_project_v1.py` の `_CREATE_SQL` と一致させてある。
    """
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE site_var (site_id TEXT, variable TEXT, kind TEXT, n INTEGER, "
            "y_from INTEGER, y_to INTEGER, avg REAL, unit TEXT)"
        )
        conn.executemany("INSERT INTO site_var VALUES (?,?,?,?,?,?,?,?)", list(site_var_rows))
        conn.execute(
            "CREATE TABLE landuse_watershed (watershed_id TEXT, year INTEGER, landuse_code TEXT, "
            "landuse_name TEXT, n_cells INTEGER, area_km2 REAL)"
        )
        conn.executemany("INSERT INTO landuse_watershed VALUES (?,?,?,?,?,?)", list(landuse_rows))
        conn.commit()
    finally:
        conn.close()


def _make_v1_projection_occurrence_db(path, org_watershed_rows=()) -> None:
    """`org_watershed` だけを持つ最小の `v1_projection_occurrence.sqlite`
    フィクスチャ（`scripts/b08_project_occurrence_v1.py` の出力の代わり）。
    """
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE org_watershed (watershed_id TEXT, n, alien_n, redlist_n, y_from, y_to)"
        )
        conn.executemany("INSERT INTO org_watershed VALUES (?,?,?,?,?,?)", list(org_watershed_rows))
        conn.commit()
    finally:
        conn.close()


def _rollup_kwargs(tmp_path, *, site_var_rows=(), landuse_rows=(), org_watershed_rows=()):
    """watershed_rollup が ATTACH する2つの射影出力を最小フィクスチャで作り、
    `b11.build_projections(..., **_rollup_kwargs(tmp_path))` の形でそのまま
    渡せる kwargs にする。中身を検証しないテストは既定（空）のままでよい——
    watershed_rollup 自体は空の proj/occ でも正しく1行を作る
    （org_n 等は COALESCE で 0、site_n/site_var_n は 0、土地利用4組は NULL）。
    """
    proj_db = tmp_path / "v1_projection.sqlite"
    occ_db = tmp_path / "v1_projection_occurrence.sqlite"
    _make_v1_projection_db(proj_db, site_var_rows, landuse_rows)
    _make_v1_projection_occurrence_db(occ_db, org_watershed_rows)
    return {"v1_projection_db": proj_db, "v1_projection_occurrence_db": occ_db}


def test_insert_sql_declares_explicit_column_list():
    """`_INSERT_WATERSHED_META_SQL` が `INSERT INTO watershed_meta (列名...)` の形で
    列名を明示していること（code-review 指摘8: CREATE の列順と SELECT の列順という
    2つの離れたリテラルを手で揃える暗黙の位置合わせにしない）。
    """
    expected = f"INSERT INTO watershed_meta ({', '.join(b11._WATERSHED_META_COLUMNS)})"
    assert expected in b11._INSERT_WATERSHED_META_SQL


def test_projects_watershed_meta_with_v1_column_order_and_types(tmp_path):
    """列名・列順・値が v1（`reports/derived_baseline.json` の `watershed_meta`
    エントリ）と一致すること（受け入れ条件1の単体版）。
    """
    registry_db = tmp_path / "registry.sqlite"
    _make_registry_db(registry_db, [_WATERSHED_ROW])
    out_db = tmp_path / "v1_projection_place.sqlite"

    counts = b11.build_projections(registry_db, out_db, **_rollup_kwargs(tmp_path))
    assert counts == {"watershed_meta": 1, "watershed_rollup": 1}

    conn = sqlite3.connect(out_db)
    conn.row_factory = sqlite3.Row
    try:
        cols = [d[1] for d in conn.execute("PRAGMA table_info(watershed_meta)")]
        assert cols == [
            "watershed_id", "water_system_code", "water_system_name",
            "water_system_category", "main_rivers", "area_km2",
            "centroid_lat", "centroid_lon", "data_year", "source_ref",
        ]
        row = conn.execute("SELECT * FROM watershed_meta").fetchone()
        assert row["watershed_id"] == "83032-0024"
        assert row["water_system_code"] == "83032"
        assert row["water_system_name"] == "相模川"
        assert row["water_system_category"] == "一級河川を含む単一水系域"
        assert row["main_rivers"] == "相模川|中津川"
        assert row["area_km2"] == pytest.approx(1.2)
        assert row["centroid_lat"] == pytest.approx(35.1)
        assert row["centroid_lon"] == pytest.approx(139.2)
        assert row["data_year"] == 1977
        assert row["source_ref"] == "https://example.invalid/w12"
    finally:
        conn.close()


def test_main_rivers_empty_string_is_preserved_not_coerced_to_null(tmp_path):
    """v1（`?? null`）に合わせ、main_rivers の空文字列を NULL に丸めない
    （docs/plans/PHASE_B_PLACE_ATTRIBUTES.md 実測: main_rivers 234/377 のみ非空）。
    """
    row = dict(_WATERSHED_ROW, place_id="common:place:watershed.nlni-x", watershed_id="x", main_rivers="")
    registry_db = tmp_path / "registry.sqlite"
    _make_registry_db(registry_db, [row])
    out_db = tmp_path / "v1_projection_place.sqlite"

    b11.build_projections(registry_db, out_db, **_rollup_kwargs(tmp_path))

    conn = sqlite3.connect(out_db)
    try:
        value = conn.execute("SELECT main_rivers FROM watershed_meta").fetchone()[0]
    finally:
        conn.close()
    assert value == ""
    assert value is not None


def test_name_ja_null_becomes_water_system_name_null(tmp_path):
    row = dict(
        _WATERSHED_ROW, place_id="common:place:watershed.nlni-y", watershed_id="y", name_ja=None
    )
    registry_db = tmp_path / "registry.sqlite"
    _make_registry_db(registry_db, [row])
    out_db = tmp_path / "v1_projection_place.sqlite"

    b11.build_projections(registry_db, out_db, **_rollup_kwargs(tmp_path))

    conn = sqlite3.connect(out_db)
    try:
        value = conn.execute("SELECT water_system_name FROM watershed_meta").fetchone()[0]
    finally:
        conn.close()
    assert value is None


def test_ignores_non_watershed_places(tmp_path):
    """place_kind が 'watershed' 以外の place（site 等）は射影対象に混ざらない。"""
    registry_db = tmp_path / "registry.sqlite"
    conn = registry_common.create_registry_db(registry_db)
    try:
        _insert_watershed_place(conn, _WATERSHED_ROW)
        conn.execute(
            "INSERT INTO place (place_id, region_id, place_kind, name_ja, status) "
            "VALUES (?,?,?,?,?)",
            ("jp-14:place:site.jma-s1", "jp-14", "site", "地点1", "ok"),
        )
        conn.commit()
    finally:
        conn.close()
    out_db = tmp_path / "v1_projection_place.sqlite"

    counts = b11.build_projections(registry_db, out_db, **_rollup_kwargs(tmp_path))
    assert counts == {"watershed_meta": 1, "watershed_rollup": 1}


def test_missing_place_watershed_table_raises_clear_error(tmp_path):
    """`place_watershed` テーブル自体が無い（P-1a より前にビルドした古い
    registry.sqlite を渡した）場合、素の `sqlite3.OperationalError`（no such table）
    ではなく「r01 を実行し直せ」と分かる `MigrationError` で止まる
    （`scripts/b05_project_v1.py` の `_assert_place_relation_table_exists` と同じ形）。
    """
    registry_db = tmp_path / "registry.sqlite"
    conn = registry_common.create_registry_db(registry_db)
    try:
        conn.execute("DROP TABLE place_watershed")
        conn.commit()
    finally:
        conn.close()

    out_db = tmp_path / "v1_projection_place.sqlite"
    with pytest.raises(migrate_common.MigrationError, match="place_watershed テーブルが無い"):
        b11.build_projections(registry_db, out_db)


def test_duplicate_source_ref_per_place_raises_and_does_not_inflate_rows(tmp_path):
    """同じ place に `place_source_ref(source_id='watershed_meta.watershed_id')` の
    行が2つあると、INNER JOIN がその place を2回ヒットさせて行が水増しされる
    （377→378 のような一番気づきにくい壊れ方）。これを `place_id` で GROUP BY して
    検出する（code-review 指摘: 以前は `external_key` で GROUP BY しており、この
    水増しを検出できていなかった——同じ external_key が別々の place に対応する
    ケース（`external_key` 側の重複）は水増しを起こさないので誤検出だった）。
    """
    registry_db = tmp_path / "registry.sqlite"
    conn = registry_common.create_registry_db(registry_db)
    try:
        _insert_watershed_place(conn, _WATERSHED_ROW)
        # 同じ place_id にもう1件、別の external_key で place_source_ref を足す
        # （水増しの原因になる本物の重複）。
        conn.execute(
            "INSERT INTO place_source_ref (place_id, external_key, source_id) VALUES (?,?,?)",
            (_WATERSHED_ROW["place_id"], "83032-0024-dup", "watershed_meta.watershed_id"),
        )
        conn.commit()
    finally:
        conn.close()
    out_db = tmp_path / "v1_projection_place.sqlite"

    with pytest.raises(migrate_common.MigrationError, match="place_id について単射でない"):
        b11.build_projections(registry_db, out_db)


def test_two_places_sharing_the_same_external_key_is_not_flagged_as_inflation(tmp_path):
    """2つの異なる place が同じ v1 の watershed_id（external_key）を指していても、
    それぞれの place 自身は `place_source_ref` を1件しか持たないので、行の水増し
    （b11 が独立に防ぐ対象）は起きない——このケースを誤って止めない
    （旧実装は `external_key` で GROUP BY しており、このケースを誤検出していた）。
    """
    row_a = dict(_WATERSHED_ROW, place_id="common:place:watershed.nlni-a")
    row_b = dict(_WATERSHED_ROW, place_id="common:place:watershed.nlni-b")  # 同じ watershed_id
    registry_db = tmp_path / "registry.sqlite"
    _make_registry_db(registry_db, [row_a, row_b])
    out_db = tmp_path / "v1_projection_place.sqlite"

    counts = b11.build_projections(registry_db, out_db, **_rollup_kwargs(tmp_path))
    assert counts == {"watershed_meta": 2, "watershed_rollup": 2}


def test_failed_validation_does_not_touch_previous_output(tmp_path):
    """検証（`_validate_registry`）が失敗したときは `common.fresh_sqlite(out_path)`
    を一切呼ばない——前回の正しい出力ファイルがバイト単位で残る（code-review
    指摘4: 以前は `fresh_sqlite(out)` を検証より先に呼んでおり、検証失敗時に
    前回の出力が消えて空/半端なファイルが残っていた）。
    """
    registry_db = tmp_path / "registry.sqlite"
    _make_registry_db(registry_db, [_WATERSHED_ROW])
    out_db = tmp_path / "v1_projection_place.sqlite"

    # 1回目: 正しい出力を作る
    b11.build_projections(registry_db, out_db, **_rollup_kwargs(tmp_path))
    before = out_db.read_bytes()

    # 2回目の直前に registry.sqlite を壊す（place_watershed テーブルを消す）。
    conn = sqlite3.connect(registry_db)
    try:
        conn.execute("DROP TABLE place_watershed")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(migrate_common.MigrationError):
        b11.build_projections(registry_db, out_db)

    after = out_db.read_bytes()
    assert after == before  # 前回の出力が1バイトも変わっていない


def test_output_is_rebuilt_from_scratch_each_run(tmp_path):
    """`common.fresh_sqlite` により毎回ゼロから作り直す（前回実行の残骸で
    行が重複しない）。"""
    registry_db = tmp_path / "registry.sqlite"
    _make_registry_db(registry_db, [_WATERSHED_ROW])
    out_db = tmp_path / "v1_projection_place.sqlite"
    kwargs = _rollup_kwargs(tmp_path)

    b11.build_projections(registry_db, out_db, **kwargs)
    b11.build_projections(registry_db, out_db, **kwargs)

    conn = sqlite3.connect(out_db)
    try:
        n_meta = conn.execute("SELECT COUNT(*) FROM watershed_meta").fetchone()[0]
        n_rollup = conn.execute("SELECT COUNT(*) FROM watershed_rollup").fetchone()[0]
    finally:
        conn.close()
    assert n_meta == 1
    assert n_rollup == 1


# ---------------------------------------------------------------------------
# watershed_rollup（v1: web/scripts/build-geo.mjs:227-251。「ゲートの統合」
# 実装指示 §A）
# ---------------------------------------------------------------------------


def _insert_site_place_with_watershed_edge(conn, *, site_place_id, site_id, watershed_place_id) -> None:
    """地点 place を作り、`place_source_ref(source_id='sites.site_id')` と
    `place_relation`（地点→流域、`relation='within'`）の辺を張る
    （`scripts/registry/build_place.py` の `_watershed_relation_rows` が
    実データで作る形と同じ。`test_ignores_non_watershed_places` の site 挿入と
    同じ最小列）。
    """
    conn.execute(
        "INSERT INTO place (place_id, region_id, place_kind, name_ja, status) VALUES (?,?,?,?,?)",
        (site_place_id, "jp-14", "site", "地点", "ok"),
    )
    conn.execute(
        "INSERT INTO place_source_ref (place_id, external_key, source_id) VALUES (?,?,?)",
        (site_place_id, site_id, "sites.site_id"),
    )
    conn.execute(
        "INSERT INTO place_relation (parent_id, child_id, relation, fraction, basis) VALUES (?,?,?,?,?)",
        (watershed_place_id, site_place_id, "within", 1.0, "test"),
    )


def test_watershed_rollup_column_order_and_types_match_v1(tmp_path):
    """`watershed_rollup` の列名・列順・宣言型（storage class）が v1
    （`reports/derived_baseline.json` の実測: 直接の列参照5つは TEXT/REAL、
    残り11列は無型）と一致すること。CTAS（`_CREATE_WATERSHED_ROLLUP_SQL`）が
    v1 と同じ SQL 構造を持つことの単体テスト——モジュール docstring
    「watershed_rollup」節参照。
    """
    registry_db = tmp_path / "registry.sqlite"
    _make_registry_db(registry_db, [_WATERSHED_ROW])
    out_db = tmp_path / "v1_projection_place.sqlite"

    b11.build_projections(registry_db, out_db, **_rollup_kwargs(tmp_path))

    conn = sqlite3.connect(out_db)
    try:
        info = [(r[1], r[2]) for r in conn.execute("PRAGMA table_info(watershed_rollup)")]
    finally:
        conn.close()
    assert [c for c, _ in info] == list(b11._WATERSHED_ROLLUP_COLUMNS)
    typed = {"watershed_id": "TEXT", "water_system_name": "TEXT", "area_km2": "REAL",
             "centroid_lat": "REAL", "centroid_lon": "REAL"}
    for col, decl in info:
        assert decl == typed.get(col, ""), f"{col}: {decl!r}"


def test_watershed_rollup_aggregates_org_watershed_site_var_and_landuse(tmp_path):
    """4つの入力（watershed_meta 自身・org_watershed・site_var・
    landuse_watershed）がそれぞれ正しく結合されること。`site_n`/`site_var_n`
    は `place_relation`（sites.watershed 由来）経由で解決し、点内包判定は
    一切行わない（モジュール docstring 参照）。土地利用は区分・年の組が
    存在しない場合 NULL のまま（v1 と同じ、CASE...ELSE 0 の丸めは無い）。
    """
    row = dict(
        _WATERSHED_ROW,
        place_id="common:place:watershed.nlni-r1",
        watershed_id="r1",
        name_ja="実験川",
        lat=35.0,
        lon=139.0,
        area_km2=2.0,
    )
    registry_db = tmp_path / "registry.sqlite"
    conn = registry_common.create_registry_db(registry_db)
    try:
        _insert_watershed_place(conn, row)
        _insert_site_place_with_watershed_edge(
            conn, site_place_id="jp-14:place:site.s1", site_id="site-1",
            watershed_place_id=row["place_id"],
        )
        conn.commit()
    finally:
        conn.close()

    out_db = tmp_path / "v1_projection_place.sqlite"
    kwargs = _rollup_kwargs(
        tmp_path,
        # site-2 は流域に紐付いていない地点なので site_var_n に混ざってはいけない。
        site_var_rows=[
            ("site-1", "水温", "daily", 10, 2001, 2010, 15.5, "℃"),
            ("site-1", "pH", "daily", 5, 2001, 2005, 7.0, None),
            ("site-2", "水温", "daily", 3, 2001, 2003, 10.0, "℃"),
        ],
        landuse_rows=[
            ("r1", 2016, "05", "建物用地", 10, 1.5),
            ("r1", 2006, "05", "建物用地", 8, 1.2),
            ("r1", 2016, "03", "森林", 20, 3.0),
            # 2006年森林・田(両年)は行が無い -> NULL のまま。
        ],
        org_watershed_rows=[("r1", 42, 3, 1, 2001, 2020)],
    )

    b11.build_projections(registry_db, out_db, **kwargs)

    conn = sqlite3.connect(out_db)
    conn.row_factory = sqlite3.Row
    try:
        r = conn.execute("SELECT * FROM watershed_rollup").fetchone()
    finally:
        conn.close()

    assert r["watershed_id"] == "r1"
    assert r["area_km2"] == pytest.approx(2.0)
    assert r["centroid_lat"] == pytest.approx(35.0)
    assert r["centroid_lon"] == pytest.approx(139.0)
    assert r["org_n"] == 42
    assert r["org_alien_n"] == 3
    assert r["org_redlist_n"] == 1
    assert r["site_n"] == 1  # site-2 は含まない
    assert r["site_var_n"] == 2  # site-1 の2変数だけ（地点数ではない）
    assert r["built_km2_2016"] == pytest.approx(1.5)
    assert r["built_km2_2006"] == pytest.approx(1.2)
    assert r["forest_km2_2016"] == pytest.approx(3.0)
    assert r["forest_km2_2006"] is None
    assert r["paddy_km2_2016"] is None
    assert r["paddy_km2_2006"] is None


def test_watershed_rollup_org_counts_default_to_zero_not_null(tmp_path):
    """`org_watershed` にその流域の行が無い（＝生物観察記録が1件も無い流域）
    場合、`org_n`/`org_alien_n`/`org_redlist_n` は v1 と同じく `COALESCE` で
    0 になる（NULL のまま残らない）。
    """
    registry_db = tmp_path / "registry.sqlite"
    _make_registry_db(registry_db, [_WATERSHED_ROW])
    out_db = tmp_path / "v1_projection_place.sqlite"

    # org_watershed_rows は空のまま（watershed_id='83032-0024' の行が無い）。
    b11.build_projections(registry_db, out_db, **_rollup_kwargs(tmp_path))

    conn = sqlite3.connect(out_db)
    try:
        row = conn.execute(
            "SELECT org_n, org_alien_n, org_redlist_n FROM watershed_rollup"
        ).fetchone()
    finally:
        conn.close()
    assert row == (0, 0, 0)


def test_duplicate_site_watershed_edge_raises_and_does_not_inflate_site_n(tmp_path):
    """同じ地点が2つの流域への `within` 辺を持つ（r01 の不変条件が本来防ぐ
    壊れ方だが、射影側でも独立に防ぐ——モジュール docstring・
    `_duplicate_site_watershed_message` 参照）と、`site_n`/`site_var_n` が
    水増しされる前に `MigrationError` で止まる。
    """
    row_a = dict(_WATERSHED_ROW, place_id="common:place:watershed.nlni-a", watershed_id="a")
    row_b = dict(_WATERSHED_ROW, place_id="common:place:watershed.nlni-b", watershed_id="b")
    registry_db = tmp_path / "registry.sqlite"
    conn = registry_common.create_registry_db(registry_db)
    try:
        _insert_watershed_place(conn, row_a)
        _insert_watershed_place(conn, row_b)
        conn.execute(
            "INSERT INTO place (place_id, region_id, place_kind, name_ja, status) VALUES (?,?,?,?,?)",
            ("jp-14:place:site.s1", "jp-14", "site", "地点", "ok"),
        )
        conn.execute(
            "INSERT INTO place_source_ref (place_id, external_key, source_id) VALUES (?,?,?)",
            ("jp-14:place:site.s1", "site-1", "sites.site_id"),
        )
        # 同じ地点から2つの流域への within 辺（本来起きない壊れ方）。
        conn.execute(
            "INSERT INTO place_relation (parent_id, child_id, relation, fraction, basis) "
            "VALUES (?,?,?,?,?)",
            (row_a["place_id"], "jp-14:place:site.s1", "within", 1.0, "test"),
        )
        conn.execute(
            "INSERT INTO place_relation (parent_id, child_id, relation, fraction, basis) "
            "VALUES (?,?,?,?,?)",
            (row_b["place_id"], "jp-14:place:site.s1", "within", 1.0, "test"),
        )
        conn.commit()
    finally:
        conn.close()
    out_db = tmp_path / "v1_projection_place.sqlite"

    with pytest.raises(migrate_common.MigrationError, match="site_id が単射でない"):
        b11.build_projections(registry_db, out_db, **_rollup_kwargs(tmp_path))


def test_missing_v1_projection_db_raises_clear_error_naming_b05(tmp_path):
    """`v1_projection_db`（`scripts/b05_project_v1.py` の出力）が無ければ、
    素の `FileNotFoundError` ではなく「先に b05 を実行せよ」と分かる
    `MigrationError` で止まる。出力ファイルには一切触れない
    （`_assert_rollup_prerequisites` はどちらも `fresh_sqlite` の前に呼ぶ）。
    """
    registry_db = tmp_path / "registry.sqlite"
    _make_registry_db(registry_db, [_WATERSHED_ROW])
    out_db = tmp_path / "v1_projection_place.sqlite"
    occ_db = tmp_path / "v1_projection_occurrence.sqlite"
    _make_v1_projection_occurrence_db(occ_db)

    with pytest.raises(migrate_common.MigrationError, match="b05_project_v1.py"):
        b11.build_projections(
            registry_db, out_db,
            v1_projection_db=tmp_path / "does-not-exist.sqlite",
            v1_projection_occurrence_db=occ_db,
        )
    assert not out_db.exists()


def test_missing_org_watershed_table_raises_clear_error_naming_b08(tmp_path):
    """`v1_projection_occurrence_db` は存在するが `org_watershed` テーブルを
    持たない（古い b08 の出力、または想定外のファイル）場合、
    「先に b08 を実行せよ」と分かる `MigrationError` で止まる。
    """
    registry_db = tmp_path / "registry.sqlite"
    _make_registry_db(registry_db, [_WATERSHED_ROW])
    out_db = tmp_path / "v1_projection_place.sqlite"
    proj_db = tmp_path / "v1_projection.sqlite"
    _make_v1_projection_db(proj_db)
    occ_db = tmp_path / "v1_projection_occurrence.sqlite"
    conn = sqlite3.connect(occ_db)
    try:
        conn.execute("CREATE TABLE org_norm (watershed_id TEXT)")  # org_watershed ではない
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(migrate_common.MigrationError, match="b08_project_occurrence_v1.py"):
        b11.build_projections(
            registry_db, out_db, v1_projection_db=proj_db, v1_projection_occurrence_db=occ_db,
        )


def test_missing_place_relation_table_raises_clear_error(tmp_path):
    """`place_relation`（ADR-0022 決定2で新設、`site_watershed_lookup` が
    読む）が無い古い registry.sqlite を渡すと `MigrationError` で止まる。
    """
    registry_db = tmp_path / "registry.sqlite"
    conn = registry_common.create_registry_db(registry_db)
    try:
        conn.execute("DROP TABLE place_relation")
        conn.commit()
    finally:
        conn.close()
    out_db = tmp_path / "v1_projection_place.sqlite"

    with pytest.raises(migrate_common.MigrationError, match="place_relation テーブルが無い"):
        b11.build_projections(registry_db, out_db, **_rollup_kwargs(tmp_path))
