"""GBIF 神奈川県収集: 失敗区画の再取得（既存 jsonl には追記、上書きしない）。

## 原因（実測で確定・仮説(b): HTTPエラーの握り潰し）
c02_gbif.py の完走ログ (data/logs/gbif.log) で「got=0」になった区画は、以下の2つの
datasetKey に集中していた:
  - 95eebc5e-f762-11e1-a439-00145eb45e9a (year 分割)
  - 4fa7b334-ce0d-4e88-aaae-2e0c138d049e (year&month 分割、通称 eBird)
これらは実行キューの末尾でほぼ連続して処理された最大級のデータセットで、4並列 x
MIN_GAP=0.12秒 のリクエストが長時間ノンストップで続いた結果、GBIF occurrence/search API から
持続的に HTTP 429 (Retry-After ヘッダで 3秒等を明示) を返され続けた。

実測で直接検証:
  同一パラメータに素の requests.get を連発 → 429 (Retry-After=3) が数回続いた後 200 に復帰。
  逆に単独(競合なし)で同じ区画(datasetKey=4fa7b334,year=2024,month=4)を叩くと
  count=7803 かつ results に300件返る(200) → 仮説(a)「countとresultsの乖離」は否定。
  同型パラメータで1000以上の区画が成功しているため仮説(c)「パラメータ型」も否定。

既存の throttled_get() は 429 を最終失敗として扱う対象から除外していない＝一応リトライは
するが、Retry-After ヘッダを無視し固定の指数バックオフ(1.5*(attempt+1)秒、5回、合計22.5秒)
しか待たない設計のため、持続的な429状態から抜けられずリトライを使い切って RuntimeError。

## 追加で判明した第2のバグ（進捗ファイルが失敗を記録しない）
c02_gbif.py の process() は例外発生時に done_labels[label] を**設定しない**
(成功時のみ line239 で設定)。そのため data/logs/gbif_progress.json だけを見ても
「どの区画が失敗したか」は分からない（失敗区画は単に progress に存在しないだけ）。
かつ data/logs/gbif_partition_report.csv は main() が **全区画完了後に一度だけ** 書き出す
設計のため、プロセスを完走させない限り区画別の params 一覧も手に入らない。
このため本スクリプトは c02_gbif.py の build_all_leaves() を再実行して全区画を
正準に再構築し、done_labels に「expect と一致する記録が無い区画」＝失敗 or 未着手区画、
として差分を取る方式にした。

## d) 仮説の検証結果（誤り）
既に取得済みの jsonl 内を grep したところ、この2つの datasetKey のレコードはゼロではなかった
（実測時点で 4fa7b334: 6,253件 / 95eebc5e: 148,122件）。「seenセットで全部弾かれていた」という
仮説(d)は誤り。該当区画のうち一部(year/monthの一部)は成功しており、失敗した区画だけが
本当に欠落していた。

## 対策
- MAX_WORKERS を 2 に削減（GBIFへの同時接続を絞る）
- 429/503 は Retry-After ヘッダを最優先で尊重し、無ければ指数バックオフ+ジッタ、
  リトライ上限を 10 に拡大
- build_all_leaves() で全区画を再構築し、done_labels に無い(=未完了/失敗)区画だけを対象に再取得
- 既存 jsonl には追記のみ。key で重複除去（seen は既存ファイル全体から再構築）。
- 再試行してもダメな区画は諦める。「どの区画が何件取れなかったか」を
  data/logs/gbif_partition_report.csv に最終確定版として書き出す（数字を誤魔化さない）。
"""
import sys, json, csv, time, pathlib, threading, random, collections
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import common
from common import PROC, LOGS, register, now
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

import c02_gbif as orig  # 区画設計(build_all_leaves)を再利用して一貫性を保つ

GADM = orig.GADM
UA = orig.UA
MAX_WORKERS = 1           # 逐次実行(coordinator指示: 2並列でも429を踏むため1に)
MIN_GAP = 1.5             # リクエスト間隔 1.0〜2.0秒 の指示に合わせる
RATE_LIMIT_BACKOFF = [10, 30, 60, 120, 300]   # 429/503 専用バックオフ(最低5回)
RATE_LIMIT_MAX_RETRIES = 5
GENERIC_RETRIES = 5       # 429/503以外(タイムアウト等)の汎用リトライ回数
TIME_BUDGET_SEC = 65 * 60  # 2回目の再開実行用: 残り70,311件(実測スループット約36件/秒)を
                            # 完了させるのに十分な時間(実測必要量は約35分、余裕を見て65分)。

FIELDS = orig.FIELDS
CSV_COLS = orig.CSV_COLS

OUT_JSONL = PROC/"gbif_kanagawa_occurrences.jsonl"
OUT_CSV = PROC/"gbif_kanagawa_occurrences.csv"
PROGRESS = LOGS/"gbif_progress.json"
PARTITION_REPORT = LOGS/"gbif_partition_report.csv"
REPAIR_LOG = LOGS/"gbif_repair.log"
SUMMARY_DATASET = PROC/"gbif_kanagawa_summary_by_dataset.csv"
CHECKLIST = PROC/"gbif_kanagawa_species_checklist.csv"

session = requests.Session()
_req_lock = threading.Lock()
_last_req_t = [0.0]

def throttled_get(params, timeout=60, retries=GENERIC_RETRIES):
    """429/503 専用のリトライ経路を持つ取得関数(common.get とは独立。他エージェントに影響しない)。
    - 429/503: Retry-After ヘッダがあればその秒数、無ければ [10,30,60,120,300]秒の
      指数バックオフで最低5回リトライする。
    - それ以外の失敗(タイムアウト等)は汎用リトライ(GENERIC_RETRIES回)。
    """
    last_err = None
    rate_limit_attempt = 0
    generic_attempt = 0
    while True:
        with _req_lock:
            dt = time.time() - _last_req_t[0]
            if dt < MIN_GAP:
                time.sleep(MIN_GAP - dt)
            _last_req_t[0] = time.time()
        try:
            r = session.get(orig.B, params=params, headers={"User-Agent": UA,
                             "Accept-Language": "ja,en;q=0.8"}, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            last_err = f"HTTP {r.status_code}"
            if r.status_code in (400, 401, 403, 404):
                break
            if r.status_code in (429, 503):
                if rate_limit_attempt >= RATE_LIMIT_MAX_RETRIES:
                    break
                ra = r.headers.get("Retry-After")
                if ra and ra.replace(".", "", 1).isdigit():
                    wait = float(ra)
                else:
                    idx = min(rate_limit_attempt, len(RATE_LIMIT_BACKOFF) - 1)
                    wait = RATE_LIMIT_BACKOFF[idx]
                wait += random.uniform(0.5, 2.0)
                log(f"    [429/503] {last_err} retry {rate_limit_attempt+1}/{RATE_LIMIT_MAX_RETRIES}"
                    f" wait={wait:.1f}s params={params}")
                time.sleep(wait)
                rate_limit_attempt += 1
                continue
        except Exception as e:
            last_err = repr(e)
        generic_attempt += 1
        if generic_attempt >= retries:
            break
        time.sleep(2.0 * generic_attempt + random.uniform(0, 1))
    raise RuntimeError(f"GET failed params={params}: {last_err}")

def flat(r):
    d = {k: r.get(k) for k in FIELDS}
    d["issues"] = "|".join(r.get("issues") or [])
    return d

def fetch_leaf(params, label):
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
            print(f"    !! offset cap hit for {label}", flush=True)
            break
    return out

def log(msg):
    print(msg, flush=True)
    with open(REPAIR_LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

def main():
    t0 = time.time()
    if REPAIR_LOG.exists():
        REPAIR_LOG.unlink()

    # build_all_leaves の facet 集計呼び出しも、より頑健な throttled_get に差し替えて実行する
    # (facet_of は orig モジュールのグローバル throttled_get を参照するため、モジュール属性を
    #  置き換えると facet_of からもこちらが呼ばれる)
    orig.throttled_get = throttled_get
    orig.MAX_WORKERS = MAX_WORKERS

    log("[repair] rebuilding canonical leaf set via c02_gbif.build_all_leaves() ...")
    leaves, ds_counts, total_via_ds = orig.build_all_leaves()
    log(f"[repair] {len(leaves)} leaves rebuilt (datasetKey facet sum={total_via_ds})")

    total_expect = throttled_get({"gadmGid": GADM, "limit": 0})["count"]
    log(f"[repair] GBIF top-level count(gadmGid={GADM}) = {total_expect}")

    if not PROGRESS.exists():
        log("ERROR: gbif_progress.json が無い。先に c02_gbif.py を実行してください。")
        sys.exit(1)
    done_labels = json.loads(PROGRESS.read_text(encoding="utf-8"))
    log(f"[repair] 既存 progress: {len(done_labels)} 区画が成功記録あり")

    # 「done_labels に無い、または got が expect と一致しない」区画だけを再取得対象にする
    # (c02_gbif.py の process() は例外時に done_labels へ書き込まないバグがあるため、
    #  progress.json に無い = 未完了(失敗 or 未着手) とみなすのが正しい判定方法。
    #  さらに、以前の repair 実行が got=0 の失敗を expect 一致のまま記録してしまうと
    #  「済み」として誤ってスキップされてしまうため、got==expect まで見て判定する)
    def is_done(lf):
        rec = done_labels.get(lf["label"])
        return rec is not None and rec.get("expect") == lf["expect"] and rec.get("got") == lf["expect"]
    targets = [lf for lf in leaves if not is_done(lf)]

    # 優先順位: year が無い(小さい)区画 と 2018年以降 を先に、2017年以前は後回し
    # (coordinator指示: 時間切れの場合は新しい年を優先して確実に取り切る)
    def sort_key(lf):
        y = lf["params"].get("year")
        if y is None:
            return (0, 0)
        yv = int(y)
        return (0, -yv) if yv >= 2018 else (1, -yv)
    targets.sort(key=sort_key)

    log(f"[repair] 再取得対象: {len(targets)} / {len(leaves)} 区画 "
        f"(2018年以降/年指定なしを優先, 2017年以前は後回し)")
    for lf in targets:
        prev = done_labels.get(lf["label"])
        log(f"  target: {lf['label']} expect={lf['expect']} prev_record={prev}")

    # 既存 jsonl から seen key を再構築（重複除去のため）
    seen = set()
    n_existing = 0
    with open(OUT_JSONL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            n_existing += 1
            try:
                seen.add(json.loads(line)["key"])
            except Exception:
                pass
    log(f"[repair] 既存 jsonl: {n_existing} 行 / {len(seen)} unique keys")

    outf = open(OUT_JSONL, "a", encoding="utf-8")

    def process(lf):
        label, params = lf["label"], lf["params"]
        try:
            records = fetch_leaf(params, label)
        except Exception as e:
            return label, 0, 0, False, repr(e)
        new_n = 0
        for r in records:
            k = r.get("key")
            if k is None or k in seen:
                continue
            seen.add(k)
            outf.write(json.dumps(flat(r), ensure_ascii=False) + "\n")
            new_n += 1
        outf.flush()
        return label, len(records), new_n, True, ""

    # MAX_WORKERS=1: 逐次実行(GBIFの429を避けるため並列化しない、coordinator指示)
    n_done = 0
    skipped_time_budget = []
    for lf in targets:
        elapsed = time.time() - t0
        if elapsed > TIME_BUDGET_SEC:
            skipped_time_budget.append(lf)
            continue
        label, got, new_n, ok, err = process(lf)
        n_done += 1
        log(f"  [{n_done}/{len(targets)}] {label}: expect={lf['expect']} "
            f"got={got} new_written={new_n} ok={ok} {('err='+err) if err else ''} "
            f"({time.time()-t0:.0f}s)")
        # 成功・失敗どちらも必ず記録する(元コードのバグ修正: 失敗も記録する。
        # got=0 の失敗は expect と一致しないので is_done() で次回また対象になる)
        done_labels[label] = {"expect": lf["expect"], "got": got}
        PROGRESS.write_text(json.dumps(done_labels, ensure_ascii=False), encoding="utf-8")

    outf.close()
    log(f"[repair] done in {time.time()-t0:.0f}s")
    if skipped_time_budget:
        log(f"[repair] 時間予算({TIME_BUDGET_SEC}s)超過のため未着手のまま残した区画: "
            f"{len(skipped_time_budget)} 件(下記、expectの合計 "
            f"{sum(lf['expect'] for lf in skipped_time_budget)} 件は今回取得できていない)")
        for lf in skipped_time_budget:
            log(f"    TIME BUDGET SKIP (未着手): {lf['label']} expect={lf['expect']}")

    # ---- 全区画(leaves全体)を対象に最終 still-missing を集計 ----
    still_missing = []
    for lf in leaves:
        rec = done_labels.get(lf["label"])
        got = rec["got"] if rec else 0
        diff = lf["expect"] - got
        if diff != 0:
            still_missing.append({"partition": lf["label"], "params": lf["params"],
                                   "expect": lf["expect"], "got": got, "diff": diff})
    log(f"[repair] 全区画完了後もなお不一致な区画: {len(still_missing)} 件, "
        f"欠落合計 {sum(m['diff'] for m in still_missing)} 件")
    for m in still_missing:
        log(f"    STILL MISSING: {m['partition']} expect={m['expect']} got={m['got']} diff={m['diff']}")

    return leaves, still_missing, total_expect, skipped_time_budget

if __name__ == "__main__":
    leaves, still_missing, total_expect, skipped_time_budget = main()

    # ---- 最終 partition report を書き出し(区画ごとの expect/got/diff を必ず記録) ----
    done_labels = json.loads(PROGRESS.read_text(encoding="utf-8"))
    skipped_labels = {lf["label"] for lf in skipped_time_budget}
    with open(PARTITION_REPORT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["partition", "params", "expect", "got", "diff", "note"])
        w.writeheader()
        rows = []
        for lf in leaves:
            label = lf["label"]
            rec = done_labels.get(label)
            got = rec["got"] if rec else 0
            diff = lf["expect"] - got
            if diff == 0:
                note = ""
            elif label in skipped_labels:
                note = "時間予算超過のため未着手(取れなかった)"
            else:
                note = "429リトライを尽くしても取得不能(GBIF側の恒常的レート制限の可能性)"
            rows.append({"partition": label, "params": json.dumps(lf["params"], ensure_ascii=False),
                         "expect": lf["expect"], "got": got, "diff": diff, "note": note})
        for row in sorted(rows, key=lambda r: -abs(r["diff"])):
            w.writerow(row)
        for g in orig.gap_records:
            w.writerow({"partition": g["scope"] + f" [{g['split_dim']}分割で欠損]",
                        "params": "", "expect": g["expect_total"], "got": g["sum_children"],
                        "diff": g["gap"], "note": g["note"]})
    print(f"[repair] partition report written -> {PARTITION_REPORT}", flush=True)

    # ---- 最終件数の検証(数字を誤魔化さない: ありのままの差分を出す) ----
    n_final = sum(1 for _ in open(OUT_JSONL, encoding="utf-8"))
    print(f"[repair] final jsonl lines={n_final}  GBIF top-level count={total_expect}  "
          f"diff={total_expect - n_final}", flush=True)
    total_gap_datefield = sum(g["gap"] for g in orig.gap_records)
    total_gap_leaf = sum(m["diff"] for m in still_missing)
    print(f"[repair] 内訳: 区画取得不能による欠落={total_gap_leaf}件, "
          f"日付フィールド欠損による分割不能ぶん={total_gap_datefield}件", flush=True)

    # ---- CSV 出力（全量を作り直し） ----
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

    # ---- 集計・チェックリスト（全量を作り直し） ----
    print("building species checklist / dataset summary...", flush=True)
    species = {}
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

    def get_title(dk):
        try:
            j = orig.throttled_dataset_get(dk) if hasattr(orig, "throttled_dataset_get") else None
            if j is None:
                r = session.get(orig.DATASET_API.format(dk), headers={"User-Agent": UA}, timeout=30)
                j = r.json() if r.status_code == 200 else {}
            return dk, j.get("title")
        except Exception as e:
            return dk, f"(取得失敗: {e!r})"

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

    # 【本タスクで修正】source_id を "gbif_kanagawa" から "gbif_kanagawa_occurrences" に統一。
    # 理由は c02_gbif.py の同箇所コメント、および docs/LICENSE_MATRIX.md 4.5 を参照。
    register("gbif_kanagawa_occurrences", "GBIF Occurrence — 神奈川県 (GADM JPN.19_1)", "GBIF",
             f"https://www.gbif.org/occurrence/search?gadm_gid={GADM}", "生物出現記録",
             "REST API (occurrence/search, datasetKey/year/month/day で分割; 429対策で再取得済み)",
             "JSONL/CSV",
             "各データセット個別 (CC0/CC BY/CC BY-NC が混在。license列に保持)",
             True, n_final, f"expect={total_expect}, got={n_final}, diff={total_expect-n_final} "
                      f"(内訳は data/logs/gbif_partition_report.csv 参照。"
                      f"再取得後もなお不一致な区画 {len(still_missing)} 件)")
