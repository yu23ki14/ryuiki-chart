"""広報たつごうの紙面を記事に切る（Issue #131 手順 3・4）。標準ライブラリだけ。

入力は「ブロック」の dict のリスト（pymupdf の get_text('dict') を `blocks_from_pymupdf` で変換したもの。
縦書きの 1 列が 1 ブロックになる）。テストは合成のブロックで走らせる（pymupdf 不要）。
 ブロック: {x0,y0,x1,y1, text, vertical, size, bold, font}

切り方（layout:v1）:
  1. ページ端の柱（ページ番号・号数）と右端の見出しタブを落とす。
  2. 本文の最頻サイズ（文字数加重）を基準に、見出しらしいブロックを選ぶ（サイズ・太字・先頭の ■◆・短さ）。
  3. 近い見出しブロックを 1 つにまとめ、残りのブロックを「見出しの下に重なる」ものとして最寄りの見出しへ割り当てる。
  4. 見出しに割り当てられないブロックは、前ページの最後の記事の続きとみなす（無ければ unsegmented）。
  推測で補わない: テキストが取れないページは本文 NULL・unreadable_reason 付きの unsegmented で残す。
"""
from __future__ import annotations

import difflib
import re
import unicodedata

LAYOUT_VERSION = "layout:v1"
RULE_VERSION = "rule:v1"

BOLD_FONT_RE = re.compile(r"Bold|Heavy|Black|Extra|Demi|-B\b|UB\b|DB\b|Medium", re.I)
FOOTER_RE = re.compile(
    r"^(?:[-－ー]?\s*\d{1,3}\s*[-－ー]?|.*Tatsugo.*|広報\s*たつごう.*|20\d\d\s*[.．]\s*\d{1,2}|\d{1,3}\s*[｜|]?\s*広報.*|.*広報たつごう\s*\d+|\d{4}\.\d{1,2})$",
    re.I)
MARK_RE = re.compile(r"^[■◆●▼◎★☆□◇○▲]")


def norm(s: str) -> str:
    """照合用: NFKC・空白と約物を除く。"""
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"[\s「」『』()（）\[\]【】〈〉・、。，．,.:：;；!！?？\-－―～~〜]", "", s)


# ---------------------------------------------------------------- pymupdf → ブロック
def blocks_from_pymupdf(page_dict: dict) -> list[dict]:
    out = []
    for b in page_dict.get("blocks", []):
        if b.get("type") != 0:
            continue
        chars = vchars = 0
        sizes: dict[float, int] = {}
        bold = 0
        font = ""
        parts = []
        for l in b["lines"]:
            t = "".join(s["text"] for s in l["spans"])
            parts.append(t)
            n = len(t.strip())
            chars += n
            if abs(l["dir"][0]) < 0.5:
                vchars += n
            for s in l["spans"]:
                k = len(s["text"].strip())
                if not k:
                    continue
                sz = round(s["size"] * 2) / 2
                sizes[sz] = sizes.get(sz, 0) + k
                if (s["flags"] & 16) or BOLD_FONT_RE.search(s["font"]):
                    bold += k
                    font = s["font"]
        text = _join_lines(parts, vertical=vchars * 2 > chars)
        if not text.strip():
            continue
        size = max(sizes.items(), key=lambda kv: kv[1])[0] if sizes else 0
        out.append({"x0": b["bbox"][0], "y0": b["bbox"][1], "x1": b["bbox"][2], "y1": b["bbox"][3],
                    "text": text, "vertical": vchars * 2 > chars, "size": size,
                    "bold": bold * 2 > max(chars, 1), "font": font})
    return out


def _join_lines(parts: list[str], vertical: bool) -> str:
    """縦書きの 1 列は文字ごとの改行を連結する。横書きは行を改行のまま（行末の改行は段落内の折り返し）。"""
    if vertical:
        return "".join(p.strip("\n") for p in parts).strip()
    return "\n".join(p.rstrip("\n") for p in parts).strip()


# ---------------------------------------------------------------- 見出しの判定
def body_size(blocks_by_page: list[list[dict]]) -> float:
    c: dict[float, int] = {}
    for blocks in blocks_by_page:
        for b in blocks:
            c[b["size"]] = c.get(b["size"], 0) + len(b["text"])
    return max(c.items(), key=lambda kv: kv[1])[0] if c else 10.0


def is_footer(b: dict, page_w: float, page_h: float) -> bool:
    t = b["text"].strip()
    near_edge = b["y0"] > page_h * 0.93 or b["y1"] < page_h * 0.05
    if near_edge and (FOOTER_RE.match(t) or len(t) <= 14):
        return True
    # 紙面の端の見出しタブ（縦の細い帯。1 ブロックに全ラベルが連結されることがある）
    if (b["x1"] - b["x0"]) < 30 and (b["y1"] - b["y0"]) > page_h * 0.5 and (b["x0"] < page_w * 0.06 or b["x1"] > page_w * 0.94):
        return True
    if b["x0"] > page_w * 0.92 and len(t) <= 14:
        return True
    return bool(FOOTER_RE.match(t)) and len(t) <= 16 and near_edge


def is_heading(b: dict, base: float) -> bool:
    t = b["text"].replace("\n", "").strip()
    n = len(t)
    if n < 2 or n > 45:
        return False
    if re.fullmatch(r"[\d\s.,()（）/:：\-－円％%]+", t):
        return False
    big = b["size"] >= base + 1.5
    if big and not t.endswith("。"):
        return True
    if MARK_RE.match(t) and n <= 40 and b["size"] >= base - 0.5:
        return True
    if b["bold"] and b["size"] >= base - 0.5 and n <= 30 and not t.endswith("。") and "：" not in t and ":" not in t:
        return True
    return False


def merge_headings(heads: list[dict]) -> list[dict]:
    """隣り合う見出しブロック（「第67回」「龍郷町相撲大会」など）を 1 つにまとめる。"""
    heads = sorted(heads, key=lambda b: (b["y0"], b["x0"]))
    out: list[dict] = []
    for b in heads:
        for g in out:
            pad = min(g["size"], b["size"]) * 1.0
            if (b["x0"] < g["x1"] + pad and b["x1"] > g["x0"] - pad and
                    b["y0"] < g["y1"] + pad and b["y1"] > g["y0"] - pad):
                g["parts"].append(b)
                for k, f in (("x0", min), ("y0", min), ("x1", max), ("y1", max)):
                    g[k] = f(g[k], b[k])
                g["size"] = max(g["size"], b["size"])
                break
        else:
            out.append({**b, "parts": [b]})
    for g in out:
        g["parts"].sort(key=lambda p: (round(p["y0"] / 6), -p["x0"] if p["vertical"] else p["x0"]))
        texts = [p["text"].replace("\n", "") for p in g["parts"]]
        # 影つきの文字・二重に置かれた同じ見出しは、他の部分に含まれるものを落とす
        texts = [t for i, t in enumerate(texts) if not any(t != u and norm(t) in norm(u) or (t == u and j < i)
                                                           for j, u in enumerate(texts))]
        g["text"] = " ".join(texts).strip()
    return out


# ---------------------------------------------------------------- 割り当てと並べ替え
def _x_overlap(a: dict, b: dict) -> float:
    return min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])


def assign(blocks: list[dict], heads: list[dict]) -> tuple[list[list[dict]], list[dict]]:
    """各ブロックを最寄りの見出しへ。戻り値: (見出しごとのブロック, どこにも入らないブロック)。"""
    groups: list[list[dict]] = [[] for _ in heads]
    orphans: list[dict] = []
    for b in blocks:
        best = None
        for i, h in enumerate(heads):
            if h["y0"] > b["y0"] + 2:
                continue  # 見出しより上にあるブロックはその見出しの本文でない
            ov = _x_overlap(h, b)
            if ov <= 0:
                continue
            dist = b["y0"] - h["y1"]
            if best is None or dist < best[0]:
                best = (dist, i)
        if best is None:
            orphans.append(b)
        else:
            groups[best[1]].append(b)
    return groups, orphans


def reading_order(blocks: list[dict]) -> list[dict]:
    """縦書きの列は右→左、横書きは段（x0 の近いもの）ごとに上→下。縦と横が混じるときは上端の高さで先に出す。"""
    v = sorted((b for b in blocks if b["vertical"]), key=lambda b: (-round(b["x0"] / 4), b["y0"]))
    hz = [b for b in blocks if not b["vertical"]]
    cols: list[list[dict]] = []
    for b in sorted(hz, key=lambda b: b["x0"]):
        for c in cols:
            if abs(c[0]["x0"] - b["x0"]) < 24:
                c.append(b)
                break
        else:
            cols.append([b])
    h_sorted = [b for c in cols for b in sorted(c, key=lambda b: b["y0"])]
    if v and h_sorted and min(b["y0"] for b in h_sorted) < min(b["y0"] for b in v):
        return h_sorted + v
    return v + h_sorted


def block_text(blocks: list[dict]) -> str:
    return "\n".join(b["text"] for b in blocks).strip()


# ---------------------------------------------------------------- ページ → 記事
def segment_file(pages: list[dict], base: float) -> list[dict]:
    """pages: [{page, w, h, blocks, n_chars_raw, image_cover}]（page は 1 始まり）。
    戻り値: 記事 dict のリスト（title, kind, page_from, page_to, body_text, confidence, unreadable_reason, section）。"""
    arts: list[dict] = []
    for pg in pages:
        blocks = [b for b in pg["blocks"] if not is_footer(b, pg["w"], pg["h"])]
        n = sum(len(b["text"].strip()) for b in blocks)
        no = pg["page"]
        if n < 20:
            reason = "scanned_no_ocr" if pg.get("image_cover", 0) > 0.3 else "no_text_layer"
            arts.append(_art(None, "unsegmented", no, no, None, 0.0, reason))
            continue
        heads, section = select_article_heads(merge_headings([b for b in blocks if is_heading(b, base)]))
        head_ids = {id(p) for h in heads for p in h["parts"]}
        rest = [b for b in blocks if id(b) not in head_ids]  # 小見出しは本文のブロックとして残す
        groups, orphans = assign(rest, heads)
        if orphans:
            body = block_text(reading_order(orphans))
            prev = arts[-1] if arts else None
            if prev and prev["kind"] == "article" and prev["page_to"] in (no - 1, no) and prev["body_text"] is not None:
                prev["body_text"] += "\n" + body
                prev["page_to"] = no
                prev["confidence"] = min(prev["confidence"], 0.5)
            else:
                arts.append(_art(None, "unsegmented", no, no, body, 0.3, None))
        for h, g in sorted(zip(heads, groups), key=lambda hg: (round(hg[0]["y0"] / 20), -hg[0]["x0"] if hg[0]["vertical"] else hg[0]["x0"])):
            body = block_text(reading_order(g))
            a = _art(_clean_title(h["text"]), "article", no, no, body or None, 0.6 if body else 0.3,
                     None if body else "heading_without_body")
            a["section"] = section
            if body and garbled(body):
                a.update(body_text=None, confidence=0.2, unreadable_reason="garbled_font_encoding")
            arts.append(a)
    return arts


def _clean_title(t: str) -> str:
    """見出しに混ざる日付バッジ（「9 19 国指定…」）の先頭の数字を落とす。"""
    return re.sub(r"^(?:(?:\d{1,2}\s+){1,2}|\d{2,3}(?=[^\d\s]))", "", t.strip())


def garbled(text: str) -> bool:
    """CJK・かな・ASCII・約物以外（私用領域・異字体の化け）が1割を超えたら文字化け。"""
    t = re.sub(r"\s", "", text)
    if not t:
        return False
    ok = sum(1 for c in t if c.isascii() or "\u3000" <= c <= "\u30ff" or "\u3400" <= c <= "\u9fff"
             or "\uff00" <= c <= "\uffef" or c in "‐‑‒–—―‥…※■□◆◇●○▲△▼▽◎★☆〒℃㎡㎏㎞㎝㌔" or "\u2460" <= c <= "\u24ff"
             or "\u2776" <= c <= "\u2793")
    return (len(t) - ok) / len(t) > 0.1


MASTHEAD_RE = re.compile(r"TOPICS|議会だより|お知らせ|インフォメーション|コラム|通信|まちの話題|町の話題|だより", re.I)


def select_article_heads(heads: list[dict]) -> tuple[list[dict], str | None]:
    """見出しの候補から、記事の先頭にする階層を選ぶ。小さい見出しは記事の中の小見出し（本文）に回す。
    ページの題字（「TOWN TOPICS」「議会だより」のような大きな 1 つ）の下に同じ大きさの見出しが並ぶときは、
    題字を section にして、並んだ見出しを記事にする。"""
    cands = [h for h in heads if len(h["text"]) >= 3 and not re.match(r"^(?:P\s*\d+|[●■◆]|\d+$)", h["text"])
             and not h["text"].rstrip().endswith("議員")]
    if not cands:
        return [], None
    clusters: list[list[dict]] = []
    for h in sorted(cands, key=lambda h: -h["size"]):
        if clusters and clusters[0][0]["size"] - h["size"] <= 2 and len(clusters) == 1:
            clusters[0].append(h)
        elif clusters and clusters[-1][0]["size"] - h["size"] <= 2:
            clusters[-1].append(h)
        else:
            clusters.append([h])
    top = clusters[0]
    if (len(top) == 1 and len(clusters) > 1 and len(clusters[1]) >= 2 and MASTHEAD_RE.search(top[0]["text"])
            and top[0]["size"] >= 1.5 * clusters[1][0]["size"]):
        return clusters[1], top[0]["text"]
    return top, None


def _art(title, kind, p0, p1, body, conf, reason) -> dict:
    return {"title": title, "kind": kind, "page_from": p0, "page_to": p1, "body_text": body,
            "confidence": conf, "unreadable_reason": reason, "section": None}


# ---------------------------------------------------------------- 話題（rule:v1）
TOPIC_RULES: dict[str, list[str]] = {
    "river_water": ["河川", "川の", "水質", "水道", "治水", "海岸", "龍郷湾", "護岸", "水源", "水害", "排水", "浄化槽", "下水"],
    "wildlife_alien": ["マングース", "ノネコ", "外来", "希少種", "野生生物", "アマミノクロウサギ", "ルリカケス", "駆除", "生き物", "生物多様性", "ケナガネズミ", "ウミガメ"],
    "disaster": ["防災", "台風", "豪雨", "避難", "災害", "地震", "津波", "洪水", "土砂", "停電", "被害"],
    "conservation_clean": ["清掃", "ごみ", "ゴミ", "クリーン", "美化", "保全", "環境", "リサイクル", "世界自然遺産", "海岸漂着"],
    "agri_fishery": ["農業", "農林", "水産", "漁", "さとうきび", "サトウキビ", "畜産", "農地", "特産", "栽培", "出荷", "林業", "タンカン", "農家"],
    "tourism": ["観光", "エコツー", "民泊", "誘客", "ふるさと祭", "ツーリズム", "イベント", "宿泊"],
}
TOPIC_IDS = ("river_water", "wildlife_alien", "disaster", "conservation_clean", "agri_fishery", "tourism", "other")


def classify(title: str | None, body: str | None) -> list[dict]:
    """語彙 ID ごとにキーワード一致を数え、見出しの一致は強く扱う。どれにも当たらなければ other。"""
    t, b = title or "", body or ""
    out = []
    for topic, kws in TOPIC_RULES.items():
        ht = sum(1 for k in kws if k in t)
        hb = sum(b.count(k) for k in kws)
        if ht or hb >= 2:
            conf = min(0.9, 0.35 + 0.25 * ht + 0.05 * min(hb, 6))
            out.append({"topic_id": topic, "extractor": RULE_VERSION, "confidence": round(conf, 2)})
    return out or [{"topic_id": "other", "extractor": RULE_VERSION, "confidence": 0.3}]


# ---------------------------------------------------------------- 地名（原文だけ拾う）
SETTLEMENTS = ["龍郷", "屋入", "嘉渡", "秋名", "幾里", "瀬留", "戸口", "安木屋場", "手広", "芦徳", "川内", "中勝", "大勝",
               "大熊", "久場", "赤尾木", "玉里", "浦", "円"]
SHORT_NEED_SUFFIX = {"浦", "円", "龍郷", "川内", "久場"}  # 1〜2 字で他の語と紛れる。「集落」「区」「公民館」が続くときだけ
SETTLEMENT_RE = re.compile("|".join(sorted(map(re.escape, SETTLEMENTS), key=len, reverse=True)))
SUFFIX_RE = re.compile(r"^(?:集落|区|公民館|地区)")
RIVER_RE = re.compile(r"[ァ-ヶー一-龠]{1,5}川")
COAST_RE = re.compile(r"龍郷湾|[ァ-ヶー一-龠]{1,4}(?:海岸|ビーチ)")
RIVER_STOP = {"河川", "小川", "大川", "上川", "下川"}


def extract_places(title: str | None, body: str | None) -> list[dict]:
    text = f"{title or ''}\n{body or ''}"
    flat = text.replace("\n", "")
    out: dict[str, dict] = {}
    for m in SETTLEMENT_RE.finditer(flat):
        w = m.group(0)
        if w in SHORT_NEED_SUFFIX and not SUFFIX_RE.match(flat[m.end():m.end() + 3]):
            continue
        out.setdefault(w, {"place_raw": w, "place_type": "settlement"})
    for m in COAST_RE.finditer(flat):
        out.setdefault(m.group(0), {"place_raw": m.group(0), "place_type": "coast"})
    for m in RIVER_RE.finditer(flat):
        w = m.group(0)
        if w not in RIVER_STOP and len(w) >= 3:
            out.setdefault(w, {"place_raw": w, "place_type": "river"})
    return list(out.values())


# ---------------------------------------------------------------- 日付
DATE_RE = re.compile(r"(?:(令和|平成)(元|\d{1,2})年)?\s*(\d{1,2})月\s*(\d{1,2})日")
ERA = {"令和": 2018, "平成": 1988}


def extract_dates(text: str | None, issue_year: int, issue_month: int, limit: int = 40) -> list[dict]:
    out, seen = [], set()
    t = unicodedata.normalize("NFKC", text or "")
    for m in DATE_RE.finditer(t):
        raw = m.group(0).strip()
        if raw in seen:
            continue
        seen.add(raw)
        mo, d = int(m.group(3)), int(m.group(4))
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            continue
        iso = None
        if m.group(1):
            y = ERA[m.group(1)] + (1 if m.group(2) == "元" else int(m.group(2)))
            iso = f"{y:04d}-{mo:02d}-{d:02d}"
        else:  # 年なし: 号の月から ±6 か月で近い年に寄せる
            y = issue_year + (1 if mo < issue_month - 6 else -1 if mo > issue_month + 6 else 0)
            iso = f"{y:04d}-{mo:02d}-{d:02d}"
        out.append({"raw": raw, "iso": iso})
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- HTML「主な記事」との照合
_TRAIL = re.compile(r"(?:\s|　)*ほか$")


def clean_headline(h: str) -> str:
    return _TRAIL.sub("", h.strip())


def reconcile_issue(headlines: list[str], articles: list[dict]) -> dict:
    """HTML の主な記事の見出しと、抽出した記事を突き合わせる。
    matched: 見出しに一致する記事の題がある／in_text_only: 題は見つからないが本文・題のどこかにある（見出し検出漏れ）／
    missed: どこにも無い（取りこぼし）。extra: どの見出しにも当たらない article（HTML は「主な」記事だけなので誤りとは限らない）。"""
    arts = [a for a in articles if a["kind"] == "article" and a.get("title")]
    titles = [(a, norm(a["title"])) for a in arts]
    alltext = norm(" ".join((a.get("title") or "") + (a.get("body_text") or "") for a in articles))
    matched, in_text, missed, used = [], [], [], set()
    for h in headlines:
        hn = norm(clean_headline(h))
        if not hn:
            continue
        hit = None
        for a, tn in titles:
            if tn and (hn in tn or tn in hn and len(tn) >= 4 or difflib.SequenceMatcher(None, hn, tn).ratio() >= 0.6):
                hit = a
                break
        if hit is not None:
            matched.append(h)
            used.add(id(hit))
        elif hn in alltext:
            in_text.append(h)
        else:
            missed.append(h)
    extra = [a["title"] for a, _ in titles if id(a) not in used]
    return {"headlines": len(headlines), "matched": matched, "in_text_only": in_text, "missed": missed,
            "extra_count": len(extra), "extra": extra}
