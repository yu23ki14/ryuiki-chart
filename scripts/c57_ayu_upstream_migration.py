"""相模川漁連 寒川取水堰 天然アユ遡上調査 -> data/processed/ayu_upstream_migration.csv

相模川漁業協同組合連合会サイト(http://sagamigawa-gyoren.jp/topics/)の「お知らせ」記事を
手作業で選別し(自動全文検索は機能しなかったため、お知らせ一覧を最大約220ページ+直近8ページ
遡って「遡上」「寒川」を含む記事タイトルを収集)、各記事本文に記載された遡上数をそのまま転記した。

【重要・厳守】
- 取れた年だけを記録する。欠測年(例: 2026年=令和8年シーズン)は本タスクで確認した限り
  該当記事が「お知らせ」フィードに見当たらなかった。これは調査自体が行われなかったことを
  意味しない(単に告知されていない可能性がある)ため、理由を断定せず「記事未検出」とだけ記す。
- count_type='cumulative' はシーズン開始(通常3月1日)からの累積尾数、
  'period' は当該記事が言及する期間限定の尾数(例:その月だけの尾数)。
  両者は単純に合算できない(累積と期間内訳が両方載っている記事はそのまま両方残す)。
- 調査方法(目視 or 魚道の数)が年によって異なる旨の原文注記がある場合は note_ja に原文のまま残す。
  例: 2022年記事(453)「２月２０日から遡上アユ目視調査を行い、３月１日から６カ所の魚道で
  遡上数調査を行っています」/ 2025年記事(2214)「７番漁場道は含まれません」
  → 年によって集計対象の魚道数が異なる可能性があり、年またぎの単純比較はできない。
"""
import sys, csv
sys.path.insert(0, "scripts")
from common import register, write_jsonl, PROC

STATION = "寒川取水堰(相模川)"
METHOD_DEFAULT = "目視によるアユ遡上数調査(寒川取水堰魚道)"

# (article_url, article_date, year, count_type, period_raw, count, note_ja)
ROWS = [
    ("http://sagamigawa-gyoren.jp/topics/453/", "2022-05-10", 2022, "cumulative",
     "2月20日(目視開始)〜3月1日(6カ所の魚道での計数開始)〜5月10日現在", 11_115_996,
     "原文:「２月２０日から遡上アユ目視調査を行い、３月１日から６カ所の魚道で遡上数調査を行っています」"
     "。2月20日〜28日は目視のみ、3月1日以降は6カ所の魚道での計数に変更されており、"
     "調査方法がシーズン内で変化している点に注意。"),
    ("http://sagamigawa-gyoren.jp/topics/521/", "2022-06-10", 2022, "cumulative",
     "3月1日〜5月31日(シーズン最終)", 11_694_770, "2022年シーズンの最終集計(原文:「合計尾数」)"),

    ("http://sagamigawa-gyoren.jp/topics/737/", "2023-03-08", 2023, "cumulative",
     "3月1日〜3月7日", 27_116, ""),
    ("http://sagamigawa-gyoren.jp/topics/789/", "2023-03-17", 2023, "cumulative",
     "3月1日〜3月17日", 1_012_384, "原文:「3月17日(金)は1日で403,930尾 17日間で一番遡上数が多くなりました」"),
    ("http://sagamigawa-gyoren.jp/topics/822/", "2023-03-31", 2023, "cumulative",
     "3月1日〜3月31日", 5_791_904, "原文:「3月18日から31日は、河川の増水や強風によって調査中止の日が数日ありました」"),
    ("http://sagamigawa-gyoren.jp/topics/832/", "2023-04-11", 2023, "period",
     "4月1日〜4月10日", 4_142_052, ""),
    ("http://sagamigawa-gyoren.jp/topics/832/", "2023-04-11", 2023, "cumulative",
     "3月1日〜4月10日", 9_933_956, ""),
    ("http://sagamigawa-gyoren.jp/topics/844/", "2023-04-18", 2023, "period",
     "4月1日〜4月17日", 12_802_242, ""),
    ("http://sagamigawa-gyoren.jp/topics/844/", "2023-04-18", 2023, "cumulative",
     "3月1日〜4月17日", 18_594_146, ""),
    ("http://sagamigawa-gyoren.jp/topics/872/", "2023-04-25", 2023, "period",
     "4月1日〜4月25日", 14_788_960, ""),
    ("http://sagamigawa-gyoren.jp/topics/872/", "2023-04-25", 2023, "cumulative",
     "3月1日〜4月25日", 20_580_864, ""),
    ("http://sagamigawa-gyoren.jp/topics/906/", "2023-05-01", 2023, "period",
     "4月1日〜4月30日", 15_287_376, ""),
    ("http://sagamigawa-gyoren.jp/topics/906/", "2023-05-01", 2023, "cumulative",
     "3月1日〜4月30日", 21_079_280, ""),
    ("http://sagamigawa-gyoren.jp/topics/927/", "2023-05-10", 2023, "period",
     "5月1日〜5月10日", 413_225, ""),
    ("http://sagamigawa-gyoren.jp/topics/927/", "2023-05-10", 2023, "cumulative",
     "3月1日〜5月10日", 21_492_505, ""),
    ("http://sagamigawa-gyoren.jp/topics/979/", "2023-05-16", 2023, "period",
     "5月1日〜5月16日", 466_147, ""),
    ("http://sagamigawa-gyoren.jp/topics/979/", "2023-05-16", 2023, "cumulative",
     "3月1日〜5月16日", 21_545_427, ""),
    ("http://sagamigawa-gyoren.jp/topics/1014/", "2023-05-25", 2023, "period",
     "5月1日〜5月24日", 646_273, ""),
    ("http://sagamigawa-gyoren.jp/topics/1014/", "2023-05-25", 2023, "cumulative",
     "3月1日〜5月24日", 21_725_553, ""),
    ("http://sagamigawa-gyoren.jp/topics/1035/", "2023-06-01", 2023, "period",
     "5月1日〜5月31日", 665_020, ""),
    ("http://sagamigawa-gyoren.jp/topics/1035/", "2023-06-01", 2023, "cumulative",
     "3月1日〜5月31日(シーズン最終・92日間)", 21_744_300,
     "原文:「寒川遡上調査 令和5年3月1日から5月31日 92日間の遡上調査報告 最終となります」"),

    ("http://sagamigawa-gyoren.jp/topics/1422/", "2024-03-11", 2024, "cumulative",
     "3月1日〜3月11日", 42_378, ""),
    ("http://sagamigawa-gyoren.jp/topics/1446/", "2024-03-18", 2024, "cumulative",
     "3月1日〜3月26日", 368_263,
     "原文:「12日から18日までの天候は良好でしたが、北風の強い日が続きました.(18日分修正）"
     "19日から26日は、遡上を確認できませんでした」"),
    ("http://sagamigawa-gyoren.jp/topics/1478/", "2024-04-02", 2024, "period",
     "3月月間", 1_130_826, "原文:「3月最終土日は、季節外れの暑さとなり2日間で758,414尾遡上しました」"),
    ("http://sagamigawa-gyoren.jp/topics/1497/", "2024-05-31", 2024, "period",
     "5月1日〜5月31日", 744_894, ""),
    ("http://sagamigawa-gyoren.jp/topics/1497/", "2024-05-31", 2024, "cumulative",
     "3月1日〜5月31日(シーズン最終)", 9_009_852,
     "原文:「3月1日から5月31日まで3ヶ月間、相模川下流 寒川取水堰でのあゆ遡上調査が終了いたしました」"),

    ("http://sagamigawa-gyoren.jp/topics/2117/", "2025-03-18", 2025, "cumulative",
     "3月1日〜3月17日", 292_927, "原文:「天候は定まらず、水温が上昇しない日が続いて、遡上条件は整っていません」"),
    ("http://sagamigawa-gyoren.jp/topics/2168/", "2025-04-04", 2025, "period",
     "3月月間", 1_183_406,
     "原文:「3月最終土曜日は、雨水量が多く、水温が低いため調査は中止となりました。"
     "最終日曜日は外気温が寒く、水温が低く遡上が見られませんでした」"),
    ("http://sagamigawa-gyoren.jp/topics/2181/", "2025-04-09", 2025, "cumulative",
     "3月1日〜4月7日", 2_117_317, ""),
    ("http://sagamigawa-gyoren.jp/topics/2191/", "2025-04-16", 2025, "cumulative",
     "3月1日〜4月16日", 3_327_143, "原文:「晴れて、水温が高い日は、遡上が沢山ありました」"),
    ("http://sagamigawa-gyoren.jp/topics/2214/", "2025-05-14", 2025, "cumulative",
     "3月1日〜4月30日", 4_655_610,
     "原文:「４月は強風や雨、増水で調査が中止になる事が多かったです。７番漁場道は含まれません」"
     "→ 2025年は7番漁場道を除いた集計であり、他年の集計対象魚道数と一致するとは限らない。"),
    ("http://sagamigawa-gyoren.jp/topics/2249/", "2025-05-15", 2025, "cumulative",
     "3月1日〜5月14日", 5_149_211, "2025年シーズンの最終報告記事は本タスクの探索範囲では見つからなかった(欠測)。"),
]


def main():
    rows = []
    for url, date, year, count_type, period_raw, count, note in ROWS:
        rows.append({
            "year": year,
            "date": date,
            "count": count,
            "count_type": count_type,
            "period_raw": period_raw,
            "station_ja": STATION,
            "method_ja": METHOD_DEFAULT,
            "note_ja": note,
            "source_ref": url,
        })

    p = PROC / "ayu_upstream_migration.csv"
    fields = ["year", "date", "count", "count_type", "period_raw", "station_ja", "method_ja", "note_ja", "source_ref"]
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow(row)
    write_jsonl("ayu_upstream_migration", rows)
    print(f"  [write] {p} ({len(rows)} rows)")

    register(
        source_id="ayu_upstream_migration",
        name="寒川取水堰 天然アユ遡上調査(相模川漁業協同組合連合会お知らせ記事より)",
        publisher="相模川漁業協同組合連合会",
        url="http://sagamigawa-gyoren.jp/topics/2214/",
        category="観測地点/市民科学(アユ遡上・河川)",
        access_method="お知らせ一覧(WordPress)を最大約228ページ手動巡回し、"
                       "タイトルに「遡上」または「寒川」を含む記事本文を目視転記",
        fmt="HTML(お知らせ記事本文からの手動転記)",
        license_="利用条件の明示なし(要問合せ)。相模川漁連の公開告知記事のため出典明記の上での引用は可能と判断",
        redistributable=0,
        record_count=len(rows),
        notes=(
            f"2022〜2025年の4シーズン分、{len(rows)}行(累積値cumulativeと期間値periodが両方載っている"
            "記事は両方残しているため記事数より行数が多い)。2026年(令和8年)シーズンの遡上調査記事は"
            "「お知らせ」フィード(2025-05-15の記事以降、2026-08-19時点の最新記事まで)に見当たらず欠測。"
            "調査方法(集計対象の魚道数)が年により異なる旨の原文注記あり: "
            "2022年記事(id453)「２月２０日から遡上アユ目視調査を行い、３月１日から６カ所の魚道で"
            "遡上数調査を行っています」、2025年記事(id2214)「７番漁場道は含まれません」。"
            "このため年またぎの単純な数値比較(尾数の増減を『遡上量の増減』と解釈すること)はできない。"
            "また相模川漁連サイトの?s=検索機能はクエリを投げても結果を返さず機能していなかったため、"
            "お知らせ一覧のページ送りを手動巡回する方法に切り替えた。"
        ),
    )


if __name__ == "__main__":
    main()
