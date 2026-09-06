"""CKAN環境1440件のうちPDFのみで残っていた重要データセットを構造化する。
優先1: 温室効果ガス排出量 / 地球温暖化対策計画進捗
優先2: 野生鳥獣による農作物被害状況 + 傷病鳥獣救護実績

data/db/cells.sqlite の documents テーブルへ登録する。
別エージェントも同DBへ書き込むため、timeout=60 + busy_timeout=60000 を必ず設定し、
DELETE/DROPは行わずINSERT OR IGNOREのみ行う。
"""
import sys, re, sqlite3, pathlib
sys.path.insert(0, "scripts")
import pdfplumber
from common import DB, ROOT, RAW, download, sha256, now, to_fiscal_year, register

LICENSE_CCBY = "クリエイティブ・コモンズ-表示(CC-BY)"

# ---- 優先1: 温室効果ガス ----
GHG_DIR = RAW / "ckan_pdf/ghg_kanagawa"
GHG_DOCS = [
    dict(doc_id="ghg_kencho_jikkou_suii_2015",
         title="神奈川県事務事業温室効果ガス排出抑制計画における温室効果ガス排出量の推移（H20〜H27）",
         publisher="神奈川県 環境農政局",
         url="https://www.pref.kanagawa.jp/documents/33148/3102274.pdf",
         local_path=GHG_DIR / "ghg_suii_3102274.pdf", fiscal_year=2015),
    dict(doc_id="ghg_kencho_jissai_2022",
         title="神奈川県庁が自ら排出した温室効果ガス量（令和4年度）",
         publisher="神奈川県 環境農政局",
         url="https://catalog.opendata.pref.kanagawa.jp/dataset/38697849-5f80-4ec4-a02e-d84eb99dad49/resource/532f1c59-941e-4872-a87a-192d4bec1ba5/download/r4ghg.pdf",
         local_path=GHG_DIR / "r4ghg.pdf", fiscal_year=2022),
    dict(doc_id="ghg_kennai_suikei_2021",
         title="2021年度県内の温室効果ガス排出量（速報値）推計結果",
         publisher="神奈川県 環境農政局 温暖化対策課",
         url="https://catalog.opendata.pref.kanagawa.jp/dataset/73bcbaf9-8f49-4e67-adc0-bceb7b2ecf50/resource/e88a181f-9db1-4f08-9601-4e683434a7dc/download/2021.pdf",
         local_path=GHG_DIR / "2021.pdf", fiscal_year=2021),
    dict(doc_id="ghg_kennai_suikei_2023",
         title="2023年度県内の温室効果ガス排出量（速報値）推計結果",
         publisher="神奈川県 環境農政局 温暖化対策課",
         url="https://www.pref.kanagawa.jp/documents/9881/2023bessi.pdf",
         local_path=GHG_DIR / "2023bessi.pdf", fiscal_year=2023),
    dict(doc_id="ghg_sankou_shiryou_2024",
         title="（参考）温室効果ガス排出量等の現状と今後の道筋",
         publisher="神奈川県 環境農政局",
         url="https://www.pref.kanagawa.jp/documents/117257/sankousiryou.pdf",
         local_path=GHG_DIR / "sankousiryou.pdf", fiscal_year=None),
    dict(doc_id="ghg_taisaku_keikaku_shinchoku_2024",
         title="神奈川県地球温暖化対策計画の進捗状況について（2024年度実績）",
         publisher="神奈川県 環境農政局",
         url="https://www.pref.kanagawa.jp/documents/117257/ontaikeikaku_sintyokutenken2024.pdf",
         local_path=GHG_DIR / "ontaikeikaku_sintyokutenken2024.pdf", fiscal_year=2024),
    dict(doc_id="ghg_kencho_yokusei_jikkou_keikaku",
         title="神奈川県庁温室効果ガス抑制実行計画",
         publisher="神奈川県 環境農政局",
         url="https://www.pref.kanagawa.jp/documents/33148/3102271.pdf",
         local_path=GHG_DIR / "kentyou_jikkoukeikaku_3102271.pdf", fiscal_year=None),
    dict(doc_id="ghg_jimujigyou_yokusei_keikaku",
         title="神奈川県事務事業温室効果ガス排出抑制計画",
         publisher="神奈川県 環境農政局",
         url="https://www.pref.kanagawa.jp/documents/33148/3102273.pdf",
         local_path=GHG_DIR / "jimujigyou_yokusei_3102273.pdf", fiscal_year=None),
]

# ---- 優先2a: 野生鳥獣による農作物被害状況 ----
HIGAI_DIR = RAW / "ckan_pdf/choju_higai"
HIGAI_KIND = [
    ("gaiyou", re.compile(r"農業被害の概況について")),
    ("shichoson_sakumotsu", re.compile(r"市町村ー作物種類別")),
    ("choju_sakumotsu", re.compile(r"鳥獣別ー作物種類別")),
    ("shichoson_choju", re.compile(r"市町村ー鳥獣別")),
]
HIGAI_RESOURCES = [
    ("令和4年度 - 令和4年度野生鳥獣による農業被害の概況について", "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8/resource/8a1dfbaa-973b-468d-b98a-94c1ea316ba8/download/tyoujuhigai_gaiyou.pdf"),
    ("令和4年度 - 市町村ー作物種類別の被害状況", "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8/resource/6f59281b-eda0-4bbf-b98b-24804b74ca1a/download/sityouson_sakumotsu.pdf"),
    ("令和4年度 - 鳥獣別ー作物種類別の被害状況", "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8/resource/c28e84ab-1146-44fe-bb02-d1f31cdb9e4c/download/tyouju_sakumotsu.pdf"),
    ("令和4年度 - 市町村ー鳥獣別の被害状況", "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8/resource/16e38133-a69f-4d9c-abe7-c2ec9f447a48/download/sityouson_tyouju.pdf"),
    ("令和3年度 - 令和3年度野生鳥獣による農業被害の概況について", "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8/resource/0e6e6a37-62f5-4a11-89c7-f50979d36ca0/download/higai_gaikyou.pdf"),
    ("令和3年度 - 市町村ー作物種類別の被害状況", "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8/resource/b40fc183-8ffa-474b-b562-d98e18485fb3/download/city_sakumotusyu.pdf"),
    ("令和3年度 - 鳥獣別ー作物種類別の被害状況", "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8/resource/f946ff5b-9bac-4fcc-8f3d-26d23d5634fe/download/tyoujyu_sakumotusyu.pdf"),
    ("令和3年度 - 市町村ー鳥獣別の被害状況", "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8/resource/78eb7a87-e34c-4373-9f23-30b053e26802/download/city_tyoujyu.pdf"),
    ("令和2年度 - 令和2年度野生鳥獣による農業被害の概況について", "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8/resource/52b65705-e359-4436-bc33-b4e7325193b2/download/r2_gaikyo.pdf"),
    ("令和2年度 - 市町村ー作物種類別の被害状況", "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8/resource/43c0a6bd-235b-46ab-ad3f-a92e132797b9/download/p13-14.pdf"),
    ("令和2年度 - 鳥獣別ー作物種類別の被害状況", "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8/resource/050de8a1-0c3c-4d80-83d2-ae6af7c1d088/download/p15-16.pdf"),
    ("令和2年度 - 市町村ー鳥獣別の被害状況", "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8/resource/aafd3fb1-9b17-411a-b725-7eceaf80ea0d/download/sityouson_tyoujyu.pdf"),
    ("令和元年度 - 令和元年度野生鳥獣による農業被害の概況について", "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8/resource/7cc1ca96-04cd-42cc-9311-8d33d5ba5ba5/download/higaigaiyou.pdf"),
    ("令和元年度 - 市町村ー作物種類別の被害状況", "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8/resource/c0e83d8c-b5f0-48af-a7ec-e252923f38a1/download/p9_10.pdf"),
    ("令和元年度 - 鳥獣別ー作物種類別の被害状況", "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8/resource/093ef075-3512-4f3e-8172-35e0581e8a77/download/p11.pdf"),
    ("令和元年度 - 市町村ー鳥獣別の被害状況", "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8/resource/8cc3e531-7e77-4de3-8733-e6f67fdf93cf/download/p3.pdf"),
    ("平成30年度 - 平成30年度野生鳥獣による農業被害の概況について", "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8/resource/a1aeaaf8-0364-48a1-9d5e-b1d0fe481ad7/download/h30higaigaiyou.pdf"),
    ("平成30年度 - 市町村ー作物種類別の被害状況", "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8/resource/b4ed84cd-7d19-408c-8258-8756948cd100/download/9-10shichousonn-sakumotushu.pdf"),
    ("平成30年度 - 鳥獣別ー作物種類別の被害状況", "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8/resource/c50c6d73-3879-4414-bef8-2bfb54c0b797/download/11choujyuushu-sakumotushu.pdf"),
    ("平成30年度 - 市町村ー鳥獣別の被害状況", "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8/resource/73285944-4c4e-4e26-988b-081ec075e886/download/3shichouson-choujuu.pdf"),
]

# ---- 優先2b: 傷病鳥獣救護実績 ----
KYUGO_DIR = RAW / "ckan_pdf/choju_kyugo"
KYUGO_RESOURCES = [
    ("野生動物救護実績_令和4年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/20bc60d8-3ff1-4db2-af5c-f3434053c095/download/r4jisseki.pdf"),
    ("野生動物救護実績_令和3年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/ca2d0b31-9d63-49d2-aacf-6e1a3a428522/download/jisekir3.pdf"),
    ("野生動物救護実績_令和2年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/03ccba67-835d-4b80-81ff-a635bf0959ad/download/zisseki2.pdf"),
    ("野生動物救護実績_令和元年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/07e15b5a-f9d7-4ef9-913e-98270651c2fd/download/zisseki.pdf"),
    ("野生動物救護実績_平成30年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/65cf8f9c-8066-4fd6-9332-ed47d89bfa76/download/h30jiseki.pdf"),
    ("野生動物救護実績_平成29年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/f38e90dd-06b3-41a0-a7e8-b9ed84bfb80e/download/13456478465.pdf"),
    ("野生動物救護実績_平成28年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/0fb9228c-9383-40e4-b616-4539c14c6a92/download/28jisseki.pdf"),
    ("野生動物救護実績_平成27年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/d41b12ba-8301-44bd-a1bc-8974c4c03292/download/27jisseki.pdf"),
    ("野生動物救護実績_平成26年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/24aa2ee3-2434-41e9-b17a-f2674a9a8899/download/26jisseki.pdf"),
    ("野生動物救護実績_平成25年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/d8b0241b-3736-4c77-8c27-ac2b05cabcb1/download/25jisseki.pdf"),
    ("野生動物救護実績_平成24年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/a50cb441-01b2-46ae-a3db-8290d1cb71fd/download/24jisseki.pdf"),
    ("野生動物救護実績_平成23年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/b9bb2005-0ba2-422b-856b-8cc71b28f1a1/download/23jisseki.pdf"),
    ("野生動物救護実績_平成22年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/d042e052-7e8d-4fe8-b670-ba2f698ec27c/download/22jisseki.pdf"),
    ("救護された鳥獣の種類と件数_令和4年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/7e9a29e3-da38-4637-a247-32cb033350ec/download/r4syurui.pdf"),
    ("救護された鳥獣の種類と件数_令和3年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/975e1f0f-1929-4e30-a00c-ca8706bc5dd2/download/kensur3.pdf"),
    ("救護された鳥獣の種類と件数_令和2年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/019a3664-d16d-45be-aff2-fca40fd64cfc/download/20210331syuruitokensuu.pdf"),
    ("救護された鳥獣の種類と件数_令和元年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/e651e212-b9c4-4ad4-8bd1-f107d28b2ca7/download/syurui_1.pdf"),
    ("救護された鳥獣の種類と件数_平成30年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/ec6dca51-70a6-4385-a42d-eadfb8888260/download/h30shurui_kensuu.pdf"),
    ("救護された鳥獣の種類と件数_平成29年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/bac26937-8676-4831-aeab-99555b14dc07/download/4351248645312.pdf"),
    ("救護された鳥獣の種類と件数_平成28年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/d537a6b0-c0a5-42f0-af73-34b41e557194/download/28syurui.pdf"),
    ("救護された鳥獣の種類と件数_平成27年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/95f2cf20-24bb-442d-8689-83ce507fe48f/download/27syurui.pdf"),
    ("救護された鳥獣の種類と件数_平成26年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/a019527e-e2a7-474a-951c-63aedfffec54/download/26syurui.pdf"),
    ("救護された鳥獣の種類と件数_平成25年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/838612ef-9f08-40a1-ba44-a2f0788a4958/download/25syurui.pdf"),
    ("救護された鳥獣の種類と件数_平成24年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/442a285d-8950-4692-8bdf-2a0402d0f0d9/download/24syurui.pdf"),
    ("救護された鳥獣の種類と件数_平成23年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/9092bca2-fa55-4f44-afe0-f0a4743f0d10/download/23syurui.pdf"),
    ("救護された鳥獣の種類と件数_平成22年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/5dda0ff3-78ca-4f14-9a54-3d08aee1316f/download/22syurui.pdf"),
    ("種別救護状況一覧_令和4年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/eb62534b-d7da-4c06-a1bc-4d6ff953cd53/download/r4ichiran.pdf"),
    ("種別救護状況一覧_令和3年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/9d04b9bc-88a6-4be3-8e55-7d29159eae09/download/syubetur3.pdf"),
    ("種別救護状況一覧_令和2年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/91a9f096-8e5f-4d44-a444-a79b0b9ea2df/download/20210331kyuugozyoukyouichiran.pdf"),
    ("種別救護状況一覧_令和元年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/31b1ac3a-54f2-4590-9d0c-909596b3a579/download/ichiran.pdf"),
    ("種別救護状況一覧_平成30年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/0c2731d0-42c6-4521-8b25-bc7ae16032c6/download/h30shubetu_itiran.pdf"),
    ("種別救護状況一覧_平成29年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/7bdf2650-7861-40c9-8c96-dbfc85a3b7eb/download/h29jyoukyou_itiran.pdf"),
    ("種別救護状況一覧_平成28年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/507353e9-aa97-4adc-9c08-7bf53961aea6/download/28syubetu.pdf"),
    ("種別救護状況一覧_平成27年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/a5ff07c5-0bd9-4a30-ac90-2e1c4fc31ab3/download/27syubetu.pdf"),
    ("種別救護状況一覧_平成26年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/1ed5c3d0-8ad6-4d57-931e-d1d9c1742fcf/download/26syubetu.pdf"),
    ("種別救護状況一覧_平成25年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/99fd65c1-1362-4116-b8df-2b1557325c03/download/25syubetu.pdf"),
    ("種別救護状況一覧_平成24年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/ba36917b-af25-4beb-ac30-cfb92ee2b66e/download/24syubetu.pdf"),
    ("種別救護状況一覧_平成23年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/58676e6c-f0ae-4a2e-a3f7-01889ce043d8/download/23syubetu.pdf"),
    ("種別救護状況一覧_平成22年度.", "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806/resource/4484b9d3-4765-4767-a2a1-1e71c00e3ff3/download/22syubetu.pdf"),
]

KYUGO_KIND = [
    ("jisseki", re.compile(r"^野生動物救護実績_")),
    ("shurui", re.compile(r"^救護された鳥獣の種類と件数_")),
    ("shubetsu", re.compile(r"^種別救護状況一覧_")),
]


def build_higai_docs():
    docs = []
    for name, url in HIGAI_RESOURCES:
        fy = to_fiscal_year(name.split(" - ")[0])
        kind = next((k for k, pat in HIGAI_KIND if pat.search(name)), None)
        assert kind, name
        fn = url.rsplit("/", 1)[-1]
        docs.append(dict(
            doc_id=f"choju_higai_{kind}_{fy}",
            title=f"{name.split(' - ',1)[-1]}（{fy}年度）",
            publisher="神奈川県 環境農政局 緑政部 自然環境保全課",
            url=url, local_path=HIGAI_DIR / fn, fiscal_year=fy,
        ))
    return docs


def build_kyugo_docs():
    docs = []
    for name, url in KYUGO_RESOURCES:
        era = name.split("_", 1)[-1].rstrip("．.")
        fy = to_fiscal_year(era)
        kind = next((k for k, pat in KYUGO_KIND if pat.search(name)), None)
        assert kind, name
        fn = url.rsplit("/", 1)[-1]
        docs.append(dict(
            doc_id=f"choju_kyugo_{kind}_{fy}",
            title=f"{name}",
            publisher="神奈川県 自然環境保全センター",
            url=url, local_path=KYUGO_DIR / fn, fiscal_year=fy,
        ))
    return docs


def register_documents(docs, license_=LICENSE_CCBY):
    con = sqlite3.connect(DB / "cells.sqlite", timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()
    n_ok, n_fail = 0, []
    for d in docs:
        try:
            download(d["url"], d["local_path"])
        except Exception as e:
            print(f"  [FAIL download] {d['doc_id']}: {e}")
            n_fail.append((d["doc_id"], str(e)))
            continue
        h = sha256(d["local_path"])
        try:
            with pdfplumber.open(str(d["local_path"])) as pdf:
                n_pages = len(pdf.pages)
        except Exception as e:
            print(f"  [FAIL open] {d['doc_id']}: {e}")
            n_fail.append((d["doc_id"], str(e)))
            continue
        rel_path = str(d["local_path"].relative_to(ROOT))
        cur.execute(
            """INSERT OR IGNORE INTO documents
            (doc_id, title, publisher, url, local_path, doc_sha256, n_pages,
             fiscal_year, license, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (d["doc_id"], d["title"], d["publisher"], d["url"], rel_path, h,
             n_pages, d["fiscal_year"], license_, now()),
        )
        con.commit()
        n_ok += 1
        print(f"  [doc] {d['doc_id']} pages={n_pages} sha256={h[:10]}...")
    con.close()
    return n_ok, n_fail


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", choices=["ghg", "higai", "kyugo", "all"], default="all")
    args = ap.parse_args()

    all_ok, all_fail = 0, []
    if args.group in ("ghg", "all"):
        ok, fail = register_documents(GHG_DOCS)
        all_ok += ok; all_fail += fail
    if args.group in ("higai", "all"):
        ok, fail = register_documents(build_higai_docs())
        all_ok += ok; all_fail += fail
    if args.group in ("kyugo", "all"):
        ok, fail = register_documents(build_kyugo_docs())
        all_ok += ok; all_fail += fail
    print(f"\nTOTAL registered={all_ok} failed={len(all_fail)}")
    for doc_id, err in all_fail:
        print(f"  FAIL {doc_id}: {err}")
