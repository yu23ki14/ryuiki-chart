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
  それ以外 -> '全公開'（要求定義書 FR-4.5）。
- quality_stage: iNaturalist の quality_grade=='research' -> '検証済'、それ以外 -> '暫定'。
  GBIF -> '公開済'（GBIF自体が公開済データベースであるため）。
- 座標の丸め（希少種の位置情報を粗くする）はアプリ表示層の責務とし、ここでは元座標を
  そのまま保持する（iNaturalist側でgeoprivacy設定により既に難読化されている場合はその値のまま）。

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
import sys, pathlib, json, re, sqlite3, csv, collections
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import appdb, PROC

def norm_taxon_id(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()

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
   source_id, source_ref, is_synthetic, record_license, license_class, commercial_ok)
  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
  ON CONFLICT(record_id) DO UPDATE SET
    record_license=excluded.record_license,
    license_class=excluded.license_class,
    commercial_ok=excluded.commercial_ok"""

def taxa_lookup(conn):
    rows = conn.execute("select taxon_id, redlist_kanagawa, redlist_national, ias_category from taxa").fetchall()
    d = {}
    for tid, rk, rn, ias in rows:
        d[tid] = (rk or rn, ias)  # 神奈川RLを優先、無ければ国RL
    return d

def _license_repr(v):
    if v is None:
        return "(null)"
    if v == "":
        return "(empty string)"
    return v

def load_inaturalist(conn, taxa, license_counter):
    n = 0
    batch = []
    n_matched = 0
    for r in rd_jsonl("inaturalist_kanagawa"):
        n += 1
        tid = norm_taxon_id(r.get("scientific_name"))
        rl, ias = taxa.get(tid, (None, None))
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
        license_counter[("inaturalist_kanagawa", _license_repr(raw_license))] += 1
        rec_license, license_class, commercial_ok = classify_license(raw_license)
        batch.append((
            f"inaturalist_kanagawa__{r['id']}", None, None,
            r.get("observed_on"), r.get("scientific_name"), r.get("vernacular_name_ja"),
            r.get("rank"), r.get("kingdom"), r.get("phylum"), r.get("class"), r.get("order"),
            r.get("family"), r.get("genus"), str(r.get("taxon_id")) if r.get("taxon_id") is not None else None,
            None, None, None,
            "HumanObservation", None, "写真+コミュニティ同定（iNaturalist quality_grade参照）", conf,
            r.get("lat"), r.get("lon"), r.get("positional_accuracy_m"),
            rl, is_alien, quality_stage, pub_scope,
            "inaturalist_kanagawa", r.get("source_ref"), 0,
            rec_license, license_class, commercial_ok,
        ))
        if len(batch) >= 20000:
            conn.executemany(INSERT_SQL, batch); conn.commit(); batch = []
    if batch:
        conn.executemany(INSERT_SQL, batch); conn.commit()
    print(f"  inaturalist_kanagawa: {n} rows read, taxa一致 {n_matched} 件 -> organism_records へ INSERT/UPDATE(license)")
    return n

def load_gbif(conn, taxa, license_counter):
    n = 0
    batch = []
    n_matched = 0
    for r in rd_jsonl("gbif_kanagawa_occurrences"):
        n += 1
        sci = r.get("scientificName") or r.get("species")
        tid = norm_taxon_id(sci)
        rl, ias = taxa.get(tid, (None, None))
        if rl is not None or ias is not None:
            n_matched += 1
        is_alien = 1 if ias else 0
        pub_scope = "限定共有" if rl else "全公開"
        obs_on = r.get("eventDate") or (
            f"{r['year']:04d}-{r.get('month',1) or 1:02d}-{r.get('day',1) or 1:02d}"
            if r.get("year") else None)
        raw_license = r.get("license")
        license_counter[("gbif_kanagawa_occurrences", _license_repr(raw_license))] += 1
        rec_license, license_class, commercial_ok = classify_license(raw_license)
        batch.append((
            f"gbif_kanagawa_occurrences__{r['key']}", None, None,
            obs_on, sci, r.get("vernacularName"),
            r.get("taxonRank"), r.get("kingdom"), r.get("phylum"), r.get("class"), r.get("order"),
            r.get("family"), r.get("genus"), str(r.get("taxonKey")) if r.get("taxonKey") is not None else None,
            r.get("individualCount"), None, None,
            r.get("basisOfRecord"), r.get("identifiedBy"), None, None,
            r.get("decimalLatitude"), r.get("decimalLongitude"), r.get("coordinateUncertaintyInMeters"),
            rl, is_alien, "公開済", pub_scope,
            "gbif_kanagawa_occurrences", r.get("occurrenceID") or str(r.get("key")), 0,
            rec_license, license_class, commercial_ok,
        ))
        if len(batch) >= 20000:
            conn.executemany(INSERT_SQL, batch); conn.commit(); batch = []
    if batch:
        conn.executemany(INSERT_SQL, batch); conn.commit()
    if n == 0:
        print("  gbif_kanagawa_occurrences: 0 rows (別エージェントの収集が未完了/未着手のためスキップ。"
              "再実行すれば取り込まれる)")
    else:
        print(f"  gbif_kanagawa_occurrences: {n} rows read, taxa一致 {n_matched} 件 -> organism_records へ INSERT/UPDATE(license)")
    return n

def main():
    conn = appdb()
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA journal_mode=WAL")

    taxa = taxa_lookup(conn)
    print(f"  taxa lookup entries: {len(taxa)}")

    license_counter = collections.Counter()
    n_inat = load_inaturalist(conn, taxa, license_counter)
    n_gbif = load_gbif(conn, taxa, license_counter)
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
