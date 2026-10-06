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


def build_rows(crosswalk_rows, existing, get_json, limit=None):
    """`crosswalk_rows`（taxon_crosswalk.csv の行）から出力行を作る。`get_json(url, params=)` は注入する
    （テストでは偽物。本番は scripts/common.get_json）。`existing` は {taxon_id: 行}（増分用）。
    戻り値: (行のリスト, 引いた API 回数)。"""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    out, n_calls = [], 0
    for r in crosswalk_rows:
        tid = r["taxon_id"]
        if not (r.get("taxon_key") or "").strip():
            continue  # GBIF が一致を返さなかった行（NONE）は対象外
        prev = existing.get(tid)
        if prev is not None and prev["accepted_basis"] != "api_failed":
            out.append(prev)
            continue
        row = {c: "" for c in FIELDS}
        row.update(taxon_id=tid, scientific_name=r["scientific_name"], gbif_key=r["taxon_key"],
                   match_type=r["matchType"], status=r.get("status") or "", fetched_at=now)
        weak = r["matchType"] in WEAK
        if limit is not None and n_calls >= limit and (weak or r.get("status") != "ACCEPTED"):
            continue
        if weak:
            query = parse_query_name(r["scientific_name"])
            match = None
            if query["reason"] is None:
                n_calls += 1
                try:
                    match = get_json("https://api.gbif.org/v1/species/match",
                                     params={"name": r["scientific_name"], "verbose": "true"})
                except Exception:
                    match = None
            d = decide_weak_match(query, match)
            row.update(weak_resolution=d["resolution"], weak_reason=d["reason"] or "",
                       accepted_basis="n/a")
            if d["resolution"] == "adopted":
                row.update(weak_key=str(match["usageKey"]), weak_rank=match.get("rank") or "",
                           weak_status=match.get("status") or "")
                if match.get("status") not in (None, "ACCEPTED"):
                    key, name = _accepted_from(match)
                    row.update(accepted_key=key, accepted_canonical_name=name, accepted_basis="api")
                else:
                    row.update(accepted_key=str(match["usageKey"]),
                               accepted_canonical_name=match.get("canonicalName") or "", accepted_basis="self")
        elif r.get("status") == "ACCEPTED":
            row.update(accepted_key=r["taxon_key"], accepted_canonical_name="", accepted_basis="self")
        else:
            n_calls += 1
            try:
                j = get_json(f"https://api.gbif.org/v1/species/{r['taxon_key']}")
                key, _ = _accepted_from(j)
                row.update(accepted_key=key, accepted_basis="api")
                if key:
                    row["accepted_canonical_name"] = j.get("accepted") or ""
            except Exception:
                row.update(accepted_basis="api_failed")
        out.append(row)
    return out, n_calls


def main():
    from common import PROC, get_json  # requests に依存するのでここで import（判定部分のテストに要らない）
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="API を引く最大件数（スモーク用）")
    args = ap.parse_args()
    cw_path, out_path = PROC / "taxon_crosswalk.csv", PROC / "taxon_gbif_accepted.csv"
    cw = list(csv.DictReader(open(cw_path, encoding="utf-8")))
    existing = {}
    if out_path.exists():
        existing = {r["taxon_id"]: r for r in csv.DictReader(open(out_path, encoding="utf-8"))}
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
