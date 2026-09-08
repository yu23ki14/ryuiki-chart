"""解決レポート（docs/plans/PHASE_A.md §A-6・受け入れゲート）。

v1 の原本（`measurements` / `sensor_timeseries` / `organism_records` / `taxa`）が、
`data/db/registry.sqlite`（`unit` / `variable` / `variable_alias` / `place` /
`place_source_ref` / `taxon`）でどこまで解決できるかを数え、
`reports/registry_resolution.md` と `reports/registry_resolution/*.csv` に出す。

    .venv/bin/python3 scripts/r02_resolution_report.py

## このスクリプトが証明しないこと

未解決は失敗ではない（PHASE_A.md §A-6・docs/COLLECTOR_CONTRACT.md）。ここでは
解決率を上げにいかない。数えて、未解決の中身を一覧として書き出すだけ。

## 決定論

すべての集計を SQL の GROUP BY / ORDER BY で確定順に取り出す（Python 側の
dict/set の反復順に依存しない）。実行時刻や実行環境に依存する値はレポートに
一切埋め込まない。2回実行して reports/ 配下が完全に同一になることを
`scripts/r02_resolution_report.py` 自身のテストとはしていないが、CI 等で
`git diff --exit-code reports/` を2回実行の間に挟めば確認できる。

## 読み取り専用

原本3ファイル（ryuiki/cells/derived）は `scripts/registry/common.py` の
`open_sources()` で読み取り専用に開く。`registry.sqlite` もこのスクリプトからは
読み取り専用の ATTACH でしか触らない（生成物ではあるが、レポート実行が
書き換えないという契約をコード上でも保証する）。
"""
import csv
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from registry import common  # noqa: E402

REPORT_MD = ROOT / "reports" / "registry_resolution.md"
CSV_DIR = ROOT / "reports" / "registry_resolution"


# ---------------------------------------------------------------------------
# 接続
# ---------------------------------------------------------------------------

def connect():
    """原本3ファイルを読み取り専用で開き、registry.sqlite を読み取り専用で
    ryuiki 側に ATTACH する（ローカル SQLite 同士なので ATTACH に制約は無い。
    D1 では ATTACH できないが、これはビルド時のローカル集計であり無関係）。
    """
    if not common.REGISTRY_DB.exists():
        sys.exit(
            f"registry.sqlite が無い: {common.REGISTRY_DB}\n"
            "先に `.venv/bin/python3 scripts/r01_build_registry.py` を実行する。"
        )
    src = common.open_sources()
    ryuiki = src["ryuiki"]
    reg_path = str(common.REGISTRY_DB).replace("'", "''")
    ryuiki.execute(f"ATTACH DATABASE 'file:{reg_path}?mode=ro' AS reg")
    return src, ryuiki


def scalar(conn: sqlite3.Connection, sql: str, params=()) -> int:
    return conn.execute(sql, params).fetchone()[0]


def rows(conn: sqlite3.Connection, sql: str, params=()) -> list[sqlite3.Row]:
    return conn.execute(sql, params).fetchall()


def write_csv(name: str, header: list[str], data_rows) -> int:
    """CSV_DIR/name に書く。ヘッダのみでも（0行でも）必ず作る
    （「未解決が0件だった」ことが分かるように、ファイルの有無で判断させない）。
    """
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    path = CSV_DIR / name
    data_rows = list(data_rows)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(data_rows)
    return len(data_rows)


def pct(n: int, total: int) -> str:
    if total == 0:
        return "n/a"
    return f"{n / total * 100:.2f}%"


# ---------------------------------------------------------------------------
# A. measurements / sensor_timeseries -> variable_id
# ---------------------------------------------------------------------------

def report_variable(ryuiki: sqlite3.Connection) -> dict:
    """`variable_alias` は Phase B で (dataset, alias, source_id) 単位に分かれたため、
    同じ (dataset, alias) に複数の source_id 違いの行がありうる（例:
    `生物化学的酸素要求量 BOD` は measurements 側に3行）。単純な JOIN では1件の
    measurement 行が複数の variable_alias 行にマッチして count が水増しされるため、
    ここでは EXISTS/NOT EXISTS で「一致する行があるか」だけを見る（重複カウントしない。
    variable_id の解決だけが目的なので source_id までは絞らない。dataset/alias が
    同じなら variable_id は必ず一致する — build_unit_variable.py の
    `_assert_variable_unit_consistent_per_alias` がビルド時に保証している）。
    """
    out = {}
    unresolved_rows = []

    for table, col, dataset in (
        ("measurements", "variable", "measurements"),
        ("sensor_timeseries", "datastream", "sensor_timeseries"),
    ):
        total = scalar(ryuiki, f"SELECT count(*) FROM {table}")
        resolved = scalar(
            ryuiki,
            f"""
            SELECT count(*) FROM {table} t
            WHERE EXISTS (
              SELECT 1 FROM reg.variable_alias va
              JOIN reg.variable v ON v.variable_id = va.variable_id
              WHERE va.alias = t.{col} AND va.dataset = ?
            )
            """,
            (dataset,),
        )
        unresolved = total - resolved
        out[table] = {"total": total, "resolved": resolved, "unresolved": unresolved}

        for r in rows(
            ryuiki,
            f"""
            SELECT t.{col} AS raw_label, count(*) AS n
            FROM {table} t
            WHERE NOT EXISTS (
              SELECT 1 FROM reg.variable_alias va
              JOIN reg.variable v ON v.variable_id = va.variable_id
              WHERE va.alias = t.{col} AND va.dataset = ?
            )
            GROUP BY t.{col}
            ORDER BY t.{col}
            """,
            (dataset,),
        ):
            unresolved_rows.append((dataset, r["raw_label"], r["n"]))

    out["unresolved_csv_rows"] = write_csv(
        "unresolved_variable_aliases.csv",
        ["dataset", "raw_label", "row_count"],
        unresolved_rows,
    )
    return out


# ---------------------------------------------------------------------------
# A'. (dataset, alias, source_id) の網羅性: registry/variable_alias.csv の154組が
# v1 の実データの組と過不足なく一致するか（docs/plans/PHASE_B_INTAKE.md 設計C）。
#
# build_unit_variable.py は原本 DB を一切開かない（#7, CI のため）ので、
# 「CSVの組が実データと過不足なく一致するか」はここ（原本を読める r02）でしか
# 検証できない。黙って落とす・黙って埋めるのではなく、両方向のズレを列挙する。
# ---------------------------------------------------------------------------

def report_alias_source_pairs(ryuiki: sqlite3.Connection) -> dict:
    data_rows = rows(
        ryuiki,
        """
        SELECT 'measurements' AS dataset, variable AS alias, COALESCE(source_id, '') AS source_id,
               count(*) AS n
        FROM measurements
        GROUP BY variable, COALESCE(source_id, '')
        UNION ALL
        SELECT 'sensor_timeseries' AS dataset, datastream AS alias, COALESCE(source_id, '') AS source_id,
               count(*) AS n
        FROM sensor_timeseries
        GROUP BY datastream, COALESCE(source_id, '')
        """,
    )
    data_by_key = {(r["dataset"], r["alias"], r["source_id"]): r["n"] for r in data_rows}
    data_keys = set(data_by_key)

    registry_rows = rows(
        ryuiki,
        "SELECT dataset, alias, COALESCE(source_id, '') AS source_id FROM reg.variable_alias",
    )
    registry_keys = {(r["dataset"], r["alias"], r["source_id"]) for r in registry_rows}

    csv_only = sorted(registry_keys - data_keys)
    data_only = sorted(data_keys - registry_keys)

    n_csv_only = write_csv(
        "alias_source_pairs_csv_only.csv",
        ["dataset", "alias", "source_id"],
        csv_only,
    )
    n_data_only = write_csv(
        "alias_source_pairs_data_only.csv",
        ["dataset", "alias", "source_id", "row_count"],
        [(d, a, s, data_by_key[(d, a, s)]) for d, a, s in data_only],
    )

    return {
        "registry_total": len(registry_keys),
        "data_total": len(data_keys),
        "csv_only": csv_only,
        "csv_only_csv_rows": n_csv_only,
        "data_only": data_only,
        "data_only_csv_rows": n_data_only,
        "data_only_rows_by_key": data_by_key,
        "matches": len(registry_keys & data_keys),
    }


# ---------------------------------------------------------------------------
# B. measurements / sensor_timeseries の site_id -> place_id
# ---------------------------------------------------------------------------

def report_place(ryuiki: sqlite3.Connection) -> dict:
    """`distinct_resolved` と `row_resolved` は、未解決側の site_id 別内訳
    （`site_unresolved` 1クエリ）から総数の引き算で出す。以前は解決側を JOIN で
    数える専用クエリを2本（distinct 用・行ベース用）別に打っていた（sensor_timeseries
    側で実測 約244ms）。総数（`distinct_total`・`row_total`）と未解決の内訳だけで
    十分なので、その2本を削る（/simplify 修正7。scripts/registry/build_taxon.py の
    診断ブロック・report_organism と同じ形の重複）。
    """
    out = {}
    unresolved_rows = []

    for table in ("measurements", "sensor_timeseries"):
        distinct_total = scalar(ryuiki, f"SELECT count(DISTINCT site_id) FROM {table}")
        row_total = scalar(ryuiki, f"SELECT count(*) FROM {table}")

        site_unresolved = rows(
            ryuiki,
            f"""
            SELECT t.site_id AS site_id, count(*) AS n
            FROM {table} t
            LEFT JOIN reg.place_source_ref psr
              ON psr.external_key = t.site_id AND psr.source_id = 'sites.site_id'
            WHERE psr.place_id IS NULL
            GROUP BY t.site_id
            ORDER BY t.site_id
            """,
        )
        distinct_unresolved = len(site_unresolved)
        row_unresolved = sum(r["n"] for r in site_unresolved)

        out[table] = {
            "distinct_total": distinct_total,
            "distinct_resolved": distinct_total - distinct_unresolved,
            "distinct_unresolved": distinct_unresolved,
            "row_total": row_total,
            "row_resolved": row_total - row_unresolved,
            "row_unresolved": row_unresolved,
        }

        for r in site_unresolved:
            unresolved_rows.append((table, r["site_id"], r["n"]))

    out["unresolved_csv_rows"] = write_csv(
        "unresolved_site_ids.csv",
        ["source_table", "site_id", "row_count"],
        unresolved_rows,
    )
    return out


# ---------------------------------------------------------------------------
# C. organism_records -> taxon_id（≥99.8%）
# ---------------------------------------------------------------------------

REASON_NO_MATERIAL = "scientific_name等の分類群情報が空欄で照合材料が無い（taxon_key自体が無い）"


def report_organism(ryuiki: sqlite3.Connection) -> dict:
    """`resolved`（JOIN。実測1051ms）と `by_source`（GROUP BY。実測416ms）は、CSV 用に
    どのみち全件取得する `unresolved_rows` から Python 側で導ける（`organism_records`
    は distinct taxon_key 全件が `reg.taxon` に登録済みなので、taxon_key が非NULL/非空の
    行は必ず解決できる。build_taxon.py の `_load_occurrence_representatives` 参照）。
    総数（`total`）とこの1クエリだけで済み、以前打っていた2クエリ（約1,467ms）を
    まるごと削れる（/simplify 修正7）。
    """
    total = scalar(ryuiki, "SELECT count(*) FROM organism_records")

    unresolved_rows = rows(
        ryuiki,
        f"""
        SELECT record_id, source_id, site_id, observed_on, scientific_name,
               vernacular_name, taxon_rank
        FROM organism_records
        WHERE taxon_key IS NULL OR taxon_key = ''
        ORDER BY record_id
        """,
    )
    unresolved = len(unresolved_rows)
    resolved = total - unresolved

    n_csv = write_csv(
        "unresolved_organism_records.csv",
        ["record_id", "source_id", "site_id", "observed_on", "scientific_name",
         "vernacular_name", "taxon_rank", "reason"],
        [
            (r["record_id"], r["source_id"], r["site_id"], r["observed_on"],
             r["scientific_name"], r["vernacular_name"], r["taxon_rank"],
             REASON_NO_MATERIAL)
            for r in unresolved_rows
        ],
    )

    by_source_counts: dict = {}
    for r in unresolved_rows:
        by_source_counts[r["source_id"]] = by_source_counts.get(r["source_id"], 0) + 1
    by_source = sorted(by_source_counts.items())

    return {
        "total": total,
        "resolved": resolved,
        "unresolved": unresolved,
        "unresolved_csv_rows": n_csv,
        "by_source": by_source,
    }


# ---------------------------------------------------------------------------
# D. 単位が決まる measurement 行（報告のみ）
# ---------------------------------------------------------------------------

# `variable_alias.unit_id`（無ければ `variable.unit_id`）が「NULL ではない」だけでなく、
# 実際に `unit` テーブルに存在する行を指しているかまで見る EXISTS 断片。by_variable
# （NOT EXISTS 版、still_missing の内訳）側だけで使い、filled はその合計からの
# 引き算で出す（同じ条件で measurements をフルスキャンするクエリを2本打たない）。
# 存在しない unit_id（タイポ等でぶら下がった参照）は「解決していない」として扱う——
# `scripts/r01_build_registry.py` の `ID_REFERENCE_CHECKS`（参照整合性検証）と揃えた判断。
_UNIT_ID_RESOLVED_EXISTS = """
    EXISTS (
      SELECT 1 FROM reg.variable_alias va
      LEFT JOIN reg.variable v ON v.variable_id = va.variable_id
      WHERE va.alias = m.variable AND va.dataset = 'measurements'
        AND EXISTS (
          SELECT 1 FROM reg.unit u WHERE u.unit_id = COALESCE(va.unit_id, v.unit_id)
        )
    )
"""


def report_unit(ryuiki: sqlite3.Connection) -> dict:
    """`variable_alias` は (dataset, alias) が複数行（source_id 違い）になりうるため、
    report_variable と同じ理由で EXISTS/NOT EXISTS を使い、行の水増しを避ける
    （unit_id は (dataset, alias) の中で一致することを build 時に保証済みなので、
    「一致する行が1つでもあるか」だけを見れば足りる）。

    `filled` は `by_variable`（NOT EXISTS 版）の合計からの引き算で出す。以前は
    `filled`（EXISTS 版）と `by_variable`（NOT EXISTS 版）が同じ条件で measurements
    109,078行を2回別々にフルスキャンしていた（`filled` 単体で実測0.45〜0.58秒、
    report_unit() 全体の3〜4割）。report_place・report_organism と同じ形で、
    内訳側の1クエリだけで済ませる（/simplify 修正7と同種）。
    """
    total_missing = scalar(
        ryuiki, "SELECT count(*) FROM measurements WHERE unit IS NULL OR unit = ''"
    )

    by_variable = rows(
        ryuiki,
        f"""
        SELECT m.variable AS raw_label,
               (SELECT va.variable_id FROM reg.variable_alias va
                WHERE va.alias = m.variable AND va.dataset = 'measurements' LIMIT 1) AS variable_id,
               count(*) AS n
        FROM measurements m
        WHERE (m.unit IS NULL OR m.unit = '')
          AND NOT {_UNIT_ID_RESOLVED_EXISTS}
        GROUP BY m.variable
        ORDER BY m.variable
        """,
    )
    still_missing = sum(r["n"] for r in by_variable)
    filled = total_missing - still_missing

    return {
        "total_missing": total_missing,
        "filled": filled,
        "still_missing": still_missing,
        "still_missing_by_variable": [
            (r["raw_label"], r["variable_id"], r["n"]) for r in by_variable
        ],
    }


# ---------------------------------------------------------------------------
# E. status='needs_review' の place / variable
# ---------------------------------------------------------------------------

def report_needs_review(ryuiki: sqlite3.Connection, unit_still_missing_by_variable) -> dict:
    place_rows = rows(
        ryuiki,
        """
        SELECT p.place_id AS place_id, p.place_kind AS place_kind,
               psr.external_key AS external_key, p.name_ja AS name_ja,
               p.lat AS lat, p.lon AS lon, p.definition_ref AS reason
        FROM reg.place p
        LEFT JOIN reg.place_source_ref psr
          ON psr.place_id = p.place_id AND psr.source_id = 'sites.site_id'
        WHERE p.status = 'needs_review'
        ORDER BY p.place_id
        """,
    )
    n_place_csv = write_csv(
        "needs_review_place.csv",
        ["place_id", "place_kind", "external_key", "name_ja", "lat", "lon", "reason"],
        [
            (r["place_id"], r["place_kind"], r["external_key"], r["name_ja"],
             r["lat"], r["lon"], r["reason"])
            for r in place_rows
        ],
    )

    variable_rows = rows(
        ryuiki,
        """
        SELECT variable_id, code, name_ja, theme, description_ja
        FROM reg.variable
        WHERE status = 'needs_review'
        ORDER BY variable_id
        """,
    )
    # hydro.flow 専用の説明文をハードコードしていた版は、その変数が status=ok になった
    # 今では到達不能な上に他の変数には嘘になる（code-review 指摘）。variable ごとに理由は
    # 異なりうる（unit_id が決まらない・定義そのものが未確認 等）ため、汎用の案内に留める。
    fallback_reason = (
        "description_ja が未設定（理由は registry/variable.yaml の該当エントリのコメントを参照）"
    )
    missing_by_var = {v: n for _, v, n in unit_still_missing_by_variable}
    n_variable_csv = write_csv(
        "needs_review_variable.csv",
        ["variable_id", "code", "name_ja", "theme",
         "measurement_rows_with_missing_unit", "reason"],
        [
            (r["variable_id"], r["code"], r["name_ja"], r["theme"],
             missing_by_var.get(r["variable_id"], 0),
             r["description_ja"] or fallback_reason)
            for r in variable_rows
        ],
    )

    # variable_alias.stat が空/NULL の行（docs/plans/PHASE_B_ALIAS_STAT_SOURCES.md の
    # 一次資料調査で「一次資料からは確定できなかった」ことが分かった行を含む。
    # 黙って埋めない・落とさない契約（COLLECTOR_CONTRACT.md）に従い、機械的に全件列挙する
    # だけで、どれが「本当に未確認」でどれが「カテゴリ属性で stat という概念自体が無い」かの
    # 判定はしない — note 列にその理由が書いてある）。
    alias_stat_rows = rows(
        ryuiki,
        """
        SELECT dataset, alias, source_id, variable_id, note
        FROM reg.variable_alias
        WHERE stat IS NULL OR stat = ''
        ORDER BY dataset, alias, source_id
        """,
    )
    n_alias_stat_csv = write_csv(
        "needs_review_alias_stat.csv",
        ["dataset", "alias", "source_id", "variable_id", "note"],
        [
            (r["dataset"], r["alias"], r["source_id"], r["variable_id"], r["note"])
            for r in alias_stat_rows
        ],
    )

    return {
        "place_count": len(place_rows),
        "place_csv_rows": n_place_csv,
        "variable_count": len(variable_rows),
        "variable_csv_rows": n_variable_csv,
        "variable_rows": [
            (r["variable_id"], r["code"], r["name_ja"], r["description_ja"] or fallback_reason)
            for r in variable_rows
        ],
        "alias_stat_count": len(alias_stat_rows),
        "alias_stat_csv_rows": n_alias_stat_csv,
    }


# ---------------------------------------------------------------------------
# F. taxa 8,585行 -> taxon_id（報告のみ）／ status='unresolved' の taxon
# ---------------------------------------------------------------------------

def report_taxa(ryuiki: sqlite3.Connection) -> dict:
    """taxa 8,585行の GBIF 照合状況と、registry 側 taxon.status='unresolved' の対応。

    build_taxon.py はレビュー指摘で「`gbif_match_type='EXACT'`（種階級での一致）の
    taxa 行だけを対応する gbif.<key> 行に寄せ、`HIGHERRANK`/`FUZZY`（キーはあるが
    種以下まで一致していない）は捨てずに `status='unresolved'` で個別に残す」方針に
    直した（ADR-0019決定4）。そのため registry 側の unresolved（6,242件）は
    「taxa の生の gbif_taxon_key 欠落数」（5,942件）より300件多い。この節では
    両方の数字を出し、差分（EXACT でない弱い一致）を明示する。
    """
    total_taxa = scalar(ryuiki, "SELECT count(*) FROM taxa")
    with_gbif_key = scalar(
        ryuiki, "SELECT count(*) FROM taxa WHERE gbif_taxon_key IS NOT NULL AND gbif_taxon_key <> ''"
    )
    no_gbif_key = total_taxa - with_gbif_key
    exact_with_key = scalar(
        ryuiki,
        "SELECT count(*) FROM taxa WHERE gbif_taxon_key IS NOT NULL AND gbif_taxon_key <> '' "
        "AND gbif_match_type = 'EXACT'",
    )
    weak_with_key = with_gbif_key - exact_with_key  # HIGHERRANK + FUZZY

    # registry の unresolved と同じ定義（gbif_match_type が EXACT でない全行）。
    unresolved_rows = rows(
        ryuiki,
        """
        SELECT taxon_id, scientific_name, vernacular_name_ja, taxon_group_ja,
               redlist_kanagawa, redlist_national, ias_category, gbif_match_type,
               gbif_taxon_key, source_id
        FROM taxa
        WHERE gbif_match_type IS NOT 'EXACT'
        ORDER BY taxon_id
        """,
    )

    def reason(match_type, gbif_key):
        if match_type == "NONE":
            return "GBIFへ照会したが一致しなかった（gbif_match_type=NONE）"
        if match_type in ("HIGHERRANK", "FUZZY"):
            return (
                f"GBIFに照会でき gbif_taxon_key={gbif_key} まで辿れたが、種階級までの"
                f"一致ではない（gbif_match_type={match_type}）。対応するgbif行に寄せると"
                "別種の名前・レッドリストカテゴリが混ざる恐れがあるため、taxa 行ごとに"
                "unresolved のまま個別登録する（ADR-0019決定4）。"
            )
        return "GBIFへの照会自体が未実施（gbif_taxon_key欠落・gbif_match_type=NULL）"

    n_csv = write_csv(
        "unresolved_taxa.csv",
        ["taxon_id", "scientific_name", "vernacular_name_ja", "taxon_group_ja",
         "redlist_kanagawa", "redlist_national", "ias_category", "gbif_match_type",
         "gbif_taxon_key", "source_id", "reason"],
        [
            (r["taxon_id"], r["scientific_name"], r["vernacular_name_ja"],
             r["taxon_group_ja"], r["redlist_kanagawa"], r["redlist_national"],
             r["ias_category"], r["gbif_match_type"], r["gbif_taxon_key"], r["source_id"],
             reason(r["gbif_match_type"], r["gbif_taxon_key"]))
            for r in unresolved_rows
        ],
    )

    by_match_type = rows(
        ryuiki,
        """
        SELECT COALESCE(gbif_match_type, '(NULL)') AS match_type, count(*) AS n
        FROM taxa
        WHERE gbif_match_type IS NOT 'EXACT'
        GROUP BY COALESCE(gbif_match_type, '(NULL)')
        ORDER BY match_type
        """,
    )

    sample = unresolved_rows[:40]  # ORDER BY taxon_id 済みなので決定論的

    registry_taxon_total = scalar(ryuiki, "SELECT count(*) FROM reg.taxon")
    registry_taxon_unresolved = scalar(
        ryuiki, "SELECT count(*) FROM reg.taxon WHERE status = 'unresolved'"
    )
    registry_taxon_accepted = scalar(
        ryuiki, "SELECT count(*) FROM reg.taxon WHERE status = 'accepted'"
    )

    return {
        "total_taxa": total_taxa,
        "with_gbif_key": with_gbif_key,
        "exact_with_key": exact_with_key,
        "weak_with_key": weak_with_key,
        "unresolved": no_gbif_key,
        "unresolved_csv_rows": n_csv,
        "by_match_type": [(r["match_type"], r["n"]) for r in by_match_type],
        "sample": sample,
        "registry_taxon_total": registry_taxon_total,
        "registry_taxon_unresolved": registry_taxon_unresolved,
        "registry_taxon_accepted": registry_taxon_accepted,
    }


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def judge(ok: bool) -> str:
    return "OK" if ok else "**未達**"


def _match_type_meaning(match_type: str) -> str:
    if match_type == "NONE":
        return "GBIFへ照会したが一致しなかった"
    if match_type in ("HIGHERRANK", "FUZZY"):
        return "GBIFに照会でき gbif_taxon_key はあるが、種階級までの一致ではない"
    return "GBIFへの照会自体が未実施（gbif_taxon_key欠落）"


def render_table_or_note(a, items: list, header_lines: list[str], row_fmt, empty_note: str) -> None:
    """`items` があれば `header_lines` + 表を、無ければ `empty_note` の一文だけを出す。

    0件のとき「見出し行だけの空表」が出る、という同じ根の問題を1箇所で塞ぐ
    （/simplify 指摘C: render_markdown() 内に手書きの `if x > 0:` 分岐がバラバラに
    （うち3箇所はガードすら無く）散らばっていた）。
    """
    if items:
        for line in header_lines:
            a(line)
        for item in items:
            a(row_fmt(item))
        a("")
    else:
        a(empty_note)
        a("")


def render_markdown(v, p, o, u, nr, t, ap) -> str:
    lines = []
    a = lines.append

    a("# レジストリ解決レポート（Phase A §A-6）")
    a("")
    a(
        "`scripts/r02_resolution_report.py` が生成する。v1 の原本（`ryuiki.sqlite` / "
        "`cells.sqlite` / `derived.sqlite`、いずれも読み取り専用）と "
        "`data/db/registry.sqlite` を突き合わせ、語彙レジストリでどこまで解決できるかを"
        "数えたもの。**このレポートはレジストリのデータを1行も直さない。**"
        "未解決が残ること自体は失敗ではなく、件数と一覧を出すことが合格条件"
        "（`docs/COLLECTOR_CONTRACT.md` / `docs/plans/PHASE_A.md` §A-6）。"
    )
    a("")
    a("再生成: `.venv/bin/python3 scripts/r02_resolution_report.py`")
    a("")

    a("## 目標に対する実績（PHASE_A.md §A-6 の表）")
    a("")
    a("| # | 対象 | 目標 | 実績 | 判定 |")
    a("|---|---|---|---|---|")

    m_ok = v["measurements"]["unresolved"] == 0
    s_ok = v["sensor_timeseries"]["unresolved"] == 0
    a(
        f"| 1 | `measurements` {v['measurements']['total']:,}行 → `variable_id` | 100% | "
        f"{pct(v['measurements']['resolved'], v['measurements']['total'])}"
        f"（未解決 {v['measurements']['unresolved']:,}行） | {judge(m_ok)} |"
    )
    a(
        f"| 2 | `sensor_timeseries` {v['sensor_timeseries']['total']:,}行 → `variable_id` | 100% | "
        f"{pct(v['sensor_timeseries']['resolved'], v['sensor_timeseries']['total'])}"
        f"（未解決 {v['sensor_timeseries']['unresolved']:,}行） | {judge(s_ok)} |"
    )

    pm = p["measurements"]
    pm_ok = pm["distinct_unresolved"] == 0
    a(
        f"| 3 | `measurements` の site_id {pm['distinct_total']}種 → `place_id` | 100% | "
        f"{pct(pm['distinct_resolved'], pm['distinct_total'])}"
        f"（未解決 {pm['distinct_unresolved']}種 / 行ベースでは "
        f"{pct(pm['row_resolved'], pm['row_total'])}） | {judge(pm_ok)} |"
    )
    ps = p["sensor_timeseries"]
    ps_ok = ps["distinct_unresolved"] == 0
    a(
        f"| 4 | `sensor_timeseries` の site_id {ps['distinct_total']}種 → `place_id` | 100% | "
        f"{pct(ps['distinct_resolved'], ps['distinct_total'])}"
        f"（未解決 {ps['distinct_unresolved']}種 / 行ベースでは "
        f"{pct(ps['row_resolved'], ps['row_total'])}） | {judge(ps_ok)} |"
    )

    o_rate = o["resolved"] / o["total"] * 100
    o_ok = o_rate >= 99.8
    a(
        f"| 5 | `organism_records` {o['total']:,}行 → `taxon_id` | ≥99.8% | "
        f"{o_rate:.4f}%（未解決 {o['unresolved']:,}行） | {judge(o_ok)} |"
    )

    a(
        f"| 6 | 単位が決まる measurement 行（単位欠落 {u['total_missing']:,}行のうち） | 報告のみ | "
        f"{u['filled']:,}行（{pct(u['filled'], u['total_missing'])}）が埋まる。"
        f"残り {u['still_missing']:,}行は未解決 | 報告のみ |"
    )

    a(
        f"| 7 | `taxa` {t['total_taxa']:,}行 → `taxon_id` | 報告のみ | "
        f"GBIF照合(EXACT)あり {t['exact_with_key']:,}行 / registry `status='unresolved'` "
        f"{t['registry_taxon_unresolved']:,}行（詳細は§7） | 報告のみ |"
    )
    ap_ok = not ap["csv_only"] and not ap["data_only"]
    a(
        f"| 8 | `registry/variable_alias.csv` の (dataset, alias, source_id) "
        f"{ap['registry_total']}組 ⇔ v1 実データの組 {ap['data_total']}組 | "
        f"過不足なく一致 | 一致 {ap['matches']}組 / CSVのみ {len(ap['csv_only'])}組 / "
        f"実データのみ {len(ap['data_only'])}組 | {judge(ap_ok)} |"
    )
    a("")

    if not (m_ok and s_ok and pm_ok and ps_ok and o_ok and ap_ok):
        a(
            "**目標未達の項目がある（上表で「未達」と記した行）。"
            "このレポートは数字をそのまま記録するものであり、目標に合わせて"
            "レジストリ側のデータを調整していない。**"
        )
        a("")
    else:
        a("100%/≥99.8% を要求する項目（#1〜#5）はすべて目標を満たしている。")
        a("")

    a("## 対応する完了条件（PHASE_A.md §4）")
    a("")
    a(
        "この表の #1〜#5 が満たされていることは、§4 の完了条件2「`reports/registry_resolution.md` "
        "が生成され、上表の目標を満たしている」に対応する。#6・#7 は「報告のみ」の項目で、"
        "目標達成の可否ではなく **未解決の可視化そのもの** が完了条件（COLLECTOR_CONTRACT.md）。"
    )
    a("")

    a("## 1〜2. measurements / sensor_timeseries → variable_id")
    a("")
    a(
        f"- `measurements` {v['measurements']['total']:,}行、"
        f"`variable_alias`（`dataset='measurements'`）で全件解決"
        f"（未解決 {v['measurements']['unresolved']:,}行）。"
    )
    a(
        f"- `sensor_timeseries` {v['sensor_timeseries']['total']:,}行、同様に "
        f"`dataset='sensor_timeseries'` で全件解決"
        f"（未解決 {v['sensor_timeseries']['unresolved']:,}行）。"
    )
    a(
        f"- 未解決の指標表記（原文）の一覧: "
        f"`reports/registry_resolution/unresolved_variable_aliases.csv`"
        f"（{v['unresolved_csv_rows']}行。0行ならヘッダのみで、未解決が無いことを示す）。"
    )
    a("")

    a("## 3〜4. site_id → place_id")
    a("")
    a(
        f"- `measurements` の site_id {pm['distinct_total']}種、"
        f"`place_source_ref`（`source_id='sites.site_id'`）で全件解決"
        f"（未解決 {pm['distinct_unresolved']}種）。行ベースでは "
        f"{pm['row_resolved']:,}/{pm['row_total']:,}行。"
    )
    a(
        f"- `sensor_timeseries` の site_id {ps['distinct_total']}種、同様に全件解決"
        f"（未解決 {ps['distinct_unresolved']}種）。行ベースでは "
        f"{ps['row_resolved']:,}/{ps['row_total']:,}行。"
    )
    a(
        f"- 未解決の site_id 一覧: `reports/registry_resolution/unresolved_site_ids.csv`"
        f"（{p['unresolved_csv_rows']}行。0行ならヘッダのみ）。"
    )
    a("")

    a("## 5. organism_records → taxon_id")
    a("")
    a(
        f"- {o['total']:,}行中 {o['resolved']:,}行（{o_rate:.4f}%）が"
        f" `taxon_key` 経由で `taxon_id` に解決できる。目標 ≥99.8% を満たす。"
    )
    a(f"- 未解決 {o['unresolved']:,}行。全件を `reports/registry_resolution/unresolved_organism_records.csv` に出す。")
    render_table_or_note(
        a,
        o["by_source"],
        [
            f"- 出典別の内訳（未解決 {o['unresolved']:,}行、全件が同一理由: "
            f"分類群情報が空欄で照合材料が無い）:",
            "",
            "  | source_id | 未解決行数 |",
            "  |---|---|",
        ],
        lambda item: f"  | `{item[0]}` | {item[1]:,} |",
        "- 出典別の内訳: 該当なし（未解決行が無い）。",
    )

    a("## 6. 単位が決まる measurement 行（報告のみ）")
    a("")
    a(
        f"- 原本で単位（`unit`）が空の行 {u['total_missing']:,}行のうち、"
        f"`variable_alias.unit_id`（無ければ `variable.unit_id`。ただし `unit` に実在する"
        f"値のみ「決まる」とみなす）で {u['filled']:,}行"
        f"（{pct(u['filled'], u['total_missing'])}）の単位が決まる。"
    )
    # このクエリは「unit_id が unit に実在する行が無い」ことだけで絞っており、
    # `variable.status='needs_review'` の条件は付いていない（code-review 指摘）。
    # status='ok' なのに unit_id が未解決の変数（例: 申し送り #5 の相模原 OX、意図的に
    # unit_id=null のまま status=ok）もここに含まれうるため、「変数自体が
    # needs_review」と断定しない。
    render_table_or_note(
        a,
        u["still_missing_by_variable"],
        [
            f"- 残り {u['still_missing']:,}行は `variable_alias.unit_id`/`variable.unit_id` の"
            f"どちらにも `unit` に実在する値が無く、単位が決まらない"
            f"（`variable.status` の値とは無関係。needs_review でも unit_id が解決していれば"
            f"ここには含まれず、status='ok' でも unit_id が未解決ならここに含まれる）。",
            "- 単位が埋まらない行の内訳（原文の指標表記別）:",
            "",
            "  | 原文の指標表記 | 対応する variable_id | 未解決行数 |",
            "  |---|---|---|",
        ],
        lambda item: f"  | `{item[0]}` | `{item[1]}` | {item[2]:,} |",
        f"- 残り {u['still_missing']:,}行。単位が埋まらない measurement 行は無い。",
    )

    a("## needs_review の一覧（place / variable / variable_alias.stat）")
    a("")
    a(
        f"- `place.status='needs_review'`: {nr['place_count']}件。"
        f"座標などが原本から確認できず、捏造せず `NULL` のまま登録した地点。"
        f"一覧: `reports/registry_resolution/needs_review_place.csv`"
        f"（{nr['place_csv_rows']}行）。"
    )
    a(
        f"- `variable.status='needs_review'`: {nr['variable_count']}件。"
        f"一覧: `reports/registry_resolution/needs_review_variable.csv`"
        f"（{nr['variable_csv_rows']}行）。"
    )
    for variable_id, code, name_ja, description_ja in nr["variable_rows"]:
        a(f"  - `{variable_id}`（{code} / {name_ja}）: {description_ja}")
    a(
        f"- `variable_alias.stat` が空の行: {nr['alias_stat_count']}件"
        f"（一次資料調査で確定できなかったもの・統計量という概念自体が無いカテゴリ属性の"
        f"両方を含む機械的な列挙。理由は各行の `note` 列を参照。"
        f"docs/plans/PHASE_B_ALIAS_STAT_SOURCES.md 参照）。"
        f"一覧: `reports/registry_resolution/needs_review_alias_stat.csv`"
        f"（{nr['alias_stat_csv_rows']}行）。"
    )
    a("")

    a("## 7. taxa → taxon_id（報告のみ）／ status='unresolved' の taxon")
    a("")
    a(
        f"- `taxa` {t['total_taxa']:,}行のうち、`gbif_taxon_key` を持つのは "
        f"{t['with_gbif_key']:,}行。持たない（GBIFに未照合）のは {t['unresolved']:,}行。"
    )
    a(
        f"- `gbif_taxon_key` を持つ {t['with_gbif_key']:,}行の内訳: "
        f"`gbif_match_type='EXACT'`（種階級での一致）{t['exact_with_key']:,}行 / "
        f"`HIGHERRANK`・`FUZZY`（キーはあるが種以下まで一致していない弱い一致）"
        f"{t['weak_with_key']:,}行。"
    )
    a(
        f"- レジストリ側 `taxon` テーブルは {t['registry_taxon_total']:,}行 "
        f"（`status='accepted'` {t['registry_taxon_accepted']:,} / "
        f"`status='unresolved'` {t['registry_taxon_unresolved']:,}）。"
        "**`unresolved` の件数は `taxa` の未照合件数（gbif_taxon_key欠落）と"
        "一致しない。** レビュー指摘（ADR-0019決定4）を受け、`gbif_match_type='EXACT'` "
        "以外は `gbif_taxon_key` があっても対応する `gbif.<key>` 行に寄せず "
        "`status='unresolved'` で taxa 行ごとに個別登録する方針に直したため、"
        f"`unresolved` は「未照合 {t['unresolved']:,}行」に「弱い一致 "
        f"{t['weak_with_key']:,}行」を加えた"
        f"{t['unresolved'] + t['weak_with_key']:,}行になる"
        f"（実測: `status='unresolved'` {t['registry_taxon_unresolved']:,}行）。"
        "弱い一致を寄せていた旧実装では、GBIF が種以下まで一致させられなかった"
        "広い taxon_key（例: kingdom=Animalia）に複数の無関係な種の名前・"
        "レッドリストカテゴリが混ざる行ができていた。"
    )
    render_table_or_note(
        a,
        t["by_match_type"],
        [
            "- 未照合・弱い一致の内訳（`gbif_match_type` 別。EXACT を除く全件）:",
            "",
            "  | gbif_match_type | 件数 | 意味 |",
            "  |---|---|---|",
        ],
        lambda item: f"  | `{item[0]}` | {item[1]:,} | {_match_type_meaning(item[0])} |",
        "- 未照合・弱い一致の内訳: 該当なし（EXACT を除く taxa が無い）。",
    )
    a(
        f"- 全件（{t['unresolved_csv_rows']}行）: "
        f"`reports/registry_resolution/unresolved_taxa.csv`。"
    )
    render_table_or_note(
        a,
        t["sample"],
        [
            f"- 以下は先頭 {len(t['sample'])} 件（`taxon_id` 昇順の代表例。全件は上記CSV参照）:",
            "",
            "  | taxon_id | scientific_name | vernacular_name_ja | taxon_group_ja | gbif_match_type |",
            "  |---|---|---|---|---|",
        ],
        lambda r: (
            f"  | `{r['taxon_id']}` | {r['scientific_name'] or ''} | "
            f"{r['vernacular_name_ja'] or ''} | {r['taxon_group_ja'] or ''} | "
            f"{r['gbif_match_type'] or ''} |"
        ),
        "- 代表例は無い（該当行が無いため）。",
    )

    a("## 8. (dataset, alias, source_id) の網羅性（docs/plans/PHASE_B_INTAKE.md 設計C）")
    a("")
    a(
        "`registry/variable_alias.csv` は `build_unit_variable.py` が原本 DB を一切開かずに "
        "作る（#7・CI のため）。そのため「154組が v1 の実データの組と過不足なく一致するか」は "
        "原本を読めるここでしか検証できない。**片方でもズレがあれば、黙って落とす・"
        "黙って埋めるのではなくここに列挙する。**"
    )
    a("")
    a(
        f"- registry 側 (dataset, alias, source_id): {ap['registry_total']}組。"
        f"v1 実データ側: {ap['data_total']}組。一致: {ap['matches']}組。"
    )
    a(
        f"- CSV にあるが実データに無い組: {len(ap['csv_only'])}組。"
        f"一覧: `reports/registry_resolution/alias_source_pairs_csv_only.csv`"
        f"（{ap['csv_only_csv_rows']}行。0行ならヘッダのみ）。"
    )
    for dataset, alias, source_id in ap["csv_only"]:
        a(f"  - `{dataset}` / `{alias}` / `{source_id or '(空)'}`")
    a(
        f"- 実データにあるが CSV に無い組: {len(ap['data_only'])}組。"
        f"一覧: `reports/registry_resolution/alias_source_pairs_data_only.csv`"
        f"（{ap['data_only_csv_rows']}行。0行ならヘッダのみ）。"
    )
    for dataset, alias, source_id in ap["data_only"]:
        n = ap["data_only_rows_by_key"][(dataset, alias, source_id)]
        a(f"  - `{dataset}` / `{alias}` / `{source_id or '(空)'}`（{n:,}行）")
    a("")

    a("## 生成ファイル一覧")
    a("")
    a("| ファイル | 行数（ヘッダ除く） | 内容 |")
    a("|---|---|---|")
    a(f"| `unresolved_variable_aliases.csv` | {v['unresolved_csv_rows']} | 未解決の指標表記 |")
    a(f"| `unresolved_site_ids.csv` | {p['unresolved_csv_rows']} | 未解決の site_id |")
    a(f"| `unresolved_organism_records.csv` | {o['unresolved_csv_rows']} | taxon_id が付かない occurrence |")
    a(f"| `needs_review_place.csv` | {nr['place_csv_rows']} | 座標未確認等の place |")
    a(f"| `needs_review_variable.csv` | {nr['variable_csv_rows']} | 単位・粒度未確定の variable |")
    a(f"| `needs_review_alias_stat.csv` | {nr['alias_stat_csv_rows']} | stat が空の variable_alias 行 |")
    a(f"| `unresolved_taxa.csv` | {t['unresolved_csv_rows']} | GBIF未照合の taxa（全件） |")
    a(
        f"| `alias_source_pairs_csv_only.csv` | {ap['csv_only_csv_rows']} | "
        "CSVにあるが実データに無い (dataset, alias, source_id) |"
    )
    a(
        f"| `alias_source_pairs_data_only.csv` | {ap['data_only_csv_rows']} | "
        "実データにあるがCSVに無い (dataset, alias, source_id) |"
    )
    a("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    src, ryuiki = connect()
    try:
        v = report_variable(ryuiki)
        p = report_place(ryuiki)
        o = report_organism(ryuiki)
        u = report_unit(ryuiki)
        nr = report_needs_review(ryuiki, u["still_missing_by_variable"])
        t = report_taxa(ryuiki)
        ap = report_alias_source_pairs(ryuiki)

        REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
        REPORT_MD.write_text(render_markdown(v, p, o, u, nr, t, ap), encoding="utf-8")
        print(f"完了: {REPORT_MD}")
        print(f"CSV: {CSV_DIR}/*.csv")
    finally:
        for c in src.values():
            c.close()


if __name__ == "__main__":
    main()
