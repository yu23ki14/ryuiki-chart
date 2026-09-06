"""アプリDBの検証 + docs/DATA_INVENTORY.md の生成。

- テーブルごとの行数、is_synthetic の内訳
- sites の流域別・zone別 地点数
- measurements / sensor_timeseries の変数別行数と期間
- organism_records の種数・科数・年別件数
- 外部キーの孤児（存在しないsite_idを参照しているevent/measurement等）の件数
- 神奈川県バウンディングボックス外のレコード数
"""
import sys, pathlib, datetime
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import appdb, ROOT

BBOX = (138.9, 35.1, 139.8, 35.7)  # lon_min, lat_min, lon_max, lat_max

def q(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()

def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if v is None else str(v) for v in r) + " |")
    return "\n".join(out)

def main():
    conn = appdb()
    conn.execute("PRAGMA busy_timeout=30000")
    lines = []
    lines.append("# データ整備状況（DATA_INVENTORY）")
    lines.append("")
    lines.append(f"生成日時: {datetime.datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("担当範囲: 収集済み公開データ -> アプリデータモデル（`data/db/ryuiki.sqlite`）へのマッピング。")
    lines.append("`zone` は操作的定義であり公式区分ではない（詳細は `docs/ZONE_DEFINITION.md`）。")
    lines.append("")

    # ---- 1) テーブル行数 / is_synthetic内訳 ----
    lines.append("## 1. テーブルごとの行数")
    tables = [r[0] for r in q(conn, "select name from sqlite_master where type='table' and name != 'sqlite_sequence'")]
    rows = []
    for t in tables:
        n = q(conn, f"select count(*) from {t}")[0][0]
        has_syn = q(conn, f"pragma table_info({t})")
        col_names = [c[1] for c in has_syn]
        if "is_synthetic" in col_names and n > 0:
            syn = dict(q(conn, f"select is_synthetic, count(*) from {t} group by is_synthetic"))
            syn_str = ", ".join(f"is_synthetic={k}: {v}" for k, v in sorted(syn.items(), key=lambda x: (x[0] is None, x[0])))
        else:
            syn_str = "(is_synthetic列なし)" if "is_synthetic" not in col_names else ""
        rows.append((t, n, syn_str))
    lines.append(md_table(["table", "rows", "is_synthetic内訳"], rows))
    lines.append("")

    # ---- 2) sites 流域別・zone別 ----
    lines.append("## 2. sites: 流域別 地点数")
    ws_rows = q(conn, """select coalesce(watershed,'(未判定)'), count(*) from sites
                          group by watershed order by count(*) desc limit 50""")
    lines.append(md_table(["watershed_id", "site数"], ws_rows))
    lines.append("")
    lines.append("## 3. sites: zone別 地点数")
    zone_rows = q(conn, """select coalesce(zone, -1) as z, count(*) from sites
                            group by z order by z""")
    zone_rows = [("NULL(標高不明)" if z == -1 else z, n) for z, n in zone_rows]
    lines.append(md_table(["zone", "site数"], zone_rows))
    lines.append("")
    lines.append("## 4. sites: source_id別 地点数")
    src_rows = q(conn, "select source_id, count(*) from sites group by source_id order by count(*) desc")
    lines.append(md_table(["source_id", "site数"], src_rows))
    lines.append("")

    # ---- 5) measurements 変数別・期間 ----
    lines.append("## 5. measurements: 変数別 行数 / 期間")
    if q(conn, "select count(*) from measurements")[0][0] > 0:
        mrows = q(conn, """select variable, count(*), min(measured_on), max(measured_on), quality_stage
                            from measurements group by variable, quality_stage
                            order by count(*) desc""")
        lines.append(md_table(["variable", "行数", "min(measured_on)", "max(measured_on)", "quality_stage"], mrows))
    else:
        lines.append("(measurements 0件)")
    lines.append("")

    # ---- 6) sensor_timeseries 変数別・期間 ----
    lines.append("## 6. sensor_timeseries: datastream別 行数 / 期間")
    if q(conn, "select count(*) from sensor_timeseries")[0][0] > 0:
        trows = q(conn, """select source_id, datastream, count(*), min(phenomenon_time), max(phenomenon_time)
                            from sensor_timeseries group by source_id, datastream
                            order by count(*) desc limit 60""")
        lines.append(md_table(["source_id", "datastream", "行数", "min(phenomenon_time)", "max(phenomenon_time)"], trows))
    else:
        lines.append("(sensor_timeseries 0件)")
    lines.append("")

    # ---- 7) organism_records ----
    lines.append("## 7. organism_records: 種数・科数・年別件数")
    n_org = q(conn, "select count(*) from organism_records")[0][0]
    if n_org > 0:
        n_species = q(conn, "select count(distinct scientific_name) from organism_records where scientific_name is not null")[0][0]
        n_family = q(conn, "select count(distinct family) from organism_records where family is not null")[0][0]
        lines.append(f"- 総レコード数: {n_org}")
        lines.append(f"- 学名のユニーク数（≒種数、rank不問）: {n_species}")
        lines.append(f"- 科(family)のユニーク数: {n_family}")
        lines.append("")
        yrows = q(conn, """select substr(observed_on,1,4) as yr, source_id, count(*) from organism_records
                            where observed_on is not null group by yr, source_id order by yr desc limit 60""")
        lines.append(md_table(["year", "source_id", "件数"], yrows))
        lines.append("")
        rl_rows = q(conn, """select red_list_category, count(*) from organism_records
                              where red_list_category is not null group by red_list_category order by count(*) desc""")
        lines.append("### レッドリストカテゴリ別件数（taxa結合で一致した分のみ）")
        lines.append(md_table(["red_list_category", "件数"], rl_rows))
        lines.append(f"\n- is_alien=1 件数: {q(conn, 'select count(*) from organism_records where is_alien=1')[0][0]}")
        lines.append(f"- publication_scope別: {q(conn, 'select publication_scope, count(*) from organism_records group by publication_scope')}")
    else:
        lines.append("(organism_records 0件)")
    lines.append("")

    # ---- 8) 外部キー孤児チェック ----
    lines.append("## 8. 外部キーの孤児（存在しないsite_id等を参照しているレコード）")
    orphan_checks = [
        ("events.site_id -> sites", "select count(*) from events e where e.site_id is not null and not exists (select 1 from sites s where s.site_id=e.site_id)"),
        ("measurements.site_id -> sites", "select count(*) from measurements m where m.site_id is not null and not exists (select 1 from sites s where s.site_id=m.site_id)"),
        ("measurements.event_id -> events", "select count(*) from measurements m where m.event_id is not null and not exists (select 1 from events e where e.event_id=m.event_id)"),
        ("sensor_timeseries.site_id -> sites", "select count(*) from sensor_timeseries t where t.site_id is not null and not exists (select 1 from sites s where s.site_id=t.site_id)"),
        ("organism_records.site_id -> sites", "select count(*) from organism_records o where o.site_id is not null and not exists (select 1 from sites s where s.site_id=o.site_id)"),
    ]
    orows = []
    for label, sql in orphan_checks:
        try:
            n = q(conn, sql)[0][0]
        except Exception as e:
            n = f"ERROR: {e}"
        orows.append((label, n))
    lines.append(md_table(["参照関係", "孤児件数"], orows))
    lines.append("")
    lines.append("補足: `sensor_timeseries` の `env_kousui`以外のセンサー系（そらまめ君・相模原市大気局）は、"
                 "station master に緯度経度が存在しないため sites テーブルに地点が作られていない。"
                 "そのため上表の sensor_timeseries 孤児件数には、この2ソース分の全行が含まれる"
                 "（データの実際の欠落であり、本スクリプトの不具合ではない。詳細は本ファイル末尾参照）。")
    lines.append("")

    # ---- 9) バウンディングボックス外レコード数 ----
    lines.append("## 9. 神奈川県バウンディングボックス外のレコード数")
    lines.append(f"bbox = lon:[{BBOX[0]},{BBOX[2]}], lat:[{BBOX[1]},{BBOX[3]}]")
    bbox_checks = [
        ("sites", "select count(*) from sites where lat is not null and lon is not null and (lon<? or lon>? or lat<? or lat>?)"),
        ("organism_records", "select count(*) from organism_records where lat is not null and lon is not null and (lon<? or lon>? or lat<? or lat>?)"),
    ]
    brows = []
    for label, sql in bbox_checks:
        n = q(conn, sql, (BBOX[0], BBOX[2], BBOX[1], BBOX[3]))[0][0]
        brows.append((label, n))
    lines.append(md_table(["table", "bbox外件数"], brows))
    lines.append("")

    # ---- 10) 既知の欠落・スコープ外事項 ----
    n_gbif_loaded = q(conn, "select count(*) from organism_records where source_id='gbif_kanagawa_occurrences'")[0][0]
    n_inat_loaded = q(conn, "select count(*) from organism_records where source_id='inaturalist_kanagawa'")[0][0]
    lines.append("## 10. 既知の欠落・スコープ外（意図的に未実施）")
    lines.append(f"""
- **GBIF (`gbif_kanagawa_occurrences.jsonl`)**: 本検証時点で organism_records に {n_gbif_loaded} 件を
  取り込み済み（iNaturalistは {n_inat_loaded} 件）。GBIF収集は2026-08-29の第3ラウンドで完走し
  （`data/logs/gbif_repair_run3.log`）、jsonl は 658,360行・重複0で確定している。同ログの
  最終突合では GBIF側 count=659,399 に対し 1,039件（区画取得不能93件＋日付フィールド欠損による
  分割不能958件）が未取得のまま残っており、区画別の内訳は `data/logs/gbif_partition_report.csv`
  に記録済み。`scripts/m03_organisms.py` は record_id をキーに INSERT ... ON CONFLICT DO UPDATE
  するため冪等であり、再実行しても重複せず既存行のライセンス3列だけが最新化される。""")
    lines.append("""
- **そらまめ君（大気）・相模原市大気局**: station master に緯度経度が一切収録されておらず
  （収集エージェントのコード上のコメントで「そらまめ君の公開CSVに緯度経度は含まれない」と明記）、
  `sites` には登録していない（要求「必ずlat/lonを持つものだけ入れる」に従う）。
  一方で `sensor_timeseries` には両ソースの実測値（そらまめ君168,793行・相模原市大気175,344行）を
  そのままロードしている。そのため `sensor_timeseries.site_id` は `soramame_stations_kanagawa__*` /
  `sagamihara_taiki_stations__*` という形式のIDを持つが、対応する `sites` 行は存在しない
  （＝意図的な孤児。上記セクション8参照）。緯度経度が判明すれば `sites` に追加登録できる設計にしてある。
- **相模原市大気データの単位**: 公開元に単位の記載が無いため `unit=NULL` のまま。推測していない。
- **県民参加型 河川モニタリング調査地点**: 収集済みデータは年度別の集計値（参加人数・捕獲調査地点数
  など5行のみ）であり、地点別の緯度経度・個別測定値は収集されていない。そのため `sites` にも
  `measurements` にも地点単位のレコードは作成していない。
- **moni1000（森林・里地・沿岸の鳥類/蝶類/哺乳類/植生調査など）・biodic植生メッシュ・丹沢関連・
  河川国勢調査など**: `sites`（`moni1000_sites`のみ）を除き、今回のタスク範囲外として
  `measurements`/`organism_records` には取り込んでいない（要求定義で明示された対象ではないため）。
""")

    out_path = ROOT / "docs" / "DATA_INVENTORY.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_path}")

    conn.close()

if __name__ == "__main__":
    main()
