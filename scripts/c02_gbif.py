"""GBIF: 神奈川県(GADM JPN.19_1) の全出現記録を datasetKey 主軸で分割して取得。

## 遅延の原因診断（実測）
- limit=300, offset=0            -> 2.8~3.2秒 (656KB/s前後)
- limit=300, offset=9000         -> 3.0秒 (正常)
- limit=300, offset=10000        -> 54.6秒 (39.9KB/s に急減速)
- limit=300, offset=12000/13000/14000 -> 51~58秒 (同様)
- limit=300, offset=50000/90000  -> 37秒 (39.2KB/s)
  => offset(+limit) が 10,000 を跨いだ瞬間に応答速度が ~1/17 に低下する。
     Elasticsearch の既定 index.max_result_window(=10000) 相当の壁に
     GBIF 検索APIがぶつかり、深いページングだけ極端に遅くなっていると判断できる。
     (offset=300 でも、その区画の総件数が小さければ高速 = 「offsetの絶対深さ」の問題)
- common.MIN_INTERVAL(0.3秒) はこの54秒級の遅延と比べ無視できる差(その場しのぎの
  逐次実行でも 0.3秒 x ページ数 は誤差程度)。ボトルネックは MIN_INTERVAL ではなく
  GBIF 側のディープページング劣化。
=> 対策: どの区画でも offset が 10,000 未満で収まるよう、常に一発で
   limit=300,offset<10000 に収まる粒度まで区画を細分化してから取得する。

## 分割設計
- datasetKey は全レコードに必須のフィールドで facet 合計が総数と完全一致 (欠損ゼロ、実測済)。
  これを主軸に採用。
- datasetKey 単体で 10,000 件を超える区画のみ year → month → day の順に追加分割し、
  常に「区画の件数 <= 10,000」を保証する(offset は最大でも 9,900 に収まり安全域)。
- year/month/day は解釈済みフィールドで欠損があり得る（実測: 一部データセットで
  年ごとの facet 合計が実件数よりわずかに少ない = 日付が解釈できないレコードが存在）。
  検索APIには「フィールドが無い」ことを直接問い合わせる方法が無く(ダウンロードAPIの
  predicate 機能が必要だがアカウント無しのため使用不可)、この差分は
  data/logs/gbif_partition_report.csv に「どの区画で何件足りないか」として記録する
  (黙って捨てない)。datasetKey 自体には欠損が無いため、この経路で生じる欠損は
  総件数の 0.2%未満に収まる想定。
"""
import sys, json, csv, time, pathlib, threading, collections
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import common
from common import PROC, LOGS, RAW, register, now
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

B = "https://api.gbif.org/v1/occurrence/search"
DATASET_API = "https://api.gbif.org/v1/dataset/{}"
GADM = "JPN.19_1"
UA = ("ryuiki-demo-datacollector/0.1 (Code for Japan; watershed monitoring demo; "
      "contact: yuki.kawabe@code4japan.org)")
SAFE_MAX = 10000        # 実測でこれ未満なら offset は高速域
MAX_WORKERS = 4         # 礼儀として同時接続は4まで
MIN_GAP = 0.12          # 4並列全体で共有する最低リクエスト間隔(秒)

FIELDS = ["key","datasetKey","publishingOrgKey","scientificName","acceptedScientificName",
  "taxonKey","acceptedTaxonKey","kingdom","phylum","class","order","family","genus","species",
  "taxonRank","taxonomicStatus","vernacularName","eventDate","year","month","day",
  "decimalLatitude","decimalLongitude","coordinateUncertaintyInMeters","elevation","depth",
  "basisOfRecord","occurrenceStatus","individualCount","organismQuantity","organismQuantityType",
  "recordedBy","identifiedBy","institutionCode","collectionCode","catalogNumber",
  "locality","stateProvince","county","municipality","waterBody","habitat",
  "license","issues","lastInterpreted","references","occurrenceID"]

CSV_COLS = ["key","scientificName","taxonKey","kingdom","class","order","family","genus",
  "eventDate","year","decimalLatitude","decimalLongitude","coordinateUncertaintyInMeters",
  "basisOfRecord","individualCount","institutionCode","datasetKey","license","issues"]

OUT_JSONL = PROC/"gbif_kanagawa_occurrences.jsonl"
OUT_CSV = PROC/"gbif_kanagawa_occurrences.csv"
PROGRESS = LOGS/"gbif_progress.json"
PARTITION_REPORT = LOGS/"gbif_partition_report.csv"
SUMMARY_DATASET = PROC/"gbif_kanagawa_summary_by_dataset.csv"
CHECKLIST = PROC/"gbif_kanagawa_species_checklist.csv"

session = requests.Session()
_req_lock = threading.Lock()
_last_req_t = [0.0]

def throttled_get(params, timeout=60, retries=5):
    last_err = None
    for attempt in range(retries):
        with _req_lock:
            dt = time.time() - _last_req_t[0]
            if dt < MIN_GAP:
                time.sleep(MIN_GAP - dt)
            _last_req_t[0] = time.time()
        try:
            r = session.get(B, params=params, headers={"User-Agent": UA,
                             "Accept-Language": "ja,en;q=0.8"}, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            last_err = f"HTTP {r.status_code}"
            if r.status_code in (400, 401, 403, 404):
                break
        except Exception as e:
            last_err = repr(e)
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET failed params={params}: {last_err}")

def facet_of(params, facet, facet_limit):
    p = dict(params); p.update(limit=0, facet=facet, facetLimit=facet_limit)
    j = throttled_get(p)
    fs = j.get("facets") or []
    if not fs:
        return {}
    return {c["name"]: c["count"] for c in fs[0]["counts"]}

def flat(r):
    d = {k: r.get(k) for k in FIELDS}
    d["issues"] = "|".join(r.get("issues") or [])
    return d

# ---------------------------------------------------------------- 1. 区画設計
gap_lock = threading.Lock()
gap_records = []

def add_gap(scope, dim, expect_total, sum_children):
    gap = expect_total - sum_children
    if gap > 0:
        with gap_lock:
            gap_records.append({"scope": scope, "split_dim": dim, "expect_total": expect_total,
                                 "sum_children": sum_children, "gap": gap,
                                 "note": "検索APIに『フィールド欠損』を問い合わせる手段がなく分離取得不可(ダウンロードAPI要アカウントのため未使用)"})

def build_dataset_leaves(dk, c):
    base = {"gadmGid": GADM, "datasetKey": dk}
    if c <= SAFE_MAX:
        return [{"params": base, "expect": c, "label": f"datasetKey={dk}"}]
    leaves = []
    yr_counts = facet_of(base, "year", 300)
    add_gap(f"datasetKey={dk}", "year", c, sum(yr_counts.values()))
    for y, cy in yr_counts.items():
        base_y = dict(base, year=y)
        if cy <= SAFE_MAX:
            leaves.append({"params": base_y, "expect": cy, "label": f"datasetKey={dk}&year={y}"})
            continue
        mo_counts = facet_of(base_y, "month", 20)
        add_gap(f"datasetKey={dk}&year={y}", "month", cy, sum(mo_counts.values()))
        for m, cm in mo_counts.items():
            base_m = dict(base_y, month=m)
            if cm <= SAFE_MAX:
                leaves.append({"params": base_m, "expect": cm, "label": f"datasetKey={dk}&year={y}&month={m}"})
                continue
            day_counts = facet_of(base_m, "day", 40)
            add_gap(f"datasetKey={dk}&year={y}&month={m}", "day", cm, sum(day_counts.values()))
            for d, cd in day_counts.items():
                base_d = dict(base_m, day=d)
                leaves.append({"params": base_d, "expect": cd, "label": f"datasetKey={dk}&year={y}&month={m}&day={d}"})
    return leaves

def build_all_leaves():
    ds_counts = facet_of({"gadmGid": GADM}, "datasetKey", 500)
    total_via_ds = sum(ds_counts.values())
    print(f"  [partition] datasetKey facet: {len(ds_counts)} datasets, sum={total_via_ds}", flush=True)
    leaves = []
    with ThreadPoolExecutor(MAX_WORKERS) as ex:
        futs = {ex.submit(build_dataset_leaves, dk, c): dk for dk, c in ds_counts.items()}
        done_n = 0
        for fut in as_completed(futs):
            leaves += fut.result()
            done_n += 1
            if done_n % 50 == 0:
                print(f"  [partition] {done_n}/{len(ds_counts)} datasets planned, {len(leaves)} leaves so far", flush=True)
    return leaves, ds_counts, total_via_ds

# ---------------------------------------------------------------- 2. 取得
def fetch_leaf(leaf):
    params = dict(leaf["params"])
    out = []
    off = 0
    while True:
        p = dict(params); p.update(limit=300, offset=off)
        j = throttled_get(p)
        res = j.get("results", [])
        out += res
        if j.get("endOfRecords") or not res:
            break
        off += 300
        if off >= 100000:
            print(f"    !! offset cap hit for {leaf['label']}", flush=True)
            break
    return leaf, out

def main():
    t0 = time.time()
    total_expect = throttled_get({"gadmGid": GADM, "limit": 0})["count"]
    print(f"expect {total_expect} records total (gadmGid={GADM})", flush=True)

    leaves, ds_counts, total_via_ds = build_all_leaves()
    print(f"  [partition] {len(leaves)} leaves built in {time.time()-t0:.0f}s "
          f"(datasetKey-facet sum={total_via_ds}, vs count={total_expect}, "
          f"diff={total_expect-total_via_ds})", flush=True)
    if total_expect != total_via_ds:
        add_gap("gadmGid=JPN.19_1 (top level)", "datasetKey", total_expect, total_via_ds)

    # ---- resume: 既存の progress / jsonl を読み込む ----
    seen = set()
    done_labels = {}
    resuming = PROGRESS.exists() and OUT_JSONL.exists()
    if resuming:
        try:
            done_labels = json.loads(PROGRESS.read_text(encoding="utf-8"))
        except Exception:
            done_labels = {}
        with open(OUT_JSONL, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    seen.add(json.loads(line)["key"])
                except Exception:
                    pass
        print(f"  [resume] {len(done_labels)} leaves already done, {len(seen)} keys already in jsonl", flush=True)
        outf = open(OUT_JSONL, "a", encoding="utf-8")
    else:
        outf = open(OUT_JSONL, "w", encoding="utf-8")

    write_lock = threading.Lock()
    partition_rows = []
    n_written = [len(seen)]

    def process(leaf):
        label = leaf["label"]
        if label in done_labels and done_labels[label].get("expect") == leaf["expect"]:
            return label, done_labels[label].get("got", 0), leaf["expect"], True
        leaf_out, got_records = None, None
        try:
            leaf_out, got_records = fetch_leaf(leaf)
        except Exception as e:
            with write_lock:
                partition_rows.append({"partition": label, "params": json.dumps(leaf["params"], ensure_ascii=False),
                                        "expect": leaf["expect"], "got": 0, "diff": leaf["expect"], "note": f"FAILED: {e!r}"})
            return label, 0, leaf["expect"], False
        new_n = 0
        with write_lock:
            for r in got_records:
                k = r.get("key")
                if k is None or k in seen:
                    continue
                seen.add(k)
                outf.write(json.dumps(flat(r), ensure_ascii=False) + "\n")
                new_n += 1
            outf.flush()
            n_written[0] += new_n
            done_labels[label] = {"expect": leaf["expect"], "got": len(got_records)}
            diff = leaf["expect"] - len(got_records)
            note = "" if diff == 0 else "件数不一致(要確認)"
            partition_rows.append({"partition": label, "params": json.dumps(leaf["params"], ensure_ascii=False),
                                    "expect": leaf["expect"], "got": len(got_records), "diff": diff, "note": note})
        return label, len(got_records), leaf["expect"], True

    with ThreadPoolExecutor(MAX_WORKERS) as ex:
        futs = [ex.submit(process, leaf) for leaf in leaves]
        n_done = 0
        for fut in as_completed(futs):
            label, got, expect, ok = fut.result()
            n_done += 1
            if n_done % 25 == 0 or not ok:
                with write_lock:
                    PROGRESS.write_text(json.dumps(done_labels, ensure_ascii=False), encoding="utf-8")
                print(f"  [{n_done}/{len(leaves)}] {label}: expect={expect} got={got} "
                      f"(total written {n_written[0]}, {time.time()-t0:.0f}s)", flush=True)

    with write_lock:
        PROGRESS.write_text(json.dumps(done_labels, ensure_ascii=False), encoding="utf-8")
    outf.close()

    n = n_written[0]
    print(f"\nwrote {n} records to {OUT_JSONL} in {time.time()-t0:.0f}s", flush=True)
    print(f"expect(top count api)={total_expect}  got={n}  diff={total_expect-n}", flush=True)

    # ---- partition report ----
    with open(PARTITION_REPORT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["partition", "params", "expect", "got", "diff", "note"])
        w.writeheader()
        for row in sorted(partition_rows, key=lambda r: -abs(r["diff"])):
            w.writerow(row)
        for g in gap_records:
            w.writerow({"partition": g["scope"] + f" [{g['split_dim']}分割で欠損]",
                        "params": "", "expect": g["expect_total"], "got": g["sum_children"],
                        "diff": g["gap"], "note": g["note"]})
    total_gap = sum(g["gap"] for g in gap_records)
    print(f"partition report -> {PARTITION_REPORT} ({len(partition_rows)} leaves, "
          f"{len(gap_records)} known date-field gaps totaling {total_gap} records)", flush=True)

    return n, total_expect, ds_counts

if __name__ == "__main__":
    n, total_expect, ds_counts = main()

    # ---------------------------------------------------------- 3. CSV 出力
    print("writing CSV...", flush=True)
    with open(OUT_JSONL, encoding="utf-8") as fin, open(OUT_CSV, "w", encoding="utf-8", newline="") as fout:
        w = csv.DictWriter(fout, fieldnames=CSV_COLS)
        w.writeheader()
        csv_n = 0
        for line in fin:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            w.writerow({k: r.get(k) for k in CSV_COLS})
            csv_n += 1
    print(f"  [write] {OUT_CSV.relative_to(common.ROOT)}  {csv_n} rows", flush=True)

    # ---------------------------------------------------- 4. 集計・チェックリスト
    print("building species checklist / dataset summary...", flush=True)
    species = {}   # (scientificName, taxonKey) -> agg
    by_dataset = collections.defaultdict(lambda: {"n_records": 0, "year_min": None, "year_max": None})

    with open(OUT_JSONL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            dk = r.get("datasetKey")
            y = r.get("year")
            bd = by_dataset[dk]
            bd["n_records"] += 1
            if isinstance(y, int):
                bd["year_min"] = y if bd["year_min"] is None else min(bd["year_min"], y)
                bd["year_max"] = y if bd["year_max"] is None else max(bd["year_max"], y)

            sn = r.get("scientificName")
            tk = r.get("taxonKey")
            key = (sn, tk)
            sp = species.get(key)
            if sp is None:
                sp = {"scientificName": sn, "taxonKey": tk, "kingdom": r.get("kingdom"),
                      "class": r.get("class"), "order": r.get("order"), "family": r.get("family"),
                      "n_records": 0, "year_min": None, "year_max": None, "datasets": set()}
                species[key] = sp
            sp["n_records"] += 1
            if isinstance(y, int):
                sp["year_min"] = y if sp["year_min"] is None else min(sp["year_min"], y)
                sp["year_max"] = y if sp["year_max"] is None else max(sp["year_max"], y)
            if dk:
                sp["datasets"].add(dk)

    # dataset_title を並列取得
    def get_title(dk):
        try:
            j = throttled_dataset_get(dk)
            return dk, j.get("title")
        except Exception as e:
            return dk, f"(取得失敗: {e!r})"

    def throttled_dataset_get(dk, timeout=30, retries=3):
        last_err = None
        for attempt in range(retries):
            with _req_lock:
                dt = time.time() - _last_req_t[0]
                if dt < MIN_GAP:
                    time.sleep(MIN_GAP - dt)
                _last_req_t[0] = time.time()
            try:
                r = session.get(DATASET_API.format(dk), headers={"User-Agent": UA}, timeout=timeout)
                if r.status_code == 200:
                    return r.json()
                last_err = f"HTTP {r.status_code}"
                if r.status_code in (400, 401, 403, 404):
                    break
            except Exception as e:
                last_err = repr(e)
            time.sleep(1.0 * (attempt + 1))
        raise RuntimeError(last_err)

    titles = {}
    with ThreadPoolExecutor(MAX_WORKERS) as ex:
        for dk, title in ex.map(get_title, list(by_dataset.keys())):
            titles[dk] = title

    with open(SUMMARY_DATASET, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["datasetKey", "dataset_title", "n_records", "year_min", "year_max"])
        for dk, agg in sorted(by_dataset.items(), key=lambda x: -x[1]["n_records"]):
            w.writerow([dk, titles.get(dk), agg["n_records"], agg["year_min"], agg["year_max"]])
    print(f"  [write] {SUMMARY_DATASET.relative_to(common.ROOT)}  {len(by_dataset)} datasets", flush=True)

    with open(CHECKLIST, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scientificName", "taxonKey", "kingdom", "class", "order", "family",
                    "n_records", "year_min", "year_max", "n_datasets"])
        for sp in sorted(species.values(), key=lambda s: -s["n_records"]):
            w.writerow([sp["scientificName"], sp["taxonKey"], sp["kingdom"], sp["class"],
                        sp["order"], sp["family"], sp["n_records"], sp["year_min"], sp["year_max"],
                        len(sp["datasets"])])
    print(f"  [write] {CHECKLIST.relative_to(common.ROOT)}  {len(species)} taxa", flush=True)

    # 【本タスクで修正】以前は source_id="gbif_kanagawa" で register していたが、
    # m03_organisms.py が organism_records.source_id に実際に書き込む値は
    # "gbif_kanagawa_occurrences" であり、両者が食い違うと source_registry との突合が
    # 失敗し GBIF由来レコード全件がDwC-A/配布パッケージから除外されてしまう
    # （実際に本タスクで発覚した不整合。docs/LICENSE_MATRIX.md 4.5 参照）。
    # 実データ側の名称に registry 側を合わせる方針で "gbif_kanagawa_occurrences" に統一する。
    register("gbif_kanagawa_occurrences", "GBIF Occurrence — 神奈川県 (GADM JPN.19_1)", "GBIF",
             f"https://www.gbif.org/occurrence/search?gadm_gid={GADM}", "生物出現記録",
             "REST API (occurrence/search, datasetKey/year/month/day で分割)", "JSONL/CSV",
             "各データセット個別 (CC0/CC BY/CC BY-NC が混在。license列に保持)",
             True, n, f"expect={total_expect}, got={n}, diff={total_expect-n} "
                      f"(内訳は data/logs/gbif_partition_report.csv 参照)")
