#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""神奈川県レッドリストの「版付き評価テーブル」redlist_assessments を構築する。

## なぜ taxa に統合しないのか（docs/nextstep.md B-3 の判断）

`taxa` テーブルは**学名（小文字化）を主キー**にしている。一方、神奈川県
レッドデータブック2022 植物編の一覧表（`data/processed/kanagawa_redlist_plants_2022.csv`、
1,033行）は **1,033行すべてで scientific_name が空欄**である。原資料（PDF p.10-39）に
学名（ラテン語二名法）の記載が一切なく、和名と科名等しか載っていないためで、
`cells.sqlite` の注記 `n_rdb2022_plants_002` に原文が記録されている。
したがって **学名キーでの taxa 統合は構造的に不可能**である。

和名での結合も機械的には成立しない。たとえば菌類では同一種が
2020年版「和名なし〈オルフェラ・ハイシイ〉」／2022年版「オルフェラ・ハイシイ*」
のように表記が異なり、単純一致では大量に取りこぼす。P6（docs/SKILL.md）の
「推測で埋めない」に抵触するため、機械的な和名結合は行わない。

さらに、統合しても実利がない。`organism_records` へのレッドリストカテゴリー付与
（`m03_organisms.py`）は学名結合で行われるため、学名を持たない2022年版を統合しても
出現記録側（FR-4.5 の希少種座標一般化）には一切効かない。

## 代わりに何をするか

`taxa` を一切変更せず、**版を列に持つ別テーブル**として2020年版・2022年版を併存させる。
どちらが「正」かを機械が決めないまま、版間比較を SQL で行えるようにするのが目的。
supersede 思想（旧版を消さずに残し監査可能にする）とも整合する。

  redlist_assessments
    - list_name / list_year で版を区別
    - scientific_name は2022年版では NULL のまま（原資料に無いため補完しない）
    - taxon_id（taxa への対応）は機械結合しないため既定 NULL。
      人手で和名→学名の対照が承認された行だけ後から埋める運用にする

## 実測した版間差分（維管束植物、和名ベース）

  2020年版 807種 / 2022年版 809種 / 共通 806種
    2022年版で追加: サワトラノオ、トダスゲ、ユクノキ（3種）
    2022年版で削除: アオナリヒラ（1種）
    807 - 1 + 3 = 809 で整合する。
  共通種でもカテゴリー変更が実在する（例: アカウキクサ 2020「絶滅危惧ⅠA類（CR）」→ 2022「絶滅」）。

冪等。assessment_id を主キーに INSERT ... ON CONFLICT DO UPDATE する。
"""
import sys, pathlib, csv, sqlite3

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import appdb, PROC

DDL = """
CREATE TABLE IF NOT EXISTS redlist_assessments (
  assessment_id        TEXT PRIMARY KEY,
  list_name            TEXT NOT NULL,   -- 版の名称
  list_year            INTEGER NOT NULL,
  taxon_group_ja       TEXT,
  taxon_subgroup_ja    TEXT,
  family_ja            TEXT,
  vernacular_name_ja   TEXT,
  scientific_name      TEXT,            -- 2022年版は原資料に記載なし -> NULL のまま（補完禁止）
  category_code        TEXT,            -- 英字コード(EX/CR/EN/VU/NT/DD等)。2022年版は原資料に無くNULL
  category_ja          TEXT,            -- 原文のカテゴリー名をそのまま
  category_prev_ja     TEXT,            -- その版が併記する「前回」カテゴリー
  national_category_ja TEXT,
  note_ja              TEXT,
  taxon_id             TEXT,            -- taxa への対応。機械結合しないため既定NULL
  source_id            TEXT,
  source_ref           TEXT
);
CREATE INDEX IF NOT EXISTS idx_rla_year   ON redlist_assessments(list_year);
CREATE INDEX IF NOT EXISTS idx_rla_vname  ON redlist_assessments(vernacular_name_ja);
CREATE INDEX IF NOT EXISTS idx_rla_group  ON redlist_assessments(taxon_group_ja);
"""

UPSERT = """INSERT INTO redlist_assessments
  (assessment_id, list_name, list_year, taxon_group_ja, taxon_subgroup_ja, family_ja,
   vernacular_name_ja, scientific_name, category_code, category_ja, category_prev_ja,
   national_category_ja, note_ja, taxon_id, source_id, source_ref)
  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
  ON CONFLICT(assessment_id) DO UPDATE SET
    category_code=excluded.category_code,
    category_ja=excluded.category_ja,
    category_prev_ja=excluded.category_prev_ja,
    national_category_ja=excluded.national_category_ja,
    note_ja=excluded.note_ja"""


def blank_to_none(v):
    v = (v or "").strip()
    return v or None


# CSV の source_id 列に入っている値と source_registry の登録名の対応。
# kanagawa_redlist_plants_2022.csv は source_id 列に PDF の doc_id
# ("kanagawa_rdb2022_plants_outline"、cells.sqlite の documents.doc_id と同じ) を
# 入れているが、source_registry 側の登録名は "kanagawa_rdb2022_plants" である。
# GBIF で起きたのと同種の source_id 孤児を新たに作らないよう、ここで台帳の登録名に
# 正規化する（元の doc_id は source_ref のURLから辿れるので情報は失われない）。
SOURCE_ID_TO_REGISTRY = {
    "kanagawa_rdb2022_plants_outline": "kanagawa_rdb2022_plants",
}


def registry_source_id(v):
    return SOURCE_ID_TO_REGISTRY.get(v, v)


def load_2020(conn):
    """kanagawa_redlist.csv（2020年版植物編 1,031行 + 2026年版昆虫 820行）"""
    path = PROC / "kanagawa_redlist.csv"
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    batch = []
    for i, r in enumerate(rows, 1):
        year = int(r["list_year"])
        name = "神奈川県レッドリスト2020（植物編CSV）" if year == 2020 else \
               "神奈川県レッドリスト2026（昆虫類・クモ類）"
        batch.append((
            f"rl{year}_{i:05d}", name, year,
            blank_to_none(r.get("taxon_group_ja")), blank_to_none(r.get("taxon_subgroup_ja")),
            blank_to_none(r.get("family_ja")), blank_to_none(r.get("vernacular_name_ja")),
            blank_to_none(r.get("scientific_name")), blank_to_none(r.get("category_code")),
            blank_to_none(r.get("category_ja")), blank_to_none(r.get("category_prev_ja")),
            blank_to_none(r.get("national_category_ja")), blank_to_none(r.get("note_ja")),
            None,  # taxon_id: 機械結合しない
            registry_source_id(r.get("source_id")), r.get("source_ref"),
        ))
    conn.executemany(UPSERT, batch)
    conn.commit()
    print(f"  kanagawa_redlist.csv: {len(batch)} 行を redlist_assessments へ")
    return len(batch)


def load_2022(conn):
    """kanagawa_redlist_plants_2022.csv（RDB2022 植物編 1,033行。学名は全件空欄）"""
    path = PROC / "kanagawa_redlist_plants_2022.csv"
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    batch = []
    n_blank_sci = 0
    for i, r in enumerate(rows, 1):
        sci = blank_to_none(r.get("scientific_name"))
        if sci is None:
            n_blank_sci += 1
        batch.append((
            f"rdb2022p_{i:05d}", "神奈川県レッドデータブック2022（植物編）", 2022,
            blank_to_none(r.get("taxon_group_ja")), None,
            blank_to_none(r.get("family_ja")), blank_to_none(r.get("vernacular_name_ja")),
            sci, blank_to_none(r.get("category_code")),
            blank_to_none(r.get("category_ja")), blank_to_none(r.get("category_prev_ja")),
            blank_to_none(r.get("national_category_ja")), blank_to_none(r.get("note_ja")),
            None,
            registry_source_id(r.get("source_id")), r.get("source_ref"),
        ))
    conn.executemany(UPSERT, batch)
    conn.commit()
    print(f"  kanagawa_redlist_plants_2022.csv: {len(batch)} 行を redlist_assessments へ"
          f"（うち scientific_name 空欄 {n_blank_sci} 件＝原資料に学名の記載なし。補完していない）")
    return len(batch)


def report_diff(conn):
    """維管束植物の版間差分を和名ベースで実測して表示する（統合はしない）"""
    def names(year, list_like):
        return {r[0] for r in conn.execute(
            "select vernacular_name_ja from redlist_assessments "
            "where list_year=? and taxon_group_ja like '%維管束%' and vernacular_name_ja is not null",
            (year,))}
    n2020, n2022 = names(2020, None), names(2022, None)
    print("\n  -- 維管束植物 版間差分（和名ベース。機械的な名寄せはしていない） --")
    print(f"     2020年版 {len(n2020)}種 / 2022年版 {len(n2022)}種 / 共通 {len(n2020 & n2022)}種")
    print(f"     2022年版で追加: {sorted(n2022 - n2020)}")
    print(f"     2020年版で削除: {sorted(n2020 - n2022)}")
    # カテゴリーが変わった共通種。
    # 表記の揺れ（全角ローマ数字Ⅰ/Ⅱ U+2160,U+2161 と ラテン文字 I/II、丸括弧の全半角）は
    # 「カテゴリーの変更」ではないので、比較時のみ正規化して切り分ける。
    # ※ これは差分レポート用の表示正規化であり、DBの値は原文のまま保存している。
    def norm_cat(v):
        if v is None:
            return None
        for a, b in (("Ⅰ", "I"), ("Ⅱ", "II"), ("Ⅲ", "III"), ("（", "("), ("）", ")")):
            v = v.replace(a, b)
        return v.strip()

    pairs = conn.execute("""
        select a.vernacular_name_ja, a.category_ja, b.category_ja
        from redlist_assessments a join redlist_assessments b
          on a.vernacular_name_ja = b.vernacular_name_ja
        where a.list_year=2020 and b.list_year=2022
          and a.taxon_group_ja like '%維管束%' and b.taxon_group_ja like '%維管束%'
        order by 1""").fetchall()
    raw_diff = [r for r in pairs if r[1] != r[2]]
    real_diff = [r for r in pairs if norm_cat(r[1]) != norm_cat(r[2])]
    print(f"     カテゴリー文字列が異なる共通種: {len(raw_diff)}件")
    print(f"       うち表記揺れのみ（Ⅰ/I・全半角括弧の違い）: {len(raw_diff) - len(real_diff)}件")
    print(f"       うち実質的なカテゴリー変更: {len(real_diff)}件")
    for r in real_diff[:15]:
        print(f"         {r[0]}: 2020「{r[1]}」-> 2022「{r[2]}」")
    if len(real_diff) > 15:
        print(f"         ...他 {len(real_diff) - 15} 件")
    print("     ※ 2020年版はコード併記（例「絶滅危惧ⅠA類（CR）」）、2022年版はコード無しのため、"
          "コードの有無自体も差として現れる。上の分類は文字正規化のみによる機械的な切り分けであり、"
          "最終的な「評価が変わったか」の判定には原資料の確認が必要。")


def main():
    conn = appdb()
    conn.executescript(DDL)
    print("redlist_assessments を構築（taxa は変更しない）:")
    n1 = load_2020(conn)
    n2 = load_2022(conn)
    total = conn.execute("select count(*) from redlist_assessments").fetchone()[0]
    print(f"\n  redlist_assessments 合計: {total} 行")
    for r in conn.execute("select list_name, list_year, count(*) from redlist_assessments "
                          "group by 1,2 order by 2"):
        print(f"    [{r[1]}] {r[0]}: {r[2]} 行")
    report_diff(conn)
    print("\n  taxa テーブルは無改変（統合・上書きはしていない）。"
          "taxa.redlist_kanagawa は引き続き2020年版CSV基準である。")
    conn.close()


if __name__ == "__main__":
    main()
