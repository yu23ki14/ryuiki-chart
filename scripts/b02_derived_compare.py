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
- **縮退モード**（`--baseline-data` 無し・既定の実データも無い。または
  `--reduced` で明示的に強制。CI の実行環境）: `derived_baseline.json` に
  記録した行数・内容ハッシュ・数値集計と候補側を比べるだけ。行レベルの内訳
  （どのキーが欠けているか等）は出せない（原本 14GB が無いと計算できない
  ため。docs/plans/PHASE_B_RECONCILIATION.md の「CI の限界」参照）。
  縮退モードでは `--tolerance` は使えない（ハッシュ同士の比較に許容誤差の
  概念が無いため、指定すると明示的なエラーで止まる）。
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

class _KeyedStream:
    """`source.fetch_rows(table, columns, order_by=key)`（キー順）を1件ずつ
    取り出せるようにする、突合用のマージ結合の片側。

    以前の実装は両テーブルを丸ごと `dict[key, row]` に読み込んでから集合演算で
    突き合わせていた。`org_norm`（816,856行）・`sensor_daily`（352,043行）の
    ような大きいテーブルでは、これがベースライン・候補それぞれ全列を
    メモリに保持することになり無駄が大きい（レビュー指摘）。両ソースは
    すでに `fetch_rows(..., order_by=key)` でキー順に取れるので、ここでは
    単純なマージ結合にして、保持するのは「今見ている1行」と
    レポート用のサンプル（`SAMPLE_LIMIT` 件まで）・数値列ごとの差分リストだけにする。

    同じキーが連続した場合は最初の行を代表として扱い、以降は重複として
    数える（`dup_count`／`dup_keys`。この突合の前提「行がキーで一意」が
    崩れている状態を検出する）。
    """

    _SENTINEL = object()

    def __init__(self, source: datasource.DataSource, table: str, columns: list[str], key: list[str]):
        self._key_idx = [columns.index(c) for c in key]
        self._iter = iter(source.fetch_rows(table, columns, order_by=key))
        self.dup_count = 0
        self.dup_keys: list[list] = []
        self._next: tuple | object = self._SENTINEL
        self._advance()

    def _row_key(self, row: tuple) -> tuple:
        return tuple(row[i] for i in self._key_idx)

    def _advance(self) -> None:
        self._next = next(self._iter, self._SENTINEL)

    def peek_key(self):
        """次に取り出される行のキー。ストリームが尽きていれば `None`。"""
        if self._next is self._SENTINEL:
            return None
        return self._row_key(self._next)

    def pop(self) -> tuple[tuple, tuple]:
        """現在のキーの代表行 `(key, row)` を返し、同じキーが続く分は
        重複として飲み込んで次の異なるキーまで進める。"""
        if self._next is self._SENTINEL:
            raise StopIteration
        current_key = self._row_key(self._next)
        row = self._next
        self._advance()
        while self._next is not self._SENTINEL and self._row_key(self._next) == current_key:
            self.dup_count += 1
            if len(self.dup_keys) < SAMPLE_LIMIT:
                self.dup_keys.append(list(current_key))
            self._advance()
        return current_key, row


def _key_less(a: tuple, b: tuple) -> bool:
    """突合のマージ結合で使うキー比較。SQLite の型順序（NULL < 数値 < TEXT
    < BLOB）に揃える（`datasource.sqlite_sort_key`）。NULL や型混在があると
    素朴な `<` は `TypeError` になる（レビュー指摘: 不一致のときにしか
    通らない経路でだけ落ちる、最悪の壊れ方だった）。
    """
    return datasource.sqlite_sort_key(a) < datasource.sqlite_sort_key(b)


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
    numeric_idx = {c: columns.index(c) for c in numeric_columns}
    # 数値以外の列（次元列だが key に含まれないもの等）も、値の変化を1つ残らず
    # 検出する対象に含める。ADR-0011 の統計量ではないので分布は出さず、
    # 完全一致件数の差分だけを数える（許容誤差はそもそも数値以外に適用できない）。
    text_columns = [c for c in columns if c not in key and c not in numeric_columns]
    text_idx = {c: columns.index(c) for c in text_columns}

    result: dict = {"mode": "full", "notes": []}

    baseline_stream = _KeyedStream(baseline_source, table, columns, key)
    candidate_stream = _KeyedStream(candidate_source, table, columns, key)

    baseline_row_count = 0
    candidate_row_count = 0
    only_in_baseline_count = 0
    only_in_baseline_sample: list[list] = []
    only_in_candidate_count = 0
    only_in_candidate_sample: list[list] = []

    abs_diffs: dict[str, list[float]] = {c: [] for c in numeric_columns}
    rel_diffs: dict[str, list[float]] = {c: [] for c in numeric_columns}
    n_null_mismatch: dict[str, int] = {c: 0 for c in numeric_columns}
    n_unparseable: dict[str, int] = {c: 0 for c in numeric_columns}
    n_exceed: dict[str, int] = {c: 0 for c in numeric_columns}
    text_diff_counts: dict[str, int] = {}

    # 両ソースをキー順にマージ結合する。片側にしか無いキーは前へ進めるだけ、
    # 両側にあるキーだけ値を突き合わせる（`_KeyedStream` のドキストリング参照）。
    while baseline_stream.peek_key() is not None or candidate_stream.peek_key() is not None:
        bk = baseline_stream.peek_key()
        ck = candidate_stream.peek_key()
        if bk is not None and (ck is None or _key_less(bk, ck)):
            baseline_stream.pop()
            baseline_row_count += 1
            only_in_baseline_count += 1
            if len(only_in_baseline_sample) < SAMPLE_LIMIT:
                only_in_baseline_sample.append(list(bk))
            continue
        if ck is not None and (bk is None or _key_less(ck, bk)):
            candidate_stream.pop()
            candidate_row_count += 1
            only_in_candidate_count += 1
            if len(only_in_candidate_sample) < SAMPLE_LIMIT:
                only_in_candidate_sample.append(list(ck))
            continue

        # bk == ck（両側に存在する共通キー）。
        _, brow = baseline_stream.pop()
        _, crow = candidate_stream.pop()
        baseline_row_count += 1
        candidate_row_count += 1

        for col in numeric_columns:
            i = numeric_idx[col]
            bv, cv = brow[i], crow[i]
            if bv is None or cv is None:
                if bv is not cv:
                    n_null_mismatch[col] += 1
                continue
            try:
                bv_f = float(bv)
                cv_f = float(cv)
            except (TypeError, ValueError):
                # 候補が数値列のはずの場所に "N/A" 等の非数値を書いてきた場合。
                # 落ちずに差として数える（レビュー指摘）。
                n_unparseable[col] += 1
                continue
            abs_diff = abs(cv_f - bv_f)
            abs_diffs[col].append(abs_diff)
            rel_diffs[col].append(
                abs_diff / abs(bv_f) if bv_f != 0 else (0.0 if abs_diff == 0 else float("inf"))
            )
            if _exceeds_tolerance(bv_f, cv_f, tolerance):
                n_exceed[col] += 1

        for col in text_columns:
            i = text_idx[col]
            if brow[i] != crow[i]:
                text_diff_counts[col] = text_diff_counts.get(col, 0) + 1

    if baseline_stream.dup_count:
        result["notes"].append(
            f"ベースライン実データに重複キーが{baseline_stream.dup_count}件ある"
            "（このテーブルの突合の前提であるキーの一意性が崩れている）。"
        )
    if candidate_stream.dup_count:
        result["notes"].append(
            f"候補側に重複キーが{candidate_stream.dup_count}件ある"
            f"（先頭N件: {candidate_stream.dup_keys[:5]}）。"
        )

    result["baseline_row_count"] = baseline_row_count
    result["candidate_row_count"] = candidate_row_count
    result["row_count_diff"] = candidate_row_count - baseline_row_count
    result["keys_only_in_baseline"] = {
        "count": only_in_baseline_count,
        "sample": only_in_baseline_sample,
    }
    result["keys_only_in_candidate"] = {
        "count": only_in_candidate_count,
        "sample": only_in_candidate_sample,
    }

    numeric_diffs = {}
    for col in numeric_columns:
        diffs = sorted(abs_diffs[col])
        numeric_diffs[col] = {
            "n_compared": len(diffs),
            "n_null_mismatch": n_null_mismatch[col],
            "n_unparseable": n_unparseable[col],
            "n_exceeding_tolerance": n_exceed[col],
            "max_abs_diff": max(diffs) if diffs else 0.0,
            "p50_abs_diff": _percentile(diffs, 50),
            "p95_abs_diff": _percentile(diffs, 95),
            "max_rel_diff": max(rel_diffs[col]) if rel_diffs[col] else 0.0,
        }
    result["numeric_diffs"] = numeric_diffs
    result["text_diffs"] = text_diff_counts

    matches = (
        only_in_baseline_count == 0
        and only_in_candidate_count == 0
        and baseline_stream.dup_count == 0
        and candidate_stream.dup_count == 0
        and not text_diff_counts
        and all(
            d["n_exceeding_tolerance"] == 0 and d["n_null_mismatch"] == 0 and d["n_unparseable"] == 0
            for d in numeric_diffs.values()
        )
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


def compare_all(
    baseline_json: dict, baseline_source, candidate_source, tolerance: float
) -> tuple[dict, list[str]]:
    """全テーブルを突合する。`baseline_source` が None なら縮退モード。

    戻り値は `(results, extra_tables)`。`results` はベースラインが持つ33
    テーブルについての突合結果（このゲートの合否＝終了コードを決める）。
    `extra_tables` は「候補側にはあるがベースライン（v1）には無いテーブル」
    （降順ではなく名前順）で、**ゲートの合否には含めない**——このゲートの
    合格条件は「v1 の33テーブルを再現できたか」であり、候補が余分にテーブルを
    持つこと自体は再現の失敗ではない（docs/plans/PHASE_B_RECONCILIATION.md
    §「候補側の余分なテーブル・列」参照）。ただし対象テーブルの中で列が
    過不足していれば、その**テーブル**は不一致として扱う（行比較の前提である
    「同じ形」が崩れているため）。
    """
    results: dict[str, dict] = {}
    for table, entry in sorted(baseline_json["tables"].items()):
        mode = "full" if baseline_source is not None else "reduced"
        if not candidate_source.has_table(table):
            results[table] = {
                "mode": mode,
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
        declared_column_set = set(declared_columns)
        missing_columns = [c for c in declared_columns if c not in candidate_columns]
        extra_columns = sorted(candidate_columns - declared_column_set)
        if missing_columns or extra_columns:
            notes = []
            if missing_columns:
                notes.append(f"候補側に列が無い: {missing_columns}")
            if extra_columns:
                notes.append(
                    f"候補側に余分な列がある（『同じ形』という前提が崩れている）: {extra_columns}"
                )
            results[table] = {
                "mode": mode,
                "status": "incomparable",
                "baseline_row_count": entry["row_count"],
                "candidate_row_count": candidate_source.row_count(table),
                "row_count_diff": candidate_source.row_count(table) - entry["row_count"],
                "notes": notes,
                "numeric_diffs": {},
            }
            continue

        if baseline_source is not None:
            results[table] = _compare_full(table, entry, baseline_source, candidate_source, tolerance)
        else:
            results[table] = _compare_reduced(table, entry, candidate_source)

    extra_tables = sorted(set(candidate_source.tables()) - set(baseline_json["tables"].keys()))
    return results, extra_tables


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


def render_markdown(
    results: dict[str, dict],
    mode: str,
    tolerance: float,
    stale_tables: list[str],
    extra_tables: list[str] | None = None,
) -> str:
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

    if extra_tables:
        a(
            "**候補側にしか無いテーブル**（参考情報。v1 の33テーブルには無いので"
            "このゲートの合否には含めない）: " + ", ".join(f"`{t}`" for t in extra_tables)
        )
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
                a(
                    "  | 数値列 | 比較件数 | NULL不一致 | 数値化不能 | 許容超え | "
                    "max絶対差 | p50絶対差 | p95絶対差 | max相対差 |"
                )
                a("  |---|---:|---:|---:|---:|---:|---:|---:|---:|")
                for col, d in sorted(r["numeric_diffs"].items()):
                    a(
                        f"  | `{col}` | {d['n_compared']} | {d['n_null_mismatch']} | "
                        f"{d.get('n_unparseable', 0)} | {d['n_exceeding_tolerance']} | "
                        f"{d['max_abs_diff']:.6g} | {d['p50_abs_diff']:.6g} | "
                        f"{d['p95_abs_diff']:.6g} | {d['max_rel_diff']:.6g} |"
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
    parser.add_argument(
        "--reduced",
        action="store_true",
        help="縮退モードを強制する。--baseline-data の指定や、既定の "
        f"{DEFAULT_BASELINE_DB} の自動検出より優先する。CI で明示的に軽い検証だけ"
        "したい場合や、実データが存在する環境で縮退モードの動作を確かめたい場合に使う"
        "（『たまたまファイルが無いので縮退モードになる』という暗黙の依存を避ける）。",
    )
    args = parser.parse_args()

    baseline_json_path = pathlib.Path(args.baseline_json)
    if not baseline_json_path.exists():
        sys.exit(
            f"ベースラインが無い: {baseline_json_path}\n"
            "先に `.venv/bin/python3 scripts/b01_derived_baseline.py` を実行すること。"
        )
    baseline_json = json.loads(baseline_json_path.read_text(encoding="utf-8"))

    if args.reduced:
        baseline_data_path = None
    else:
        baseline_data_path = args.baseline_data
        if baseline_data_path is None and DEFAULT_BASELINE_DB.exists():
            baseline_data_path = str(DEFAULT_BASELINE_DB)

    if baseline_data_path is None and args.tolerance > 0:
        # 縮退モードは content_hash 同士の完全一致と numeric_stats の厳密一致
        # しか見ておらず、許容誤差を適用する手段が原理的に無い（行レベルの値を
        # 持っていないため）。黙って無視するのではなく、ここで明示的に落とす
        # （レビュー指摘: `--tolerance 1e-6` を付けた CI が無警告でゼロ寛容に
        # なっていた）。#4 でハッシュ側の数値表現を正準化したので、表現差による
        # 偽の不一致はそもそも起きなくなっており、縮退モードで許容誤差を
        # 別途サポートする理由も無い。
        sys.exit(
            "縮退モード（--baseline-data 無し）では --tolerance は使えない。"
            "content_hash 同士の比較に許容誤差の概念が無く、適用したふりをしない。"
            "行レベルの許容誤差比較には --baseline-data が要る。"
        )

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

    results, extra_tables = compare_all(baseline_json, baseline_source, candidate_source, args.tolerance)

    md = render_markdown(results, mode, args.tolerance, stale_tables, extra_tables)
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
