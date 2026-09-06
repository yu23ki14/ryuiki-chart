#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""神奈川県レッドデータ生物調査報告書2006 レッドリスト(集計結果・一覧) — 動物編(脊椎動物)

このPDF(RedData2006_shukeikekka_ichiran.pdf, 全29ページ)は634ページの本冊
「神奈川県レッドデータ生物調査報告書2006」のうち「評価結果一覧(分類群ごと、
カテゴリー順で掲載)」だけを抜粋した一覧表で、スキャン画像+OCRテキストのPDF。

pdfplumber.find_tables() は罫線なしのため0件 (page1,14,20 で確認済み)。
OCRテキストも文字化けが激しく(縦書き見出しの混入等)、生テキストからの
literal照合だけでは幻覅防止と実データ抽出を両立できない。そのため
P1 Maker の本来の入力仕様([IMAGE]+[RAW_TEXT])に立ち返り、ページ画像を
直接目視で読み取って転記した(このスクリプトは転記結果を機械的に
DB/CSVへ流し込むだけで、値の推測・補完は行っていない)。

対象ページ: 本PDFの14〜18ページ(哺乳類・鳥類・爬虫類・両生類・汽水淡水魚類)。
昆虫類・クモ類(18ページ後半〜29ページ)は kanagawa_redlist (2026年版Excel)で
既に取得済みのため対象外。「その他無脊椎動物」はこのPDF自体に区分が存在しない
(貝類・甲殻類等のキーワードは全29ページ中に一度も出現しない)。

転記の正しさは、このPDF1ページ目(本冊6ページ)に掲載されている
「分類群ごとに集計した評価結果」表の分類群別合計と全件突合して検証した:
  哺乳類31, 鳥類122, 爬虫類8, 両生類12, 汽水・淡水魚類48  (すべて一致)

学名は本PDFのどこにも記載がないため scientific_name は全件 null。
(和名から学名を推測することは禁止されているため補完していない)
"""
import sys, pathlib, re, csv, sqlite3, json
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import DB, PROC, ROOT, now, appdb

DOC_ID = "kanagawa_rdb2006_animals"
PDF_PATH = ROOT / "data/raw/kanagawa_rdb2006/RedData2006_shukeikekka_ichiran.pdf"
SOURCE_URL = ("https://nh.kanagawa-museum.jp/assets/icp/contents/1657590295853/"
              "simple/RedData2006_shukeikekka_ichiran.pdf")
LIST_YEAR = 2006

# ---------------------------------------------------------------------------
# 転記データ: (vernacular_ja, family_ja_or_None, book_page, category_prev_ja, national_category_ja)
# family_ja_or_None が None の行は「種」ではなく地域個体群/集団繁殖地などの特殊エントリ。
# 空文字は「原文に記載なし(空欄)」を表す(None と区別しない: どちらも「値なし」)。
# ---------------------------------------------------------------------------

MAMMALS = [
    ("絶滅", [
        ("オオカミ", "イヌ科", "231", "絶滅種B", "絶滅"),
        ("オコジョ", "イタチ科", "231", "", "準絶滅危惧"),
        ("カワウソ", "イタチ科", "232", "絶滅種B", "絶滅危惧ⅠA類"),
        ("ニホンアシカ", "アシカ科", "232", "絶滅種B", "絶滅危惧ⅠA類"),
    ]),
    ("絶滅危惧Ⅰ類", [
        ("ヒメヒミズ", "モグラ科", "228", "希少種Ⅰ", ""),
        ("キクガシラコウモリ", "キクガシラコウモリ科", "228", "減少種G", ""),
        ("モリアブラコウモリ", "ヒナコウモリ科", "229", "希少種Ⅰ*", "絶滅危惧ⅠB類"),
        ("チチブコウモリ", "ヒナコウモリ科", "229", "", "絶滅危惧Ⅱ類"),
        ("テングコウモリ", "ヒナコウモリ科", "229", "希少種Ⅰ*", "絶滅危惧Ⅱ類"),
        ("コテングコウモリ", "ヒナコウモリ科", "229", "希少種Ⅰ*", "絶滅危惧Ⅱ類"),
        ("ツキノワグマ", "クマ科", "231", "絶滅危惧種D", "絶滅のおそれのある地域個体群"),
        ("スナメリ", "ネズミイルカ科", "232", "絶滅危惧種E", ""),
    ]),
    ("絶滅危惧Ⅱ類", [
        ("コキクガシラコウモリ", "キクガシラコウモリ科", "228", "減少種G", ""),
        ("ユビナガコウモリ", "ヒナコウモリ科", "228", "減少種G", ""),
        ("ヤマコウモリ", "ヒナコウモリ科", "229", "減少種G", "絶滅危惧Ⅱ類"),
        ("ヒナコウモリ", "ヒナコウモリ科", "229", "減少種G", "絶滅危惧Ⅱ類"),
        ("ホンドモモンガ", "リス科", "230", "絶滅危惧種D", ""),
        ("ヤマネ", "ヤマネ科", "230", "絶滅危惧種L", "準絶滅危惧"),
    ]),
    ("準絶滅危惧", [
        ("カワネズミ", "トガリネズミ科", "227", "減少種G", "準絶滅危惧"),
        ("コウベモグラ", "モグラ科", "228", "", ""),
        ("モモジロコウモリ", "ヒナコウモリ科", "229", "減少種G", ""),
        ("ニホンリス", "リス科", "230", "減少種G", "絶滅のおそれのある地域個体群"),
        ("カヤネズミ", "ネズミ科", "230", "減少種H", ""),
        ("スミスネズミ", "ネズミ科", "231", "健在種Ⅰ", ""),
        ("ハタネズミ", "ネズミ科", "231", "健在種Ⅰ", ""),
        ("キツネ", "イヌ科", "231", "減少種", ""),
        ("イタチ", "イタチ科", "231", "健在種J", ""),
        ("ニホンカモシカ", "ウシ科", "232", "減少種G", ""),
    ]),
    ("情報不足", [
        ("ウサギコウモリ", "ヒナコウモリ科", "228", "減少種Ⅰ*", "絶滅危惧Ⅱ類"),
        ("オヒキコウモリ", "オヒキコウモリ科", "230", "希少種Ⅰ*", "情報不足"),
    ]),
    ("絶滅のおそれのある地域個体群", [
        ("ニホンザルの西湘地域個体群", None, "232", "健在種Ⅰ", ""),
    ]),
]

BIRDS = [
    ("(繁)絶滅種、(非)絶滅種", [
        ("カラスバト", "ハト科", "251", "(繁)絶滅種A", "準絶滅危惧"),
    ]),
    ("(繁)絶滅種", [
        ("オオジシギ", "シギ科", "250", "(非)絶滅危惧種F", "準絶滅危惧"),
    ]),
    ("(繁)絶滅危惧Ⅰ類、(非)絶滅危惧Ⅰ類", [
        ("オオアカゲラ", "キツツキ科", "255", "(繁)希少種Ⅰ", ""),
    ]),
    ("(繁)絶滅危惧Ⅰ類、(非)希少種", [
        ("ハヤブサ", "ハヤブサ科", "241", "", "絶滅危惧Ⅱ類"),
        ("タマシギ", "タマシギ科", "242", "(繁)絶滅危惧種F", ""),
        ("オオコノハズク", "フクロウ科", "253", "", ""),
    ]),
    ("(繁)絶滅危惧Ⅰ類、(非)減少種", [
        ("クロジ", "ホオジロ科", "262", "", ""),
    ]),
    ("(繁)絶滅危惧Ⅰ類", [
        ("ミゾゴイ", "サギ科", "236", "(繁)絶滅危惧種E", "準絶滅危惧"),
        ("ハチクマ", "タカ科", "239", "", "準絶滅危惧"),
        ("サシバ", "タカ科", "240", "(繁)減少種G", ""),
        ("ヒクイナ", "クイナ科", "241", "(繁)絶滅危惧種E", ""),
        ("コアジサシ", "カモメ科", "250", "(繁)絶滅危惧種F", "絶滅危惧Ⅱ類"),
        ("コノハズク", "フクロウ科", "252", "(繁)絶滅危惧種E", ""),
        ("ブッポウソウ", "ブッポウソウ科", "254", "(繁)絶滅危惧種D", "絶滅危惧Ⅱ類"),
        ("チゴモズ", "モズ科", "257", "", "絶滅危惧Ⅱ類"),
        ("アカモズ", "モズ科", "257", "", "準絶滅危惧"),
        ("コマドリ", "ツグミ科", "258", "", ""),
        ("コヨシキリ", "ウグイス科", "259", "", ""),
        ("コサメビタキ", "ヒタキ科", "261", "(繁)絶滅危惧種E", ""),
        ("ホオアカ", "ホオジロ科", "262", "(繁)減少種H", ""),
    ]),
    ("(繁)絶滅危惧Ⅱ類、(非)絶滅危惧Ⅱ類", [
        ("クマタカ", "タカ科", "240", "(繁)希少種Ⅰ", "絶滅危惧ⅠB類"),
        ("ヤマドリ", "キジ科", "241", "(繁)減少種G", ""),
    ]),
    ("(繁)絶滅危惧Ⅱ類、(非)準絶滅危惧", [
        ("ミサゴ", "タカ科", "239", "", "準絶滅危惧"),
        ("シロチドリ", "チドリ科", "243", "(繁)絶滅危惧種E、(非)減少種G", ""),
        ("コガラ", "シジュウカラ科", "261", "", ""),
    ]),
    ("(繁)絶滅危惧Ⅱ類、(非)希少種", [
        ("オオタカ", "タカ科", "239", "(繁)希少種Ⅰ", "絶滅危惧Ⅱ類"),
        ("ツミ", "タカ科", "239", "(繁)希少種Ⅰ", ""),
        ("ノスリ", "タカ科", "240", "", ""),
    ]),
    ("(繁)絶滅危惧Ⅱ類", [
        ("ヨシゴイ", "サギ科", "236", "(繁)絶滅危惧種E", ""),
        ("ササゴイ", "サギ科", "237", "(繁)減少種G", ""),
        ("クロサギ", "サギ科", "237", "(繁)絶滅危惧種D", ""),
        ("カッコウ", "カッコウ科", "251", "", ""),
        ("アオバズク", "フクロウ科", "253", "(繁)絶滅危惧種E", ""),
        ("ヨタカ", "ヨタカ科", "253", "(繁)減少種G", ""),
        ("アカショウビン", "カワセミ科", "254", "(繁)希少種Ⅰ", ""),
        ("ビンズイ", "セキレイ科", "256", "", ""),
        ("サンショウクイ", "サンショウクイ科", "257", "(繁)減少種G", "絶滅危惧Ⅱ類"),
        ("コルリ", "ツグミ科", "258", "", ""),
        ("ルリビタキ", "ツグミ科", "258", "", ""),
        ("クロツグミ", "ツグミ科", "259", "", ""),
        ("オオヨシキリ", "ウグイス科", "259", "(繁)減少種H", ""),
        ("メボソムシクイ", "ウグイス科", "259", "", ""),
        ("サンコウチョウ", "カササギヒタキ科", "261", "(繁)減少種H", ""),
        ("アオジ", "ホオジロ科", "262", "(繁)希少種Ⅰ*", ""),
    ]),
    ("(繁)準絶滅危惧、(非)注目種", [
        ("イカルチドリ", "チドリ科", "242", "(繁)減少種G", ""),
    ]),
    ("(繁)準絶滅危惧", [
        ("ジュウイチ", "カッコウ科", "251", "", ""),
        ("フクロウ", "フクロウ科", "253", "(繁)減少種H", ""),
        ("ヤブサメ", "ウグイス科", "259", "(繁)減少種H", ""),
        ("エゾムシクイ", "ウグイス科", "260", "", ""),
        ("センダイムシクイ", "ウグイス科", "260", "", ""),
        ("オオルリ", "ヒタキ科", "261", "(繁)減少種H", ""),
        ("ゴジュウカラ", "ゴジュウカラ科", "261", "", ""),
    ]),
    ("(繁)希少種、(非)準絶滅危惧", [
        ("ケリ", "チドリ科", "243", "(非)減少種G", ""),
    ]),
    ("(繁)希少種、(非)減少種", [
        ("オシドリ", "カモ科", "238", "(繁)希少種Ⅰ", ""),
    ]),
    ("(繁)希少種、(非)注目種", [
        ("イソシギ", "シギ科", "248", "(繁)減少種G、(非)減少種G", ""),
    ]),
    ("(繁)希少種", [
        ("ヤマセミ", "カワセミ科", "254", "", ""),
        ("マミジロ", "ツグミ科", "258", "", ""),
        ("キクイタダキ", "ウグイス科", "260", "(繁)希少種Ⅰ", ""),
        ("ノジコ", "ホオジロ科", "262", "(繁)希少種Ⅰ*", ""),
    ]),
    ("(繁)減少種、(非)減少種", [
        ("カワガラス", "カワガラス科", "258", "", ""),
        ("セッカ", "ウグイス科", "260", "(繁)減少種H、(非)減少種H", ""),
    ]),
    ("(繁)減少種", [
        ("アマサギ", "サギ科", "237", "(繁)減少種G", ""),
        ("ヒメアマツバメ", "アマツバメ科", "254", "", ""),
        ("ヒバリ", "ヒバリ科", "255", "(繁)減少種H、(非)減少種H", ""),
        ("ツバメ", "ツバメ科", "255", "", ""),
        ("コシアカツバメ", "ツバメ科", "256", "(繁)減少種H", ""),
        ("キセキレイ", "セキレイ科", "256", "", ""),
        ("セグロセキレイ", "セキレイ科", "256", "", ""),
        ("モズ", "モズ科", "257", "", ""),
        ("トラツグミ", "ツグミ科", "258", "", ""),
        ("アカハラ", "ツグミ科", "259", "", ""),
        ("キビタキ", "ヒタキ科", "260", "", ""),
        ("カワラヒワ", "アトリ科", "263", "", ""),
    ]),
    ("(繁)注目種、(非)注目種", [
        ("アオバト", "ハト科", "251", "", ""),
    ]),
    ("(繁)注目種", [
        ("コチドリ", "チドリ科", "242", "(繁)減少種G", ""),
    ]),
    ("(繁)情報不足", [
        ("ヤイロチョウ", "ヤイロチョウ科", "255", "", "絶滅危惧ⅠB類"),
    ]),
    ("(繁)情報不足、(非)希少種", [
        ("ハイタカ", "タカ科", "239", "(繁)希少種Ⅰ", "準絶滅危惧"),
    ]),
    ("(繁)不明種、(非)不明種", [
        ("トキ", "トキ科", "237", "", "野生絶滅"),
    ]),
    ("(非)絶滅危惧Ⅰ類", [
        ("ミユビシギ", "シギ科", "246", "(非)減少種G", ""),
        ("ダイシャクシギ", "シギ科", "249", "(非)絶滅危惧種D", ""),
        ("ホウロクシギ", "シギ科", "249", "(非)絶滅危惧種D", "絶滅危惧Ⅱ類"),
        ("トラフズク", "フクロウ科", "252", "(非)絶滅危惧種D", ""),
        ("コミミズク", "フクロウ科", "252", "(非)絶滅危惧種D", ""),
        ("ニュウナイスズメ", "ハタオリドリ科", "263", "(非)絶滅危惧種D", ""),
    ]),
    ("(非)絶滅危惧Ⅱ類", [
        ("オオヨシゴイ", "サギ科", "236", "", "絶滅危惧ⅠB類"),
        ("チュウヒ", "タカ科", "240", "", "絶滅危惧Ⅱ類"),
        ("ウズラ", "キジ科", "241", "(非)減少種H", "情報不足"),
        ("クイナ", "クイナ科", "241", "", ""),
        ("タゲリ", "チドリ科", "244", "(非)減少種G", ""),
        ("キョウジョシギ", "シギ科", "244", "(非)減少種G", ""),
        ("トウネン", "シギ科", "244", "(非)減少種G", ""),
        ("ハマシギ", "シギ科", "245", "(非)減少種H", ""),
        ("サルハマシギ", "シギ科", "245", "", ""),
        ("オバシギ", "シギ科", "246", "(非)絶滅危惧種E", ""),
        ("キアシシギ", "シギ科", "248", "(非)減少種H", ""),
        ("ソリハシシギ", "シギ科", "248", "(非)減少種G", ""),
        ("オグロシギ", "シギ科", "248", "(非)絶滅危惧種F", ""),
        ("オオソリハシシギ", "シギ科", "249", "(非)絶滅危惧種F", ""),
        ("チュウシャクシギ", "シギ科", "249", "(非)減少種G", ""),
        ("コジュリン", "ホオジロ科", "262", "", ""),
        ("オオジュリン", "ホオジロ科", "263", "(非)減少種G", ""),
    ]),
    ("(非)準絶滅危惧", [
        ("ウミウ", "ウ科", "235", "(非)減少種G", ""),
        ("ヒメウ", "ウ科", "236", "(非)減少種G", ""),
        ("ウミアイサ", "カモ科", "238", "", ""),
        ("メダイチドリ", "チドリ科", "243", "(非)減少種H", ""),
        ("ヒバリシギ", "シギ科", "245", "(非)絶滅危惧種F", ""),
        ("ウズラシギ", "シギ科", "245", "(非)減少種H", ""),
        ("エリマキシギ", "シギ科", "246", "(非)絶滅危惧種F", ""),
        ("ツルシギ", "シギ科", "246", "(非)絶滅危惧種F", ""),
        ("アカアシシギ", "シギ科", "246", "", "絶滅危惧Ⅱ類"),
        ("コアオアシシギ", "シギ科", "247", "", ""),
        ("アオアシシギ", "シギ科", "247", "(非)減少種G", ""),
        ("クサシギ", "シギ科", "247", "(非)減少種G", ""),
        ("タカブシギ", "シギ科", "247", "(非)減少種G", ""),
    ]),
    ("(非)希少種", [
        ("トモエガモ", "カモ科", "238", "", "絶滅危惧Ⅱ類"),
        ("シマアジ", "カモ科", "238", "", ""),
        ("ヤマシギ", "シギ科", "249", "(非)減少種G", ""),
    ]),
    ("(非)減少種", [
        ("ムナグロ", "チドリ科", "243", "(非)減少種H", ""),
        ("ダイゼン", "チドリ科", "243", "(非)絶滅危惧種F", ""),
    ]),
    ("(非)注目種", [
        ("タシギ", "シギ科", "250", "(非)減少種H", ""),
    ]),
    ("(非)情報不足", [
        ("サンカノゴイ", "サギ科", "236", "", "絶滅危惧ⅠB類"),
    ]),
    ("絶滅のおそれのある地域個体群", [
        ("サギ類の集団繁殖地", None, "263", "", ""),
    ]),
]

REPTILES = [
    ("絶滅危惧Ⅰ類", [("イシガメ", "イシガメ科", "265", "絶滅危惧種E", "")]),
    ("絶滅危惧Ⅱ類", [("アカウミガメ", "ウミガメ科", "266", "絶滅危惧種E", "絶滅危惧Ⅱ類")]),
    ("準絶滅危惧", [("ヒバカリ", "ヘビ科", "267", "減少種H", "")]),
    ("要注意種", [
        ("トカゲ", "トカゲ科", "266", "減少種H", ""),
        ("シマヘビ", "ヘビ科", "266", "減少種H", ""),
        ("アオダイショウ", "ヘビ科", "267", "減少種H", ""),
        ("ヤマカガシ", "ヘビ科", "267", "減少種H", ""),
        ("マムシ", "クサリヘビ科", "267", "減少種H", ""),
    ]),
]

AMPHIBIANS = [
    ("絶滅危惧Ⅰ類", [
        ("トウキョウサンショウウオ", "サンショウウオ科", "269", "絶滅危惧種D", ""),
        ("イモリ", "イモリ科", "270", "絶滅危惧種F", ""),
        ("トノサマガエル", "アカガエル科", "271", "絶滅危惧種D", ""),
    ]),
    ("絶滅危惧Ⅱ類", [
        ("ヒダサンショウウオ", "サンショウウオ科", "270", "希少種Ⅰ*", ""),
        ("トウキョウダルマガエル", "アカガエル科", "271", "減少種H", ""),
        ("ニホンアカガエル", "アカガエル科", "271", "減少種H", ""),
    ]),
    ("準絶滅危惧", [("ハコネサンショウウオ", "サンショウウオ科", "270", "減少種G", "")]),
    ("希少種", [("ナガレタゴガエル", "アカガエル科", "271", "希少種Ⅰ", "")]),
    ("要注意種", [
        ("アズマヒキガエル", "ヒキガエル科", "270", "減少種H", ""),
        ("ツチガエル", "アカガエル科", "272", "健在種", ""),
        ("シュレーゲルアオガエル", "アオガエル科", "272", "減少種H", ""),
        ("モリアオガエル", "アオガエル科", "272", "希少種Ⅰ*", ""),
    ]),
]

FISH = [
    ("絶滅", [
        ("ヤリタナゴ", "コイ科", "279", "絶滅種", ""),
        ("タナゴ", "コイ科", "279", "絶滅種", "準絶滅危惧"),
    ]),
    ("野生絶滅", [
        ("ミヤコタナゴ", "コイ科", "278", "絶滅種", "絶滅危惧ⅠA類"),
        ("ゼニタナゴ", "コイ科", "280", "絶滅危惧種", "絶滅危惧ⅠB類"),
    ]),
    ("絶滅危惧ⅠA類", [
        ("ギバチ", "ギギ科", "286", "絶滅危惧種F", "絶滅危惧Ⅱ類"),
        ("アカザ", "アカザ科", "287", "", "絶滅危惧Ⅱ類"),
        ("ヤマトイワナ", "サケ科", "287", "絶滅危惧種D", ""),
        ("ヤマメ", "サケ科", "288", "減少種G", ""),
        ("アマゴ", "サケ科", "288", "", ""),
        ("メダカ", "メダカ科", "290", "絶滅危惧種F", "絶滅危惧Ⅱ類"),
        ("カマキリ", "カジカ科", "291", "絶滅危惧種E", ""),
    ]),
    ("絶滅危惧ⅠB類", [
        ("スナヤツメ", "ヤツメウナギ科", "277", "絶滅危惧種E", "絶滅危惧Ⅱ類"),
        ("キンブナ", "コイ科", "278", "", ""),
        ("タカハヤ", "コイ科", "281", "", ""),
        ("ホトケドジョウ", "ドジョウ科", "285", "絶滅危惧種F", "絶滅危惧ⅠB類"),
        ("カワアナゴ", "カワアナゴ科", "292", "絶滅危惧種E", ""),
        ("トビハゼ", "ハゼ科", "293", "絶滅種B", "絶滅のおそれのある地域個体群"),
    ]),
    ("絶滅危惧Ⅱ類", [
        ("マルタ", "コイ科", "281", "絶滅危惧種D", ""),
        ("ニゴイ", "コイ科", "283", "絶滅危惧種F", ""),
        ("カジカ", "カジカ科", "291", "減少種", ""),
    ]),
    ("準絶滅危惧", [
        ("アブラハヤ", "コイ科", "280", "", ""),
        ("ウグイ", "コイ科", "282", "減少種H", ""),
        ("カマツカ", "コイ科", "283", "減少種H", ""),
        ("シマドジョウ", "ドジョウ科", "284", "減少種H", ""),
        ("ボウズハゼ", "ハゼ科", "293", "絶滅危惧種E", ""),
        ("スミウキゴリ", "ハゼ科", "295", "減少種G", ""),
        ("ゴクラクハゼ", "ハゼ科", "296", "減少種G", ""),
        ("オオヨシノボリ", "ハゼ科", "297", "", ""),
        ("ルリヨシノボリ", "ハゼ科", "297", "", ""),
        ("クロヨシノボリ", "ハゼ科", "297", "", ""),
    ]),
    ("注目種", [
        ("ナマズ", "ナマズ科", "286", "減少種", ""),
        ("イッセンヨウジ", "ヨウジウオ科", "289", "", ""),
        ("テングヨウジ", "ヨウジウオ科", "289", "", ""),
        ("ウロハゼ", "ハゼ科", "296", "希少種Ⅰ", ""),
    ]),
    ("情報不足", [
        ("コイ", "コイ科", "278", "減少種H", ""),
        ("アカヒレタビラ", "コイ科", "279", "", "絶滅のおそれのある地域個体群"),
        ("シナイモツゴ", "コイ科", "283", "", "絶滅危惧ⅠB類"),
        ("メナダ", "ボラ科", "289", "絶滅危惧種E", ""),
        ("ウツセミカジカ", "カジカ科", "292", "減少種H", "絶滅危惧Ⅱ類"),
        ("キチヌ", "タイ科", "292", "希少種Ⅰ", ""),
        ("チチブモドキ", "カワアナゴ科", "293", "", ""),
        ("シロウオ", "ハゼ科", "294", "絶滅危惧種D", "準絶滅危惧"),
        ("ミミズハゼ", "ハゼ科", "294", "減少種H", "絶滅のおそれのある地域個体群"),
        ("ヒモハゼ", "ハゼ科", "294", "希少種Ⅰ", ""),
        ("エドハゼ", "ハゼ科", "295", "希少種Ⅰ", ""),
        ("ジュズカケハゼ", "ハゼ科", "295", "希少種Ⅰ", "絶滅のおそれのある地域個体群"),
        ("マサゴハゼ", "ハゼ科", "296", "希少種Ⅰ", "絶滅のおそれのある地域個体群"),
        ("サツキハゼ", "クロユリハゼ科", "298", "希少種Ⅰ", ""),
    ]),
]

GROUPS = [
    ("哺乳類", MAMMALS, 14),
    ("鳥類", BIRDS, 15),        # 15-17ページに跨る(page_noは代表値。cellsには実際のページを入れる)
    ("爬虫類", REPTILES, 17),
    ("両生類", AMPHIBIANS, 17),
    ("汽水・淡水魚類", FISH, 17),  # 17-18ページに跨る
]

EXPECTED_TOTALS = {"哺乳類": 31, "鳥類": 122, "爬虫類": 8, "両生類": 12, "汽水・淡水魚類": 48}


def build_records():
    """(taxon_group_ja, category_ja, vernacular_ja, family_ja, book_page,
        category_prev_ja, national_category_ja, is_population_entry) のフラットなリストを作る。"""
    out = []
    for group_name, cat_blocks, _pageno in GROUPS:
        for category_ja, rows in cat_blocks:
            for (vern, fam, bookpage, prev, nat) in rows:
                out.append({
                    "taxon_group_ja": group_name,
                    "category_ja": category_ja,
                    "vernacular_name_ja": vern,
                    "family_ja": fam,
                    "book_page": bookpage,
                    "category_prev_ja": prev,
                    "national_category_ja": nat,
                    "is_population_entry": fam is None,
                })
    return out


def verify_totals(records):
    counts = {}
    for r in records:
        counts.setdefault(r["taxon_group_ja"], 0)
        counts[r["taxon_group_ja"]] += 1
    print("  [verify] 分類群別件数 (本PDF1ページ目の集計表と突合):")
    ok = True
    for g, expected in EXPECTED_TOTALS.items():
        actual = counts.get(g, 0)
        mark = "OK" if actual == expected else "MISMATCH"
        if actual != expected:
            ok = False
        print(f"    {g}: actual={actual} expected={expected} [{mark}]")
    return ok


# ---------------------------------------------------------------------------
# cells テーブルへの投入(トレーサビリティ用)。
# source_text は当該ページの pdfplumber 生テキストから和名の literal 部分文字列を
# 検索して埋める。見つからない場合は unreadable_reason に「OCR化けのため生テキスト
# に見つからないが、ページ画像を直接目視して転記した」旨を明記し、value_raw 自体は
# ページ画像から直接読み取った値をそのまま保持する(scripts/p1_maker.py の
# pdfplumber テーブル抽出はこの文書では機能しない: find_tables()が全ページ0件)。
# ---------------------------------------------------------------------------
EXTRACTOR = "vision:claude-manual-transcription-2026-08-29"


def page_raw_text_cache():
    import pdfplumber
    cache = {}
    with pdfplumber.open(str(PDF_PATH)) as pdf:
        for p in pdf.pages:
            cache[p.page_number] = p.extract_text() or ""
    return cache


def literal_find(raw_text, needle):
    if not needle:
        return None
    idx = raw_text.find(needle)
    if idx >= 0:
        s = max(0, idx - 15)
        e = min(len(raw_text), idx + len(needle) + 15)
        return raw_text[s:e]
    return None


# ページ割り当て(このPDF内の実際のページ番号 = pdfplumber page_no)。
# 各グループがどのページにまたがるかを row 単位で判定するための助け。
PAGE_HINTS = {
    "哺乳類": [14, 15],
    "鳥類": [15, 16, 17],
    "爬虫類": [17],
    "両生類": [17],
    "汽水・淡水魚類": [17, 18],
}


def populate_cells(records):
    con = sqlite3.connect(DB / "cells.sqlite", timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()
    cur.execute("DELETE FROM cells WHERE doc_id=? AND extractor=?", (DOC_ID, EXTRACTOR))

    rawtext = page_raw_text_cache()
    n_cells = 0
    n_unreadable = 0
    for i, r in enumerate(records):
        group = r["taxon_group_ja"]
        pages = PAGE_HINTS[group]
        # このグループが複数ページに跨る場合、確定的にどのページか分からないので
        # 候補ページ全部を試して見つかったページを採用する。見つからなければ先頭候補を仮に置く。
        found_page = None
        found_text = None
        for pn in pages:
            rt = rawtext.get(pn, "")
            hit = literal_find(rt, r["vernacular_name_ja"])
            if hit:
                found_page = pn
                found_text = hit
                break
        table_id = f"animals2006_{group}"
        row_key = r["vernacular_name_ja"]
        for col_key, value_raw in [
            ("category_ja", r["category_ja"]),
            ("family_ja", r["family_ja"]),
            ("book_page", r["book_page"]),
            ("category_prev_ja", r["category_prev_ja"]),
            ("national_category_ja", r["national_category_ja"]),
        ]:
            if value_raw in (None, ""):
                continue
            unreadable_reason = None
            source_text = found_text
            if source_text is None:
                unreadable_reason = (
                    "OCRテキストに literal 一致なし(スキャンPDFのOCR化けが激しいため)。"
                    "値はページ画像(page_no候補=" + ",".join(map(str, pages)) +
                    ")を直接目視して転記した。"
                )
                n_unreadable += 1
            cur.execute(
                """INSERT INTO cells
                (doc_id, doc_sha256, page_no, table_id, row_key, col_key,
                 value_raw, value, value_type, unit, fiscal_year, era_raw,
                 source_text, source_bbox, notes_ref, is_total, merged,
                 unreadable_reason, confidence, extractor, verified_by, extracted_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (DOC_ID, None, found_page or pages[0], table_id, row_key, col_key,
                 str(value_raw), None, "string", None, LIST_YEAR, None,
                 source_text, None, None, 0, 0,
                 unreadable_reason, None, EXTRACTOR, "claude(vision)", now()),
            )
            n_cells += 1
    con.commit()
    con.close()
    print(f"  [cells] inserted={n_cells} unreadable(no literal OCR match)={n_unreadable}")
    return n_cells, n_unreadable


def write_csvs(records):
    out_rows = []
    for r in records:
        out_rows.append({
            "taxon_group_ja": r["taxon_group_ja"],
            "scientific_name": "",  # 本PDFに学名の記載なし。推測補完はしない。
            "vernacular_name_ja": r["vernacular_name_ja"],
            "family_ja": r["family_ja"] or "",
            "category_code": "",  # 本PDFに英字コード(CR/EN/VU等)の記載なし。
            "category_ja": r["category_ja"],
            "category_prev_ja": r["category_prev_ja"],
            "national_category_ja": r["national_category_ja"],
            "note_ja": ("種ではなく地域個体群/集団繁殖地の単位で評価された行(和名列は個体群等の名称)"
                        if r["is_population_entry"] else
                        f"原典(神奈川県レッドデータ生物調査報告書2006本冊, 634頁)掲載ページ: {r['book_page']}"),
            "list_year": LIST_YEAR,
            "source_id": DOC_ID,
            "source_ref": f"{SOURCE_URL}#group={r['taxon_group_ja']}&name={r['vernacular_name_ja']}",
        })
    cols = ["taxon_group_ja", "scientific_name", "vernacular_name_ja", "family_ja",
            "category_code", "category_ja", "category_prev_ja", "national_category_ja",
            "note_ja", "list_year", "source_id", "source_ref"]
    csv_path = PROC / "kanagawa_redlist_animals_2006.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for row in out_rows:
            w.writerow(row)
    jsonl_path = PROC / "kanagawa_redlist_animals_2006.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for row in out_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  [write] {csv_path} ({len(out_rows)} rows)")
    print(f"  [write] {jsonl_path} ({len(out_rows)} rows)")

    # --- カテゴリー定義表 ---
    # 本PDF(集計結果・一覧)自体にはカテゴリーの定義文(基準の説明文)が見当たらない。
    # 見つかった「カテゴリー名の一覧」だけを、推測の定義文を付けずにそのまま出す。
    cats = []
    seen = set()
    for group_name, cat_blocks, _ in GROUPS:
        for category_ja, _rows in cat_blocks:
            key = (group_name, category_ja)
            if key in seen:
                continue
            seen.add(key)
            cats.append({
                "taxon_group_ja": group_name,
                "category_ja": category_ja,
                "category_code": "",
                "definition_ja": "",
                "list_year": LIST_YEAR,
                "source_id": DOC_ID,
                "source_ref": SOURCE_URL,
                "note_ja": ("本PDF(評価結果一覧, 全29頁)中にカテゴリーの定義文は見当たらず、"
                            "カテゴリー名のみが小見出しとして表中に現れる。定義文は本冊(634頁, 未取得)"
                            "本体に記載されている可能性があるが、本タスクでは未確認のため推測で埋めていない。"
                            + ("鳥類は繁殖期(繁)/非繁殖期(非)で異なるカテゴリーに区分される場合があり、"
                               "その場合は本PDF内の表記通り両方を category_ja に併記している。"
                               if group_name == "鳥類" else "")),
            })
    cat_cols = ["taxon_group_ja", "category_ja", "category_code", "definition_ja",
                "list_year", "source_id", "source_ref", "note_ja"]
    cat_path = PROC / "kanagawa_redlist_animals_2006_categories.csv"
    with open(cat_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cat_cols)
        w.writeheader()
        for row in cats:
            w.writerow(row)
    print(f"  [write] {cat_path} ({len(cats)} category rows)")
    return csv_path, cat_path, out_rows


def norm_id(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def insert_taxa(out_rows):
    """既存 taxa テーブルへ INSERT OR IGNORE のみ(既存行は一切書き換えない)。
    taxon_id の付け方は scripts/c25_taxa_table.py の norm_id() に合わせる。
    学名が無いので、既存実装の分岐通り 'wamei:<和名>' を taxon_id にする。"""
    c = appdb()
    before = c.execute("SELECT COUNT(*) FROM taxa").fetchone()[0]
    n_ins = 0
    n_skip_exists = 0
    n_skip_no_key = 0
    for r in out_rows:
        sci = (r["scientific_name"] or "").strip() or None
        wam = (r["vernacular_name_ja"] or "").strip() or None
        tid = norm_id(sci) if sci else (("wamei:" + norm_id(wam)) if wam else None)
        if not tid:
            n_skip_no_key += 1
            continue
        exists = c.execute("SELECT 1 FROM taxa WHERE taxon_id=?", (tid,)).fetchone()
        code = (r["category_code"] or "").strip()
        redlist_kanagawa = f"{r['category_ja']}（{code}）" if code else r["category_ja"]
        cur = c.execute(
            """INSERT OR IGNORE INTO taxa
            (taxon_id, scientific_name, vernacular_name_ja, taxon_group_ja,
             kingdom, phylum, class, "order", family, genus,
             gbif_taxon_key, gbif_match_type,
             redlist_kanagawa, redlist_national, ias_category,
             source_id, source_ref)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (tid, sci, wam, r["taxon_group_ja"],
             None, None, None, None, r["family_ja"] or None, None,
             None, None,
             redlist_kanagawa, (r["national_category_ja"] or None), None,
             r["source_id"], r["source_ref"]),
        )
        if cur.rowcount == 1:
            n_ins += 1
        else:
            n_skip_exists += 1
    c.commit()
    after = c.execute("SELECT COUNT(*) FROM taxa").fetchone()[0]
    c.close()
    print(f"  [taxa] before={before} after={after} inserted_new={n_ins} "
          f"already_existed(skipped)={n_skip_exists} no_key(skipped)={n_skip_no_key}")
    return before, after, n_ins


def write_pending_gbif(out_rows):
    """学名が無いためGBIF照合は不可能(和名からの学名推測は禁止)。
    かつ現在 c02_gbif_repair.py が動作中のため、そもそも今回はGBIF APIを叩かない。
    参考用に和名一覧だけ出力しておく(将来、学名が別途判明した場合の橋渡し用)。"""
    path = PROC / "taxa_pending_gbif_match.csv"
    # 既存ファイルがあれば追記的に統合(他のバッチが同名ファイルを使っている可能性を考慮し、
    # 既存内容は壊さず末尾に本バッチの分を追加する)。
    existing_header = None
    existing_rows = []
    if path.exists():
        with open(path, encoding="utf-8") as f:
            r = csv.reader(f)
            rows = list(r)
        if rows:
            existing_header = rows[0]
            existing_rows = rows[1:]
    header = ["taxon_id", "scientific_name", "vernacular_name_ja", "taxon_group_ja",
              "source_id", "reason"]
    new_rows = []
    for r in out_rows:
        wam = (r["vernacular_name_ja"] or "").strip()
        tid = "wamei:" + norm_id(wam) if wam else ""
        new_rows.append([
            tid, "", wam, r["taxon_group_ja"], r["source_id"],
            "本PDFに学名の記載なし。和名からの学名推測は禁止のためGBIF照合不可(要人手で学名を別途特定)。",
        ])
    if existing_header and existing_header == header:
        all_rows = existing_rows + new_rows
    else:
        all_rows = new_rows
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(all_rows)
    print(f"  [write] {path} ({len(new_rows)} rows added this run, {len(all_rows)} total)")


NOTES = [
    {
        "note_id": "n_rdb2006_animals_001",
        "table_ids": ["animals2006_鳥類"],
        "kind": "definition_change",
        "text": ("＊鳥類では、繁殖期と非繁殖期で異なるカテゴリーに属する種があるが、"
                 "その場合ここではより厳しいカテゴリーで集計してある。"),
        "page": 1,
        "blocks_timeseries": True,
        "reason": ("鳥類の一部の種は(繁)と(非)で異なるカテゴリーを持つ複合評価であり、"
                   "本CSVのcategory_jaはPDF記載の(繁)/(非)表記をそのまま両方残しているため、"
                   "単純に「1種1カテゴリー」として集計・比較すると県の公式集計(より厳しい方で1本化)"
                   "と数え方が変わる。時系列比較や単純集計の際は要注意。"),
    },
    {
        "note_id": "n_rdb2006_animals_002",
        "table_ids": ["animals2006_哺乳類", "animals2006_鳥類", "animals2006_爬虫類",
                      "animals2006_両生類", "animals2006_汽水・淡水魚類"],
        "kind": "comparability",
        "text": ("本PDF(神奈川県レッドリスト集計結果・一覧, 2006年版)のカテゴリー体系"
                 "(絶滅/野生絶滅/絶滅危惧Ⅰ類・ⅠA類・ⅠB類/絶滅危惧Ⅱ類/準絶滅危惧/減少種/希少種/"
                 "要注意種/注目種/情報不足/不明種/絶滅のおそれのある地域個体群)は、"
                 "現行(2020年版植物編等)の英字コード付きカテゴリー(EX/EW/CR/EN/VU/NT/DD/LP等)"
                 "とは体系が異なり、本PDF中に英字コードの記載は一切ない。"
                 "さらに『旧判定』列には絶滅種A/B, 希少種Ⅰ, 減少種G/H, 健在種Ⅰ/J, "
                 "絶滅危惧種D/E/F/L, 評価検討種 という第三の(1995年前後と推測される、"
                 "本PDF内に年次の明記なし)分類体系が併記されている。"),
        "page": None,
        "blocks_timeseries": True,
        "reason": ("2006年版・(旧判定列が示す)より古い版・2020年版以降版の3つの体系は"
                   "カテゴリー名も区分数も異なり、対応関係を示す公式な変換表が本PDF中に"
                   "見当たらないため、機械的な読み替え・突合はできない。カテゴリー記号の意味を"
                   "推測しないという方針上、本CSVでは原文のカテゴリー名をそのまま残し、"
                   "category_code(英字コード)は全件空欄にしてある。"),
    },
    {
        "note_id": "n_rdb2006_animals_003",
        "table_ids": [],
        "kind": "survey_scope",
        "text": "評価結果一覧（分類群ごと、カテゴリー順で掲載）",
        "page": 1,
        "blocks_timeseries": False,
        "reason": ("本PDF(RedData2006_shukeikekka_ichiran.pdf, 全29ページ)は、"
                   "神奈川県立生命の星・地球博物館サイトのリンク文言にある「634ページ」の"
                   "本冊そのものではなく、本冊の中の『評価結果一覧』章だけを抜き出したPDFである"
                   "(掲載元のリンクテキストが指す634ページは本冊の総ページ数であり、"
                   "本PDFファイル自体は29ページ)。各行の「ページ」列は本冊(634頁)側のページ番号"
                   "を指しており、本PDF内のページ番号(1〜29)とは別物のため、note_ja に"
                   "「原典...掲載ページ」として本冊側のページ番号をそのまま引用してある。"),
    },
    {
        "note_id": "n_rdb2006_animals_004",
        "table_ids": [],
        "kind": "survey_scope",
        "text": "(全29ページ中に「貝類」「甲殻類」「無脊椎」等のキーワードは一度も出現しない)",
        "page": None,
        "blocks_timeseries": False,
        "reason": ("2006年版の本評価結果一覧には、哺乳類・鳥類・爬虫類・両生類・汽水淡水魚類・"
                   "昆虫類・クモ類の7分類群のみが掲載されており、『その他無脊椎動物』"
                   "(貝類・甲殻類等)に相当する区分は存在しない。ユーザー依頼にあった"
                   "『その他無脊椎動物』のデータは、本PDFには含まれていない(取得漏れではなく"
                   "原資料に該当区分自体が無い)。"),
    },
    {
        "note_id": "n_rdb2006_animals_005",
        "table_ids": [],
        "kind": "footnote",
        "text": ("＊菌類では「／情報不足」と付記されたカテゴリーに属する種があるが、"
                 "ここではそれを付記してないものとみなして集計してある。"),
        "page": 1,
        "blocks_timeseries": False,
        "reason": "菌類に関する注記であり、本タスクの対象(動物編)には直接関係しないが原文のまま記録する。",
    },
    {
        "note_id": "n_rdb2006_animals_006",
        "table_ids": [],
        "kind": "definition_change",
        "text": "本PDF中に学名(ラテン語二名法)の記載は一切なく、和名と科名(和名表記)のみが記載されている。",
        "page": None,
        "blocks_timeseries": False,
        "reason": ("和名から学名を推測して補完することは禁止されているため、"
                   "kanagawa_redlist_animals_2006.csv の scientific_name は全件空欄。"
                   "taxa テーブルへの投入も taxon_id='wamei:<和名>' 方式(学名なし)で行っている。"
                   "GBIF学名照合(FR未達)は学名が無いため原理的に実施不可能。"),
    },
]


def insert_notes():
    con = sqlite3.connect(DB / "cells.sqlite", timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()
    for n in NOTES:
        cur.execute(
            """INSERT OR REPLACE INTO notes
            (note_id, doc_id, table_ids, kind, text, page, blocks_timeseries, reason)
            VALUES (?,?,?,?,?,?,?,?)""",
            (n["note_id"], DOC_ID, json.dumps(n["table_ids"], ensure_ascii=False),
             n["kind"], n["text"], n["page"], int(n["blocks_timeseries"]), n["reason"]),
        )
    con.commit()
    con.close()
    print(f"  [notes] inserted {len(NOTES)} notes for {DOC_ID}")


def update_source_registry(n_records):
    c = appdb()
    c.execute(
        """UPDATE source_registry SET record_count=?, fetched_at=?, notes=? WHERE source_id=?""",
        (n_records, now(),
         ("動物編(哺乳類31・鳥類122・爬虫類8・両生類12・汽水淡水魚類48=計221種/個体群)を"
          "ページ画像の目視転記で取得。件数はPDF1ページ目の集計表(分類群ごとに集計した評価結果)"
          "と完全一致で突合済み。学名の記載が原本に無いため scientific_name は全件空欄"
          "(和名からの学名推測は行っていない)。カテゴリー体系は2020年版と異なり英字コードなし"
          "(詳細は notes テーブル/P4注記参照)。昆虫類・クモ類はkanagawa_redlist(2026年版)で"
          "別途取得済みのため対象外。『その他無脊椎動物』は原本に区分自体が存在せず未取得。"
          "出力: data/processed/kanagawa_redlist_animals_2006.csv, "
          "kanagawa_redlist_animals_2006_categories.csv。"
          "リンク文言の『634ページ』は本冊の総頁数であり本PDF自体は29ページ"
          "(評価結果一覧のみの抜粋)。"),
         DOC_ID),
    )
    c.commit()
    c.close()
    print(f"  [registry] {DOC_ID}: record_count={n_records}")


def main():
    records = build_records()
    ok = verify_totals(records)
    if not ok:
        print("  !! 分類群別件数が想定と一致しない行がある。処理は継続するが要確認。")
    n_cells, n_unreadable = populate_cells(records)
    csv_path, cat_path, out_rows = write_csvs(records)
    before, after, n_ins = insert_taxa(out_rows)
    write_pending_gbif(out_rows)
    insert_notes()
    update_source_registry(len(out_rows))
    print(f"\nTOTAL records={len(records)} cells={n_cells}(unreadable_by_ocr={n_unreadable}) "
          f"taxa {before}->{after} (+{n_ins})")


if __name__ == "__main__":
    main()
