#!/usr/bin/env python3
"""v1 派生テーブルのベースライン指紋（`reports/derived_baseline.json`）と、
候補側（v2 のキューブから射影した「同じ形」のテーブル群）を突き合わせる
（ADR-0016 Phase B の受け入れゲート。docs/plans/PHASE_B_RECONCILIATION.md 参照）。

    .venv/bin/python3 scripts/b02_derived_compare.py --candidate <sqlite または .json>

`reports/derived_reconciliation.md` を書き、差が1つでもあれば非0で終了する
（既定の許容誤差は0＝完全一致。浮動小数の表現差だけを吸収したい場合のみ
`--tolerance` を渡す）。

## 2つの動作モード

候補側は「v2 のキューブが無いいま」でもテストできるよう、sqlite / JSON の
どちらでも受ける（拡張子で自動判定。`scripts/reconcile/datasource.py`）。

- **完全モード**（`--baseline-data` を指定、または既定の
  `data/db/derived.sqlite` が存在する）: ベースライン側の実データと候補側の
  実データを行レベルで突き合わせる。キー集合の差・数値列ごとの差の分布が出せる。
  併せて、渡された実データが `derived_baseline.json` の記録と食い違っていないか
  （＝ b01 を再実行し忘れていないか）も検証する。
- **縮退モード**（`--baseline-data` 無し・既定の実データも無い。CI の実行環境）:
  `derived_baseline.json` に記録した行数・内容ハッシュ・数値集計と候補側を
  比べるだけ。行レベルの内訳（どのキーが欠けているか等）は出せない
  （原本 14GB が無いと計算できないため。docs/plans/PHASE_B_RECONCILIATION.md
  の「CI の限界」参照）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Sequence

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from reconcile import common, datasource  # noqa: E402

DEFAULT_BASELINE_JSON = ROOT / "reports" / "derived_baseline.json"
DEFAULT_BASELINE_DB = ROOT / "data" / "db" / "derived.sqlite"
DEFAULT_OUT_MD = ROOT / "reports" / "derived_reconciliation.md"

SAMPLE_LIMIT = 20  # レポートに出す「先頭N件の実例」


# ---------------------------------------------------------------------------
# 数値の差
# ---------------------------------------------------------------------------

def _percentile(sorted_values: Sequence[float], p: float) -> float:
    """最近傍法の簡易パーセンタイル（numpy 非依存）。`sorted_values` は昇順ソート済み。"""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = min(len(sorted_values) - 1, max(0, round(p / 100 * (len(sorted_values) - 1))))
    return sorted_values[idx]


def _exceeds_tolerance(baseline_val: float, candidate_val: float, tolerance: float) -> bool:
    """既定（tolerance=0）は完全一致。tolerance>0 のときは相対誤差で判定するが、
    ベースライン値が0付近でも壊れないよう極小の絶対許容（1e-9）を下限にする。
    """
    abs_diff = abs(candidate_val - baseline_val)
    if tolerance <= 0:
        return abs_diff != 0
    allowed = max(tolerance * abs(baseline_val), 1e-9)
    return abs_diff > allowed


# ---------------------------------------------------------------------------
# テーブル単位の突合
# ---------------------------------------------------------------------------

def _build_key_map(source: datasource.DataSource, table: str, columns: list[str], key: list[str]):
    """`table` を `key` 順に読み、key タプル -> 行タプル の辞書を作る。

    重複キー（この突合の前提「行がキーで一意」が崩れている状態）が見つかった場合は
    別リストで返す（最初の出現を代表として辞書には残す）。
    """
    key_idx = [columns.index(c) for c in key]
    key_map: dict[tuple, tuple] = {}
    duplicates: list[tuple] = []
    for row in source.fetch_rows(table, columns, order_by=key):
        k = tuple(row[i] for i in key_idx)
        if k in key_map:
            duplicates.append(k)
        else:
            key_map[k] = row
    return key_map, duplicates


def _compare_full(
    table: str,
    entry: dict,
    baseline_source: datasource.DataSource,
    candidate_source: datasource.DataSource,
    tolerance: float,
) -> dict:
    columns = [c["name"] for c in entry["columns"]]
    key = entry["key"]
    numeric_columns = list(entry["numeric_columns"].keys())
    result: dict = {"mode": "full", "notes": []}

    baseline_map, baseline_dupes = _build_key_map(baseline_source, table, columns, key)
    candidate_map, candidate_dupes = _build_key_map(candidate_source, table, columns, key)

    if baseline_dupes:
        result["notes"].append(
            f"ベースライン実データに重複キーが{len(baseline_dupes)}件ある"
            "（このテーブルの突合の前提であるキーの一意性が崩れている）。"
        )
    if candidate_dupes:
        result["notes"].append(
            f"候補側に重複キーが{len(candidate_dupes)}件ある"
            "（先頭N件: " + ", ".join(str(k) for k in candidate_dupes[:5]) + "）。"
        )

    baseline_keys = set(baseline_map.keys())
    candidate_keys = set(candidate_map.keys())
    only_in_baseline = sorted(baseline_keys - candidate_keys)
    only_in_candidate = sorted(candidate_keys - baseline_keys)
    common_keys = baseline_keys & candidate_keys

    result["baseline_row_count"] = len(baseline_map)
    result["candidate_row_count"] = len(candidate_map)
    result["row_count_diff"] = len(candidate_map) - len(baseline_map)
    result["keys_only_in_baseline"] = {
        "count": len(only_in_baseline),
        "sample": [list(k) for k in only_in_baseline[:SAMPLE_LIMIT]],
    }
    result["keys_only_in_candidate"] = {
        "count": len(only_in_candidate),
        "sample": [list(k) for k in only_in_candidate[:SAMPLE_LIMIT]],
    }

    numeric_diffs = {}
    numeric_idx = {c: columns.index(c) for c in numeric_columns}
    for col in numeric_columns:
        i = numeric_idx[col]
        abs_diffs = []
        rel_diffs = []
        n_exceed = 0
        n_null_mismatch = 0
        for k in common_keys:
            bv = baseline_map[k][i]
            cv = candidate_map[k][i]
            if bv is None or cv is None:
                if bv is not cv:
                    n_null_mismatch += 1
                continue
            bv = float(bv)
            cv = float(cv)
            abs_diff = abs(cv - bv)
            abs_diffs.append(abs_diff)
            rel_diffs.append(abs_diff / abs(bv) if bv != 0 else (0.0 if abs_diff == 0 else float("inf")))
            if _exceeds_tolerance(bv, cv, tolerance):
                n_exceed += 1
        abs_diffs.sort()
        numeric_diffs[col] = {
            "n_compared": len(abs_diffs),
            "n_null_mismatch": n_null_mismatch,
            "n_exceeding_tolerance": n_exceed,
            "max_abs_diff": max(abs_diffs) if abs_diffs else 0.0,
            "p50_abs_diff": _percentile(abs_diffs, 50),
            "p95_abs_diff": _percentile(abs_diffs, 95),
            "max_rel_diff": max(rel_diffs) if rel_diffs else 0.0,
        }
    result["numeric_diffs"] = numeric_diffs

    # 数値以外の列（次元列だが key に含まれないもの等）も、値の変化を1つ残らず
    # 検出する対象に含める。ADR-0011 の統計量ではないので分布は出さず、
    # 完全一致件数の差分だけを数える（許容誤差はそもそも数値以外に適用できない）。
    text_columns = [c for c in columns if c not in key and c not in numeric_columns]
    text_idx = {c: columns.index(c) for c in text_columns}
    text_diffs = {}
    for col in text_columns:
        i = text_idx[col]
        n_diff = sum(1 for k in common_keys if baseline_map[k][i] != candidate_map[k][i])
        if n_diff:
            text_diffs[col] = n_diff
    result["text_diffs"] = text_diffs

    matches = (
        not only_in_baseline
        and not only_in_candidate
        and not baseline_dupes
        and not candidate_dupes
        and not text_diffs
        and all(d["n_exceeding_tolerance"] == 0 and d["n_null_mismatch"] == 0 for d in numeric_diffs.values())
    )
    result["status"] = "match" if matches else "mismatch"
    return result


def _compare_reduced(table: str, entry: dict, candidate_source: datasource.DataSource) -> dict:
    columns = [c["name"] for c in entry["columns"]]
    key = entry["key"]
    numeric_columns = list(entry["numeric_columns"].keys())
    result: dict = {"mode": "reduced", "notes": [
        "縮退モード: ベースラインの実データが無いため、行レベルの内訳"
        "（キー集合の差・数値列ごとの差の分布）は計算できない。"
        "行数・内容ハッシュ・数値集計の一致だけを見る。"
    ]}

    fp = common.compute_fingerprint(candidate_source, table, columns, key, numeric_columns)
    result["baseline_row_count"] = entry["row_count"]
    result["candidate_row_count"] = fp["row_count"]
    result["row_count_diff"] = fp["row_count"] - entry["row_count"]
    result["baseline_content_hash"] = entry["content_hash"]
    result["candidate_content_hash"] = fp["content_hash"]
    hash_matches = fp["content_hash"] == entry["content_hash"]

    numeric_diffs = {}
    for col in numeric_columns:
        baseline_stat = entry["numeric_columns"][col]
        candidate_stat = fp["numeric_stats"][col]
        col_matches = baseline_stat == candidate_stat
        numeric_diffs[col] = {
            "baseline": baseline_stat,
            "candidate": candidate_stat,
            "matches": col_matches,
        }
    result["numeric_diffs"] = numeric_diffs

    matches = (
        result["row_count_diff"] == 0
        and hash_matches
        and all(d["matches"] for d in numeric_diffs.values())
    )
    result["status"] = "match" if matches else "mismatch"
    return result


def compare_all(baseline_json: dict, baseline_source, candidate_source, tolerance: float) -> dict:
    """全テーブルを突合する。`baseline_source` が None なら縮退モード。"""
    results: dict[str, dict] = {}
    for table, entry in sorted(baseline_json["tables"].items()):
        if not candidate_source.has_table(table):
            results[table] = {
                "mode": "full" if baseline_source is not None else "reduced",
                "status": "missing_in_candidate",
                "baseline_row_count": entry["row_count"],
                "candidate_row_count": 0,
                "row_count_diff": -entry["row_count"],
                "notes": ["候補側にこのテーブルが無い。"],
                "numeric_diffs": {},
            }
            continue

        candidate_columns = set(candidate_source.columns(table))
        declared_columns = [c["name"] for c in entry["columns"]]
        missing_columns = [c for c in declared_columns if c not in candidate_columns]
        if missing_columns:
            results[table] = {
                "mode": "full" if baseline_source is not None else "reduced",
                "status": "incomparable",
                "baseline_row_count": entry["row_count"],
                "candidate_row_count": candidate_source.row_count(table),
                "row_count_diff": candidate_source.row_count(table) - entry["row_count"],
                "notes": [f"候補側に列が無い: {missing_columns}"],
                "numeric_diffs": {},
            }
            continue

        if baseline_source is not None:
            results[table] = _compare_full(table, entry, baseline_source, candidate_source, tolerance)
        else:
            results[table] = _compare_reduced(table, entry, candidate_source)
    return results


def check_baseline_freshness(baseline_json: dict, baseline_source) -> list[str]:
    """`baseline_source`（実データ）から再計算した指紋が `baseline_json` の記録と
    一致するか確認する。食い違いがあれば、そのテーブル名を返す
    （= b01 を再実行してコミットし直す必要がある、という意味）。
    """
    stale: list[str] = []
    for table, entry in sorted(baseline_json["tables"].items()):
        if not baseline_source.has_table(table):
            stale.append(table)
            continue
        columns = [c["name"] for c in entry["columns"]]
        key = entry["key"]
        numeric_columns = list(entry["numeric_columns"].keys())
        fp = common.compute_fingerprint(baseline_source, table, columns, key, numeric_columns)
        if fp["row_count"] != entry["row_count"] or fp["content_hash"] != entry["content_hash"]:
            stale.append(table)
    return stale


# ---------------------------------------------------------------------------
# レポート
# ---------------------------------------------------------------------------

STATUS_LABEL = {
    "match": "一致",
    "mismatch": "不一致",
    "missing_in_candidate": "候補側に無い",
    "incomparable": "比較不能（列が無い）",
}


def render_markdown(results: dict[str, dict], mode: str, tolerance: float, stale_tables: list[str]) -> str:
    lines: list[str] = []
    a = lines.append

    a("# Phase B 突合レポート")
    a("")
    a(
        "`scripts/b02_derived_compare.py` が `reports/derived_baseline.json`"
        "（v1 派生テーブルの指紋）と候補側を突き合わせた結果。"
    )
    a("")
    mode_ja = "完全モード（行レベルの内訳あり）" if mode == "full" else "縮退モード（行数・ハッシュ・集計のみ）"
    a(f"モード: **{mode_ja}** / 許容誤差: {tolerance}")
    a("")

    if stale_tables:
        a("## ベースラインの整合性エラー")
        a("")
        a(
            "**`--baseline-data` の実データが `derived_baseline.json` の記録と食い違うテーブルがある。"
            "`scripts/b01_derived_baseline.py` を再実行して `derived_baseline.json` を更新すること。"
            "このレポートの以下の内容は信頼できない可能性がある。**"
        )
        a("")
        for t in stale_tables:
            a(f"- `{t}`")
        a("")

    matched = sorted(t for t, r in results.items() if r["status"] == "match")
    mismatched = sorted(t for t, r in results.items() if r["status"] != "match")

    a("## サマリ（先に見る場所）")
    a("")
    a(f"- 一致: {len(matched)}テーブル")
    a(f"- 不一致: {len(mismatched)}テーブル")
    a("")
    if matched:
        a("**一致したテーブル**: " + ", ".join(f"`{t}`" for t in matched))
        a("")
    if mismatched:
        a("**不一致のテーブル**:")
        a("")
        a("| テーブル | 状態 | 行数差 |")
        a("|---|---|---:|")
        for t in mismatched:
            r = results[t]
            a(f"| `{t}` | {STATUS_LABEL.get(r['status'], r['status'])} | {r.get('row_count_diff', 'n/a')} |")
        a("")

    a("## テーブルごとの詳細")
    a("")
    for table in sorted(results):
        r = results[table]
        a(f"### `{table}` — {STATUS_LABEL.get(r['status'], r['status'])}")
        a("")
        a(f"- ベースライン行数: {r.get('baseline_row_count', 'n/a')}")
        a(f"- 候補行数: {r.get('candidate_row_count', 'n/a')}（差 {r.get('row_count_diff', 'n/a')}）")
        for note in r.get("notes", []):
            a(f"- {note}")

        if r["mode"] == "full" and "keys_only_in_baseline" in r:
            kob = r["keys_only_in_baseline"]
            koc = r["keys_only_in_candidate"]
            a(f"- ベースラインにしか無い行: {kob['count']}件" + (f"（例: {kob['sample'][:5]}）" if kob["sample"] else ""))
            a(f"- 候補にしか無い行: {koc['count']}件" + (f"（例: {koc['sample'][:5]}）" if koc["sample"] else ""))
            if r.get("text_diffs"):
                a(
                    "- 数値以外の列で値が食い違う行がある: "
                    + ", ".join(f"`{c}` {n}件" for c, n in sorted(r["text_diffs"].items()))
                )
            if r.get("numeric_diffs"):
                a("")
                a("  | 数値列 | 比較件数 | NULL不一致 | 許容超え | max絶対差 | p50絶対差 | p95絶対差 | max相対差 |")
                a("  |---|---:|---:|---:|---:|---:|---:|---:|")
                for col, d in sorted(r["numeric_diffs"].items()):
                    a(
                        f"  | `{col}` | {d['n_compared']} | {d['n_null_mismatch']} | "
                        f"{d['n_exceeding_tolerance']} | {d['max_abs_diff']:.6g} | "
                        f"{d['p50_abs_diff']:.6g} | {d['p95_abs_diff']:.6g} | {d['max_rel_diff']:.6g} |"
                    )
        elif r["mode"] == "reduced" and "numeric_diffs" in r and r.get("baseline_content_hash"):
            a(f"- ベースライン内容ハッシュ: `{r['baseline_content_hash']}`")
            a(f"- 候補内容ハッシュ: `{r['candidate_content_hash']}`")
            mismatched_cols = [c for c, d in r["numeric_diffs"].items() if not d["matches"]]
            if mismatched_cols:
                a(f"- 集計が食い違う数値列: {', '.join(f'`{c}`' for c in mismatched_cols)}")
        a("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-json", default=str(DEFAULT_BASELINE_JSON))
    parser.add_argument(
        "--baseline-data",
        default=None,
        help="ベースライン側の実データ（sqlite または .json）。省略時は "
        f"{DEFAULT_BASELINE_DB} があれば使い、無ければ縮退モードにする。",
    )
    parser.add_argument("--candidate", required=True, help="候補側（sqlite または .json）")
    parser.add_argument("--tolerance", type=float, default=0.0)
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    args = parser.parse_args()

    baseline_json_path = pathlib.Path(args.baseline_json)
    if not baseline_json_path.exists():
        sys.exit(
            f"ベースラインが無い: {baseline_json_path}\n"
            "先に `.venv/bin/python3 scripts/b01_derived_baseline.py` を実行すること。"
        )
    baseline_json = json.loads(baseline_json_path.read_text(encoding="utf-8"))

    baseline_data_path = args.baseline_data
    if baseline_data_path is None and DEFAULT_BASELINE_DB.exists():
        baseline_data_path = str(DEFAULT_BASELINE_DB)

    candidate_source = datasource.open_source(args.candidate)

    stale_tables: list[str] = []
    if baseline_data_path is not None:
        baseline_source = datasource.open_source(baseline_data_path)
        stale_tables = check_baseline_freshness(baseline_json, baseline_source)
        mode = "full"
    else:
        baseline_source = None
        mode = "reduced"
        print(
            "▶ ベースラインの実データが無いので縮退モードで実行する"
            "（行レベルの内訳は出せない。docs/plans/PHASE_B_RECONCILIATION.md 参照）"
        )

    results = compare_all(baseline_json, baseline_source, candidate_source, args.tolerance)

    md = render_markdown(results, mode, args.tolerance, stale_tables)
    out_md = pathlib.Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md, encoding="utf-8")
    print(f"→ {out_md}")

    n_mismatch = sum(1 for r in results.values() if r["status"] != "match")
    n_match = len(results) - n_mismatch
    print(f"一致: {n_match} / 不一致: {n_mismatch}")

    if stale_tables:
        print(f"ベースラインが実データと食い違うテーブル: {stale_tables}", file=sys.stderr)
        return 1
    return 1 if n_mismatch > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
