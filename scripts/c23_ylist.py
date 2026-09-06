"""YList（植物和名ー学名インデックス）— 利用条件の確認のみ

http://ylist.info/ にはデータ一括ダウンロード（xlsx / タブ区切りtxt）へのリンクがあるが、
- ページ上に利用許諾（ライセンス）の明示が無く、「暫定公開」と記載されている
- 示されているのは引用形式のみで、再配布の可否が明記されていない
ため、契約（docs/COLLECTOR_CONTRACT.md「再配布不可・要申請のものはダウンロードせず」）に従い
**ファイルは取得せず**、registry に条件のみ記録する。
"""
import sys, pathlib, re, html, json
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import get, register, RAW

SID = "ylist"
URL = "http://ylist.info/"
RAWD = RAW/SID; RAWD.mkdir(parents=True, exist_ok=True)

r = get(URL); r.encoding = r.apparent_encoding
(RAWD/"page.html").write_text(r.text, encoding="utf-8")

dl = [m for m in re.findall(r'href="([^"]+\.(?:xlsx|txt|csv))"', r.text)]
txt = html.unescape(re.sub(r"<[^>]+>", "\n", r.text))
txt = "\n".join(l.strip() for l in txt.split("\n") if l.strip())
(RAWD/"page.txt").write_text(txt, encoding="utf-8")
(RAWD/"download_links.json").write_text(json.dumps(dl, ensure_ascii=False, indent=1), encoding="utf-8")
print("  [ylist] download links found:", dl)

# ページ内で利用条件に相当しうる語を探す（原文のまま記録する）
quotes = []
for kw in ["ライセンス", "利用条件", "利用規約", "著作権", "再配布", "引用形式", "暫定公開"]:
    for m in re.finditer(kw, txt):
        seg = txt[max(0, m.start()-120):m.start()+160].replace("\n", " ")
        quotes.append(f"[{kw}] …{seg}…")
(RAWD/"license_quotes.txt").write_text("\n\n".join(quotes), encoding="utf-8")
print(f"  [ylist] {len(quotes)} license-related quotes saved")

register(SID, "YList 植物和名ー学名インデックス（日本産維管束植物 和名-学名インデックス）",
         "米倉浩司・梶田忠（琉球大学熱帯生物圏研究センター）", URL,
         "分類・名寄せ語彙", "未取得（利用条件が不明のため）", "XLSX,TXT",
         "ライセンス表示なし（引用形式のみ指定）", 0, 0,
         "利用条件: ページに「要望の多かったYListのデータを暫定公開します。下のリンクから右クリックで"
         "保存してお使い下さい。」とあるのみで、ライセンス・再配布可否の明示が無い。"
         "引用形式は「米倉浩司・梶田忠 (2003-)「BG Plants 和名－学名インデックス」（YList），"
         "http://ylist.info」と指定。再配布可否が不明のため契約に従いダウンロードせず登録のみ。"
         f"（一括ダウンロードのリンク自体は存在: {', '.join(dl)}）")
print("done.")
