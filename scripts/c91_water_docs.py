"""水源マップの根拠資料（PDF）を取得して data/water/source_doc.csv を作る。

  .venv/bin/python scripts/c91_water_docs.py

docs/WATER_SOURCE_MAP.md の Phase 1。設計図 §6-1「根拠のないデータは入れない」を満たすため、
flow_edge / zone_assignment が指す資料をここで確定させる。

PDF の実体は data/raw/water/<utility>/ に置く（Git 管理外・2026-09-05 に司令塔決定）。
クローンし直したときに復元できるよう、url と sha256 を source_doc.csv に必ず残す。

取得先は事業体の公開ページ。ログインもフォーム送信も要らない
（docs/COLLECTOR_CONTRACT.md の「外向きアクションの禁止」に触れない）。
"""
import sys, pathlib, csv, datetime
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import download, register, sha256, RAW, ROOT, now

WATER_RAW = RAW / "water"
WATER_CSV = ROOT / "data" / "water" / "source_doc.csv"

# 政府標準利用規約系。PDF そのものは再配布しない（Git に入れない）ので、
# ここでのライセンス表記は「読み取った数値を出典明示で使ってよいか」の判断に使う。
LIC_YOKOHAMA = "横浜市サイトの利用について（出典明示で利用可）https://www.city.yokohama.lg.jp/site/copyright.html"
LIC_KIGYODAN = "神奈川県内広域水道企業団サイトの利用について（出典明示で利用可・要確認）https://www.kwsa.or.jp/"
LIC_KANAGAWA = ("神奈川県ウェブサイトのサイトポリシー（引用等の著作権法上認められている範囲で"
                "自由に利用可・出典の記載が必要）https://www.pref.kanagawa.jp/master/sitepolicy.html")
LIC_KANAGAWA_OD = ("クリエイティブ・コモンズ 表示 4.0（CC-BY）"
                   "https://catalog.opendata.pref.kanagawa.jp/ の掲載条件による")
LIC_KAWASAKI = ("川崎市 著作権・リンク・免責事項（「私的使用のための複製」や「引用」など"
                "著作権法上認められた場合を除き無断転載を禁止。出典明示での引用は可）"
                "https://www.city.kawasaki.jp/main/site_policy/0000000027.html")
LIC_YOKOSUKA = ("横須賀市ホームページについて（著作権は市または原権利者に帰属。私的使用と"
                "出所明示を伴う引用を除き無断転載・改変を禁止）"
                "https://www.city.yokosuka.kanagawa.jp/about_site/menseki.html")

# ------------------------------------------------------------------ #
# Phase 3 後半（独立系・地下水系）のサイト利用条件                        #
# 政府標準利用規約や CC-BY を全サイトに適用している自治体は無く、          #
# いずれも「著作権は当該自治体に帰属。私的使用・引用等を除き無断転載不可」型。 #
# ------------------------------------------------------------------ #
LIC_ODAWARA = ("小田原市 著作権・免責事項等（著作権は原則として小田原市が保有。二次利用は禁止だが"
               "著作権法上の私的使用・引用は可）https://www.city.odawara.kanagawa.jp/tyosaku/tyosakuetc.html")
LIC_MINAMIASHIGARA = ("南足柄市 このサイトについて（著作権は南足柄市または原権利者に帰属。私的使用または"
                      "引用等著作権法上認められている行為を除き無断転載不可）"
                      "https://www.city.minamiashigara.kanagawa.jp/about/about.html")
LIC_MIURA = ("三浦市 このサイトについて（三浦市が著作権を有し、法律で認められた場合を除き無断転用・引用を"
             "禁止。指定オープンデータのみ CC BY 4.0）"
             "https://www.city.miura.kanagawa.jp/soshiki/digitalka/digitalka_joho/1948.html")
LIC_NAKAI = ("中井町ウェブサイト（著作権・免責事項の専用ページは見つからず、フッターの"
             "Copyright (c) Nakai Town 表示のみ）https://www.town.nakai.kanagawa.jp/")
LIC_KAISEI = ("開成町ウェブサイト（著作権・免責事項の専用ページは見つからず）"
              "https://www.town.kaisei.kanagawa.jp/")
LIC_OI = ("大井町 リンク・著作権・免責事項（諸権利は原則として大井町に帰属。私的使用・引用を除き"
          "無断使用・複製・転載を禁止）https://www.town.oi.kanagawa.jp/site/userguide/lcd.html")
LIC_MATSUDA = ("松田町 リンク・著作権・免責事項（諸権利は原則として松田町に帰属。著作権法上の私的使用・"
               "引用を除き複製・転載・販売・貸与は不可）https://town.matsuda.kanagawa.jp/site/userguide/08.html")
LIC_HADANO = ("秦野市 リンク方針・著作権（秦野市役所ホームページの情報は原則として秦野市が著作権を有する。"
              "法律で認められた場合を除き無断で転用・引用することを禁じる）"
              "https://www.city.hadano.kanagawa.jp/shisei/koho/9/9176.html")
LIC_ZAMA = ("座間市 著作権・免責事項（諸権利は原則として座間市に帰属。「私的使用のための複製」や「引用」など"
            "著作権法上認められる場合を除き無断使用・複製・転載を禁止）"
            "https://www.city.zama.kanagawa.jp/about/1007657.html")
LIC_YAMAKITA = ("山北町ホームページについて（著作権は原則として山北町に帰属。私的使用・引用等を除き"
                "無断複製・転用不可）https://www.town.yamakita.kanagawa.jp/site_policy/0000000009.html")
LIC_YUGAWARA = ("湯河原町 リンク・著作権・免責事項（著作権は湯河原町または原著作者に帰属。引用・私的使用"
                "以外の無断複製・転用を禁止）https://www.town.yugawara.kanagawa.jp/site/userguide/13507.html")
LIC_MANAZURU = ("真鶴町ウェブサイト（著作権・免責事項の専用ページは見つからず。別途オープンデータ図書館"
                "https://opendata.manazuru.kanagawa.jp/terms/ のデータのみ CC BY 4.0）"
                "https://www.town.manazuru.kanagawa.jp/")
LIC_KIYOKAWA = ("清川村ウェブサイト（著作権・免責事項の専用ページは見つからず、フッターの"
                "Copyright(c) Kiyokawa Village 表示のみ）https://www.town.kiyokawa.kanagawa.jp/")
LIC_AIKAWA = ("愛川町ウェブサイト（利用条件ページは未確認。著作権は愛川町に帰属するものとして"
              "出典明示の引用の範囲で使っている）https://www.town.aikawa.kanagawa.jp/")
LIC_HAKONE = ("箱根町ウェブサイト（利用条件ページは未確認。著作権は箱根町に帰属するものとして"
              "出典明示の引用の範囲で使っている）https://www.town.hakone.kanagawa.jp/")
LIC_SAGAMIHARA = ("相模原市ウェブサイト（利用条件ページは未確認。著作権は相模原市に帰属するものとして"
                  "出典明示の引用の範囲で使っている）https://www.city.sagamihara.kanagawa.jp/")

DOCS = [
    {
        "doc_id": "DOC_YOK_SUISHITSU_R8",
        "utility": "yokohama",
        "title": "横浜市水道局 令和8年度水質検査計画",
        "publisher": "横浜市水道局",
        "url": "https://www.city.yokohama.lg.jp/kurashi/sumai-kurashi/suido-gesui/suido/suishitsu/suidosui/suishitsu-keikaku.files/R8suishitsu-keikaku.pdf",
        "published_at": "2026-03-23",
        "license_ja": LIC_YOKOHAMA,
        "file": "yokohama_R8_suishitsu_keikaku.pdf",
    },
    {
        "doc_id": "DOC_KGD_GAIYOU_R8",
        "utility": "kigyodan",
        "title": "神奈川県内広域水道企業団 事業の概要 令和8年度",
        "publisher": "神奈川県内広域水道企業団",
        "url": "https://www.kwsa.or.jp/aboutus/files/r8jigyounogaiyou.pdf",
        "published_at": "2026-04-01",
        "license_ja": LIC_KIGYODAN,
        "file": "kigyodan_r8_jigyounogaiyou.pdf",
    },
    {
        "doc_id": "DOC_YOK_KAWAI_GAIYOU",
        "utility": "yokohama",
        "title": "横浜市水道局 川井浄水場 施設概要（ウェブページ）",
        "publisher": "横浜市水道局",
        "url": "https://www.city.yokohama.lg.jp/kurashi/sumai-kurashi/suido-gesui/suido/suishitsu/josuijo/kawai/gaiyou.html",
        "published_at": "",
        "license_ja": LIC_YOKOHAMA,
        "file": "kawai_gaiyou.html",
    },
    {
        "doc_id": "DOC_YOK_NISHIYA_GAIYOU",
        "utility": "yokohama",
        "title": "横浜市水道局 西谷浄水場 施設概要（ウェブページ）",
        "publisher": "横浜市水道局",
        "url": "https://www.city.yokohama.lg.jp/kurashi/sumai-kurashi/suido-gesui/suido/suishitsu/josuijo/nishiya/gaiyou.html",
        "published_at": "",
        "license_ja": LIC_YOKOHAMA,
        "file": "nishiya_gaiyou.html",
    },
    {
        "doc_id": "DOC_YOK_KOSUZUME_GAIYOU",
        "utility": "yokohama",
        "title": "横浜市水道局 小雀浄水場 施設概要（ウェブページ）",
        "publisher": "横浜市水道局",
        "url": "https://www.city.yokohama.lg.jp/kurashi/sumai-kurashi/suido-gesui/suido/suishitsu/josuijo/kosuzume/gaiyou.html",
        "published_at": "",
        "license_ja": LIC_YOKOHAMA,
        "file": "kosuzume_gaiyou.html",
    },
    # ------------------------------------------------------------------ #
    # Phase 2: 神奈川県企業局 県営水道（UTL_KENEI）                          #
    # ------------------------------------------------------------------ #
    # 給水区域は市町村単位でしか公表されていないので、「12市6町の一覧」＋
    # 「一部給水の市町の町名リスト」＋「浄水場別の原水と配水系統」の 3 種類を取る。
    {
        "doc_id": "DOC_KEN_WEP_R8",
        "utility": "kenei",
        "title": "神奈川県営水道 令和8年度水質検査計画",
        "publisher": "神奈川県企業局 水道部浄水課",
        "url": "https://www.pref.kanagawa.jp/documents/47452/keikakur8.pdf",
        "published_at": "2026-03-25",
        "license_ja": LIC_KANAGAWA,
        "file": "kenei_r8_suishitsu_keikaku.pdf",
    },
    {
        "doc_id": "DOC_KEN_KYUSUIKUIKI",
        "utility": "kenei",
        "title": "神奈川県企業局 県営水道の給水区域（ウェブページ）",
        "publisher": "神奈川県企業局 水道部経営課",
        "url": "https://www.pref.kanagawa.jp/docs/r4a/keneisuidousyoukai/kyusuikuiki.html",
        "published_at": "2026-06-16",
        "license_ja": LIC_KANAGAWA,
        "file": "kyusuikuiki.html",
    },
    {
        "doc_id": "DOC_KEN_KUIKI_SAGAMIHARA",
        "utility": "kenei",
        "title": "神奈川県企業局 水道営業所管轄区域（相模原市）（ウェブページ）",
        "publisher": "神奈川県企業局 水道部経営課",
        "url": "https://www.pref.kanagawa.jp/docs/r4a/keneisuidousyoukai/sagamiharakuiki.html",
        "published_at": "",
        "license_ja": LIC_KANAGAWA,
        "file": "kuiki_sagamihara.html",
    },
    {
        "doc_id": "DOC_KEN_KUIKI_ODAWARA",
        "utility": "kenei",
        "title": "神奈川県企業局 小田原市の給水区域（ウェブページ）",
        "publisher": "神奈川県企業局 水道部経営課",
        "url": "https://www.pref.kanagawa.jp/docs/r4a/keneisuidousyoukai/odawarakuiki.html",
        "published_at": "",
        "license_ja": LIC_KANAGAWA,
        "file": "kuiki_odawara.html",
    },
    {
        "doc_id": "DOC_KEN_KUIKI_HAYAMA",
        "utility": "kenei",
        "title": "神奈川県企業局 葉山町の給水区域（ウェブページ）",
        "publisher": "神奈川県企業局 水道部経営課",
        "url": "https://www.pref.kanagawa.jp/docs/r4a/keneisuidousyoukai/hayamakuiki.html",
        "published_at": "",
        "license_ja": LIC_KANAGAWA,
        "file": "kuiki_hayama.html",
    },
    {
        "doc_id": "DOC_KEN_KUIKI_HAKONE",
        "utility": "kenei",
        "title": "神奈川県企業局 箱根町の給水区域（ウェブページ）",
        "publisher": "神奈川県企業局 水道部経営課",
        "url": "https://www.pref.kanagawa.jp/docs/r4a/keneisuidousyoukai/hakonekuiki.html",
        "published_at": "",
        "license_ja": LIC_KANAGAWA,
        "file": "kuiki_hakone.html",
    },
    {
        "doc_id": "DOC_KEN_KUIKI_AIKAWA",
        "utility": "kenei",
        "title": "神奈川県企業局 愛川町の給水区域（ウェブページ）",
        "publisher": "神奈川県企業局 水道部経営課",
        "url": "https://www.pref.kanagawa.jp/docs/r4a/keneisuidousyoukai/aikawakuiki.html",
        "published_at": "",
        "license_ja": LIC_KANAGAWA,
        "file": "kuiki_aikawa.html",
    },
    {
        "doc_id": "DOC_KEN_YAGAHARA",
        "utility": "kenei",
        "title": "神奈川県企業局 谷ケ原浄水場ホームページ（ウェブページ）",
        "publisher": "神奈川県企業局 谷ケ原浄水場",
        "url": "https://www.pref.kanagawa.jp/docs/h3x/index.html",
        "published_at": "2026-07-17",
        "license_ja": LIC_KANAGAWA,
        "file": "yagahara_top.html",
    },
    {
        "doc_id": "DOC_KEN_NENPO_R4",
        "utility": "kenei",
        "title": "神奈川県企業局 令和4年度 水道事業統計年報",
        "publisher": "神奈川県企業局",
        # 神奈川県オープンデータカタログ（CC-BY）。浄水場別の送水量・企業団受水地点別実績・
        # 主要配水系統図はこの年報にしか無い。
        "url": ("https://catalog.opendata.pref.kanagawa.jp/dataset/"
                "6d1a1c34-30ee-4070-a6ea-75e9b5dc8334/resource/"
                "fc549018-e51c-4254-b67f-121490e0cc39/download/nenpo4.pdf"),
        "published_at": "2024-02-16",
        "license_ja": LIC_KANAGAWA_OD,
        "file": "kenei_nenpo_r4.pdf",
    },
    {
        "doc_id": "DOC_KGD_GAIYOU_R7",
        "utility": "kigyodan",
        "title": "神奈川県内広域水道企業団 事業の概要 令和7年度",
        "publisher": "神奈川県内広域水道企業団",
        "url": "https://www.kwsa.or.jp/aboutus/files/r7jigyounogaiyou.pdf",
        "published_at": "2025-04-01",
        "license_ja": LIC_KIGYODAN,
        "file": "kigyodan_r7_jigyounogaiyou.pdf",
    },
    # ------------------------------------------------------------------ #
    # Phase 3: 川崎市上下水道局（UTL_KAWASAKI）                             #
    # ------------------------------------------------------------------ #
    # 給水区域は市内全域なので区域一覧は要らない。要るのは「どの配水系統がどこに来るか」で、
    # それは水質検査計画 p11 の図−7 にしか無い（scripts/c93_water_trace_kawasaki.py が読む）。
    {
        "doc_id": "DOC_KWS_SUISHITSU_R8",
        "utility": "kawasaki",
        "title": "川崎市上下水道局 令和8年度水質検査計画",
        "publisher": "川崎市上下水道局",
        "url": ("https://www.city.kawasaki.jp/800/cmsfiles/contents/"
                "0000083/83603/R8_kensakeikaku.pdf"),
        "published_at": "2026-03-31",
        "license_ja": LIC_KAWASAKI,
        "file": "kawasaki_r8_suishitsu_keikaku.pdf",
    },
    {
        "doc_id": "DOC_KWS_SHISETSU",
        "utility": "kawasaki",
        "title": "川崎市上下水道局 水道事業の施設（ウェブページ）",
        "publisher": "川崎市上下水道局",
        "url": "https://www.city.kawasaki.jp/800/page/0000083181.html",
        "published_at": "",
        "license_ja": LIC_KAWASAKI,
        "file": "shisetsu.html",
    },
    # ------------------------------------------------------------------ #
    # Phase 3: 横須賀市上下水道局（UTL_YOKOSUKA）                           #
    # ------------------------------------------------------------------ #
    # 統計年報の「系統別着水量」に水源系統ごとの年間実績があるので、施設能力比ではなく
    # 実績で按分できる（basis=estimated。値は実測だが市全体の平均を全町丁目に当てるため）。
    {
        "doc_id": "DOC_YKS_WEP_R8",
        "utility": "yokosuka",
        "title": "横須賀市上下水道局 令和8年度水道水質検査計画",
        "publisher": "横須賀市上下水道局",
        "url": "https://www.city.yokosuka.kanagawa.jp/6955/suisitu/documents/r8keikaku.pdf",
        "published_at": "2026-03-31",
        "license_ja": LIC_YOKOSUKA,
        "file": "yokosuka_r8_suishitsu_keikaku.pdf",
    },
    {
        "doc_id": "DOC_YKS_TOUKEI_R6",
        "utility": "yokosuka",
        "title": "横須賀市上下水道局 令和6年度 水道事業統計年報",
        "publisher": "横須賀市上下水道局",
        "url": ("https://www.city.yokosuka.kanagawa.jp/6731/torikumi/keiei/"
                "documents/r6suidoutoukei.pdf"),
        "published_at": "2025-10-01",
        "license_ja": LIC_YOKOSUKA,
        "file": "yokosuka_r6_suidou_toukei.pdf",
    },
    {
        "doc_id": "DOC_YKS_KEITO",
        "utility": "yokosuka",
        "title": "横須賀市上下水道局 水源系統（ウェブページ）",
        "publisher": "横須賀市上下水道局",
        "url": "https://www.city.yokosuka.kanagawa.jp/6911/torikumi/keito.html",
        "published_at": "",
        "license_ja": LIC_YOKOSUKA,
        "file": "keito.html",
    },
    {
        "doc_id": "DOC_YKS_KEITO_ARIMA",
        "utility": "yokosuka",
        "title": "横須賀市上下水道局 有馬系統（ウェブページ）",
        "publisher": "横須賀市上下水道局",
        "url": "https://www.city.yokosuka.kanagawa.jp/6911/torikumi/keito/arima.html",
        "published_at": "",
        "license_ja": LIC_YOKOSUKA,
        "file": "keito_arima.html",
    },
    {
        "doc_id": "DOC_YKS_KEITO_KOSUZUME",
        "utility": "yokosuka",
        "title": "横須賀市上下水道局 小雀系統（ウェブページ）",
        "publisher": "横須賀市上下水道局",
        "url": "https://www.city.yokosuka.kanagawa.jp/6911/torikumi/keito/kosuzume.html",
        "published_at": "",
        "license_ja": LIC_YOKOSUKA,
        "file": "keito_kosuzume.html",
    },
    {
        "doc_id": "DOC_YKS_KEITO_MIYAGASE",
        "utility": "yokosuka",
        "title": "横須賀市上下水道局 宮ヶ瀬系統（ウェブページ）",
        "publisher": "横須賀市上下水道局",
        "url": "https://www.city.yokosuka.kanagawa.jp/6911/torikumi/keito/miyagase.html",
        "published_at": "",
        "license_ja": LIC_YOKOSUKA,
        "file": "keito_miyagase.html",
    },
    {
        "doc_id": "DOC_YKS_KEITO_SAKAWA",
        "utility": "yokosuka",
        "title": "横須賀市上下水道局 酒匂川系統（ウェブページ）",
        "publisher": "横須賀市上下水道局",
        "url": "https://www.city.yokosuka.kanagawa.jp/6911/torikumi/keito/sakawagawa.html",
        "published_at": "",
        "license_ja": LIC_YOKOSUKA,
        "file": "keito_sakawagawa.html",
    },
    {
        "doc_id": "DOC_YKS_KEITO_HASHIRIMIZU",
        "utility": "yokosuka",
        "title": "横須賀市上下水道局 走水系統（ウェブページ）",
        "publisher": "横須賀市上下水道局",
        "url": "https://www.city.yokosuka.kanagawa.jp/6911/torikumi/keito/hasirimizu.html",
        "published_at": "",
        "license_ja": LIC_YOKOSUKA,
        "file": "keito_hasirimizu.html",
    },
    # ------------------------------------------------------------------ #
    # 県内全事業体の棚卸し（docs/UTILITY_INVENTORY.md）の典拠               #
    # ------------------------------------------------------------------ #
    # データ行は指していないが、どの事業体が県内にいくつあるか・給水人口はいくらかを
    # 1 か所から取るために取得して sha256 を残す。
    {
        "doc_id": "DOC_KAN_JIGYOSHA",
        "utility": "kanagawa",
        "title": "神奈川県 神奈川県内の水道事業者一覧（ウェブページ）",
        "publisher": "神奈川県 健康医療局生活衛生部生活衛生課",
        "url": "https://www.pref.kanagawa.jp/docs/e8z/cnt/f1029/p70915-1.html",
        "published_at": "2026-08-17",
        "license_ja": LIC_KANAGAWA,
        "file": "jigyosha_ichiran.html",
    },
    {
        "doc_id": "DOC_KAN_SUIDOU_R5",
        "utility": "kanagawa",
        "title": "神奈川県 令和5年度 神奈川県の水道",
        "publisher": "神奈川県 健康医療局生活衛生部生活衛生課",
        "url": "https://www.pref.kanagawa.jp/documents/11042/r5suidou.pdf",
        "published_at": "",
        "license_ja": LIC_KANAGAWA,
        "file": "kanagawa_r5_suidou.pdf",
    },
    # ================================================================== #
    # Phase 3 後半: 独立系・地下水系（reports/dokuritsu.md）                 #
    # ================================================================== #
    {
        "doc_id": "DOC_ODW_WEP_R8",
        "utility": "odawara",
        "title": "令和8年度 小田原市水道事業水質検査計画",
        "publisher": "小田原市上下水道局",
        "url": "https://www.city.odawara.kanagawa.jp/global-image/units/627837/1-20260331115747_b69cb382b671f1.pdf",
        "published_at": "2026-03-31",
        "license_ja": LIC_ODAWARA,
        "file": "odawara_r8_suishitsu_keikaku.pdf",
    },
    {
        "doc_id": "DOC_ODW_FAQ_MIZU",
        "utility": "odawara",
        "title": "小田原市 小田原の水はどこから取っているのですか。（FAQ・ウェブページ）",
        "publisher": "小田原市上下水道局",
        "url": "https://www.city.odawara.kanagawa.jp/faq/p06373.html",
        "published_at": "2021-08-25",
        "license_ja": LIC_ODAWARA,
        "file": "odawara_faq_mizu.html",
    },
    {
        "doc_id": "DOC_ODW_TAKATA",
        "utility": "odawara",
        "title": "小田原市 高田浄水場再整備事業について（ウェブページ）",
        "publisher": "小田原市上下水道局",
        "url": "https://www.city.odawara.kanagawa.jp/field/c-planning/water/intro/preparation/p34393.html",
        "published_at": "2026-06-02",
        "license_ja": LIC_ODAWARA,
        "file": "odawara_takata.html",
    },
    {
        "doc_id": "DOC_MAS_WEP_R8",
        "utility": "minamiashigara",
        "title": "令和8年度 南足柄市水道事業水質検査計画",
        "publisher": "南足柄市上下水道課",
        "url": "https://www.city.minamiashigara.kanagawa.jp/global-image/units/204661/1-20260319113924.pdf",
        "published_at": "2026-03-19",
        "license_ja": LIC_MINAMIASHIGARA,
        "file": "minamiashigara_r8_suishitsu_keikaku.pdf",
    },
    {
        "doc_id": "DOC_MAS_ANZEN_R8",
        "utility": "minamiashigara",
        "title": "南足柄市水安全計画（令和8年3月）概要版",
        "publisher": "南足柄市",
        "url": "https://www.city.minamiashigara.kanagawa.jp/global-image/units/189103/1-20260623150301.pdf",
        "published_at": "2026-03-01",
        "license_ja": LIC_MINAMIASHIGARA,
        "file": "minamiashigara_mizuanzen_gaiyou.pdf",
    },
    {
        "doc_id": "DOC_MAS_JOSUI",
        "utility": "minamiashigara",
        "title": "南足柄市 浄水場（ウェブページ）",
        "publisher": "南足柄市上下水道課",
        "url": "https://www.city.minamiashigara.kanagawa.jp/kurashi/mizu/iroiro/suidou_jigyou/1354_3116.html",
        "published_at": "2024-03-05",
        "license_ja": LIC_MINAMIASHIGARA,
        "file": "minamiashigara_josuijo.html",
    },
    {
        "doc_id": "DOC_MAS_HAISUI_ZU",
        "utility": "minamiashigara",
        "title": "南足柄市配水区域図",
        "publisher": "南足柄市上下水道課",
        "url": "https://www.city.minamiashigara.kanagawa.jp/global-image/units/104599/1-20240304140717.pdf",
        "published_at": "",
        "license_ja": LIC_MINAMIASHIGARA,
        "file": "minamiashigara_haisui_kuiki_zu.pdf",
    },
    {
        "doc_id": "DOC_MIU_WEP_R8",
        "utility": "miura",
        "title": "令和8（2026）年度 三浦市水質検査計画書",
        "publisher": "三浦市上下水道部",
        "url": "https://www.city.miura.kanagawa.jp/material/files/group/42/R8suisitukennsakeikakusyo.pdf",
        "published_at": "",
        "license_ja": LIC_MIURA,
        "file": "miura_r8_suishitsu_keikaku.pdf",
    },
    {
        "doc_id": "DOC_MIU_VISION",
        "utility": "miura",
        "title": "三浦市水道ビジョン(経営戦略) 第1〜4章",
        "publisher": "三浦市上下水道部",
        "url": "https://www.city.miura.kanagawa.jp/material/files/group/41/37372723.pdf",
        "published_at": "2021-03-31",
        "license_ja": LIC_MIURA,
        "file": "miura_suidou_vision_1_4.pdf",
    },
    {
        "doc_id": "DOC_MIU_VISION_GAIYOU",
        "utility": "miura",
        "title": "三浦市水道ビジョン(経営戦略) 概要版",
        "publisher": "三浦市上下水道部",
        "url": "https://www.city.miura.kanagawa.jp/material/files/group/41/miurasisuidouvisiongaiyouban20210331.pdf",
        "published_at": "2021-03-31",
        "license_ja": LIC_MIURA,
        "file": "miura_suidou_vision_gaiyou.pdf",
    },
    {
        "doc_id": "DOC_NKI_WEP_R8",
        "utility": "nakai",
        "title": "令和8年度 中井町水道事業水質検査計画",
        "publisher": "中井町上下水道課",
        "url": "https://www.town.nakai.kanagawa.jp/material/files/group/15/R8suidotukennsakeikaku.pdf",
        "published_at": "",
        "license_ja": LIC_NAKAI,
        "file": "nakai_r8_suishitsu_keikaku.pdf",
    },
    {
        "doc_id": "DOC_KAI_WEP_R8",
        "utility": "kaisei",
        "title": "令和8年度 開成町水質検査計画（ウェブページ）",
        "publisher": "開成町都市整備課",
        "url": "https://www.town.kaisei.kanagawa.jp/info/711",
        "published_at": "2026-03-30",
        "license_ja": LIC_KAISEI,
        "file": "kaisei_r8_suishitsu_keikaku.html",
    },
    {
        "doc_id": "DOC_KAI_KEIEI",
        "utility": "kaisei",
        "title": "開成町水道事業経営戦略（令和7年3月・計画期間 R6〜R16）",
        "publisher": "開成町都市整備課",
        "url": "https://www.town.kaisei.kanagawa.jp/div/machi/pdf/Suidou/suidou_keiseisenryaku_R6.pdf",
        "published_at": "2025-03-01",
        "license_ja": LIC_KAISEI,
        "file": "kaisei_keiei_senryaku.pdf",
    },
    {
        "doc_id": "DOC_KAI_OISHII",
        "utility": "kaisei",
        "title": "開成町のおいしい水の紹介（ウェブページ）",
        "publisher": "開成町都市整備課",
        "url": "https://www.town.kaisei.kanagawa.jp/info/327",
        "published_at": "",
        "license_ja": LIC_KAISEI,
        "file": "kaisei_oishii_mizu.html",
    },
    {
        "doc_id": "DOC_OI_KEIEI",
        "utility": "oi",
        "title": "大井町水道事業経営戦略 改定版（令和7年度〜令和16年度）",
        "publisher": "大井町生活環境課",
        "url": "https://www.town.oi.kanagawa.jp/uploaded/life/30020_54494_misc.pdf",
        "published_at": "",
        "license_ja": LIC_OI,
        "file": "oi_keiei_senryaku.pdf",
    },
    {
        "doc_id": "DOC_OI_WEP",
        "utility": "oi",
        "title": "大井町 水質検査実施計画（ウェブページ）",
        "publisher": "大井町生活環境課",
        "url": "https://www.town.oi.kanagawa.jp/soshiki/9/13-2.html",
        "published_at": "2026-04-01",
        "license_ja": LIC_OI,
        "file": "oi_suishitsu_keikaku.html",
    },
    {
        "doc_id": "DOC_MTD_VISION",
        "utility": "matsuda",
        "title": "松田町水道ビジョン（令和5年度改定版）",
        "publisher": "松田町",
        "url": "https://town.matsuda.kanagawa.jp/uploaded/attachment/15214.pdf",
        "published_at": "2023-12-01",
        "license_ja": LIC_MATSUDA,
        "file": "matsuda_suidou_vision.pdf",
    },
    {
        "doc_id": "DOC_MTD_IMA",
        "utility": "matsuda",
        "title": "まつだの水道の今 〜みんなで支える みんなの水〜（令和8年1月）",
        "publisher": "松田町",
        "url": "https://town.matsuda.kanagawa.jp/uploaded/life/34563_110779_misc.pdf",
        "published_at": "2026-01-13",
        "license_ja": LIC_MATSUDA,
        "file": "matsuda_suidou_no_ima.pdf",
    },
    {
        "doc_id": "DOC_HAD_WEP_R8",
        "utility": "hadano",
        "title": "令和8年度 秦野市上下水道局水道水質検査計画",
        "publisher": "秦野市上下水道局",
        "url": "https://www.city.hadano.kanagawa.jp/material/files/group/68/R08_suisitu_plan.pdf",
        "published_at": "2026-07-13",
        "license_ja": LIC_HADANO,
        "file": "hadano_r8_suishitsu_keikaku.pdf",
    },
    {
        "doc_id": "DOC_HAD_TOUKEI_R6",
        "utility": "hadano",
        "title": "秦野市 上下水道事業統計要覧 令和6年度版",
        "publisher": "秦野市上下水道局",
        "url": "https://www.city.hadano.kanagawa.jp/material/files/group/66/R06_toukeiyouran.pdf",
        "published_at": "2026-05-31",
        "license_ja": LIC_HADANO,
        "file": "hadano_r6_toukei_youran.pdf",
    },
    {
        "doc_id": "DOC_HAD_DEKIRUMADE",
        "utility": "hadano",
        "title": "秦野市 水道水ができるまで（ウェブページ）",
        "publisher": "秦野市上下水道局",
        "url": "https://www.city.hadano.kanagawa.jp/soshiki/11/1065/4/2880.html",
        "published_at": "",
        "license_ja": LIC_HADANO,
        "file": "hadano_dekirumade.html",
    },
    {
        "doc_id": "DOC_HAD_JOREI",
        "utility": "hadano",
        "title": "秦野市水道事業給水条例 別表第1（第2条関係）",
        "publisher": "秦野市",
        "url": "https://www1.g-reiki.net/city.hadano/reiki_honbun/g213RG00000617.html",
        "published_at": "",
        "license_ja": LIC_HADANO,
        "file": "hadano_kyusui_jorei.html",
    },
    {
        "doc_id": "DOC_ZAM_WEP_R8",
        "utility": "zama",
        "title": "令和8年度 座間市上下水道局水質検査計画",
        "publisher": "座間市上下水道局水道施設課",
        "url": "https://www.city.zama.kanagawa.jp/_res/projects/default_project/_page_/001/011/705/r08zamasuikei.pdf",
        "published_at": "2026-03-01",
        "license_ja": LIC_ZAMA,
        "file": "zama_r8_suishitsu_keikaku.pdf",
    },
    {
        "doc_id": "DOC_ZAM_GAIYOU_R5",
        "utility": "zama",
        "title": "座間市公営企業概要 令和5年度版",
        "publisher": "座間市上下水道局",
        "url": "https://www.city.zama.kanagawa.jp/_res/projects/default_project/_page_/001/002/400/koueikigyougaiyour5.pdf",
        "published_at": "",
        "license_ja": LIC_ZAMA,
        "file": "zama_koueikigyou_gaiyou_r5.pdf",
    },
    {
        "doc_id": "DOC_ZAM_KENSUI",
        "utility": "zama",
        "title": "座間市 神奈川県企業庁からの受水（ウェブページ）",
        "publisher": "座間市上下水道局水道施設課",
        "url": "https://www.city.zama.kanagawa.jp/kurashi/suidou/josuidou/kensui/1002389.html",
        "published_at": "2024-09-02",
        "license_ja": LIC_ZAMA,
        "file": "zama_kensui.html",
    },
    {
        "doc_id": "DOC_YMK_WEP_R8",
        "utility": "yamakita",
        "title": "令和8年度 山北町水質検査計画",
        "publisher": "山北町上下水道課",
        "url": "https://www.town.yamakita.kanagawa.jp/cmsfiles/contents/0000004/4173/R08suisitukennsakeikaku.pdf",
        "published_at": "2026-02-01",
        "license_ja": LIC_YAMAKITA,
        "file": "yamakita_r8_suishitsu_keikaku.pdf",
    },
    {
        "doc_id": "DOC_YMK_JOREI",
        "utility": "yamakita",
        "title": "山北町水道事業給水条例 別表第1",
        "publisher": "山北町",
        "url": "http://www.town.yamakita.kanagawa.jp/machidukuri/reiki/reiki_honbun/w700RG00000276.html",
        "published_at": "",
        "license_ja": LIC_YAMAKITA,
        "file": "yamakita_kyusui_jorei.html",
    },
    {
        "doc_id": "DOC_YGW_WEP_R8",
        "utility": "yugawara",
        "title": "令和8年度 湯河原町水質検査計画書",
        "publisher": "湯河原町水道課",
        "url": "https://www.town.yugawara.kanagawa.jp/uploaded/attachment/17619.pdf",
        "published_at": "2026-04-01",
        "license_ja": LIC_YUGAWARA,
        "file": "yugawara_r8_suishitsu_keikaku.pdf",
    },
    {
        "doc_id": "DOC_YGW_VISION",
        "utility": "yugawara",
        "title": "湯河原町水道ビジョン・経営戦略",
        "publisher": "湯河原町水道課",
        "url": "https://www.town.yugawara.kanagawa.jp/uploaded/attachment/3118.pdf",
        "published_at": "2021-12-01",
        "license_ja": LIC_YUGAWARA,
        "file": "yugawara_suidou_vision.pdf",
    },
    {
        "doc_id": "DOC_YGW_KUIKI",
        "utility": "yugawara",
        "title": "湯河原町 転入・転出・町内転居するときは（給水区域の区分・ウェブページ）",
        "publisher": "湯河原町水道課",
        "url": "https://www.town.yugawara.kanagawa.jp/soshiki/28/1841.html",
        "published_at": "",
        "license_ja": LIC_YUGAWARA,
        "file": "yugawara_kuiki.html",
    },
    {
        "doc_id": "DOC_MNZ_WEP",
        "utility": "manazuru",
        "title": "真鶴町水質検査計画書（令和6年度）",
        "publisher": "真鶴町上下水道課",
        "url": "https://www.town.manazuru.kanagawa.jp/material/files/group/41/suisitukeikaku.pdf",
        "published_at": "",
        "license_ja": LIC_MANAZURU,
        "file": "manazuru_suishitsu_keikaku.pdf",
    },
    {
        "doc_id": "DOC_MNZ_KEIEI",
        "utility": "manazuru",
        "title": "真鶴町水道事業経営戦略（2025年度改定・令和8年3月）",
        "publisher": "真鶴町都市基盤課",
        "url": "https://www.town.manazuru.kanagawa.jp/material/files/group/41/R8-R17suidokeieisennryaku.pdf",
        "published_at": "2026-03-01",
        "license_ja": LIC_MANAZURU,
        "file": "manazuru_keiei_senryaku.pdf",
    },
    {
        "doc_id": "DOC_KYK_WEP_R8",
        "utility": "kiyokawa",
        "title": "令和8年度 清川村簡易水道事業水質検査計画",
        "publisher": "清川村環境上下水道課",
        "url": "https://www.town.kiyokawa.kanagawa.jp/material/files/group/9/r08suisitukeikaku.pdf",
        "published_at": "2026-03-01",
        "license_ja": LIC_KIYOKAWA,
        "file": "kiyokawa_r8_suishitsu_keikaku.pdf",
    },
    {
        "doc_id": "DOC_AIK_WEP_R8",
        "utility": "aikawa",
        "title": "令和8年度 愛川町水質検査計画",
        "publisher": "愛川町水道事業所",
        "url": "https://www.town.aikawa.kanagawa.jp/material/files/group/32/R8suisitukensakeikaku2.pdf",
        "published_at": "",
        "license_ja": LIC_AIKAWA,
        "file": "aikawa_r8_suishitsu_keikaku.pdf",
    },
    {
        "doc_id": "DOC_AIK_KEITOZU",
        "utility": "aikawa",
        "title": "愛川町水道施設配水系統図（令和8年度）",
        "publisher": "愛川町水道事業所",
        "url": "https://www.town.aikawa.kanagawa.jp/material/files/group/32/R8haisuikeitouzu.pdf",
        "published_at": "",
        "license_ja": LIC_AIKAWA,
        "file": "aikawa_r8_haisui_keitozu.pdf",
    },
    {
        "doc_id": "DOC_AIK_KUIKI",
        "utility": "aikawa",
        "title": "愛川町 給水区域（ウェブページ）",
        "publisher": "愛川町水道事業所",
        "url": "https://www.town.aikawa.kanagawa.jp/soshiki/suido/gyomu/info/1422277675354.html",
        "published_at": "",
        "license_ja": LIC_AIKAWA,
        "file": "aikawa_kuiki.html",
    },
    {
        "doc_id": "DOC_HKN_WEP",
        "utility": "hakone",
        "title": "箱根町水道事業 水質検査計画書",
        "publisher": "箱根町上下水道温泉課",
        "url": "https://www.town.hakone.kanagawa.jp/www/contents/1100000000021/simple/zigyoukeikaku.pdf",
        "published_at": "",
        "license_ja": LIC_HAKONE,
        "file": "hakone_suishitsu_keikaku.pdf",
    },
    {
        "doc_id": "DOC_HKN_KUIKI",
        "utility": "hakone",
        "title": "箱根町 上水道給水区域（ウェブページ）",
        "publisher": "箱根町上下水道温泉課",
        "url": "https://www.town.hakone.kanagawa.jp/www/contents/1100000001041/index.html",
        "published_at": "",
        "license_ja": LIC_HAKONE,
        "file": "hakone_kuiki.html",
    },
    {
        "doc_id": "DOC_KEN_SHOUSUIGEN",
        "utility": "kenei",
        "title": "神奈川県企業局 小規模水源浄水場（落合、鎌沢、和田）（ウェブページ）",
        "publisher": "神奈川県企業局 谷ケ原浄水場",
        "url": "https://www.pref.kanagawa.jp/docs/h3x/top/syousuigenitiran.html",
        "published_at": "",
        "license_ja": LIC_KANAGAWA,
        "file": "kenei_shousuigen.html",
    },
    {
        "doc_id": "DOC_KEN_TORIYA",
        "utility": "kenei",
        "title": "神奈川県企業局 小規模水源浄水場 鳥屋浄水場（ウェブページ）",
        "publisher": "神奈川県企業局 谷ケ原浄水場",
        "url": "https://www.pref.kanagawa.jp/docs/h3x/top/toyanaganojousuijou.html",
        "published_at": "",
        "license_ja": LIC_KANAGAWA,
        "file": "kenei_toriya.html",
    },
    {
        "doc_id": "DOC_KEN_SAMUKAWA_HP",
        "utility": "kenei",
        "title": "神奈川県企業局 寒川浄水場ホームページ（ウェブページ）",
        "publisher": "神奈川県企業局 寒川浄水場",
        "url": "https://www.pref.kanagawa.jp/docs/k5f/index.html",
        "published_at": "",
        "license_ja": LIC_KANAGAWA,
        "file": "kenei_samukawa_top.html",
    },
    {
        "doc_id": "DOC_SGH_KANSUI",
        "utility": "sagamihara",
        "title": "相模原市 相模原市営簡易水道事業とは（ウェブページ）",
        "publisher": "相模原市 津久井下水道事務所",
        "url": "https://www.city.sagamihara.kanagawa.jp/shisei/1026823/1004616/1026848/1020969/1020970.html",
        "published_at": "",
        "license_ja": LIC_SAGAMIHARA,
        "file": "sagamihara_kanisuido.html",
    },
]

COLS = ["doc_id", "title", "publisher", "url", "published_at", "retrieved_at",
        "local_path", "sha256", "license_ja"]


def main():
    rows, failed = [], []
    for d in DOCS:
        dest = WATER_RAW / d["utility"] / d["file"]
        try:
            download(d["url"], dest)
        except Exception as e:
            print(f"NG  {d['doc_id']}: {e}")
            failed.append((d, str(e)))
            continue
        h = sha256(dest)
        rows.append({
            "doc_id": d["doc_id"],
            "title": d["title"],
            "publisher": d["publisher"],
            "url": d["url"],
            "published_at": d["published_at"],
            "retrieved_at": datetime.date.today().isoformat(),
            "local_path": str(dest.relative_to(ROOT)),
            "sha256": h,
            "license_ja": d["license_ja"],
        })
        print(f"OK  {d['doc_id']}  {dest.stat().st_size/1e6:.2f} MB  {h[:12]}…")

    WATER_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(WATER_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"\n[write] {WATER_CSV.relative_to(ROOT)}  {len(rows)} 行")

    register("water_source_docs", "水道水の水源マップ 根拠資料（事業体の水質検査計画・事業概要）",
             "各水道事業体", "https://www.kwsa.or.jp/ ほか", "document", "http", "pdf",
             "各事業体のサイト利用条件（出典明示で利用可）", 0, len(rows),
             notes="PDF の実体は data/raw/water/ に置き Git 管理外。url と sha256 で再取得できる。"
                   f"取得失敗 {len(failed)} 件。" + ("; ".join(f"{d['doc_id']}: {e}" for d, e in failed) if failed else ""))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
