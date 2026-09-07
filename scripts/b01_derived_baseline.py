#!/usr/bin/env python3
"""v1 派生33テーブル（`data/db/derived.sqlite`）の指紋を作る（ADR-0016 Phase B の
受け入れゲート。docs/plans/PHASE_B_RECONCILIATION.md 参照）。

    .venv/bin/python3 scripts/b01_derived_baseline.py

`reports/derived_baseline.json`（このコマンドが唯一の正）と、人が読む要約
`reports/derived_baseline.md` を書く。**derived.sqlite は読み取り専用でしか開かない。**

## このスクリプトがすること

各テーブルについて:
  - 行数、列名と宣言型
  - 一意なキー列（自動導出。`scripts/reconcile/common.py` の `derive_key()` 参照）
  - 数値列ごとの非NULL件数・min・max・合計（丸め規則: 小数点以下6桁固定）
  - キー順にソートした全行の内容ハッシュ（sha256）

`reports/derived_baseline.json` はコミットする。数百KB〜数MBに収まる設計
（行データそのものは持たず、集計値と1個のハッシュだけを持つため）。

## 決定論

実行時刻・ホスト名など実行環境に依存する値は一切書き込まない。同じ
`derived.sqlite` に対して2回実行すると、出力ファイルはバイト単位で一致する
（`scripts/tests/test_b01_determinism.py` で検証）。JSON は `sort_keys=True` で書く。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from reconcile import common, datasource  # noqa: E402

DEFAULT_DB = ROOT / "data" / "db" / "derived.sqlite"
DEFAULT_KEYS_YAML = ROOT / "scripts" / "reconcile" / "derived_keys.yaml"
DEFAULT_DESTINATIONS_YAML = ROOT / "scripts" / "reconcile" / "adr0011_destinations.yaml"
DEFAULT_OUT_JSON = ROOT / "reports" / "derived_baseline.json"
DEFAULT_OUT_MD = ROOT / "reports" / "derived_baseline.md"


def build_baseline(db_path, keys_yaml_path) -> tuple[dict, dict[str, int]]:
    """`db_path` の全テーブルを指紋化する。`(baseline, key_sources)` を返す
    （ファイルには書かない）。

    `baseline` の構造はそのまま `reports/derived_baseline.json` の中身になる
    （`write_json` に渡す）。`key_sources` はキーの由来（`"pk"`/`"auto"`/
    `"declared"`）ごとのテーブル数で、CLI のログ出力と `render_markdown` の
    「キーの由来の内訳」節の両方に使う（`main()` 参照。決定論が要る出力
    ファイルには含めない）。

    b02 はこの関数を使わず、この関数が書いた JSON を読む側（`derive_key` を
    再実行しない。理由は docs/plans/PHASE_B_RECONCILIATION.md 参照）。
    """
    conn = common.open_readonly(db_path)
    overrides = common.load_key_overrides(keys_yaml_path)
    source = datasource.SqliteSource(conn)
    try:
        table_entries = {}
        key_sources: dict[str, int] = {}
        for table in source.tables():
            columns = common.get_columns(conn, table)
            column_types = common.get_column_types(conn, table)
            key, key_source, key_note = common.derive_key(conn, table, overrides)
            key_sources[key_source] = key_sources.get(key_source, 0) + 1

            numeric_columns = common.numeric_columns_of(conn, table, columns)
            fp = common.compute_fingerprint(source, table, columns, key, numeric_columns)

            table_entries[table] = {
                "row_count": fp["row_count"],
                "columns": [{"name": c, "type": column_types[c]} for c in columns],
                "key": key,
                "key_source": key_source,
                "key_note": key_note,
                "numeric_columns": fp["numeric_stats"],
                "content_hash": fp["content_hash"],
            }

        total_rows = sum(t["row_count"] for t in table_entries.values())
        baseline = {
            "schema_version": common.SCHEMA_VERSION,
            "source_db": pathlib.Path(db_path).name,
            "table_count": len(table_entries),
            "total_rows": total_rows,
            "tables": table_entries,
        }
        return baseline, key_sources
    finally:
        conn.close()


def write_json(baseline: dict, out_path) -> None:
    out_path = pathlib.Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(baseline, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    out_path.write_text(text, encoding="utf-8")


def render_markdown(baseline: dict, destinations: dict[str, dict], key_sources: dict[str, int]) -> str:
    lines: list[str] = []
    a = lines.append

    a("# v1 派生テーブルのベースライン指紋（Phase B 受け入れゲート）")
    a("")
    a(
        "`scripts/b01_derived_baseline.py` が `data/db/derived.sqlite`（読み取り専用）から生成する。"
        "機械可読な本体は `reports/derived_baseline.json`。このファイルは人が読む要約。"
    )
    a("")
    a("再生成: `.venv/bin/python3 scripts/b01_derived_baseline.py`")
    a("")
    a(
        f"テーブル数 **{baseline['table_count']}** / 総行数 **{baseline['total_rows']:,}**"
        f"（`data/db/{baseline['source_db']}` より）。"
    )
    a("")
    a(
        "「行き先」列は `docs/adr/0011-aggregation-cube.md` の「33テーブルの行き先」表"
        "（`scripts/reconcile/adr0011_destinations.yaml` にデータとして持つ）。"
    )
    a("")
    a("## テーブル一覧")
    a("")
    a("| テーブル | 行数 | キー | キーの由来 | 行き先（ADR-0011） | 内容ハッシュ（先頭12桁） |")
    a("|---|---:|---|---|---|---|")
    for table in sorted(baseline["tables"]):
        entry = baseline["tables"][table]
        key = ", ".join(f"`{c}`" for c in entry["key"])
        dest = destinations.get(table, {}).get("label_ja", "（未分類）")
        hash_short = entry["content_hash"].removeprefix("sha256:")[:12]
        a(
            f"| `{table}` | {entry['row_count']:,} | {key} | {entry['key_source']} | "
            f"{dest} | `{hash_short}…` |"
        )
    a("")

    declared = [t for t, e in baseline["tables"].items() if e["key_source"] == "declared"]
    a("## キーの由来の内訳")
    a("")
    for source_kind in ("pk", "auto", "declared"):
        if source_kind in key_sources:
            a(f"- `{source_kind}`: {key_sources[source_kind]}テーブル")
    a("")
    if declared:
        a(
            "`declared`（`scripts/reconcile/derived_keys.yaml` の宣言に頼ったテーブル）。"
            "宣言キーには「なぜ自動で決まらないか」の理由（`derived_keys.yaml` の"
            "`reason`）を必ず添えることになっているので、ここにその理由も出す:"
        )
        a("")
        for t in sorted(declared):
            note = baseline["tables"][t].get("key_note") or "（理由が記録されていない）"
            a(f"- `{t}`: {note}")
    else:
        a(
            "`declared` は0件。33テーブルすべて自動導出できた"
            "（`scripts/reconcile/derived_keys.yaml` は現時点で空）。"
        )
    a("")

    a("## 数値列のサマリ")
    a("")
    a("列数が多いテーブルもあるため、数値列ごとの詳細は JSON 側（`numeric_columns`）を参照。")
    a("ここでは数値列の個数だけを一覧にする。")
    a("")
    a("| テーブル | 数値列の数 |")
    a("|---|---:|")
    for table in sorted(baseline["tables"]):
        n = len(baseline["tables"][table]["numeric_columns"])
        a(f"| `{table}` | {n} |")
    a("")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--keys-yaml", default=str(DEFAULT_KEYS_YAML))
    parser.add_argument("--destinations-yaml", default=str(DEFAULT_DESTINATIONS_YAML))
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    args = parser.parse_args()

    print(f"▶ 読み取り専用で開く: {args.db}")
    baseline, key_sources = build_baseline(args.db, args.keys_yaml)
    print(
        f"完了: {baseline['table_count']}テーブル / {baseline['total_rows']:,}行。"
        f"キーの由来: {key_sources}"
    )

    write_json(baseline, args.out_json)
    print(f"→ {args.out_json}")

    destinations = common.load_destinations(args.destinations_yaml)
    md = render_markdown(baseline, destinations, key_sources)
    out_md = pathlib.Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md, encoding="utf-8")
    print(f"→ {args.out_md}")


if __name__ == "__main__":
    main()
