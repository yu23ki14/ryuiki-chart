#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行政文書の表を cells.sqlite（documents / cells / notes / extraction_log）に書く共通部品。

AMAMI_STEP2C §2。c95〜c98b が使う。要点:
- 書き込みは doc_id 単位。`DELETE ... WHERE doc_id=?` だけを使い、ほかの doc_id には触れない
  （表全体の削除や extractor を条件にした削除はしない。AMAMI_STEP2A の教訓）。
- 検算（check_identity）は書く前に済ませる。原本の誤りは「宣言した例外」として列挙し、
  過不足なく一致しなければ止める。
- 関数は接続を受け取り commit しない。1つのトランザクションにまとめるには write_doc を使う。
  write_doc は、呼び手が開いたトランザクションがあれば止める（自分の分だけを commit/rollback するため）。
- 使い分け: PDF の一括抽出（p1_maker / p2_checker の p1/p2）は従来どおり。検算つきの個別文書（c95〜c98b など、
  1文書ごとに表の形と検算を書く）はこのモジュール。
- 後始末までの流れは commit_doc（cellsdb を開いて write_doc、必要なら source_registry に register）。
- extraction_log.failures の形は **dict か None**（失敗の種類 -> 詳細。宣言した例外・警告など。リストにしない）。
"""
import json
import re
import sqlite3
import unicodedata
from datetime import datetime

from common import to_fiscal_year  # noqa: E402

# 鹿児島県のサイトから事実（数値）だけを抜き出す文書の license（c95・c98b 共通）
LICENSE_PREF_KAGOSHIMA = "鹿児島県ホームページ（無断転載・改変不可）。事実（数値）のみ抽出し出典を明記"

# ライセンス表記のない文書から事実（数値）だけを抜き出すときの license（c102b。registry/source/license.yaml の mappings にある）
LICENSE_NOTE_UNSTATED = "ライセンス表記なし（事実（数値）のみ抽出し出典を明記。原本の PDF は再配布しない）"

# 環境省ホームページコンテンツの PDL1.0 の原文（c96・c99 共通。registry/source/license.yaml の mappings にある）
LICENSE_MOE_PDL = "公共データ利用規約（第1.0版）PDL1.0（環境省ホームページコンテンツの利用について）: https://www.env.go.jp/mail.html"

CELL_COLUMNS = (
    "doc_id", "doc_sha256", "page_no", "table_id", "row_key", "col_key",
    "value_raw", "value", "value_type", "unit", "fiscal_year", "era_raw",
    "source_text", "source_bbox", "notes_ref", "is_total", "merged",
    "unreadable_reason", "confidence", "extractor", "verified_by", "extracted_at",
    "superseded",
)
DOC_COLUMNS = ("doc_id", "title", "publisher", "url", "local_path", "doc_sha256",
               "n_pages", "fiscal_year", "license", "fetched_at")
NOTE_KINDS = ("comparability", "definition_change", "footnote", "survey_scope")


def _now():
    return datetime.now().isoformat(timespec="seconds")


# ---- 値の読み取り ------------------------------------------------------

_BLANKS = {"", "-", "－", "―", "ー", "‐", "—", "–", "−"}


def parse_count(s):
    """件数の文字列 → (値, かっこ内の値)。

    "5(1)" → (5, 1)、"1,796" → (1796, None)、"－" や空欄 → (None, None)。0 は 0（空欄と区別する）。
    common.to_number は "5(1)" を 51 と読むので使わない。読めない文字列は ValueError。
    """
    if s is None:
        return None, None
    t = unicodedata.normalize("NFKC", str(s)).strip().replace(",", "").replace(" ", "")
    if t in _BLANKS:
        return None, None
    m = re.fullmatch(r"(\d+)(?:\((\d+)\))?", t)
    if not m:
        raise ValueError(f"件数として読めない: {s!r}")
    return int(m.group(1)), (int(m.group(2)) if m.group(2) is not None else None)


def count_cell(raw, **base):
    """件数の文字列から cells の1行（dict）を作る。base は page_no・table_id・row_key など残りの列。
    value は文字列（JSON）、value_type は int（読めた）／string（「-」など読めない表記）／NULL（空欄。value_raw も NULL）。"""
    v, _ = parse_count(raw)
    blank = raw is None or str(raw).strip() == ""
    return dict(base, value_raw=None if blank else raw, value=None if v is None else str(v),
                value_type="int" if v is not None else (None if blank else "string"))


def era_to_year(s):
    """"Ｒ１"・"R元"・"H２３"・"令和4年度" → 西暦年。NFKC で全角を半角にしてから to_fiscal_year へ。"""
    if s is None:
        return None
    return to_fiscal_year(unicodedata.normalize("NFKC", str(s)).strip())


# ---- 検算 --------------------------------------------------------------

class IdentityError(AssertionError):
    pass


def check_identity(label, observed, declared=None):
    """和などの恒等式の検算。

    observed: {キー: (左辺, 右辺)} 全部の検算。左右が違うものが「食い違い」。
    declared: {キー: (左辺, 右辺)} 原本の誤りとして宣言した食い違い（値まで含めて）。
    食い違いの集合と宣言が過不足なく一致しなければ IdentityError。一致すれば宣言した食い違いを返す。
    """
    declared = declared or {}
    actual = {k: (a, b) for k, (a, b) in observed.items() if a != b}
    problems = []
    for k in sorted(set(actual) - set(declared), key=str):
        problems.append(f"宣言にない食い違い {k}: {actual[k][0]} != {actual[k][1]}")
    for k in sorted(set(declared) - set(actual), key=str):
        problems.append(f"宣言した例外が食い違っていない {k}: 宣言 {declared[k]}")
    for k in sorted(set(actual) & set(declared), key=str):
        if tuple(actual[k]) != tuple(declared[k]):
            problems.append(f"宣言と値が違う {k}: 宣言 {tuple(declared[k])} / 実際 {tuple(actual[k])}")
    if problems:
        raise IdentityError(f"[{label}] 検算が通らない:\n  " + "\n  ".join(problems))
    return actual


# ---- 書き込み ----------------------------------------------------------

def put_document(con, doc_id, **fields):
    """documents を doc_id で入れ替える（その1行だけ）。"""
    unknown = set(fields) - set(DOC_COLUMNS)
    if unknown:
        raise TypeError(f"documents にない列: {sorted(unknown)}")
    fields.setdefault("fetched_at", _now())
    row = {c: fields.get(c) for c in DOC_COLUMNS if c != "doc_id"}
    con.execute("DELETE FROM documents WHERE doc_id=?", (doc_id,))
    cols = ["doc_id", *row]
    con.execute(f"INSERT INTO documents ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                [doc_id, *row.values()])


def replace_doc_cells(con, doc_id, rows):
    """その doc_id の cells だけを消して入れ直す。rows は dict の列。返り値は挿入した行数。"""
    now = _now()
    prepared = []
    for r in rows:
        if r.get("doc_id", doc_id) != doc_id:
            raise ValueError(f"別の doc_id の行が混じっている: {r.get('doc_id')!r} != {doc_id!r}")
        unknown = set(r) - set(CELL_COLUMNS)
        if unknown:
            raise TypeError(f"cells にない列: {sorted(unknown)}")
        d = {c: r.get(c) for c in CELL_COLUMNS}
        d["doc_id"] = doc_id
        d["is_total"] = int(d["is_total"] or 0)
        d["merged"] = int(d["merged"] or 0)
        d["superseded"] = int(d["superseded"] or 0)
        d["extracted_at"] = d["extracted_at"] or now
        if d["value"] is not None and not isinstance(d["value"], str):
            d["value"] = json.dumps(d["value"])  # value は JSON の文字列
        prepared.append(d)
    con.execute("DELETE FROM cells WHERE doc_id=?", (doc_id,))
    con.executemany(
        f"INSERT INTO cells ({','.join(CELL_COLUMNS)}) VALUES ({','.join('?' * len(CELL_COLUMNS))})",
        [[d[c] for c in CELL_COLUMNS] for d in prepared])
    return len(prepared)


def put_notes(con, doc_id, notes):
    """notes を入れ替える。note_id は f"{doc_id}_n{連番(1始まり、3桁)}"。
    notes: dict の列（kind, text, page, table_ids(list)|None, blocks_timeseries, reason）。"""
    con.execute("DELETE FROM notes WHERE doc_id=?", (doc_id,))
    ids = []
    for i, n in enumerate(notes, 1):
        if n["kind"] not in NOTE_KINDS:
            raise ValueError(f"kind が不正: {n['kind']!r}")
        nid = f"{doc_id}_n{i:03d}"
        con.execute(
            "INSERT INTO notes (note_id, doc_id, table_ids, kind, text, page, blocks_timeseries, reason)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (nid, doc_id, json.dumps(n.get("table_ids") or [], ensure_ascii=False), n["kind"], n["text"],
             n.get("page"), int(n.get("blocks_timeseries") or 0), n.get("reason")))
        ids.append(nid)
    return ids


def log_check(con, doc_id, verdict, *, page_no=None, table_id=None, role="checker",
              attempt=1, failures=None, note=None):
    """extraction_log に1行追記するだけ（消さない）。"""
    con.execute(
        "INSERT INTO extraction_log (ts, doc_id, page_no, table_id, role, attempt, verdict, failures, note)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (_now(), doc_id, page_no, table_id, role, attempt, verdict,
         json.dumps(failures, ensure_ascii=False) if failures is not None else None, note))


def write_doc(con, doc_id, document, cells, notes, log=None):
    """検算が済んだあとに呼ぶ。documents・cells・notes・log を1つのトランザクションで書く。
    呼び手が開いたトランザクションがあれば RuntimeError（その中に混ぜず、自分の分だけを確定するため）。"""
    if con.in_transaction:
        raise RuntimeError("write_doc: 呼び手のトランザクションが開いている。commit してから呼ぶ")
    con.execute("BEGIN IMMEDIATE")
    try:
        put_document(con, doc_id, **document)
        n = replace_doc_cells(con, doc_id, cells)
        put_notes(con, doc_id, notes)
        for entry in log or []:
            log_check(con, doc_id, **entry)
        con.commit()
    except BaseException:
        con.rollback()
        raise
    return n


def commit_doc(doc_id, document, cells, notes, log=None, source=None):
    """cellsdb を開いて write_doc し、閉じる。source（common.register の引数の dict。record_count は挿入した行数）が
    あれば source_registry に登録する。返り値は挿入した cells の行数。"""
    import common
    con = common.cellsdb()
    try:
        n = write_doc(con, doc_id, document, cells, notes, log)
    finally:
        con.close()
    if source:
        common.register(**source, record_count=n)
    return n


def fetch_pdf(url, path):
    """PDF が無ければ取得して保存する。-> (path, sha256)。path は絶対パス。"""
    import common
    if not path.exists():
        common.download(url, path)
    return path, common.sha256(path)


def fetch_verified(url, path, want_sha256):
    """保存済みで sha256 が同じなら何もしない。違う・無いなら取得し、検査してから置き換える。
    sha256 が期待と違えば（既存の良いコピーは壊さず）SystemExit。取得の間隔は common.get の throttle に任せる。-> 'skip' | 'save'"""
    import common
    if path.exists() and common.sha256(path) == want_sha256:
        return "skip"
    tmp = path.with_name(path.name + ".part")
    tmp.unlink(missing_ok=True)
    common.download(url, tmp)
    sha = common.sha256(tmp)
    if sha != want_sha256:
        tmp.unlink()
        raise SystemExit(f"{path.name}: sha256 が期待と違う（{sha}）。資料が更新された？ 正解 csv を作り直す前に人が確認する")
    tmp.replace(path)
    return "save"


def number_value(raw):
    """数値の印字（カンマ付き可）-> (value〔JSON の文字列〕, value_type)。小数点があれば float、なければ int。"""
    from decimal import Decimal
    v = Decimal(str(raw).replace(",", ""))
    return (str(float(v)), "float") if "." in str(raw) else (str(int(v)), "int")


def pdf_page_count(path):
    """PDF のページ数。先頭が %PDF でない・pdfplumber で開けない PDF は ValueError。"""
    with open(path, "rb") as f:
        if not f.read(5).startswith(b"%PDF"):
            raise ValueError(f"PDF ではない: {path}")
    import pdfplumber  # 先頭の検査より後（pdfplumber の無い環境でも壊れたファイルは弾ける）
    try:
        with pdfplumber.open(str(path)) as pdf:
            return len(pdf.pages)
    except Exception as e:  # pdfminer の例外は種類が多い
        raise ValueError(f"PDF を開けない: {path}: {e!r}") from e


def pdf_tables(path, pages):
    """pdfplumber の罫線で表を読む。-> (ページ数, {ページ番号: [表（行のリスト）…]})。pages は 1 始まり。"""
    import pdfplumber
    with pdfplumber.open(str(path)) as pdf:
        return len(pdf.pages), {p: pdf.pages[p - 1].extract_tables() for p in pages}
