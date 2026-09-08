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

## 宣言済み差分（`scripts/reconcile/expected_diffs.yaml`）

「v1 を再現できないが、原因が判明していて v1 側のバグだと確定しているもの」だけを、
テーブル名 -> `[{key, kind, reason, found_on, record}, ...]` の形でキー1件ずつ宣言できる
（ワイルドカード・テーブル単位の免除は書けない。ファイルの形はオーナー決定）。
既定でこのファイルを読む。`--expected-diffs <path>` で別ファイルに差し替え、
`--no-expected-diffs` で宣言を一切読まずに実行できる（「宣言なしで何が赤くなるか」を
見る用）。ファイルが無ければ「宣言0件」として動く。

宣言だからといって信用せず、以下をすべて検証する（`derive_key` が宣言キーでも
一意性を assert しているのと同じ思想）:

- 宣言のテーブル名が `derived_baseline.json` に無い → 非0で止まる。
- `key` の要素数がそのテーブルのキー列数と違う → 非0で止まる。
- `kind` が `row_only_in_candidate`/`row_only_in_baseline`/`value_diff` のどれでもない
  → 非0で止まる。
- **宣言したキーが実際には差分になっていない（腐った宣言）→ 非0で止まる。**
  これが一番重要。免除が残り続けて他の退行を隠すのを防ぐ。
- 宣言した `kind` と実際の差分の種類が食い違う → 非0で止まる。

宣言と完全に一致した差分だけを不一致から除く。除いた結果すべての差分が説明できた
テーブルは、状態表示を「一致」ではなく「宣言済み差分のみ」にする
（`STATUS_LABEL["declared_diffs_only"]`）。合否（終了コード）には数えない。
レポートに専用の節を作り、適用した宣言を1件ずつ出す。

**縮退モード（`--baseline-data` 無し・ベースライン実データ無し）では宣言を適用できない**
（行レベルの差分を見られないので「実際に差分になっているか」を検証できない）。
対象テーブル（`--tables`/既定で選ばれた範囲）に宣言が1件でもあるのに縮退モードなら、
黙って無視せず非0で止まる（`--tolerance` を縮退モードで拒否しているのと同じ考え方）。
"""
from __future__ import annotations

import argparse
import hashlib
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
DEFAULT_EXPECTED_DIFFS = ROOT / "scripts" / "reconcile" / "expected_diffs.yaml"

SAMPLE_LIMIT = 20  # レポートに出す「先頭N件の実例」


class ExpectedDiffError(Exception):
    """宣言済み差分（expected_diffs.yaml）の検証に失敗したときに投げる。

    「腐った宣言（実際には差分になっていない）」「kind の食い違い」は行レベルの
    データを見ないと判定できないため、`main()` の引数検証より後、`_compare_full`
    の中で（そのテーブルの突合結果が揃った時点で）検出する。`main()` はこれを
    捕まえてメッセージだけを出し非0で終了する（Traceback は出さない）。
    """


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
    expected_entries: Sequence[dict] = (),
) -> dict:
    """完全モードの1テーブル分の突合。

    マージ結合でベースライン行を読みながら、その場で `entry`（記録された
    指紋）に対する鮮度チェック（B-1）も行う。以前は突合の前に
    `check_baseline_freshness` が全33テーブルのベースラインをフルスキャンし、
    直後にこの関数がまた同じベースラインをキー順に読み直しており、完全モード
    実測 4m2.6s のうち93.33秒（38.5%）が鮮度チェックの二重スキャン分だった
    （レビュー指摘）。ここでベースライン行を `pop()` するたびに
    `canonical_row_bytes` を sha256 へ流し込み、ループを抜けたところで
    `entry["row_count"]`/`entry["content_hash"]` と突き合わせれば、
    別パスは要らない。候補に無いテーブル・列が過不足するテーブルの鮮度は
    `compare_all` 側の `_baseline_fingerprint_matches` が別途見る
    （そちらはマージ結合が無いのでベースライン単独の1パスのまま）。

    `expected_entries`（`expected_diffs.yaml` のこのテーブル分の宣言）を渡すと、
    宣言されたキーが実際に差分になっているかを検証したうえで、不一致から除く
    （モジュール docstring「宣言済み差分」参照）。空（既定）のときは、この
    検証のための追加のキー集合（`*_full_keys`）を一切作らない——宣言が無い
    30テーブルぶんの突合で、行数の多いテーブル（`org_norm` 等）に余計なメモリを
    使わないため。
    """
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
    baseline_hasher = hashlib.sha256()

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

    # 宣言済み差分の検証用に、キー単位の完全な集合を持つかどうか
    # （docstring 参照。宣言が無いテーブルでは一切作らない）。
    track_expected = bool(expected_entries)
    only_in_baseline_keys: set[tuple] = set() if track_expected else None
    only_in_candidate_keys: set[tuple] = set() if track_expected else None
    value_diff_keys: set[tuple] = set() if track_expected else None

    # 両ソースをキー順にマージ結合する。片側にしか無いキーは前へ進めるだけ、
    # 両側にあるキーだけ値を突き合わせる（`_KeyedStream` のドキストリング参照）。
    # ベースライン側は「候補に無いキー」「共通キー」のどちらの分岐でも
    # 必ず `pop()` されるので、候補に存在しない・候補の方が少ないテーブルでも
    # ベースラインの全行がハッシュに入る（鮮度チェックが成立する）。
    while baseline_stream.peek_key() is not None or candidate_stream.peek_key() is not None:
        bk = baseline_stream.peek_key()
        ck = candidate_stream.peek_key()
        if bk is not None and (ck is None or _key_less(bk, ck)):
            _, brow = baseline_stream.pop()
            baseline_row_count += 1
            baseline_hasher.update(common.canonical_row_bytes(brow))
            only_in_baseline_count += 1
            if len(only_in_baseline_sample) < SAMPLE_LIMIT:
                only_in_baseline_sample.append(list(bk))
            if track_expected:
                only_in_baseline_keys.add(bk)
            continue
        if ck is not None and (bk is None or _key_less(ck, bk)):
            candidate_stream.pop()
            candidate_row_count += 1
            only_in_candidate_count += 1
            if len(only_in_candidate_sample) < SAMPLE_LIMIT:
                only_in_candidate_sample.append(list(ck))
            if track_expected:
                only_in_candidate_keys.add(ck)
            continue

        # bk == ck（両側に存在する共通キー）。
        _, brow = baseline_stream.pop()
        _, crow = candidate_stream.pop()
        baseline_row_count += 1
        candidate_row_count += 1
        baseline_hasher.update(common.canonical_row_bytes(brow))
        row_differs = False

        for col in numeric_columns:
            i = numeric_idx[col]
            bv, cv = brow[i], crow[i]
            if bv is None or cv is None:
                if bv is not cv:
                    n_null_mismatch[col] += 1
                    row_differs = True
                continue
            try:
                bv_f = float(bv)
                cv_f = float(cv)
            except (TypeError, ValueError):
                # 候補が数値列のはずの場所に "N/A" 等の非数値を書いてきた場合。
                # 落ちずに差として数える（レビュー指摘）。
                n_unparseable[col] += 1
                row_differs = True
                continue
            abs_diff = abs(cv_f - bv_f)
            abs_diffs[col].append(abs_diff)
            rel_diffs[col].append(
                abs_diff / abs(bv_f) if bv_f != 0 else (0.0 if abs_diff == 0 else float("inf"))
            )
            if _exceeds_tolerance(bv_f, cv_f, tolerance):
                n_exceed[col] += 1
                row_differs = True

        for col in text_columns:
            i = text_idx[col]
            if brow[i] != crow[i]:
                text_diff_counts[col] = text_diff_counts.get(col, 0) + 1
                row_differs = True

        if track_expected and row_differs:
            value_diff_keys.add(bk)

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

    baseline_content_hash = "sha256:" + baseline_hasher.hexdigest()
    result["baseline_stale"] = (
        baseline_row_count != entry["row_count"] or baseline_content_hash != entry["content_hash"]
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
    status = "match" if matches else "mismatch"

    if track_expected:
        # `expected_entries` の構造（テーブル名の実在・key の長さ・kind の語彙）は
        # 呼び出し側（`main()`）が事前に検証済みであることが前提（`compare_all` の
        # `selected_tables` と同じ考え方——ここでは黙って信用して使うだけ）。
        # ここで検証するのは、行レベルのデータを見ないと判定できない1点だけ:
        # 「宣言したキーが、宣言した kind の実際の差分として本当に存在するか」。
        kind_to_set = {
            "row_only_in_candidate": only_in_candidate_keys,
            "row_only_in_baseline": only_in_baseline_keys,
            "value_diff": value_diff_keys,
        }
        # 不正な宣言は見つけたその場で raise せず、このテーブルの宣言を全部
        # 走査してから1回でまとめて投げる（レビュー指摘: 上流のバグを1つ直すと
        # 同じテーブルの宣言がまとめて腐るのが普通（atsugi の宣言がその例）なので、
        # 1件ずつ投げると完全モードで4分かけて1件ずつ知らされることになる）。
        applied: list[dict] = []
        bad_entries: list[str] = []
        for d in expected_entries:
            key_tuple = tuple(d["key"])
            kind = d["kind"]
            target_set = kind_to_set[kind]
            if key_tuple in target_set:
                target_set.discard(key_tuple)
                applied.append({**d, "table": table})
                continue
            actual_kind = next((k for k, s in kind_to_set.items() if key_tuple in s), None)
            if actual_kind is not None:
                bad_entries.append(
                    f"key={list(d['key'])} の kind が実際の差分と食い違う"
                    f"（宣言: {kind!r}、実際: {actual_kind!r}）"
                )
            else:
                bad_entries.append(
                    f"key={list(d['key'])}（kind={kind!r}）は実際には差分になっていない（腐った宣言）"
                )
        if bad_entries:
            raise ExpectedDiffError(
                f"{table}: expected_diffs.yaml の宣言に不正なものが{len(bad_entries)}件ある"
                "（これは他の退行を隠さないための検証であり、無効化できない。kind の食い違いは "
                "expected_diffs.yaml の kind を直し、腐った宣言（既に再現できている）はそこから"
                "削除すること）:\n- " + "\n- ".join(bad_entries)
            )
        result["declared_diffs_applied"] = applied

        # 宣言で説明しきれた（＝残りが0件になった）ときだけ「宣言済み差分のみ」にする。
        # 重複キー（dup_count）は宣言の対象外なので、それが残っていれば常に mismatch のまま。
        remaining = len(only_in_baseline_keys) + len(only_in_candidate_keys) + len(value_diff_keys)
        dup_ok = baseline_stream.dup_count == 0 and candidate_stream.dup_count == 0
        if remaining == 0 and dup_ok:
            status = "declared_diffs_only"

    result["status"] = status
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


def _baseline_fingerprint_matches(baseline_source, table: str, entry: dict) -> bool:
    """`baseline_source`（実データ）を読み直した指紋が `entry`（`derived_baseline.json`
    の記録）と一致するか。候補にこのテーブルが無い・列が過不足するために
    `_compare_full` の（鮮度チェックも兼ねる）マージ結合に乗せられない
    テーブルの鮮度だけを、ここで別途1パス読んで確認する
    （B-1: `_compare_full` に乗る大多数のテーブルは、そちらが自前で
    鮮度チェックまで済ませるので、ここは通らない）。

    `numeric_columns=[]` を渡して集計（min/max/合計）の計算を省く
    （鮮度判定は `row_count`/`content_hash` だけを見るので不要。
    `content_hash` は全列を読んで計算するので、これを渡しても変わらない）。
    """
    if not baseline_source.has_table(table):
        return False
    columns = [c["name"] for c in entry["columns"]]
    key = entry["key"]
    fp = common.compute_fingerprint(baseline_source, table, columns, key, numeric_columns=[])
    return fp["row_count"] == entry["row_count"] and fp["content_hash"] == entry["content_hash"]


def _unresolved_result(
    mode: str,
    status: str,
    baseline_row_count: int,
    candidate_row_count: int,
    notes: list[str],
    baseline_source,
    table: str,
    entry: dict,
) -> dict:
    """`missing_in_candidate` / `incomparable`（候補と行レベルで突き合わせられない
    テーブル）の結果 dict を組み立てる共通ビルダー（レビュー指摘 A-7:
    以前はこの2つがほぼ同じ形の dict をそれぞれ手で組み立てていた）。
    """
    result = {
        "mode": mode,
        "status": status,
        "baseline_row_count": baseline_row_count,
        "candidate_row_count": candidate_row_count,
        "row_count_diff": candidate_row_count - baseline_row_count,
        "notes": notes,
        "numeric_diffs": {},
    }
    if baseline_source is not None:
        result["baseline_stale"] = not _baseline_fingerprint_matches(baseline_source, table, entry)
    return result


def compare_all(
    baseline_json: dict,
    baseline_source,
    candidate_source,
    tolerance: float,
    selected_tables: set[str] | None = None,
    expected_diffs_by_table: dict[str, list[dict]] | None = None,
) -> tuple[dict, list[str]]:
    """全テーブルを突合する。`baseline_source` が None なら縮退モード。

    戻り値は `(results, extra_tables)`。`results` はベースラインが持つ33
    テーブルについての突合結果（このゲートの合否＝終了コードを決める）。
    完全モードでは各エントリに `baseline_stale`（`derived_baseline.json` の
    記録が実データと食い違うか）も入る——呼び出し側（`main()`）はこれを
    集めて「b01 を再実行してコミットし忘れている」を報告する。
    `extra_tables` は「候補側にはあるがベースライン（v1）には無いテーブル」
    （降順ではなく名前順）で、**ゲートの合否には含めない**——このゲートの
    合格条件は「v1 の33テーブルを再現できたか」であり、候補が余分にテーブルを
    持つこと自体は再現の失敗ではない（docs/plans/PHASE_B_RECONCILIATION.md
    §「候補側の余分なテーブル・列」参照）。ただし対象テーブルの中で列が
    過不足していれば、その**テーブル**は不一致として扱う（行比較の前提である
    「同じ形」が崩れているため）。

    `selected_tables` を渡すと、ベースラインが持つテーブルのうちその集合に含まれるものだけを
    突合する（`--tables` 用。呼び出し前に検証済みであること――未知の名前が混じっていないこと――が
    前提で、ここでは黙ってフィルタするだけであり、タイポの検出はしない。検証は `main()` 側の責務）。
    `extra_tables` は `selected_tables` の影響を受けない。ベースラインの全体集合を使って判定する
    ――「`--tables` で選ばなかっただけの、v1に実在するテーブル」を「候補側の余分」に混ぜないため。

    `expected_diffs_by_table`（`expected_diffs.yaml` を読んだもの）を渡すと、テーブルごとに
    該当する宣言のリストを `_compare_full` に渡す（縮退モードでは使わない——渡されても
    無視する。`--reduced`/実データ無しでの整合性検証は `main()` の責務）。この関数自身も
    含め、宣言の構造（テーブル名の実在・key の長さ・kind の語彙）を検証**しない**——
    `selected_tables` と同じ理由で、検証は呼び出し前（`main()`）に済んでいる前提。
    """
    results: dict[str, dict] = {}
    target_items = [
        (table, entry)
        for table, entry in baseline_json["tables"].items()
        if selected_tables is None or table in selected_tables
    ]
    for table, entry in sorted(target_items):
        mode = "full" if baseline_source is not None else "reduced"
        if not candidate_source.has_table(table):
            results[table] = _unresolved_result(
                mode,
                "missing_in_candidate",
                entry["row_count"],
                0,
                ["候補側にこのテーブルが無い。"],
                baseline_source,
                table,
                entry,
            )
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
            candidate_row_count = candidate_source.row_count(table)  # 1回だけ呼ぶ
            results[table] = _unresolved_result(
                mode, "incomparable", entry["row_count"], candidate_row_count, notes,
                baseline_source, table, entry,
            )
            continue

        if baseline_source is not None:
            expected_entries = (expected_diffs_by_table or {}).get(table, [])
            results[table] = _compare_full(
                table, entry, baseline_source, candidate_source, tolerance, expected_entries
            )
        else:
            results[table] = _compare_reduced(table, entry, candidate_source)

    extra_tables = sorted(set(candidate_source.tables()) - set(baseline_json["tables"].keys()))
    return results, extra_tables


# ---------------------------------------------------------------------------
# レポート
# ---------------------------------------------------------------------------

STATUS_LABEL = {
    "match": "一致",
    "declared_diffs_only": "宣言済み差分のみ",
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
    partial_tables: list[str] | None = None,
    total_baseline_tables: int | None = None,
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
    if partial_tables is not None:
        excluded_count = (total_baseline_tables or 0) - len(partial_tables)
        a(
            f"**部分ゲート**: ベースライン{total_baseline_tables}テーブル中"
            f"{len(partial_tables)}テーブルだけを対象にした"
            "（対象: " + ", ".join(f"`{t}`" for t in partial_tables) + "）。"
            "全体の合格ではない。"
        )
        a(f"（対象外にしたテーブル: {excluded_count}件）")
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
    declared_only = sorted(t for t, r in results.items() if r["status"] == "declared_diffs_only")
    mismatched = sorted(t for t, r in results.items() if r["status"] not in ("match", "declared_diffs_only"))

    a("## サマリ（先に見る場所）")
    a("")
    a(f"- 一致: {len(matched)}テーブル")
    a(f"- 宣言済み差分のみ: {len(declared_only)}テーブル（合否には数えない）")
    a(f"- 不一致: {len(mismatched)}テーブル")
    a("")
    if matched:
        a("**一致したテーブル**: " + ", ".join(f"`{t}`" for t in matched))
        a("")
    if declared_only:
        a(
            "**宣言済み差分のみのテーブル**（`expected_diffs.yaml` の宣言で全差分が説明できている。"
            "詳細は下の「宣言済み差分」節）: " + ", ".join(f"`{t}`" for t in declared_only)
        )
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

    applied_all = [
        {**d, "table": table}
        for table in sorted(results)
        for d in results[table].get("declared_diffs_applied", [])
    ]
    if applied_all:
        applied_all.sort(key=lambda d: (d["table"], [str(x) for x in d["key"]]))
        a("## 宣言済み差分（expected_diffs.yaml で適用したもの）")
        a("")
        a(
            "「v1 を再現できないが、原因が判明していて v1 側のバグだと確定しているもの」として"
            "`scripts/reconcile/expected_diffs.yaml` に宣言され、実際にその通りの差分として"
            "検証できたため、不一致から除いたもの。"
        )
        a("")
        a("| テーブル | キー | kind | reason | found_on | record |")
        a("|---|---|---|---|---|---|")
        for d in applied_all:
            # YAML の `>`（折り畳みブロックスカラー）で書いた reason は、改行が
            # スペースに変わっても末尾の改行（chomping）は残る。Markdown の表は
            # 1行に収まっていないと崩れるので、ここで空白に正規化する。
            reason = " ".join(str(d.get("reason", "")).split())
            record = " ".join(str(d.get("record", "")).split())
            a(
                f"| `{d['table']}` | {d['key']} | `{d['kind']}` | {reason} | "
                f"{d.get('found_on', '')} | {record} |"
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
    parser.add_argument(
        "--tables",
        default=None,
        help="カンマ区切りでテーブル名を絞り込む（例: meas_daily,meas_month,meas_year）。"
        "省略時はベースラインの全テーブルが対象（従来通り）。指定した名前が"
        "derived_baseline.json に無ければ、その名前を挙げて即座に終了する"
        "（黙って無視しない。タイポで『0件を突合して緑』になるのが最悪の失敗のため）。",
    )
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    parser.add_argument(
        "--reduced",
        action="store_true",
        help="縮退モードを強制する。--baseline-data の指定や、既定の "
        f"{DEFAULT_BASELINE_DB} の自動検出より優先する。CI で明示的に軽い検証だけ"
        "したい場合や、実データが存在する環境で縮退モードの動作を確かめたい場合に使う"
        "（『たまたまファイルが無いので縮退モードになる』という暗黙の依存を避ける）。",
    )
    parser.add_argument(
        "--expected-diffs",
        default=str(DEFAULT_EXPECTED_DIFFS),
        help="宣言済み差分（v1を再現できないが原因が判明しているキー）の YAML。既定は "
        f"{DEFAULT_EXPECTED_DIFFS}。ファイルが無ければ『宣言0件』として動く。",
    )
    parser.add_argument(
        "--no-expected-diffs",
        action="store_true",
        help="宣言済み差分を一切読まずに実行する（--expected-diffs の値も無視する）。"
        "『宣言なしで何が赤くなるか』を見たいときに使う。",
    )
    args = parser.parse_args()

    baseline_json_path = pathlib.Path(args.baseline_json)
    if not baseline_json_path.exists():
        sys.exit(
            f"ベースラインが無い: {baseline_json_path}\n"
            "先に `.venv/bin/python3 scripts/b01_derived_baseline.py` を実行すること。"
        )
    baseline_json = json.loads(baseline_json_path.read_text(encoding="utf-8"))
    if baseline_json.get("schema_version") != common.SCHEMA_VERSION:
        sys.exit(
            f"{baseline_json_path} の schema_version が想定と異なる"
            f"（期待 {common.SCHEMA_VERSION}、実際 {baseline_json.get('schema_version')!r}）。"
            "scripts/b01_derived_baseline.py を実行して作り直すこと。"
        )

    selected_tables: set[str] | None = None
    if args.tables is not None:
        # 空文字・空白だけのトークンは「カンマの打ち間違いで意図せず0件/欠けた対象になる」
        # 事故に繋がるので許容しない(黙って無視すると『0件を突合して緑』の亜種になる)。
        # 重複は実害が無い(同じテーブルを2回選んでも結果は変わらない。タイポの検出とは
        # 性質が違う)ので、順序を保って重複除去するだけにする。
        raw_names = [name.strip() for name in args.tables.split(",")]
        if any(name == "" for name in raw_names):
            sys.exit(
                f"--tables に空のテーブル名が含まれている（カンマの打ち間違いの可能性）: {args.tables!r}"
            )
        seen: set[str] = set()
        requested: list[str] = []
        for name in raw_names:
            if name not in seen:
                seen.add(name)
                requested.append(name)
        unknown = [name for name in requested if name not in baseline_json["tables"]]
        if unknown:
            sys.exit(
                f"--tables に指定した名前がベースラインに無い: {unknown}\n"
                f"ベースラインが持つテーブル（{len(baseline_json['tables'])}件）: "
                f"{sorted(baseline_json['tables'].keys())}"
            )
        selected_tables = set(requested)

    # 宣言済み差分（expected_diffs.yaml）の読み込みと構造の検証。
    # ここでの検証は「行レベルのデータを見なくても分かること」だけ
    # （宣言の形（マッピングのリスト）・テーブル名の実在・key の要素数・kind の語彙）。
    # 前半（形）は `load_expected_diffs` 自身が検証し、後半3点は `derived_baseline.json`
    # と突き合わせないと判定できないので `common.validate_expected_diffs` に任せる
    # （CI の宣言ファイル構造検証ステップと同じ関数を呼び、検証ロジックを2箇所に
    # 書かない）。「宣言したキーが実際に差分になっているか」は行レベルの突合を
    # しないと判定できないので、`_compare_full` 側（`ExpectedDiffError`）で検証する。
    if args.no_expected_diffs:
        expected_diffs_by_table: dict[str, list[dict]] = {}
    else:
        expected_diffs_by_table = common.load_expected_diffs(args.expected_diffs)
        common.validate_expected_diffs(
            expected_diffs_by_table, baseline_json["tables"], str(args.expected_diffs)
        )

    if args.reduced:
        baseline_data_path = None
    else:
        baseline_data_path = args.baseline_data
        if baseline_data_path is None and DEFAULT_BASELINE_DB.exists():
            baseline_data_path = str(DEFAULT_BASELINE_DB)

    # 縮退モード（ベースライン実データ無し）では、宣言が実際に差分になっているかを
    # 行レベルで検証できない。--tolerance を縮退モードで拒否しているのと同じ考え方で、
    # 黙って無視せず明示的に落とす（対象＝今回突合する範囲に宣言があるときだけ）。
    target_tables = selected_tables if selected_tables is not None else set(baseline_json["tables"].keys())
    tables_with_declared_diffs_in_scope = sorted(
        t for t, diffs in expected_diffs_by_table.items() if diffs and t in target_tables
    )
    if baseline_data_path is None and tables_with_declared_diffs_in_scope:
        sys.exit(
            "縮退モード（--baseline-data 無し・ベースライン実データ無し）では宣言済み差分"
            "（expected_diffs.yaml）を適用できない（行レベルの差分を見られないので、宣言が"
            f"実際に差分になっているか検証できない）。対象テーブルに宣言がある: "
            f"{tables_with_declared_diffs_in_scope}\n"
            "縮退モードで動かしたいなら --no-expected-diffs を付けること。"
        )

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

    if baseline_data_path is not None:
        baseline_source = datasource.open_source(baseline_data_path)
        mode = "full"
    else:
        baseline_source = None
        mode = "reduced"
        print(
            "▶ ベースラインの実データが無いので縮退モードで実行する"
            "（行レベルの内訳は出せない。docs/plans/PHASE_B_RECONCILIATION.md 参照）"
        )

    try:
        results, extra_tables = compare_all(
            baseline_json,
            baseline_source,
            candidate_source,
            args.tolerance,
            selected_tables,
            expected_diffs_by_table,
        )
    except ExpectedDiffError as e:
        sys.exit(str(e))
    # 鮮度チェックは `compare_all` が各テーブルの結果に畳み込んでいる
    # （`_compare_full` のマージ結合中、または `_unresolved_result` 経由。B-1）。
    stale_tables = sorted(t for t, r in results.items() if r.get("baseline_stale"))

    # 「部分ゲート」とみなすのは、選んだテーブル数がベースライン全体より少ない場合だけ。
    # --tables に全テーブル名を明示的に列挙しても実質フルゲートなので区別しない
    # （フラグの有無ではなく選択結果で判定する方が『たまたま全部列挙した』場合に
    # 誤って部分ゲート表示になる/ならないの揺れが無い）。
    is_partial = selected_tables is not None and len(selected_tables) < len(baseline_json["tables"])

    md = render_markdown(
        results,
        mode,
        args.tolerance,
        stale_tables,
        extra_tables,
        partial_tables=sorted(selected_tables) if is_partial else None,
        total_baseline_tables=len(baseline_json["tables"]) if is_partial else None,
    )
    out_md = pathlib.Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md, encoding="utf-8")
    print(f"→ {out_md}")

    n_mismatch = sum(1 for r in results.values() if r["status"] not in ("match", "declared_diffs_only"))
    n_declared_only = sum(1 for r in results.values() if r["status"] == "declared_diffs_only")
    n_match = len(results) - n_mismatch - n_declared_only
    print(f"一致: {n_match} / 宣言済み差分のみ: {n_declared_only} / 不一致: {n_mismatch}")
    n_applied = sum(len(r.get("declared_diffs_applied", [])) for r in results.values())
    if n_applied:
        print(f"適用した宣言済み差分: {n_applied}件")

    if is_partial:
        excluded_count = len(baseline_json["tables"]) - len(selected_tables)
        print(
            f"部分ゲート: ベースライン{len(baseline_json['tables'])}テーブル中"
            f"{len(selected_tables)}テーブルだけが対象（--tables指定）。"
            f"全体の合格ではない（対象外: {excluded_count}テーブル）。"
        )

    if stale_tables:
        print(f"ベースラインが実データと食い違うテーブル: {stale_tables}", file=sys.stderr)
        return 1
    return 1 if n_mismatch > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
