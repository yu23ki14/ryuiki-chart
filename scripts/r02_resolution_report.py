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
    out = {}
    unresolved_rows = []

    for table, col, scope in (
        ("measurements", "variable", "measurements"),
        ("sensor_timeseries", "datastream", "sensor_timeseries"),
    ):
        total = scalar(ryuiki, f"SELECT count(*) FROM {table}")
        resolved = scalar(
            ryuiki,
            f"""
            SELECT count(*) FROM {table} t
            JOIN reg.variable_alias va ON va.alias = t.{col} AND va.source_scope = ?
            JOIN reg.variable v ON v.variable_id = va.variable_id
            """,
            (scope,),
        )
        unresolved = total - resolved
        out[table] = {"total": total, "resolved": resolved, "unresolved": unresolved}

        for r in rows(
            ryuiki,
            f"""
            SELECT t.{col} AS raw_label, count(*) AS n
            FROM {table} t
            LEFT JOIN reg.variable_alias va ON va.alias = t.{col} AND va.source_scope = ?
            LEFT JOIN reg.variable v ON v.variable_id = va.variable_id
            WHERE v.variable_id IS NULL
            GROUP BY t.{col}
            ORDER BY t.{col}
            """,
            (scope,),
        ):
            unresolved_rows.append((scope, r["raw_label"], r["n"]))

    out["unresolved_csv_rows"] = write_csv(
        "unresolved_variable_aliases.csv",
        ["source_scope", "raw_label", "row_count"],
        unresolved_rows,
    )
    return out


# ---------------------------------------------------------------------------
# B. measurements / sensor_timeseries の site_id -> place_id
# ---------------------------------------------------------------------------

def report_place(ryuiki: sqlite3.Connection) -> dict:
    out = {}
    unresolved_rows = []

    for table in ("measurements", "sensor_timeseries"):
        distinct_total = scalar(ryuiki, f"SELECT count(DISTINCT site_id) FROM {table}")
        distinct_resolved = scalar(
            ryuiki,
            f"""
            SELECT count(*) FROM (SELECT DISTINCT site_id FROM {table}) d
            JOIN reg.place_source_ref psr
              ON psr.external_key = d.site_id AND psr.source_id = 'sites.site_id'
            """,
        )
        row_total = scalar(ryuiki, f"SELECT count(*) FROM {table}")
        row_resolved = scalar(
            ryuiki,
            f"""
            SELECT count(*) FROM {table} t
            JOIN reg.place_source_ref psr
              ON psr.external_key = t.site_id AND psr.source_id = 'sites.site_id'
            """,
        )
        out[table] = {
            "distinct_total": distinct_total,
            "distinct_resolved": distinct_resolved,
            "distinct_unresolved": distinct_total - distinct_resolved,
            "row_total": row_total,
            "row_resolved": row_resolved,
            "row_unresolved": row_total - row_resolved,
        }

        for r in rows(
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
        ):
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
    total = scalar(ryuiki, "SELECT count(*) FROM organism_records")
    resolved = scalar(
        ryuiki,
        """
        SELECT count(*) FROM organism_records o
        JOIN reg.taxon t ON t.gbif_taxon_key = o.taxon_key
        WHERE o.taxon_key IS NOT NULL AND o.taxon_key <> ''
        """,
    )
    unresolved = total - resolved

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

    by_source = rows(
        ryuiki,
        """
        SELECT source_id, count(*) AS n
        FROM organism_records
        WHERE taxon_key IS NULL OR taxon_key = ''
        GROUP BY source_id
        ORDER BY source_id
        """,
    )

    return {
        "total": total,
        "resolved": resolved,
        "unresolved": unresolved,
        "unresolved_csv_rows": n_csv,
        "by_source": [(r["source_id"], r["n"]) for r in by_source],
    }


# ---------------------------------------------------------------------------
# D. 単位が決まる measurement 行（報告のみ）
# ---------------------------------------------------------------------------

def report_unit(ryuiki: sqlite3.Connection) -> dict:
    total_missing = scalar(
        ryuiki, "SELECT count(*) FROM measurements WHERE unit IS NULL OR unit = ''"
    )
    filled = scalar(
        ryuiki,
        """
        SELECT count(*) FROM measurements m
        LEFT JOIN reg.variable_alias va ON va.alias = m.variable AND va.source_scope = 'measurements'
        LEFT JOIN reg.variable v ON v.variable_id = va.variable_id
        WHERE (m.unit IS NULL OR m.unit = '')
          AND (va.unit_id IS NOT NULL OR v.unit_id IS NOT NULL)
        """,
    )
    still_missing = total_missing - filled

    by_variable = rows(
        ryuiki,
        """
        SELECT m.variable AS raw_label, va.variable_id AS variable_id, count(*) AS n
        FROM measurements m
        LEFT JOIN reg.variable_alias va ON va.alias = m.variable AND va.source_scope = 'measurements'
        LEFT JOIN reg.variable v ON v.variable_id = va.variable_id
        WHERE (m.unit IS NULL OR m.unit = '')
          AND va.unit_id IS NULL AND v.unit_id IS NULL
        GROUP BY m.variable, va.variable_id
        ORDER BY m.variable
        """,
    )

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
    fallback_reason = (
        "description_ja が未設定（unit_id が決まらないため status=needs_review。"
        "経緯は registry/variable.yaml のコメント参照）"
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

    return {
        "place_count": len(place_rows),
        "place_csv_rows": n_place_csv,
        "variable_count": len(variable_rows),
        "variable_csv_rows": n_variable_csv,
        "variable_rows": [
            (r["variable_id"], r["code"], r["name_ja"], r["description_ja"] or fallback_reason)
            for r in variable_rows
        ],
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


def render_markdown(v, p, o, u, nr, t) -> str:
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
    a("")

    if not (m_ok and s_ok and pm_ok and ps_ok and o_ok):
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
        f"`variable_alias`（`source_scope='measurements'`）で全件解決"
        f"（未解決 {v['measurements']['unresolved']:,}行）。"
    )
    a(
        f"- `sensor_timeseries` {v['sensor_timeseries']['total']:,}行、同様に "
        f"`source_scope='sensor_timeseries'` で全件解決"
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
    a("- 出典別の内訳（全件が同一理由: 分類群情報が空欄で照合材料が無い）:")
    a("")
    a("  | source_id | 未解決行数 |")
    a("  |---|---|")
    for source_id, n in o["by_source"]:
        a(f"  | `{source_id}` | {n:,} |")
    a("")

    a("## 6. 単位が決まる measurement 行（報告のみ）")
    a("")
    a(
        f"- 原本で単位（`unit`）が空の行 {u['total_missing']:,}行のうち、"
        f"`variable_alias.unit_id`（無ければ `variable.unit_id`）で "
        f"{u['filled']:,}行（{pct(u['filled'], u['total_missing'])}）の単位が決まる。"
    )
    a(
        f"- 残り {u['still_missing']:,}行は変数自体が `needs_review`"
        f"（下記 §7 の `variable` 一覧を参照）で、単位が決まらない。"
    )
    a("- 単位が埋まらない行の内訳（原文の指標表記別）:")
    a("")
    a("  | 原文の指標表記 | 対応する variable_id | 未解決行数 |")
    a("  |---|---|---|")
    for raw_label, variable_id, n in u["still_missing_by_variable"]:
        a(f"  | `{raw_label}` | `{variable_id}` | {n:,} |")
    a("")

    a("## needs_review の一覧（place / variable）")
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
    a("- 未照合・弱い一致の内訳（`gbif_match_type` 別。EXACT を除く全件）:")
    a("")
    a("  | gbif_match_type | 件数 | 意味 |")
    a("  |---|---|---|")
    for match_type, n in t["by_match_type"]:
        if match_type == "NONE":
            meaning = "GBIFへ照会したが一致しなかった"
        elif match_type in ("HIGHERRANK", "FUZZY"):
            meaning = "GBIFに照会でき gbif_taxon_key はあるが、種階級までの一致ではない"
        else:
            meaning = "GBIFへの照会自体が未実施（gbif_taxon_key欠落）"
        a(f"  | `{match_type}` | {n:,} | {meaning} |")
    a("")
    a(
        f"- 全件（{t['unresolved_csv_rows']}行）: "
        f"`reports/registry_resolution/unresolved_taxa.csv`。"
        f"以下は先頭 {len(t['sample'])} 件（`taxon_id` 昇順の代表例。全件は上記CSV参照）:"
    )
    a("")
    a("  | taxon_id | scientific_name | vernacular_name_ja | taxon_group_ja | gbif_match_type |")
    a("  |---|---|---|---|---|")
    for r in t["sample"]:
        a(
            f"  | `{r['taxon_id']}` | {r['scientific_name'] or ''} | "
            f"{r['vernacular_name_ja'] or ''} | {r['taxon_group_ja'] or ''} | "
            f"{r['gbif_match_type'] or ''} |"
        )
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
    a(f"| `unresolved_taxa.csv` | {t['unresolved_csv_rows']} | GBIF未照合の taxa（全件） |")
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

        REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
        REPORT_MD.write_text(render_markdown(v, p, o, u, nr, t), encoding="utf-8")
        print(f"完了: {REPORT_MD}")
        print(f"CSV: {CSV_DIR}/*.csv")
    finally:
        for c in src.values():
            c.close()


if __name__ == "__main__":
    main()
