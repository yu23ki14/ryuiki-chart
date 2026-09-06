"""FR-4.1/4.2: organism_records + measurements → Darwin Core Archive (Event core + Occurrence + eMoF)
GBIF/JBIF へそのまま投入できる構造にする。希少種の位置は FR-4.5 に従い粗く丸める。

本版はストリーミング実装（45万件超の organism_records を全件メモリに載せない）。
- event.txt / occurrence.txt / extendedmeasurementorfact.txt は行を読みながらそのまま書き出す。
- eventID の重複排除だけは Python の set で追跡する（フルレコードではなく文字列のみを保持）。
- FR-4.4 (redistributable=0 由来レコードを DwC-A に含めない): source_registry.redistributable=0 の
  source_id を持つ organism_records / measurements 行はスキップする。
  GBIF 収集エージェントが source_registry に登録する source_id は "gbif_kanagawa" だが、
  organism_records.source_id に実際に格納されている値は "gbif_kanagawa_occurrences" であり、
  両者の文字列は一致しない（既知の命名不整合。docs/LICENSE_MATRIX.md 4.5 参照。収集側スクリプト
  c02_gbif.py/c02_gbif_repair.py 自体も "gbif_kanagawa_occurrences" で register するよう修正済みだが、
  修正前のコードで既に起動していたプロセスが後から "gbif_kanagawa" で登録する可能性が残るため、
  本スクリプトでは引き続き GBIF_ALIAS で両方向を吸収する）。
- レコード単位ライセンスフィルタ (本タスクで追加): organism_records.license_class が
  'noncommercial'（CC BY-NC系）または 'unknown'（表示なし・空）の occurrence は、
  既定では DwC-A に含めない（--include-noncommercial で無効化可能）。除外は
  source_registry.redistributable によるソース単位の除外とは独立に、レコード単位で行う。
"""
import sys, csv, json, re, sqlite3, zipfile, pathlib, datetime, argparse
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import DB, ROOT, now

OUT = ROOT/"data/dwca"; OUT.mkdir(parents=True, exist_ok=True)
# DwC-A の zip は展開形と同じ data/dwca/ に置く。
# （以前は配布パッケージ data/dist/ に出力していたが、配布パッケージ自体を廃止したため移した）

GBIF_ALIAS = {"gbif_kanagawa_occurrences": "gbif_kanagawa"}
EXCLUDED_LICENSE_CLASSES_DEFAULT = {"noncommercial", "unknown"}

# --- FR-4.5 希少種の位置の一般化 ---
# 【重要・修正済みバグ】旧実装は red_list_category の原表記全体（例:「絶滅危惧Ⅱ類（VU）」）が
# SENSITIVE 集合の要素（"CR"等の記号単体、または全角ローマ数字を含まない「絶滅危惧II類」等の文字列）
# と "完全一致" するかだけを見ていた。しかし実データのカテゴリ表記は「絶滅危惧ⅠＡ類（CR）」のように
# 全角ローマ数字(Ⅰ/Ⅱ、半角と字形が異なるUnicode文字)＋全角括弧を伴うため、どの実データも完全一致
# せず、n_gen は常に 0 だった（本タスクで実データを流して検証した際に判明）。
# 修正: 末尾の（半角/全角）括弧内のコード（CR/EN/VU/EX/EW/CR+EN）だけを抽出して判定する
# （準絶滅危惧(NT)・情報不足(DD)・絶滅のおそれのある地域個体群(LP)・「注目種」等、元々
# SENSITIVE集合に含まれる意図のなかったカテゴリを誤って拾わないようにするため）。
SENSITIVE_CODES = {"CR", "EN", "VU", "EX", "EW", "CR+EN"}
_CODE_RE = re.compile(r"[（(]([^）)]+)[）)]\s*$")
def is_sensitive(redlist):
    if not redlist: return False
    m = _CODE_RE.search(str(redlist).strip())
    if not m: return False
    return m.group(1).strip() in SENSITIVE_CODES

def generalize(lat, lon, redlist):
    """希少種は約10km(0.1度)グリッドの中心に丸め、不確実性を明示する"""
    if lat is None or lon is None: return None, None, None, 0
    if is_sensitive(redlist):
        return round(round(lat/0.1)*0.1, 4), round(round(lon/0.1)*0.1, 4), 10000, 1
    return lat, lon, None, 0

EVENT_COLS = ["eventID","parentEventID","eventDate","year","month","day","samplingProtocol",
  "sampleSizeValue","sampleSizeUnit","locationID","locality","stateProvince","county",
  "municipality","waterBody","habitat","decimalLatitude","decimalLongitude",
  "geodeticDatum","coordinateUncertaintyInMeters","country","countryCode",
  "minimumElevationInMeters","recordedBy","eventRemarks"]
OCC_COLS = ["occurrenceID","eventID","basisOfRecord","occurrenceStatus","scientificName",
  "acceptedNameUsage","taxonID","taxonRank","kingdom","phylum","class","order","family",
  "genus","specificEpithet","vernacularName","individualCount","organismQuantity",
  "organismQuantityType","identifiedBy","identificationRemarks","identificationVerificationStatus",
  "recordedBy","institutionCode","collectionCode","catalogNumber","license","rightsHolder",
  "informationWithheld","dataGeneralizations","occurrenceRemarks","associatedReferences"]
EMOF_COLS = ["eventID","occurrenceID","measurementID","measurementType","measurementTypeID",
  "measurementValue","measurementUnit","measurementUnitID","measurementAccuracy",
  "measurementDeterminedDate","measurementDeterminedBy","measurementMethod","measurementRemarks"]

META_XML = """<?xml version="1.0" encoding="UTF-8"?>
<archive xmlns="http://rs.tdwg.org/dwc/text/">
  <core encoding="UTF-8" fieldsTerminatedBy="\\t" linesTerminatedBy="\\n" fieldsEnclosedBy=""
        ignoreHeaderLines="1" rowType="http://rs.tdwg.org/dwc/terms/Event">
    <files><location>event.txt</location></files>
    <id index="0"/>
{event_fields}
  </core>
  <extension encoding="UTF-8" fieldsTerminatedBy="\\t" linesTerminatedBy="\\n" fieldsEnclosedBy=""
        ignoreHeaderLines="1" rowType="http://rs.tdwg.org/dwc/terms/Occurrence">
    <files><location>occurrence.txt</location></files>
    <coreid index="1"/>
{occ_fields}
  </extension>
  <extension encoding="UTF-8" fieldsTerminatedBy="\\t" linesTerminatedBy="\\n" fieldsEnclosedBy=""
        ignoreHeaderLines="1"
        rowType="http://rs.iobis.org/obis/terms/ExtendedMeasurementOrFact">
    <files><location>extendedmeasurementorfact.txt</location></files>
    <coreid index="0"/>
{emof_fields}
  </extension>
</archive>
"""
NS = {"measurementID":"http://rs.tdwg.org/dwc/terms/measurementID",
      "measurementType":"http://rs.tdwg.org/dwc/terms/measurementType",
      "measurementTypeID":"http://rs.iobis.org/obis/terms/measurementTypeID",
      "measurementValue":"http://rs.tdwg.org/dwc/terms/measurementValue",
      "measurementValueID":"http://rs.iobis.org/obis/terms/measurementValueID",
      "measurementUnit":"http://rs.tdwg.org/dwc/terms/measurementUnit",
      "measurementUnitID":"http://rs.iobis.org/obis/terms/measurementUnitID"}
def term(c): return NS.get(c, f"http://rs.tdwg.org/dwc/terms/{c}")
def fields(cols, skip):
    return "\n".join(f'    <field index="{i}" term="{term(c)}"/>'
                     for i, c in enumerate(cols) if i not in skip)

EML = """<?xml version="1.0" encoding="UTF-8"?>
<eml:eml xmlns:eml="eml://ecoinformatics.org/eml-2.1.1"
  xmlns:dc="http://purl.org/dc/terms/" packageId="{pkg}" system="ryuiki-demo"
  scope="system" xml:lang="ja">
  <dataset>
    <title xml:lang="ja">流域カルテ デモデータセット — 神奈川県 生物観察・環境測定</title>
    <title xml:lang="en">Watershed Chart Demo Dataset - Kanagawa Biodiversity and Environmental Monitoring</title>
    <creator><organizationName>Code for Japan</organizationName>
      <electronicMailAddress>info@code4japan.org</electronicMailAddress></creator>
    <pubDate>{date}</pubDate>
    <abstract><para xml:lang="ja">神奈川県を対象に、公開データ（GBIF・iNaturalist・環境省・国土交通省・
神奈川県オープンデータ等）を統合し、Darwin Core Event Core + Occurrence + eMoF 形式に
変換したデモデータセット。合成レコードを含む場合は occurrenceRemarks / eventRemarks に
"synthetic" と明記している。研究利用を目的とした実データセットではない。
source_registry.redistributable=0 のソースに由来するレコードは本アーカイブから除外している。
iNaturalist / GBIF の個々のレコードは元データ側で観察・データセット単位のライセンス
（CC0/CC BY/CC BY-NC 等）が個別に異なるため、occurrence.txt の license 列に元の表記
（record_license）をそのまま出力するとともに、既定では license_class が
'noncommercial'（CC BY-NC系）または 'unknown'（表示なし・空）のレコードを本アーカイブから
除外している（{excl_summary}）。除外の詳細は data/dwca/EXCLUDED_LICENSE.md を参照。
--include-noncommercial オプションで除外を無効化することもできるが、その場合は生成物を
商用・公開の用途に用いる前に個別のライセンス条件を確認すること。</para></abstract>
    <intellectualRights><para>occurrence.txt の license 列には、各レコードの元データが持つ
ライセンス表記（record_license）をそのまま格納している（例: CC0, CC BY 4.0, CC BY-NC 4.0 等、
出典によって表記形式が異なる）。本アーカイブ全体としての単一の再配布ライセンスは設定していない
（複数ライセンスが混在する集合物のため）。利用者は occurrence 単位で license 列を参照すること。
</para></intellectualRights>
    <coverage><geographicCoverage>
      <geographicDescription>Kanagawa Prefecture, Japan</geographicDescription>
      <boundingCoordinates>
        <westBoundingCoordinate>138.9</westBoundingCoordinate>
        <eastBoundingCoordinate>139.8</eastBoundingCoordinate>
        <northBoundingCoordinate>35.7</northBoundingCoordinate>
        <southBoundingCoordinate>35.1</southBoundingCoordinate>
      </boundingCoordinates></geographicCoverage></coverage>
  </dataset>
</eml:eml>
"""

TAB_NL_RE = re.compile(r"[\t\r\n]+")
def clean(v):
    if v is None: return ""
    return TAB_NL_RE.sub(" ", str(v))

def load_allowed_sources(conn):
    reg = dict(conn.execute("select source_id, redistributable from source_registry").fetchall())
    allowed = {sid for sid, red in reg.items() if red == 1}
    for alias, real in GBIF_ALIAS.items():
        if reg.get(real) == 1:
            allowed.add(alias)
    return allowed, reg

def rows(conn, sql):
    cur = conn.execute(sql); cols = [d[0] for d in cur.description]
    for r in cur: yield dict(zip(cols, r))

def build(include_noncommercial=False):
    excluded_classes = set() if include_noncommercial else set(EXCLUDED_LICENSE_CLASSES_DEFAULT)

    conn = sqlite3.connect(DB/"ryuiki.sqlite", timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    allowed, reg = load_allowed_sources(conn)
    if "gbif_kanagawa" not in reg and "gbif_kanagawa_occurrences" not in reg:
        print("  !! gbif_kanagawa は source_registry に未登録。gbif_kanagawa_occurrences 由来行は"
              "『未登録=除外扱い』となる。GBIF収集完了後、source_registryへのregister後に再実行すること。")

    stats = {"n_events": 0, "n_occ": 0, "n_emof": 0, "n_gen": 0,
              "n_occ_excluded_source": 0, "n_meas_excluded_source": 0,
              "n_occ_excluded_license_class": 0,
              "n_blank_sciname": 0, "excluded_source_ids": {},
              "excluded_license_class_counts": {},
              "included_license_class_counts": {},
              "include_noncommercial_flag": include_noncommercial}
    written_event_ids = set()

    ev_path, occ_path, emof_path = OUT/"event.txt", OUT/"occurrence.txt", OUT/"extendedmeasurementorfact.txt"
    fev = open(ev_path, "w", encoding="utf-8", newline="")
    focc = open(occ_path, "w", encoding="utf-8", newline="")
    femof = open(emof_path, "w", encoding="utf-8", newline="")
    wev = csv.DictWriter(fev, fieldnames=EVENT_COLS, delimiter="\t", extrasaction="ignore",
                          lineterminator="\n", quoting=csv.QUOTE_NONE, escapechar=None)
    wocc = csv.DictWriter(focc, fieldnames=OCC_COLS, delimiter="\t", extrasaction="ignore",
                           lineterminator="\n", quoting=csv.QUOTE_NONE, escapechar=None)
    wemof = csv.DictWriter(femof, fieldnames=EMOF_COLS, delimiter="\t", extrasaction="ignore",
                            lineterminator="\n", quoting=csv.QUOTE_NONE, escapechar=None)
    wev.writeheader(); wocc.writeheader(); wemof.writeheader()

    def write_event_once(eid, event_dict):
        if eid in written_event_ids:
            return
        written_event_ids.add(eid)
        wev.writerow({k: clean(v) for k, v in event_dict.items()})
        stats["n_events"] += 1

    def excl(source_id):
        stats["excluded_source_ids"][source_id] = stats["excluded_source_ids"].get(source_id, 0) + 1

    # ---- 1) organism_records -> event + occurrence (+ emof for density) ----
    for r in rows(conn, "SELECT * FROM organism_records"):
        sid = r["source_id"]
        if sid is not None and sid not in allowed and not r["is_synthetic"]:
            stats["n_occ_excluded_source"] += 1
            excl(sid)
            continue
        # レコード単位ライセンスフィルタ（source_registry.redistributable とは独立）
        lic_class = r["license_class"] or "unknown"
        if lic_class in excluded_classes:
            stats["n_occ_excluded_license_class"] += 1
            stats["excluded_license_class_counts"][lic_class] = \
                stats["excluded_license_class_counts"].get(lic_class, 0) + 1
            continue
        stats["included_license_class_counts"][lic_class] = \
            stats["included_license_class_counts"].get(lic_class, 0) + 1
        eid = r["event_id"] or f"ev_{r['record_id']}"
        lat, lon, unc, gen = generalize(r["lat"], r["lon"], r["red_list_category"])
        stats["n_gen"] += gen
        d = r["observed_on"] or ""
        write_event_once(eid, {
          "eventID": eid, "parentEventID": r["site_id"] or "",
          "eventDate": d, "year": d[:4], "month": d[5:7], "day": d[8:10],
          "samplingProtocol": "", "sampleSizeValue": "", "sampleSizeUnit": "",
          "locationID": r["site_id"] or "", "locality": "", "stateProvince": "Kanagawa",
          "county": "", "municipality": "", "waterBody": "", "habitat": "",
          "decimalLatitude": lat if lat is not None else "",
          "decimalLongitude": lon if lon is not None else "",
          "geodeticDatum": "WGS84",
          "coordinateUncertaintyInMeters": unc or (r["coordinate_uncertainty_m"] or ""),
          "country": "Japan", "countryCode": "JP", "minimumElevationInMeters": "",
          "recordedBy": "", "eventRemarks": "synthetic" if r["is_synthetic"] else ""})
        sci = r["scientific_name"] or ""
        if not sci.strip():
            stats["n_blank_sciname"] += 1
        wocc.writerow({k: clean(v) for k, v in {
          "occurrenceID": r["record_id"], "eventID": eid,
          "basisOfRecord": r["basis_of_record"] or "HumanObservation",
          "occurrenceStatus": "present",
          "scientificName": sci, "acceptedNameUsage": "",
          "taxonID": r["taxon_key"] or "", "taxonRank": r["taxon_rank"] or "",
          "kingdom": r["kingdom"] or "", "phylum": r["phylum"] or "",
          "class": r["class"] or "", "order": r["order"] or "",
          "family": r["family"] or "", "genus": r["genus"] or "", "specificEpithet": "",
          "vernacularName": r["vernacular_name"] or "",
          "individualCount": r["individual_count"] if r["individual_count"] is not None else "",
          "organismQuantity": r["density"] if r["density"] is not None else "",
          "organismQuantityType": r["density_unit"] or "",
          "identifiedBy": r["identified_by"] or "",
          "identificationRemarks": r["identification_basis"] or "",
          "identificationVerificationStatus": r["quality_stage"] or "",
          "recordedBy": "", "institutionCode": "", "collectionCode": "",
          "catalogNumber": "", "license": r["record_license"] or "", "rightsHolder": "",
          "informationWithheld": "coordinates generalized to 0.1 degree (sensitive taxon)" if gen else "",
          "dataGeneralizations": "rounded to 0.1 degree grid" if gen else "",
          "occurrenceRemarks": "synthetic" if r["is_synthetic"] else "",
          "associatedReferences": r["source_ref"] or ""}.items()})
        stats["n_occ"] += 1
        if r["density"] is not None:
            wemof.writerow({k: clean(v) for k, v in {
              "eventID": eid, "occurrenceID": r["record_id"],
              "measurementID": f"{r['record_id']}_density",
              "measurementType": "個体密度 / population density", "measurementTypeID": "",
              "measurementValue": r["density"], "measurementUnit": r["density_unit"] or "",
              "measurementUnitID": "", "measurementAccuracy": "",
              "measurementDeterminedDate": r["observed_on"] or "",
              "measurementDeterminedBy": r["identified_by"] or "",
              "measurementMethod": "", "measurementRemarks":
                "synthetic" if r["is_synthetic"] else ""}.items()})
            stats["n_emof"] += 1

    # ---- 2) measurements -> event + emof ----
    for r in rows(conn, "SELECT * FROM measurements"):
        sid = r["source_id"]
        if sid is not None and sid not in allowed and not r["is_synthetic"]:
            stats["n_meas_excluded_source"] += 1
            excl(sid)
            continue
        eid = r["event_id"] or f"ev_site_{r['site_id']}_{(r['measured_on'] or '')[:10]}"
        d = r["measured_on"] or ""
        write_event_once(eid, {
          "eventID": eid, "parentEventID": r["site_id"] or "", "eventDate": d,
          "year": d[:4], "month": d[5:7], "day": d[8:10],
          "samplingProtocol": r["method"] or "", "sampleSizeValue": "", "sampleSizeUnit": "",
          "locationID": r["site_id"] or "", "locality": "", "stateProvince": "Kanagawa",
          "county": "", "municipality": "", "waterBody": "", "habitat": "",
          "decimalLatitude": "", "decimalLongitude": "", "geodeticDatum": "WGS84",
          "coordinateUncertaintyInMeters": "", "country": "Japan", "countryCode": "JP",
          "minimumElevationInMeters": "", "recordedBy": "",
          "eventRemarks": "synthetic" if r["is_synthetic"] else ""})
        wemof.writerow({k: clean(v) for k, v in {
          "eventID": eid, "occurrenceID": "",
          "measurementID": r["measurement_id"],
          "measurementType": r["variable"] or "",
          "measurementTypeID": r["variable_en"] or "",
          "measurementValue": r["value"] if r["value"] is not None else (r["value_raw"] or ""),
          "measurementUnit": r["unit"] or "", "measurementUnitID": "",
          "measurementAccuracy": "", "measurementDeterminedDate": r["measured_on"] or "",
          "measurementDeterminedBy": r["verified_by"] or "",
          "measurementMethod": r["method"] or "",
          "measurementRemarks": ("synthetic; " if r["is_synthetic"] else "")
                                + f"quality_stage={r['quality_stage']}"}.items()})
        stats["n_emof"] += 1

    conn.close()
    fev.close(); focc.close(); femof.close()

    if include_noncommercial:
        excl_summary = ("本タスクの --include-noncommercial 指定により、レコード単位ライセンスによる"
                         "noncommercial/unknown の除外は行っていない")
    else:
        excl_summary = (f"レコード単位ライセンスにより noncommercial/unknown を"
                         f"{stats['n_occ_excluded_license_class']}件除外した"
                         f"（内訳: {stats['excluded_license_class_counts']}）")
    (OUT/"meta.xml").write_text(META_XML.format(
        event_fields=fields(EVENT_COLS, {0}),
        occ_fields=fields(OCC_COLS, {1}),
        emof_fields=fields(EMOF_COLS, {0})), encoding="utf-8")
    (OUT/"eml.xml").write_text(EML.format(
        pkg="ryuiki-demo-kanagawa/v1.0",
        date=datetime.date.today().isoformat(),
        excl_summary=excl_summary), encoding="utf-8")

    zp = OUT/"dwca_ryuiki_kanagawa.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in ("meta.xml","eml.xml","event.txt","occurrence.txt",
                  "extendedmeasurementorfact.txt"):
            z.write(OUT/n, n)

    write_excluded_license_md(stats, include_noncommercial)

    print(f"DwC-A: events={stats['n_events']} occurrences={stats['n_occ']} eMoF={stats['n_emof']} "
          f"generalized={stats['n_gen']} blank_scientificName={stats['n_blank_sciname']}\n"
          f"  excluded by source_registry.redistributable=0 / 未登録ソース: "
          f"occurrence={stats['n_occ_excluded_source']} measurement={stats['n_meas_excluded_source']} "
          f"by_source={stats['excluded_source_ids']}\n"
          f"  excluded by record-level license_class (include_noncommercial={include_noncommercial}): "
          f"occurrence={stats['n_occ_excluded_license_class']} "
          f"by_class={stats['excluded_license_class_counts']}\n"
          f"  included occurrence license_class breakdown: {stats['included_license_class_counts']}\n"
          f"  -> {zp}\n"
          f"  -> {OUT/'EXCLUDED_LICENSE.md'}")
    return stats


def write_excluded_license_md(stats, include_noncommercial):
    lines = []
    lines.append("# DwC-A レコード単位ライセンス除外一覧（EXCLUDED_LICENSE）\n")
    lines.append(f"生成日時: {now()}\n")
    lines.append("対象: `data/dwca/occurrence.txt`（organism_records由来）の構築時に、"
                  "レコード単位ライセンス（`organism_records.license_class`）に基づいて"
                  "除外した件数と理由。`source_registry.redistributable=0`によるソース単位の除外は"
                  "別集計（本書では扱わない。除外件数はスクリプト標準出力を参照）。\n")
    lines.append("## 除外基準\n")
    lines.append("- 既定（`--include-noncommercial` 未指定）では、"
                  f"`license_class` が `{'` `'.join(sorted(EXCLUDED_LICENSE_CLASSES_DEFAULT))}` の"
                  "いずれかである occurrence を DwC-A から除外する。\n")
    lines.append("  - `noncommercial`: iNaturalist の `cc-by-nc` 系（cc-by-nc / cc-by-nc-sa / "
                  "cc-by-nc-nd）、GBIF の `CC BY-NC 4.0`。商用利用が明示的に許諾されていない。\n")
    lines.append("  - `unknown`: ライセンス表示なし（元データが `null` または空文字）。表示が"
                  "無いことを「オープン」とは推測せず、安全側に倒して除外する。\n")
    lines.append("- `open`（CC0 / CC BY 系）・`restricted`（CC BY-SA / CC BY-ND。商用利用自体は"
                  "妨げないが Share-Alike・改変禁止等の付帯条件がある）は既定で **含める**。\n")
    lines.append(f"- 本回の実行では `--include-noncommercial` = {include_noncommercial} で実行した。\n")
    lines.append("\n## 今回の実行結果\n")
    lines.append(f"- 除外件数（record-level license）: {stats['n_occ_excluded_license_class']}\n")
    lines.append(f"- 除外内訳（license_class別）: {stats['excluded_license_class_counts']}\n")
    lines.append(f"- 含めた内訳（license_class別）: {stats['included_license_class_counts']}\n")
    lines.append(f"- ソース単位（redistributable=0/未登録）で別途除外した occurrence 件数: "
                 f"{stats['n_occ_excluded_source']}（内訳: {stats['excluded_source_ids']}）\n")
    lines.append("\n## 注意\n")
    lines.append("- この除外はDwC-A出力に対するものであり、マスタDB "
                  "`data/db/ryuiki.sqlite` からは除外していない"
                  "（`license_class`/`commercial_ok`列で識別可能な形で全件保持している。"
                  "第三者に渡す場合は `license_class IN ('open','restricted')` または "
                  "`commercial_ok = 1` で絞り込むこと）。\n")
    lines.append("- `--include-noncommercial` を付けて実行した場合、noncommercial/unknown を"
                  "含む DwC-A が生成される。生成物を実際にGBIF/JBIF等へ公開する場合は、"
                  "必ずデフォルト（除外あり）で生成し直すこと。\n")
    (OUT/"EXCLUDED_LICENSE.md").write_text("".join(lines), encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--include-noncommercial", action="store_true",
                     help="既定ではDwC-Aから除外する license_class='noncommercial'/'unknown'のoccurrenceを含める"
                          "（商用公開前提のGBIF/JBIF提出物には使わないこと）")
    args = ap.parse_args()
    build(include_noncommercial=args.include_noncommercial)
