"""GBIF の受理名（acceptedKey）と弱い一致の再照合（Issue #34 D2・D3）

入力: data/processed/taxon_crosswalk.csv（c24 の成果物。読むだけで書き換えない）
出力: data/processed/taxon_gbif_accepted.csv（新規）

- ACCEPTED の行: 受理名は自分自身（accepted_basis='self'。API を引かない）。
- SYNONYM/DOUBTFUL 等の行: GET /v1/species/{key} の acceptedKey・受理名を取る（accepted_basis='api'）。
  acceptedKey が無ければ accepted_key は空のまま（推測で埋めない）。
- 弱い一致（matchType が HIGHERRANK/FUZZY）の行: species/match?verbose=true を引き直し、
  scripts/taxon_gbif_adopt.py の3条件（正規形が完全一致・種以下・候補1つ）をすべて満たすものだけ
  weak_resolution='adopted'（weak_key に採用した GBIF key）。それ以外は 'unresolved' と weak_reason。
- 増分: 既存の出力にある行（accepted_basis='api_failed' を除く）は引き直さない。
- User-Agent は scripts/common.py の UA（組織の連絡先。個人名を入れない）。

実行: python3 scripts/c26_taxon_gbif_accepted.py [--limit N]（N 件だけ API を引く。スモーク用）
"""
import argparse
import csv
import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from taxon_gbif_adopt import decide_weak_match, parse_query_name  # noqa: E402

FIELDS = ["taxon_id", "scientific_name", "gbif_key", "match_type", "status",
          "accepted_key", "accepted_canonical_name", "accepted_basis",
          "weak_resolution", "weak_reason", "weak_key", "weak_rank", "weak_status",
          "fetched_at"]
WEAK = {"HIGHERRANK", "FUZZY"}


def _accepted_from(j: dict) -> tuple[str, str]:
    """species/{key} または species/match の応答から (acceptedKey, 受理名の canonicalName)。"""
    key = j.get("acceptedKey") or j.get("acceptedUsageKey") or ""
    return str(key), (j.get("accepted") or "") if key else ""


def _reusable(prev, r) -> bool:
    """既存の出力行 `prev` を引き直さず再利用してよいか。API 失敗（`accepted_basis='api_failed'`・
    弱い一致の `weak_reason='api_failed'`）は再取得する。入力の crosswalk が変わった
    （gbif_key・学名が違う）行も再取得する（taxon_id だけで再利用すると古い結果が残る）。"""
    return (
        prev is not None
        and prev["accepted_basis"] != "api_failed"
        and prev["weak_reason"] != "api_failed"
        and prev["gbif_key"] == r["taxon_key"]
        and prev["scientific_name"] == r["scientific_name"]
    )


def _resolve_weak(row, name, get_json) -> int:
    """弱い一致の行 `row` を再照合して書き込む。戻り値: 引いた API 回数。"""
    query = parse_query_name(name)
    match, n_calls = None, 0
    if query["reason"] is None:
        n_calls = 1
        try:
            match = get_json("https://api.gbif.org/v1/species/match", params={"name": name, "verbose": "true"})
        except Exception:
            match = None
    d = decide_weak_match(query, match)
    row.update(weak_resolution=d["resolution"], weak_reason=d["reason"] or "", accepted_basis="n/a")
    if d["resolution"] == "adopted":
        row.update(weak_key=str(match["usageKey"]), weak_rank=match.get("rank") or "",
                   weak_status=match.get("status") or "")
        if match.get("status") not in (None, "ACCEPTED"):
            key, accepted_name = _accepted_from(match)
            row.update(accepted_key=key, accepted_canonical_name=accepted_name, accepted_basis="api")
        else:
            row.update(accepted_key=str(match["usageKey"]),
                       accepted_canonical_name=match.get("canonicalName") or "", accepted_basis="self")
    return n_calls


def _resolve_accepted(row, taxon_key, get_json) -> None:
    """ACCEPTED 以外の行の受理名を `species/{key}` から取る（失敗は 'api_failed'。次回再取得される）。"""
    try:
        j = get_json(f"https://api.gbif.org/v1/species/{taxon_key}")
        key, _ = _accepted_from(j)
        row.update(accepted_key=key, accepted_basis="api",
                   accepted_canonical_name=(j.get("accepted") or "") if key else "")
    except Exception:
        row.update(accepted_basis="api_failed")


def build_rows(crosswalk_rows, existing, get_json, limit=None):
    """`crosswalk_rows`（taxon_crosswalk.csv の行）から出力行を作る。`get_json(url, params=)` は注入する
    （テストでは偽物。本番は scripts/common.get_json）。`existing` は {taxon_id: 行}（増分用）。
    戻り値: (行のリスト, 引いた API 回数)。"""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    out, n_calls = [], 0
    for r in crosswalk_rows:
        if not (r.get("taxon_key") or "").strip():
            continue  # GBIF が一致を返さなかった行（NONE）は対象外
        prev = existing.get(r["taxon_id"])
        if _reusable(prev, r):
            out.append(prev)
            continue
        weak = r["matchType"] in WEAK
        needs_api = weak or r.get("status") != "ACCEPTED"
        if limit is not None and n_calls >= limit and needs_api:
            continue
        row = {c: "" for c in FIELDS}
        row.update(taxon_id=r["taxon_id"], scientific_name=r["scientific_name"], gbif_key=r["taxon_key"],
                   match_type=r["matchType"], status=r.get("status") or "", fetched_at=now)
        if weak:
            n_calls += _resolve_weak(row, r["scientific_name"], get_json)
        elif not needs_api:
            row.update(accepted_key=r["taxon_key"], accepted_canonical_name="", accepted_basis="self")
        else:
            n_calls += 1
            _resolve_accepted(row, r["taxon_key"], get_json)
        out.append(row)
    return out, n_calls


def main():
    from common import PROC, get_json  # requests に依存するのでここで import（判定部分のテストに要らない）
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="API を引く最大件数（スモーク用）")
    args = ap.parse_args()
    cw_path, out_path = PROC / "taxon_crosswalk.csv", PROC / "taxon_gbif_accepted.csv"
    with open(cw_path, encoding="utf-8") as f:
        cw = list(csv.DictReader(f))
    existing = {}
    if out_path.exists():
        with open(out_path, encoding="utf-8") as f:
            existing = {r["taxon_id"]: r for r in csv.DictReader(f)}
    rows, n_calls = build_rows(cw, existing, get_json, limit=args.limit)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    import collections
    print(f"  [write] {out_path}  {len(rows)} rows（API {n_calls} 回）")
    print("  [accepted_basis]", dict(collections.Counter(r["accepted_basis"] for r in rows)))
    print("  [weak_resolution]", dict(collections.Counter(r["weak_resolution"] for r in rows if r["weak_resolution"])))
    print("  [weak_reason]", dict(collections.Counter(r["weak_reason"] for r in rows if r["weak_reason"])))


if __name__ == "__main__":
    main()
