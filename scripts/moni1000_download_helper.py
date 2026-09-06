"""モニタリングサイト1000データファイル: アンケートフォームを1コードずつ通過し、
fileDL.cgi の実ダウンロードURLを得て zip を data/raw/moni1000/ に保存する。
"""
import sys, re, time, pathlib
sys.path.insert(0, "scripts")
import requests
from common import RAW

UA = ("ryuiki-demo-datacollector/0.1 (Code for Japan; watershed monitoring demo; "
      "contact: yuki.kawabe@code4japan.org)")

SIZES = {
    'SAT02': '1045KB', 'SAT03': '560KB', 'SAT07': '760KB',
    'SIN04': '4733KB',
    'KOS04': '19KB', 'KOS06': '548KB', 'KOS07': '751KB',
    'SIT01': '5125KB',
    'GAN01': '3744KB', 'SIG02': '3567KB',
}

def fetch_dl_link(code, size):
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"})
    r0 = s.get("https://www.biodic.go.jp/moni1000/question/question.html", timeout=60)
    time.sleep(1.5)
    data = {
        'belong': '08', 'txtbelong': '', 'belongname': 'NPO法人コード・フォー・ジャパン',
        'purpose': ['04', '02'],
        'opinion': '流域カルテデモプロジェクトのための神奈川県域データ収集',
        'filename': [code],
        'sbutton': '次へ',
    }
    r1 = s.post("https://www.biodic.go.jp/cgi-bin/question/check.cgi", data=data,
                headers={"Referer": r0.url}, timeout=60)
    time.sleep(1.5)
    data2 = {
        'belong': '08', 'txtbelong': '', 'belongname': 'NPO法人コード・フォー・ジャパン',
        'purpose': '04 02', 'filename': code,
        'opinion': '流域カルテデモプロジェクトのための神奈川県域データ収集',
        'dlnum': '1', 'dlfilename': code, 'dlsize': size,
        'sbutton': '同意する',
    }
    r2 = s.post("https://www.biodic.go.jp/cgi-bin/question/download.cgi", data=data2,
                headers={"Referer": r1.url}, timeout=60)
    m = re.search(r'href="(\./fileDL\.cgi\?[^"]+)"', r2.text)
    if not m:
        return None, s, r2.text
    dl_url = "https://www.biodic.go.jp/cgi-bin/question/" + m.group(1)[2:]
    return dl_url, s, r2.text


def download_code(code):
    size = SIZES[code]
    dl_url, s, errtext = fetch_dl_link(code, size)
    if not dl_url:
        print(f"  [fail] {code}: no download link found. snippet={errtext[:300]}")
        return None
    time.sleep(1.5)
    r3 = s.get(dl_url, headers={"Referer": "https://www.biodic.go.jp/cgi-bin/question/download.cgi"}, timeout=120)
    ctype = r3.headers.get("content-type", "")
    outdir = RAW / "moni1000"
    outdir.mkdir(parents=True, exist_ok=True)
    ext = "zip" if "zip" in ctype or r3.content[:2] == b"PK" else "bin"
    dest = outdir / f"{code}.{ext}"
    dest.write_bytes(r3.content)
    print(f"  [dl] {code}: {len(r3.content)} bytes, content-type={ctype} -> {dest}")
    return dest


if __name__ == "__main__":
    codes = sys.argv[1:] or list(SIZES.keys())
    for c in codes:
        try:
            download_code(c)
        except Exception as e:
            print(f"  [error] {c}: {e}")
