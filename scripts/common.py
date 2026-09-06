"""共通: レート制限付き取得 / source_registry 登録 / 正規化ヘルパ"""
import hashlib, json, os, re, sqlite3, time, datetime, pathlib, urllib.parse
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW, PROC, DB, LOGS = ROOT/"data/raw", ROOT/"data/processed", ROOT/"data/db", ROOT/"data/logs"
for d in (RAW, PROC, DB, LOGS): d.mkdir(parents=True, exist_ok=True)

# クローラの名乗り。個人名・個人アドレスは載せない。
# 2026-08-30: 以前は特定個人のメールアドレスを全リクエストに付与していたが、
# 当該個人の承諾が未確認だったため docs/COLLECTOR_CONTRACT.md の定める代替手順
# （「承諾が無い場合は UA から個人名・個人アドレスを外し、組織の代表連絡先に差し替える」）
# に従って組織の代表連絡先に置き換えた。個人名義に戻すなら本人の承諾を先に取ること。
UA = ("ryuiki-demo-datacollector/0.2 (Code for Japan; watershed monitoring demo; "
      "contact: info@code4japan.org)")
_last = {}
MIN_INTERVAL = 1.5

def _throttle(url):
    host = urllib.parse.urlparse(url).netloc
    dt = time.time() - _last.get(host, 0)
    if dt < MIN_INTERVAL: time.sleep(MIN_INTERVAL - dt)
    _last[host] = time.time()

def get(url, *, params=None, timeout=60, retries=3, headers=None, stream=False):
    h = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"}
    if headers: h.update(headers)
    last = None
    for i in range(retries):
        _throttle(url)
        try:
            r = requests.get(url, params=params, headers=h, timeout=timeout, stream=stream)
            if r.status_code == 200: return r
            last = f"HTTP {r.status_code}"
            if r.status_code in (400,401,403,404): break
        except Exception as e:
            last = repr(e)
        time.sleep(2 * (i+1))
    raise RuntimeError(f"GET failed {url}: {last}")

def get_json(url, **kw):
    return get(url, **kw).json()

def download(url, dest: pathlib.Path, **kw):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0: return dest
    r = get(url, stream=True, **kw)
    with open(dest, "wb") as f:
        for chunk in r.iter_content(1 << 16): f.write(chunk)
    return dest

def sha256(p): 
    h = hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda: f.read(1<<20), b""): h.update(b)
    return h.hexdigest()

def now(): return datetime.datetime.now().isoformat(timespec="seconds")

def appdb(): return sqlite3.connect(DB/"ryuiki.sqlite", timeout=30)
def cellsdb(): return sqlite3.connect(DB/"cells.sqlite", timeout=30)

def register(source_id, name, publisher, url, category, access_method, fmt,
             license_, redistributable, record_count, notes=""):
    c = appdb()
    c.execute("""INSERT OR REPLACE INTO source_registry
        (source_id,name,publisher,url,category,access_method,format,license,
         redistributable,fetched_at,record_count,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (source_id,name,publisher,url,category,access_method,fmt,license_,
         int(redistributable),now(),record_count,notes))
    c.commit(); c.close()
    print(f"  [registry] {source_id}: {record_count} records")

def write_jsonl(name, rows):
    p = PROC/f"{name}.jsonl"
    with open(p,"w",encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False)+"\n")
    print(f"  [write] {p.relative_to(ROOT)}  {len(rows)} rows")
    return p

# ---- 正規化 (P6 SKILL.md 準拠) ----
ERA = {"令和":2018, "平成":1988, "昭和":1925, "R":2018, "H":1988, "S":1925}
def to_fiscal_year(s):
    """「令和4年度」「H29年度」「2006(平成18)年度」「平成19(2007)年度」→ 西暦年度(int)"""
    if s is None: return None
    s = str(s).strip()
    m = re.search(r"(19|20)\d{2}", s)
    if m and not re.match(r"^(令和|平成|昭和|R|H|S)", s): return int(m.group(0))
    for k, base in ERA.items():
        m = re.search(rf"{k}\s*(元|\d+)", s)
        if m:
            n = 1 if m.group(1) == "元" else int(m.group(1))
            return base + n
    return int(m.group(0)) if m else None

def to_number(v):
    """"2,194"→2194 / "－","-","n.d.",""→None / "1.5"→1.5"""
    if v is None: return None, None
    s = str(v).strip().replace(",", "").replace("，","")
    if s in ("", "－", "―", "-", "‐", "n.d.", "N.D.", "・", "…", "NA"): return None, None
    if re.search(r"[※*注]", s): return s, "string"   # 注記付きは数値化しない
    s2 = re.sub(r"[\)\(（）\s]", "", s)
    try:
        if re.fullmatch(r"-?\d+", s2): return int(s2), "int"
    except Exception: pass
    try:
        if re.fullmatch(r"-?\d*\.\d+", s2): return float(s2), "float"
    except Exception: pass
    return s, "string"

AREA_TO_HA = {"ha":1.0, "ヘクタール":1.0, "km2":100.0, "km²":100.0, "平方キロメートル":100.0,
              "m2":0.0001, "㎡":0.0001, "a":0.01}
MONEY_TO_YEN = {"円":1, "千円":1_000, "万円":10_000, "百万円":1_000_000, "億円":100_000_000}
