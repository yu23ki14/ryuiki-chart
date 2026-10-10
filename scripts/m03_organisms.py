"""アプリDB organism_records の構築（iNaturalist + GBIF）。

- iNaturalist (inaturalist_kanagawa.jsonl): 取得済み。全件ロードする。
- GBIF (gbif_kanagawa_occurrences.jsonl): 別エージェントが収集中のことがある。
  存在しても0件でも壊れないように書く（冪等・再実行可能）。record_id を主キーに
  INSERT ... ON CONFLICT DO UPDATE するので、後から行が増えたファイルを再ロードしても
  重複しない（かつ既存行のライセンス3列も再実行のたびに最新化される＝バックフィル）。
- taxa テーブル（学名を正規化した taxon_id をキーに保持）と学名で結合し、
  一致した場合のみ red_list_category / is_alien を埋める。一致しない場合は
  red_list_category=NULL, is_alien=0（デフォルト）のままにする。学名の推測補完はしない。
- publication_scope: レッドリスト掲載種(red_list_category が非NULL) -> '限定共有'、
  それ以外 -> '全公開'（要求定義書 FR-4.5）。値は出典側の旗としてそのまま持たせるだけで、
  これを根拠に出力を絞ることはしない（ADR-0028）。
- quality_stage: iNaturalist の quality_grade=='research' -> '検証済'、それ以外 -> '暫定'。
  GBIF -> '公開済'（GBIF自体が公開済データベースであるため）。
- occurrence_status: GBIF の occurrenceStatus（PRESENT/ABSENT）をそのまま。iNaturalist は NULL。不在記録（ABSENT）は
  原本に残し b06 が occurrence から除く。既存DBへの追加は `python scripts/m03_organisms.py --backfill-occurrence-status`（冪等）。
- 座標は一般化・秘匿しない。元座標をそのまま保持する（iNaturalist側でgeoprivacy設定により
  既に難読化されている場合はその値のまま）。FR-4.5 が定めていた希少種座標の一般化は
  ADR-0028 により撤回された（旧実装は `scripts/x01_dwca.py` の DwC-A 出力時に丸めていたが、
  現在は丸めない）。

--- 県版 → 全国版の順（地域ごと。docs/plans/AMAMI_STEP2A.md §3）---
前提: `taxa`（c25）と、`redlist_assessments`・`pref_redlist_lookup`（c28）が先にできていること
（c25 → c28 → m03。c28 が無いと taxa_lookup は何を先に回すかを示して止まる）。
red_list_category は地域ごとに `regions.REGIONS[rid]["pref_redlist"]` の宣言で県版を引き、無ければ環境省の全国版
（taxa.redlist_national）を使う。どちらで付けたかは organism_records.red_list_source（県版の list_id か 'national'）
に持つ。カテゴリーの文字列は c25 の `taxa` と同じ形（「カテゴリー（コード）」）。神奈川（jp-14）は従来どおり
`redlist_kanagawa or redlist_national` で、red_list_category・publication_scope は変えない。
条例の指定種（kgord）は赤リスト該当に含めない。

--- レコード単位ライセンス (record_license / license_class / commercial_ok) ---
iNaturalist・GBIFはソース単位のredistributableフラグだけでは再配布可否を判定できず、
観察/データセット単位でライセンスが混在する（例: iNaturalist 165,332件中 約82% が
CC BY-NC またはライセンス表示なし）。organism_records にレコード単位でライセンスを
保持する3列を追加し、ここで実際に出現した値だけをマッピングして埋める
（表示のない値を推測で 'open' に分類することはしない）。

マッピングは LICENSE_MAP（iNaturalist生値・GBIFライセンスURLの両方を実測して作成）
で行う。未知の値が出現した場合は 'unknown'・commercial_ok=0 としたうえで警告を出す
（推測でopen/noncommercialに割り当てない）。実際に出現した値の集計は
data/processed/license_code_mapping.csv に出力する。
"""
import sys, pathlib, json, re, sqlite3, csv, collections, argparse
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import appdb, PROC, norm_taxon_id
import regions
from regions import REGIONS

def rd_jsonl(name):
    p = PROC / f"{name}.jsonl"
    if not p.exists():
        return
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                # 並行して書き込み中のファイル末尾で不完全な行を拾った場合はスキップする
                # (GBIF収集エージェントが同時に追記している可能性があるため、行単位で
                # 読めないものは無視し、次回再実行時に再取得すればよい)
                continue

# ---- レコード単位ライセンスの正規化 ----
# 実測で出現した値のみを列挙する（docs/LICENSE_MATRIX.md 4.5 で確認済みの値）。
# license_class: open / noncommercial / unknown / restricted
#   open          = CC0 / CC BY / パブリックドメイン相当（改変・商用利用に追加条件なし）
#   noncommercial = CC BY-NC 系（NC条件を含むものは全てここに分類する。SA/ND が
#                   併記されていても NC が付けば商用利用不可という制約が優先されるため）
#   restricted    = 商用利用自体は妨げないが、Share-Alike（二次的著作物の同一条件公開義務）
#                   や改変禁止(ND)など、単純な「開いている」扱いにはできない付帯条件があるもの
#   unknown       = ライセンス表示なし（None）・空文字など、確認できないもの
#     （表示がないことを「オープン」とは推測しない。全著作権留保の可能性を安全側で見る）
LICENSE_MAP = {
    # --- iNaturalist license_code の原表記 (小文字, ハイフン区切り) ---
    "cc0": ("open", 1),
    "cc-by": ("open", 1),
    "cc-by-sa": ("restricted", 1),
    "cc-by-nd": ("restricted", 1),
    "cc-by-nc": ("noncommercial", 0),
    "cc-by-nc-sa": ("noncommercial", 0),
    "cc-by-nc-nd": ("noncommercial", 0),
    # --- GBIF license (Creative Commons legalcode URL) ---
    "http://creativecommons.org/publicdomain/zero/1.0/legalcode": ("open", 1),
    "https://creativecommons.org/publicdomain/zero/1.0/legalcode": ("open", 1),
    "http://creativecommons.org/licenses/by/4.0/legalcode": ("open", 1),
    "https://creativecommons.org/licenses/by/4.0/legalcode": ("open", 1),
    "http://creativecommons.org/licenses/by-sa/4.0/legalcode": ("restricted", 1),
    "https://creativecommons.org/licenses/by-sa/4.0/legalcode": ("restricted", 1),
    "http://creativecommons.org/licenses/by-nc/4.0/legalcode": ("noncommercial", 0),
    "https://creativecommons.org/licenses/by-nc/4.0/legalcode": ("noncommercial", 0),
    "http://creativecommons.org/licenses/by-nc-sa/4.0/legalcode": ("noncommercial", 0),
    "https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode": ("noncommercial", 0),
}
_unknown_warned = set()

def classify_license(raw):
    """raw: 元データのライセンス表記そのまま (None / '' / 'cc-by-nc' / URL 等)。
    戻り値: (record_license_to_store, license_class, commercial_ok)
    record_license は元の値をそのまま保存する（None は SQL NULL、'' は空文字のまま）。
    """
    if raw is None:
        return None, "unknown", 0
    key = str(raw).strip()
    if key == "":
        return "", "unknown", 0
    mapped = LICENSE_MAP.get(key.lower()) if not key.startswith("http") else LICENSE_MAP.get(key)
    if mapped is None:
        # 未知の値: 推測でopen/noncommercialに割り当てず、安全側(unknown/商用不可)にする
        if key not in _unknown_warned:
            print(f"  !! 未知のライセンス表記を検出: {key!r} -> license_class='unknown' として扱う "
                  f"(LICENSE_MAP に追記して要再分類)")
            _unknown_warned.add(key)
        return raw, "unknown", 0
    cls, ok = mapped
    return raw, cls, ok

def write_license_mapping_csv(counters):
    """実際に出現したライセンス原表記の集計を data/processed/license_code_mapping.csv に出力する。
    counters: {(source, raw_repr): count}
    """
    out = PROC / "license_code_mapping.csv"
    rows = []
    for (source, raw), cnt in counters.items():
        _, cls, ok = classify_license(None if raw == "(null)" else ("" if raw == "(empty string)" else raw))
        rows.append((source, raw, cls, ok, cnt))
    rows.sort(key=lambda r: (r[0], -r[4]))
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source", "raw_license_repr", "license_class", "commercial_ok", "count"])
        for r in rows:
            w.writerow(r)
    print(f"  [write] {out.relative_to(PROC.parent.parent)}  {len(rows)} rows (原表記の集計)")

INSERT_SQL = """INSERT INTO organism_records
  (record_id, event_id, site_id, observed_on, scientific_name, vernacular_name,
   taxon_rank, kingdom, phylum, class, "order", family, genus, taxon_key,
   individual_count, density, density_unit, basis_of_record, identified_by,
   identification_basis, identification_confidence, lat, lon, coordinate_uncertainty_m,
   red_list_category, is_alien, quality_stage, publication_scope,
   source_id, source_ref, is_synthetic, record_license, license_class, commercial_ok,
   occurrence_status, red_list_source)
  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
  ON CONFLICT(record_id) DO UPDATE SET
    record_license=excluded.record_license,
    license_class=excluded.license_class,
    commercial_ok=excluded.commercial_ok,
    occurrence_status=excluded.occurrence_status,
    red_list_category=excluded.red_list_category,
    publication_scope=excluded.publication_scope,
    red_list_source=excluded.red_list_source"""

NATIONAL_SOURCE = "national"   # red_list_source: 環境省の全国版で付けた


def _cat_text(category_ja, code):
    return f"{category_ja}（{code}）" if code else category_ja   # c25 と同じ形


def _kanagawa_list_by_taxon(conn, list_ids):
    """神奈川の taxa.redlist_kanagawa の元になった list_id（c25 と同じ「新しい版が勝つ」）。
    redlist_assessments（c28）を学名で引く。学名の無い行は taxa の taxon_id が wamei: になる。"""
    ph = ",".join("?" * len(list_ids))
    out = {}
    for aid, sci in conn.execute(
            f"select assessment_id, scientific_name from redlist_assessments "
            f"where scientific_name is not null and substr(assessment_id, 1, instr(assessment_id, '_') - 1) in ({ph}) "
            f"order by list_year, assessment_id", list_ids):
        out[norm_taxon_id(sci)] = aid.split("_", 1)[0]
    return out


def taxa_lookup(conn, rid=regions.DEFAULT_REGION):
    """taxon_id -> (red_list_category, ias_category, red_list_source)。地域の県版 → 全国版の順。"""
    decl = REGIONS[rid]["pref_redlist"]
    need = "redlist_assessments" if decl["source"] == "taxa_column" else "pref_redlist_lookup"
    if not conn.execute("select 1 from sqlite_master where type='table' and name=?", (need,)).fetchone():
        raise SystemExit(f"{need} 表が無い（{rid} の赤リスト判定に要る）。先に "
                         "`python scripts/c28_redlist_assessments.py` を実行すること（c25 → c28 → m03 の順）")
    rows = conn.execute("select taxon_id, redlist_kanagawa, redlist_national, ias_category from taxa").fetchall()
    d = {}
    if decl["source"] == "taxa_column":
        kan = _kanagawa_list_by_taxon(conn, decl["list_ids"])
        for tid, rk, rn, ias in rows:
            if tid.startswith("wamei:"):   # 学名の無い行。出現記録（学名の正規化キー）とは結べない
                continue
            if rk:
                src = kan.get(tid)
                if src is None:
                    raise ValueError(f"taxa.redlist_kanagawa があるのに redlist_assessments に学名が無い: {tid!r}"
                                     "（c28 を c25 の後に実行したか確認）")
                d[tid] = (rk, ias, src)
            else:
                d[tid] = (rn, ias, NATIONAL_SOURCE if rn else None)
    elif decl["source"] == "lookup_table":
        pref = {tid: _cat_text(cat, code) for tid, cat, code in conn.execute(
            "select taxon_id, category_ja, category_code from pref_redlist_lookup where region_id=? and list_id=?",
            (rid, decl["list_id"]))}
        for tid, rk, rn, ias in rows:
            if tid.startswith("wamei:"):
                continue
            if tid in pref:
                d[tid] = (pref[tid], ias, decl["list_id"])
            else:
                d[tid] = (rn, ias, NATIONAL_SOURCE if rn else None)
        for tid, cat in pref.items():   # 県版にだけある種（taxa に無い）。c25 は神奈川の2版と環境省しか見ないため
            d.setdefault(tid, (cat, None, decl["list_id"]))
    else:
        raise ValueError(f"{rid}: 未知の pref_redlist.source={decl['source']!r}")
    return d

def _license_repr(v):
    if v is None:
        return "(null)"
    if v == "":
        return "(empty string)"
    return v

def load_inaturalist(conn, taxa, license_counter, rid=regions.DEFAULT_REGION):
    src = regions.name("inaturalist_kanagawa", rid)   # 既定の地域は inaturalist_kanagawa のまま
    n = 0
    batch = []
    n_matched = 0
    for r in rd_jsonl(src):
        n += 1
        tid = norm_taxon_id(r.get("scientific_name"))
        rl, ias, rl_src = taxa.get(tid, (None, None, None))
        if rl is not None or ias is not None:
            n_matched += 1
        is_alien = 1 if ias else 0
        agree = r.get("num_identification_agreements") or 0
        disagree = r.get("num_identification_disagreements") or 0
        tot = agree + disagree
        conf = (agree / tot) if tot > 0 else None
        quality_stage = "検証済" if r.get("quality_grade") == "research" else "暫定"
        pub_scope = "限定共有" if rl else "全公開"
        raw_license = r.get("license_code")
        license_counter[(src, _license_repr(raw_license))] += 1
        rec_license, license_class, commercial_ok = classify_license(raw_license)
        batch.append((
            f"{src}__{r['id']}", None, None,
            r.get("observed_on"), r.get("scientific_name"), r.get("vernacular_name_ja"),
            r.get("rank"), r.get("kingdom"), r.get("phylum"), r.get("class"), r.get("order"),
            r.get("family"), r.get("genus"), str(r.get("taxon_id")) if r.get("taxon_id") is not None else None,
            None, None, None,
            "HumanObservation", None, "写真+コミュニティ同定（iNaturalist quality_grade参照）", conf,
            r.get("lat"), r.get("lon"), r.get("positional_accuracy_m"),
            rl, is_alien, quality_stage, pub_scope,
            src, r.get("source_ref"), 0,
            rec_license, license_class, commercial_ok,
            None,  # occurrence_status: iNaturalist に不在の概念は無い
            rl_src,
        ))
        if len(batch) >= 20000:
            conn.executemany(INSERT_SQL, batch); conn.commit(); batch = []
    if batch:
        conn.executemany(INSERT_SQL, batch); conn.commit()
    print(f"  {src}: {n} rows read, taxa一致 {n_matched} 件 -> organism_records へ INSERT/UPDATE(license)")
    return n

def load_gbif(conn, taxa, license_counter, rid=regions.DEFAULT_REGION):
    src = regions.name("gbif_kanagawa_occurrences", rid)   # 既定の地域は gbif_kanagawa_occurrences のまま
    n = 0
    batch = []
    n_matched = 0
    for r in rd_jsonl(src):
        n += 1
        sci = r.get("scientificName") or r.get("species")
        tid = norm_taxon_id(sci)
        rl, ias, rl_src = taxa.get(tid, (None, None, None))
        if rl is not None or ias is not None:
            n_matched += 1
        is_alien = 1 if ias else 0
        pub_scope = "限定共有" if rl else "全公開"
        obs_on = r.get("eventDate") or (
            f"{r['year']:04d}-{r.get('month',1) or 1:02d}-{r.get('day',1) or 1:02d}"
            if r.get("year") else None)
        raw_license = r.get("license")
        license_counter[(src, _license_repr(raw_license))] += 1
        rec_license, license_class, commercial_ok = classify_license(raw_license)
        batch.append((
            f"{src}__{r['key']}", None, None,
            obs_on, sci, r.get("vernacularName"),
            r.get("taxonRank"), r.get("kingdom"), r.get("phylum"), r.get("class"), r.get("order"),
            r.get("family"), r.get("genus"), str(r.get("taxonKey")) if r.get("taxonKey") is not None else None,
            r.get("individualCount"), None, None,
            r.get("basisOfRecord"), r.get("identifiedBy"), None, None,
            r.get("decimalLatitude"), r.get("decimalLongitude"), r.get("coordinateUncertaintyInMeters"),
            rl, is_alien, "公開済", pub_scope,
            src, r.get("occurrenceID") or str(r.get("key")), 0,
            rec_license, license_class, commercial_ok,
            r.get("occurrenceStatus"),  # GBIF の語彙（PRESENT/ABSENT）のまま
            rl_src,
        ))
        if len(batch) >= 20000:
            conn.executemany(INSERT_SQL, batch); conn.commit(); batch = []
    if batch:
        conn.executemany(INSERT_SQL, batch); conn.commit()
    if n == 0:
        print(f"  {src}: 0 rows (別エージェントの収集が未完了/未着手のためスキップ。"
              "再実行すれば取り込まれる)")
    else:
        print(f"  {src}: {n} rows read, taxa一致 {n_matched} 件 -> organism_records へ INSERT/UPDATE(license)")
    return n

def _ensure_column(conn, column):
    """既存の organism_records に列が無ければ TEXT で足す（冪等。足したら True）。
    schema_app.sql の CREATE TABLE IF NOT EXISTS は既存表に列を足さないので、原本DBにはこちらで足す。
    表そのものが無い（空の DB・別の DB を指した）ときは、分かる文言で止める。"""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(organism_records)")]
    if not cols:
        raise SystemExit(f"organism_records 表が無い。対象の DB が違う（--db）か、先に m03 を全件実行して表を作ること")
    if column in cols:
        return False
    conn.execute(f"ALTER TABLE organism_records ADD COLUMN {column} TEXT")
    conn.commit()
    return True

def ensure_occurrence_status_column(conn):
    """organism_records.occurrence_status を足す（足したら True）。"""
    return _ensure_column(conn, "occurrence_status")

def ensure_red_list_source_column(conn):
    """organism_records.red_list_source を足す（足したら True）。足した直後は NULL で、
    m03 の全件再投入（ON CONFLICT で更新）が埋める。"""
    return _ensure_column(conn, "red_list_source")

def backfill_occurrence_status(conn, batch_size=20000, rid=regions.DEFAULT_REGION):
    """m03 の全件再投入なしで、GBIF の occurrenceStatus を既存行へ入れる（冪等）。

    列が無ければ足し、jsonl の key から record_id='gbif_kanagawa_occurrences__<key>' へ UPDATE する。
    iNaturalist など GBIF 以外の行は触らない（NULL のまま）。jsonl の key のうち organism_records に
    行が無いものがあれば、何も書かずに止める（黙って飛ばさない）。ただし organism_records にその出典の行が1行も
    無い地域は、未取り込みなので「飛ばした」と表示して次の地域に進む。戻り値は (列を足したか, 読んだ行数,
    更新した行数, 値の内訳 Counter)。"""
    conn.execute("PRAGMA busy_timeout=60000")
    added = ensure_occurrence_status_column(conn)
    src = regions.name("gbif_kanagawa_occurrences", rid)
    counts = collections.Counter()
    pairs = []
    for r in rd_jsonl(src):
        st = r.get("occurrenceStatus")
        counts[st] += 1
        pairs.append((f"{src}__{r['key']}", st))
    in_db = {x for (x,) in conn.execute(
        "SELECT record_id FROM organism_records WHERE source_id=?", (src,))}
    if not in_db:   # その地域の記録が organism_records に1行も無い＝未取り込み。止めずに飛ばす
        print(f"  {src}: organism_records に1行も無い（未取り込みのため飛ばした）")
        return added, 0, 0, collections.Counter()
    missing = [x for x, _ in pairs if x not in in_db]
    if missing:
        raise SystemExit(
            f"jsonl の key のうち organism_records に行が無いものが {len(missing)} 件ある（例: {missing[:3]}）。"
            "m03 を全件実行して取り込んでから backfill すること")
    changed = 0
    for i in range(0, len(pairs), batch_size):
        before = conn.total_changes
        conn.executemany(
            "UPDATE organism_records SET occurrence_status=? WHERE record_id=? "
            "AND occurrence_status IS NOT ?", [(st, k, st) for k, st in pairs[i:i + batch_size]])
        changed += conn.total_changes - before
        conn.commit()
    return added, len(pairs), changed, counts

def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="アプリDB organism_records の構築（iNaturalist + GBIF）。引数なしで全件を取り込む。")
    ap.add_argument("--backfill-occurrence-status", action="store_true",
                    help="全件の取り込みはせず、既存の organism_records に occurrence_status 列を足して "
                         "GBIF の occurrenceStatus を入れる（冪等）")
    ap.add_argument("--db", default=None,
                    help="--backfill-occurrence-status の対象 DB（既定は data/db/ryuiki.sqlite。一時コピーでの確認用）")
    args = ap.parse_args(argv)
    if args.db and not args.backfill_occurrence_status:
        ap.error("--db は --backfill-occurrence-status と一緒にだけ使える")
    return args

def main(argv=None):
    args = parse_args(argv)
    if args.backfill_occurrence_status:
        conn = sqlite3.connect(args.db, timeout=30) if args.db else appdb()
        added, n, changed, counts = False, 0, 0, collections.Counter()
        for rid in REGIONS:
            a, n1, c1, k1 = backfill_occurrence_status(conn, rid=rid)
            added, n, changed, counts = added or a, n + n1, changed + c1, counts + k1
        print(f"  occurrence_status 列を{'追加した' if added else '追加済み'}。jsonl {n} 行を読み、{changed} 行を更新した（2回目以降は 0）")
        print(f"  jsonl の内訳: {dict(counts)}")
        for st, c in conn.execute("select occurrence_status, count(*) from organism_records "
                                  "group by occurrence_status order by 1"):
            print(f"    organism_records.occurrence_status={st!r}: {c}")
        conn.close()
        return
    conn = appdb()
    conn.execute("PRAGMA busy_timeout=60000")
    ensure_occurrence_status_column(conn)
    ensure_red_list_source_column(conn)
    conn.execute("PRAGMA journal_mode=WAL")

    taxa_by_region = {rid: taxa_lookup(conn, rid) for rid in REGIONS}   # 赤リストの引き方は地域ごと
    print("  taxa lookup entries: " + ", ".join(f"{rid}={len(t)}" for rid, t in taxa_by_region.items()))

    license_counter = collections.Counter()
    n_inat = n_gbif = 0
    for rid in REGIONS:   # 地域ごとに別の jsonl・別の record_id 接頭辞（無い出典は 0 件で飛ぶ）
        n_inat += load_inaturalist(conn, taxa_by_region[rid], license_counter, rid)
        n_gbif += load_gbif(conn, taxa_by_region[rid], license_counter, rid)
    write_license_mapping_csv(license_counter)

    n_total = conn.execute("select count(*) from organism_records").fetchone()[0]
    print(f"\n  organism_records total rows: {n_total} "
          f"(iNaturalist入力{n_inat}件 + GBIF入力{n_gbif}件、重複はrecord_idでON CONFLICT UPDATE)")

    print("\n  license_class 内訳 (organism_records 全件):")
    for sid, cls, ok, cnt in conn.execute(
            "select source_id, license_class, commercial_ok, count(*) as cnt from organism_records "
            "group by source_id, license_class, commercial_ok order by source_id, cnt desc"):
        print(f"    {sid} / {cls} / commercial_ok={ok}: {cnt}")
    conn.close()

if __name__ == "__main__":
    main()
