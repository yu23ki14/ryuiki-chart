"""
さがみはらデジタルアーカイブ（相模原市立博物館ほか / Drupal10サイト）
https://digital-sagamihara.jp/digital-archive/

## 事実確認
- OAI-PMH: 無し。/jsonapi (Drupal標準JSON:API) も404で無効化されている。
- sitemap.xml: 無し(404)。robots.txt はDrupal標準内容で /digital-archive 配下に
  Disallowは無い(クロール可能)。
- サイトはDrupal10 + 独自JS(jQuery)によるSPA的検索UIで、内部で以下の非公開だが
  認証不要のJSON APIを呼び出している(JSファイルからエンドポイントを発見):
      GET https://digital-sagamihara.jp/api/list-product
      パラメータ: domain=archive (総合目録・6件超) / 省略時は「写真で見るさがみはら」
                  (記録写真のみ、category=2で1,004件) にスコープされる。
                  category[0]=<id> でカテゴリ絞り込み。category一覧:
                  1=文化財,2=記録写真,3=歴史,4=天文,5=生物,6=図書館資料,
                  7=歴史的公文書,8=広報,9=民俗,11=館報等,12=考古,
                  13=収蔵美術品,14=保存行政資料,15=広報的資料
                  page, perPage(最大1000で確認), hasImage 等。
      レスポンスは JSON (records: {collection_id: {"ja": {...}}} 形式)。
- category[0]=5 (生物) を domain=archive で叩くと 15,737 件がヒット。
  中身は相模原市立博物館の自然史標本(コケ・シダ・種子植物などの押し葉標本が中心、
  genre_id 12/24/26 で構成)で、標本名(和名)・所蔵機関・カテゴリ・権利(ほぼCC0)・
  作成日時・IIIFマニフェストURLが一覧APIから取得できる。
- 個別資料ページ(例 /digital-archive/29840)には採集地(都道府県/市町村/調査地)・
  採集年月日・採集者名など、より詳細な項目がHTML表として存在するが、コレクション
  ごとに項目名が異なる可変スキーマであり、15,737件全件を個別に取得すると
  リクエスト数が膨大(15,737件×1.5秒=6時間超)になるため、今回は一覧APIで
  取得できる範囲(目録)のみを収集する。個別ページの構造は本ファイル末尾のコメント
  に記録。

## ライセンス確認 (https://digital-sagamihara.jp/terms)
- 「２-１．目録情報の二次利用について」:
  デジタルアーカイブで公開している"目録情報"は、オープンデータとしてCC0
  (CC0 1.0 全世界 パブリック・ドメイン提供) で提供される。→ 今回取得する
  タイトル・カテゴリ等のメタデータはCC0で再配布可。
- 「２-２．デジタル画像等の二次利用について」: 画像そのものは資料詳細ページの
  表示に従う。市立博物館所蔵資料については「資料写真の二次利用については、
  市立博物館へお問い合わせください。」と明記されており、画像の再配布には
  別途問い合わせが必要。→ 本スクリプトは画像はダウンロードせず、目録情報
  (CC0)のみを収集する。
"""
import sys, pathlib, csv, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import get, register, write_jsonl, PROC, RAW, now

SOURCE_ID = "sagamihara_digital_archive"
API = "https://digital-sagamihara.jp/api/list-product"
ITEM_BASE = "https://digital-sagamihara.jp/digital-archive/"
PER_PAGE = 1000

def fetch_all_biology_records():
    rows = []
    page = 1
    total_pages = None
    while True:
        r = get(API, params={
            "domain": "archive",
            "category[0]": "5",
            "page": page,
            "perPage": PER_PAGE,
        })
        d = r.json()["data"]
        if total_pages is None:
            total_pages = d.get("totalPages", 1)
            print(f"  recordsTotal={d.get('recordsTotal')} totalPages={total_pages}")
        records = d.get("records") or {}
        # records can be a dict (collection_id -> {"ja": {...}}) or an empty list
        items = records.items() if isinstance(records, dict) else []
        for cid, byLang in items:
            ja = (byLang or {}).get("ja") or {}
            collection_id = ja.get("collection_id") or cid
            rows.append({
                "source_id": SOURCE_ID,
                "source_ref": f"{ITEM_BASE}{collection_id}",
                "item_url": f"{ITEM_BASE}{collection_id}",
                "collection_id": collection_id,
                "title_ja": ja.get("title"),
                "title_kana_ja": ja.get("title_kana"),
                "category_ja": ja.get("category"),
                "organization_ja": ja.get("organization"),
                "content_type_ja": ja.get("content_type"),
                "copyright_ja": ja.get("copyright"),
                "genre_id": ja.get("genre_id"),
                "doi": ja.get("doi"),
                "created_at_raw": ja.get("created_at"),
                "updated_at_raw": ja.get("updated_at"),
                "iiif_manifest_url": ja.get("iiif"),
            })
        print(f"  page {page}/{total_pages}: +{len(items)} rows (total {len(rows)})")
        if page >= total_pages or not items:
            break
        page += 1
    return rows

def main():
    RAW.joinpath(SOURCE_ID).mkdir(parents=True, exist_ok=True)
    try:
        rows = fetch_all_biology_records()
    except Exception as e:
        register(SOURCE_ID,
                 name="さがみはらデジタルアーカイブ 生物カテゴリ目録",
                 publisher="相模原市（相模原市立博物館ほか）",
                 url="https://digital-sagamihara.jp/digital-archive/",
                 category="自然史標本",
                 access_method="非公開JSON API(/api/list-product?domain=archive&category[0]=5)を"
                                "JSバンドルから発見して取得試行",
                 fmt="JSON",
                 license_="不明(取得失敗)",
                 redistributable=0,
                 record_count=0,
                 notes=f"取得中にエラー: {e!r}")
        raise

    if not rows:
        register(SOURCE_ID,
                 name="さがみはらデジタルアーカイブ 生物カテゴリ目録",
                 publisher="相模原市（相模原市立博物館ほか）",
                 url="https://digital-sagamihara.jp/digital-archive/",
                 category="自然史標本",
                 access_method="非公開JSON API(/api/list-product?domain=archive&category[0]=5)",
                 fmt="JSON",
                 license_="目録情報はCC0 1.0 (相模原市デジタルアーカイブ利用規約2-1)",
                 redistributable=0,
                 record_count=0,
                 notes="category[0]=5(生物)で0件。API仕様変更の可能性あり。")
        return

    # CSV / JSONL 出力
    fieldnames = list(rows[0].keys())
    csv_path = PROC / f"{SOURCE_ID}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"  [write] {csv_path} {len(rows)} rows")
    write_jsonl(SOURCE_ID, rows)

    register(SOURCE_ID,
             name="さがみはらデジタルアーカイブ 生物カテゴリ目録（相模原市立博物館 自然史標本）",
             publisher="相模原市（相模原市立博物館）",
             url="https://digital-sagamihara.jp/digital-archive/?category=5",
             category="自然史標本",
             access_method="HTMLからJSバンドルを解析し非公開JSON APIを発見して取得: "
                            "GET /api/list-product?domain=archive&category[0]=5&page=<n>&perPage=1000 "
                            "(OAI-PMHやjsonapiは無し。robots.txt/sitemap.xmlも確認済み)",
             fmt="JSON->CSV/JSONL",
             license_="目録情報はCC0 1.0 全世界パブリック・ドメイン提供"
                      "(https://digital-sagamihara.jp/terms 2-1)。"
                      "個別資料の画像2次利用は所蔵機関(市立博物館)へ要問合せのため画像は未取得。",
             redistributable=1,
             record_count=len(rows),
             notes="相模原市立博物館所蔵の自然史標本(押し葉標本等、コケ・シダ・種子植物が中心)"
                   "の目録。一覧APIで取得できるのはtitle/organization/category/copyright/"
                   "genre_id/created_at/updated_at/iiif_manifest_urlのみ。個別資料ページ"
                   "(/digital-archive/<id>)には採集地(都道府県/市町村/調査地)・採集年月日・"
                   "採集者名等の詳細項目がHTML表として存在するが、コレクションごとに項目名が"
                   "異なりスキーマが不定であること、15,737件全件を個別取得すると"
                   "リクエスト数が膨大になることから、今回は一覧APIの目録情報のみを収集した。")

if __name__ == "__main__":
    main()
