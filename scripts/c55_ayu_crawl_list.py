"""相模川漁連 お知らせ一覧を遡って「遡上」「寒川」を含む記事タイトルを収集する下調べスクリプト
(processedへの出力はしない。標準出力に一覧を出すだけ)
"""
import sys, re
sys.path.insert(0, "scripts")
from common import get

BASE = "http://sagamigawa-gyoren.jp/topics/"
MAX_PAGES = 220

def main():
    found = []
    empty_streak = 0
    for page in range(1, MAX_PAGES + 1):
        url = BASE if page == 1 else f"{BASE}page/{page}/"
        try:
            r = get(url, retries=2)
        except Exception as e:
            print(f"PAGE {page} ERROR {e}", file=sys.stderr)
            if "404" in str(e):
                break
            continue
        r.encoding = r.apparent_encoding
        t = r.text
        matches = list(re.finditer(r'<a href="(http://sagamigawa-gyoren\.jp/topics/\d+/)"[^>]*>(.*?)</a>', t, re.S))
        if not matches:
            empty_streak += 1
            if empty_streak > 3:
                print(f"stopping at page {page}: no more posts", file=sys.stderr)
                break
            continue
        empty_streak = 0
        for m in matches:
            href, inner = m.groups()
            inner_clean = re.sub("<[^>]+>", " ", inner)
            inner_clean = re.sub(r"\s+", " ", inner_clean).strip()
            if any(k in inner_clean for k in ["遡上", "寒川"]):
                print(f"{href} | {inner_clean[:120]}")
                found.append((href, inner_clean))
        if page % 20 == 0:
            print(f"...page {page} done, {len(found)} matches so far", file=sys.stderr)
    print(f"TOTAL matches: {len(found)}", file=sys.stderr)

if __name__ == "__main__":
    main()
