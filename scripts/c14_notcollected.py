"""取得しなかった/取得できなかったソースの記録（COLLECTOR_CONTRACT 3. に従い必ず register する）"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import *

# 1) かながわの水がめ（神奈川県企業庁）— 著作権表示により再配布不可のためデータ取得せず
register(
    "kanagawa_dam_mizugame", "かながわの水がめ（相模川・酒匂川水系 降水量/貯水量/ダム諸量）",
    "神奈川県企業庁", "https://kanagawa-dam.jp/", "水文",
    "JSON API（/api/rainfall-table.php?g=sagami|sakawa, /api/quantity-3days.php?n=sagami|shiroyama|miho|doushi, "
    "/api/quantity-water-level.php, /api/quantity-flow-rate.php, /api/dam-discharge.php）",
    "JSON", "無断複製・転用不可（サイトポリシー）", 0, 0,
    "再配布不可: https://kanagawa-dam.jp/web_data/sitepolicy.html 原文引用「「かながわの水がめ」及び掲載している"
    "個々の情報は著作権の対象になっています。「私的使用のための複製」や「引用」など著作権法上認められた場合を除き、"
    "無断で複製・転用することはできません。」→ COLLECTOR_CONTRACT「ライセンス」に従いダウンロードせず登録のみ。"
    "参考（実在確認済みの機械判読エンドポイント）: GET /api/rainfall-table.php?g=sagami は "
    "{lastUpdate, data:{beforeLast,last,current,avg}} 形式で当年・前年・前々年・10か年平均の月別降水量(mm)を返す。"
    "GET /api/quantity-3days.php?n=sagami は過去3日間の正時データ "
    "[{rain,rain_sum,v(貯水位EL.m),v_active(有効貯水量 千m3),v_per(有効貯水率%),in(流入量 m3/s),"
    "out_v(発電放流量),out_g(ゲート放流量),out_sum(下流放流量),dt}] を返す。")

# 2) 国交省 水文水質データベース — サイト側が自動収集を明示的に非推奨
register(
    "mlit_river_hydro", "国土交通省 水文水質データベース", "国土交通省",
    "https://www1.river.go.jp/", "水文", "CGI (SrchSite.exe 等)", "HTML",
    "公共データ利用規約（第1.0版）", 1, 0,
    "取得せず。素の curl では 403 だが、通常ブラウザ相当の User-Agent + Referer で 200 になることは確認した"
    "（https://www1.river.go.jp/ および /cgi-bin/SrchSite.exe?KOMOKU=0&SUIKEI=0&KEN=0）。"
    "ただし https://www1.river.go.jp/caution.html に原文で「また、当ホームページは一般を対象としており、"
    "通常のブラウザで閲覧することを前提に情報を掲載しております。ツール等による、自動的なデータ収集等は"
    "サーバに負荷がかかり、情報提供できなくなる恐れがありますので原則としてご遠慮ください。ご理解・ご協力"
    "お願いします。」とあるため、自動収集を行わない判断とした。"
    "同ページの時系列比較上の注意（原文）:「暫定値（青字表記）とは、現在の観測データから過去の統計データまで"
    "シームレスにお知らせすることを目的として、無人観測所から送られてくるデータをそのままデータベースに登録"
    "公表しているものであり、観測機器の故障、通信異常などによる欠測や異常値を含んでいる可能性があります。"
    "したがって、防災面での利用や統計データとしての利用には十分注意して下さい。」")

# 3) 平塚市の大気環境状況 — 経路は確認済みだが本デモでは取り込まず（重複と行数）
register(
    "hiratsuka_taiki", "平塚市の大気環境状況 確定値1時間値", "平塚市（環境保全課）",
    "https://hiratsukataiki.sakura.ne.jp/", "大気",
    "静的CSV: https://hiratsukataiki.sakura.ne.jp/download/<年度>_<局番>.csv", "CSV",
    "利用条件の明示なし（自治体公開データ・出典明示前提）", 1, 0,
    "取得せず（そらまめ君・相模原市と項目が重複し、5局×13年度×1時間値=数百万行になるため本デモの範囲外）。"
    "アクセス方法は確認済み: 年度=2013〜2025、局番=101 大野公民館 / 102 神田小学校 / 103 旭小学校 / "
    "104 花水小学校 / 105 松原歩道橋。CSV はヘッダ無し 27列 = 日付(YYYYMMDD),局番,項目CD(001-016),1時〜24時。"
    "項目CDは koumoku.php の並び順（001 SO2,002 NO,003 NO2,004 NOX,005 CO,006 OX,007 NMHC,008 CH4,009 THC,"
    "010 SPM,011 PM2.5,012 WD,013 WS,014 TEMP,015 HUM,016 RAIN）と一致することを、"
    "そらまめ君の同一局（14203100 大野公民館）2025-08-01 の1時間値と突合して確認済み"
    "（例: SO2/NO2/OX は ppm×1000、SPM は mg/m3×1000、TEMP/HUM/WS は ×10 の整数表現）。"
    "時系列比較を妨げる注記（原文, https://hiratsukataiki.sakura.ne.jp/download-kakutei.php）:"
    "「※ 大野公民館測定局の窒素酸化物濃度については、2014 年度から2019 年度まで測定値が高めに出ていたことが"
    "確認されていますので、個別の測定結果を取り扱う場合には注意してください。」")

print("  done")
