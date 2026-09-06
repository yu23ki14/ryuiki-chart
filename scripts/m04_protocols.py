"""アプリDB protocols / instruments の構築。

素材: data/raw/kanagawa_river_monitoring/ の PDF一式（神奈川県 環境科学センター
「県民参加型調査」関連文書、実在するプロトコル文書）。
- manyual.pdf（44ページ、共通マニュアル）から「６ 調査の流れ」章（p.8-13）の
  ①〜⑦の手順を読み取り steps_json に入れる。読み取れない・存在しない部分は
  空配列のままにし、推測で埋めない。
- gyorui/syokubutu/ryouseirui/tyourui.pdf は分類群別の「現地調査シート」（種の
  チェックリスト・簡易図鑑）であり、手順書ではないため steps_json=[]。
- genchisheet-teisei.pdf（底生動物 現地調査シート）は画像のみのスキャンPDFで
  pdfplumberによるテキスト抽出が0文字だった（実際に確認済み）。steps_json=[]。
- instruments はマニュアル本文に機材名として明記されているもの（温度計・pHメーター）
  のみ登録する。校正記録は公開文書に記載が無いため uncalibrated_flag=1 とし、
  その根拠を calibration_note に残す。

冪等性: protocol_id / instrument_id を主キーに INSERT OR REPLACE。
"""
import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import appdb, RAW

SOURCE_ID = "kanagawa_river_citizen_survey"
DOC_BASE_URL = "https://www.pref.kanagawa.jp/documents/3188/"
RAW_DIR = RAW / "kanagawa_river_monitoring"

MAIN_STEPS = [
    {"step": 1, "title": "調査の計画を立てる",
     "description": "何を調べたいか（水質・底生動物・魚類・植物・両生類・鳥類）と、いつ・どこで"
                    "調査するかを決める。分類群ごとに適期・適地が異なる（底生動物は8〜9月/12〜1月、"
                    "魚類は初夏〜秋、植物は春と秋が適期、と本文に記載）。"},
    {"step": 2, "title": "調査に必要な手続きを行う",
     "description": "底生動物・魚類を調査する場合は事前に特別採捕許可の登録が必要（環境科学センター"
                    "が手続き）。調査の1週間前までに調査日時・場所・使用する漁具を事務局へ連絡する。"
                    "投網利用時や多人数実施時はのぼり旗を掲げる。"},
    {"step": 3, "title": "調査に必要な道具を用意する",
     "description": "分類群別に必要な道具が本文に列挙されている："
                    "底生動物＝濡れてよい服・長靴・タモ網・バケツ・白色バット・ピンセット・ルーペ・"
                    "サンプル瓶・固定液(エタノール)／魚類＝同左＋観察用アクリル水槽／植物＝ビニール袋・"
                    "剪定ばさみ・新聞紙／水質＝温度計・pHメーター／共通＝調査シート・筆記用具・カメラ・"
                    "調査マニュアル・図鑑・のぼり旗・救急箱・緊急連絡先。下線付きの道具は貸出可。"},
    {"step": 4, "title": "現地調査をする",
     "description": "共通シート(表)にまず調査日時・場所・水質の状況を記録する。水質は水質ランク"
                    "(人の五感)・気温(温度計、直射日光を避けて測定)・水温(温度計、採水後直ちに測定)・"
                    "pH(pHメーター)を測定する。分類群ごとの採集・観察方法が本文に定められている"
                    "（底生動物＝タモ網で1分間×3箇所採取、魚類＝投網、植物＝踏査）。"},
    {"step": 5, "title": "標本を作成する（必要な場合）",
     "description": "底生動物・魚類は現地で名前が分からない個体をアルコール(70〜80%)で固定・保存し、"
                    "採集ラベル・同定ラベルを付す（ホルマリンは劇物のため使用しない）。植物は新聞紙に"
                    "挟んで乾燥させる。"},
    {"step": 6, "title": "同定する",
     "description": "調査シート・図鑑・顕微鏡等を用いて種を同定する。名前が分からない場合は写真・"
                    "標本を事務局に送り、専門家に同定してもらうことができる。"},
    {"step": 7, "title": "記録・報告する",
     "description": "共通シート・現地調査シート・結果シートの3種に記録する。共通シート・結果シートは"
                    "電子メールまたは郵送で事務局へ提出する。調査期間後の提出分は次年度の調査結果として"
                    "扱われる（本文注記）。"},
]

PROTOCOLS = [
    {
        "protocol_id": f"{SOURCE_ID}__manual",
        "name": "県民参加型調査 調査マニュアル（神奈川県環境科学センター）",
        "version": None,
        "domain": "河川モニタリング(水質・底生動物・魚類・植物・両生類・鳥類 総合)",
        "steps_json": MAIN_STEPS,
        "url": DOC_BASE_URL + "manyual.pdf",
    },
    {
        "protocol_id": f"{SOURCE_ID}__fish_sheet",
        "name": "県民参加型調査 現地調査シート（魚類）",
        "version": None, "domain": "魚類",
        "steps_json": [],  # 種チェックリスト形式の簡易図鑑で、手順の記載なし
        "url": DOC_BASE_URL + "gyorui.pdf",
    },
    {
        "protocol_id": f"{SOURCE_ID}__plant_sheet",
        "name": "県民参加型調査 現地調査シート（植物）",
        "version": None, "domain": "植物",
        "steps_json": [],
        "url": DOC_BASE_URL + "syokubutu.pdf",
    },
    {
        "protocol_id": f"{SOURCE_ID}__amphibian_sheet",
        "name": "県民参加型調査 現地調査シート（補足記録：両生類）",
        "version": None, "domain": "両生類",
        "steps_json": [],
        "url": DOC_BASE_URL + "ryouseirui.pdf",
    },
    {
        "protocol_id": f"{SOURCE_ID}__bird_sheet",
        "name": "県民参加型調査 現地調査シート（補足記録：鳥類）",
        "version": None, "domain": "鳥類",
        "steps_json": [],
        "url": DOC_BASE_URL + "tyourui.pdf",
    },
    {
        "protocol_id": f"{SOURCE_ID}__benthos_sheet",
        "name": "県民参加型調査 現地調査シート（底生動物）",
        "version": None, "domain": "底生動物",
        # pdfplumberでテキスト抽出0文字（画像のみのスキャンPDF、4ページとも images>0, text=0を確認済み）
        "steps_json": [],
        "url": DOC_BASE_URL + "genchisheet-teisei.pdf",
    },
]

INSTRUMENTS = [
    {
        "instrument_id": f"{SOURCE_ID}__thermometer",
        "kind": "温度計（気温・水温測定用）",
        "model": None,
        "calibrated_on": None,
        "calibration_note": "調査マニュアル本文(p.9-10)に機材名の記載はあるが、校正記録・校正手順の"
                            "記載は無い（公開文書からは校正状況が確認できない）。",
        "uncalibrated_flag": 1,
    },
    {
        "instrument_id": f"{SOURCE_ID}__ph_meter",
        "kind": "pHメーター",
        "model": None,
        "calibrated_on": None,
        "calibration_note": "同上（調査マニュアルに機材名の記載はあるが校正記録の記載なし）。",
        "uncalibrated_flag": 1,
    },
]

def main():
    conn = appdb()
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")

    # 実ファイル存在確認（読み取れると主張する前に実在を確認する）
    missing = [p["url"].rsplit("/", 1)[-1] for p in PROTOCOLS
               if not (RAW_DIR / p["url"].rsplit("/", 1)[-1]).exists()]
    if missing:
        print(f"  !! 警告: 以下のPDFが data/raw に見当たらない: {missing}")

    conn.executemany(
        """INSERT OR REPLACE INTO protocols
           (protocol_id, name, version, domain, steps_json, source_id, url)
           VALUES (?,?,?,?,?,?,?)""",
        [(p["protocol_id"], p["name"], p["version"], p["domain"],
          json.dumps(p["steps_json"], ensure_ascii=False), SOURCE_ID, p["url"])
         for p in PROTOCOLS])

    conn.executemany(
        """INSERT OR REPLACE INTO instruments
           (instrument_id, kind, model, calibrated_on, calibration_note, uncalibrated_flag)
           VALUES (?,?,?,?,?,?)""",
        [(i["instrument_id"], i["kind"], i["model"], i["calibrated_on"],
          i["calibration_note"], i["uncalibrated_flag"]) for i in INSTRUMENTS])
    conn.commit()

    n_p = conn.execute("select count(*) from protocols").fetchone()[0]
    n_i = conn.execute("select count(*) from instruments").fetchone()[0]
    print(f"  protocols: +{len(PROTOCOLS)} (table total={n_p})")
    print(f"  instruments: +{len(INSTRUMENTS)} (table total={n_i})")
    conn.close()

if __name__ == "__main__":
    main()
