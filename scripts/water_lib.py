"""水道水の水源マップ（docs/WATER_SOURCE_MAP.md）の検証と再帰合成。

ここに置くのは「CSV を読む」「壊れていないか調べる」「水源比率を合成する」の 3 つだけ。
DB への出し入れは m06_water.py、資料の取得は c9N_*.py が持つ。

設計図 §6 の品質ルールをコードで担保する場所でもある:
  - source_doc_id が無い行はビルドで落とす（落とした件数は必ず報告する。黙って消さない）
  - 推測は confidence=low + basis=estimated。合成後もいちばん弱い値が残るようにする
  - 不明は「不明」。埋まらなかった町丁目を 0 や平均で埋めない
"""
import csv, pathlib, sys, datetime, collections

ROOT = pathlib.Path(__file__).resolve().parent.parent
WATER = ROOT / "data" / "water"

# 弱い順。経路に 1 つでも弱いものがあれば結果はそこまで落ちる。
CONFIDENCE_ORDER = ["low", "medium", "high"]
BASIS_ORDER = ["unknown", "nominal", "estimated", "measured"]

# basis=unknown は「上流の顔ぶれは資料で確定しているが、混合比が公表されていない」を表す。
# このとき share は**空にする**（0.5 や施設能力比で埋めない）。合成結果もその町丁目については
# 比率を持たず、画面は水源名だけを並べて「比率は公表されていません」と出す。
# 施設能力比で概算を置ける場合は unknown ではなく nominal を使うこと。両者は別物。
BASIS_UNKNOWN = "unknown"

VALID_SOURCE_TYPE = {"river", "dam", "groundwater", "spring"}
VALID_FACILITY_TYPE = {"intake", "purification", "reservoir", "junction"}
VALID_UTILITY_KIND = {"bulk", "retail"}

# CSV のファイル名 → 主キー列
FILES = {
    "utility": "utility_id",
    "water_source": "source_id",
    "facility": "facility_id",
    "source_doc": "doc_id",
    "flow_edge": "edge_id",
    "zone_rule": "rule_id",
    "zone_assignment": "assignment_id",
}

# zone_rule の当て方。町丁目リストが公表されていない事業体では、給水区域が
# 「○○区」「○○市」の粒度でしか書かれていない。1 行ずつ 1,741 町丁目を手で書く代わりに
# 区・市町村単位のルールを 1 行書いて m06_water.py が展開する。
# 町丁目ごとの上書きは zone_assignment.csv に直接書く（そちらが優先）。
MATCH_TYPES = {
    "city_exact",   # e-Stat の city_name と完全一致（例: 横浜市青葉区）
    "city_prefix",  # city_name の前方一致（例: 横浜市 → 全区）
    "key_prefix",   # KEY_CODE の前方一致（市区町村コード 5 桁など）
}


class Problems:
    """検証結果。error があれば m06 は書き込みを行わない。"""

    def __init__(self):
        self.errors = []
        self.warnings = []
        self.dropped = []          # source_doc_id が無くて落とした行

    def error(self, where, msg):
        self.errors.append(f"{where}: {msg}")

    def warn(self, where, msg):
        self.warnings.append(f"{where}: {msg}")

    def report(self):
        for w in self.warnings:
            print(f"  [warn]  {w}")
        for e in self.errors:
            print(f"  [ERROR] {e}")
        if self.dropped:
            print(f"  [drop]  source_doc_id 無しで落とした行 {len(self.dropped)} 件:")
            for d in self.dropped[:20]:
                print(f"            {d}")
            if len(self.dropped) > 20:
                print(f"            … 他 {len(self.dropped)-20} 件")
        print(f"  検証: エラー {len(self.errors)} / 警告 {len(self.warnings)} / 落とした行 {len(self.dropped)}")
        return not self.errors


def read(name):
    """data/water/<name>.csv を読む。無ければ空リスト（まだ着手していない事業体があるのは正常）。"""
    p = WATER / f"{name}.csv"
    if not p.exists():
        return []
    with open(p, encoding="utf-8-sig", newline="") as f:
        return [{k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
                for row in csv.DictReader(f)]


def load_all():
    return {name: read(name) for name in FILES}


def num(v):
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse_date(v):
    """YYYY-MM-DD / YYYY-MM / YYYY を受ける。ダメなら None。"""
    s = (v or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def active(row, as_of):
    """as_of（date）時点で有効な行か。valid_to が空なら現行。"""
    vf = parse_date(row.get("valid_from"))
    vt = parse_date(row.get("valid_to"))
    if vf and as_of < vf:
        return False
    if vt and as_of >= vt:
        return False
    return True


def weakest(order, values):
    """order の弱い順で、与えられた値のうちいちばん弱いものを返す。未知の値は最弱扱い。"""
    best = None
    for v in values:
        if v not in order:
            return order[0]
        if best is None or order.index(v) < order.index(best):
            best = v
    return best if best is not None else order[0]


# ------------------------------------------------------------------ #
# 検証                                                                 #
# ------------------------------------------------------------------ #

def expand_rules(data, zones):
    """zone_rule を町丁目単位の zone_assignment に展開する。

    **その町丁目に明示の割付が 1 行でもあれば、ルールは一切当てない。**
    突き合わせを (key_code, facility_id) の組にすると、明示が A 浄水場・ルールが B 浄水場の
    ときに両方が残って share の合計が 2.0 になり、検証で落ちる。それ以前に、同じ町丁目に
    粒度の違う 2 つの根拠が並ぶこと自体が正しくない。細かい方（明示）だけを残す。
    """
    explicit = {a["key_code"] for a in data["zone_assignment"]}
    out = []
    for r in data["zone_rule"]:
        mt, mv = r.get("match_type"), r.get("match_value", "")
        for z in zones:
            if mt == "city_exact" and z["city_name"] != mv:
                continue
            if mt == "city_prefix" and not (z["city_name"] or "").startswith(mv):
                continue
            if mt == "key_prefix" and not (z["key_code"] or "").startswith(mv):
                continue
            if mt not in MATCH_TYPES:
                continue
            if z["key_code"] in explicit:
                continue
            out.append({
                "assignment_id": f"{r['rule_id']}:{z['key_code']}",
                "key_code": z["key_code"],
                "facility_id": r["facility_id"],
                "share": r.get("share"),
                "confidence": r.get("confidence"),
                "valid_from": r.get("valid_from"),
                "valid_to": r.get("valid_to"),
                "source_doc_id": r.get("source_doc_id"),
                "note_ja": r.get("note_ja"),
                "_from_rule": r["rule_id"],
            })
    return out


def validate_rules(data, zones, p):
    """ルール自体の検査。1 件も当たらないルールは書き間違いなので落とす。"""
    facs = {f["facility_id"] for f in data["facility"]}
    docs = {d["doc_id"] for d in data["source_doc"]}
    for r in data["zone_rule"]:
        if r.get("match_type") not in MATCH_TYPES:
            p.error("zone_rule", f"{r['rule_id']}: match_type={r.get('match_type')!r} が語彙外")
        if r["facility_id"] not in facs:
            p.error("zone_rule", f"{r['rule_id']}: facility_id={r['facility_id']} が facility に無い")
        if not (r.get("source_doc_id") or ""):
            p.dropped.append(f"zone_rule {r['rule_id']}")
        elif r["source_doc_id"] not in docs:
            p.error("zone_rule", f"{r['rule_id']}: source_doc_id={r['source_doc_id']} が source_doc に無い")
        if r.get("confidence") not in CONFIDENCE_ORDER:
            p.error("zone_rule", f"{r['rule_id']}: confidence={r.get('confidence')!r} が語彙外")
        sh = num(r.get("share"))
        if sh is None or not (0 < sh <= 1.0000001):
            p.error("zone_rule", f"{r['rule_id']}: share={r.get('share')!r} が (0, 1] の外")
        _check_period(p, "zone_rule", r["rule_id"], r)
    data["zone_rule"] = [r for r in data["zone_rule"] if r.get("source_doc_id")]
    # 1 件も当たらないルールを検出する。ただし「明示の割付に全部先を越された」場合は
    # 書き間違いではないので、そちらは警告にとどめる。
    hit = collections.Counter(a["_from_rule"] for a in expand_rules(data, zones))
    explicit = {a["key_code"] for a in data["zone_assignment"]}
    for r in data["zone_rule"]:
        if hit[r["rule_id"]]:
            continue
        mt, mv = r.get("match_type"), r.get("match_value", "")
        matched = [z for z in zones
                   if (mt == "city_exact" and z["city_name"] == mv)
                   or (mt == "city_prefix" and (z["city_name"] or "").startswith(mv))
                   or (mt == "key_prefix" and (z["key_code"] or "").startswith(mv))]
        if matched and all(z["key_code"] in explicit for z in matched):
            p.warn("zone_rule", f"{r['rule_id']}: 当たる町丁目 {len(matched)} 件はすべて"
                                f"明示の割付があるのでルールは使われない。消してよい")
        else:
            p.error("zone_rule", f"{r['rule_id']}: match_value={mv!r} に当たる町丁目が 1 件も無い")


def validate(data, zone_keys, p=None):
    """設計図 §2 のスキーマと §6 の品質ルールに対する検査。

    zone_keys は e-Stat 由来の KEY_CODE の集合。zone_assignment の突合に使う。
    戻り値: (Problems, 落とした行を除いた data)
    """
    p = p or Problems()
    docs = {d["doc_id"] for d in data["source_doc"] if d.get("doc_id")}
    utils = {u["utility_id"] for u in data["utility"]}
    srcs = {s["source_id"] for s in data["water_source"]}
    facs = {f["facility_id"] for f in data["facility"]}

    # -- 主キーの重複 --
    for name, pk in FILES.items():
        seen = collections.Counter(r.get(pk, "") for r in data[name])
        for k, n in seen.items():
            if n > 1:
                p.error(name, f"主キー {pk}={k!r} が {n} 行ある")
            if not k:
                p.error(name, f"主キー {pk} が空の行がある")

    # -- 語彙 --
    for u in data["utility"]:
        if u.get("kind") not in VALID_UTILITY_KIND:
            p.error("utility", f"{u['utility_id']}: kind={u.get('kind')!r} は bulk / retail のいずれかにする")
    for s in data["water_source"]:
        if s.get("type") not in VALID_SOURCE_TYPE:
            p.error("water_source", f"{s['source_id']}: type={s.get('type')!r} が語彙外")
        if s.get("parent_id") and s["parent_id"] not in srcs:
            p.error("water_source", f"{s['source_id']}: parent_id={s['parent_id']} が water_source に無い")
    for f in data["facility"]:
        if f.get("type") not in VALID_FACILITY_TYPE:
            p.error("facility", f"{f['facility_id']}: type={f.get('type')!r} が語彙外")
        if f.get("utility_id") and f["utility_id"] not in utils:
            p.error("facility", f"{f['facility_id']}: utility_id={f['utility_id']} が utility に無い")

    # -- 水源の自己参照に閉路が無いか --
    for s in data["water_source"]:
        seen, cur = set(), s["source_id"]
        parent = {x["source_id"]: x.get("parent_id") for x in data["water_source"]}
        while cur:
            if cur in seen:
                p.error("water_source", f"parent_id が循環している: {' → '.join(list(seen))}")
                break
            seen.add(cur)
            cur = parent.get(cur) or None

    # -- 根拠資料（§6-1: source_doc_id が NULL の行は落とす）--
    for name in ("flow_edge", "zone_assignment"):
        keep = []
        for r in data[name]:
            did = r.get("source_doc_id") or ""
            if not did:
                p.dropped.append(f"{name} {r.get(FILES[name])}")
                continue
            if did not in docs:
                p.error(name, f"{r.get(FILES[name])}: source_doc_id={did} が source_doc に無い")
            keep.append(r)
        data[name] = keep
    for name in ("water_source", "facility"):
        for r in data[name]:
            did = r.get("source_doc_id") or ""
            if did and did not in docs:
                p.error(name, f"{r.get(FILES[name])}: source_doc_id={did} が source_doc に無い")
    for d in data["source_doc"]:
        if not (d.get("url") or "").strip():
            p.warn("source_doc", f"{d['doc_id']}: url が空。リンク切れ時に再取得できない")

    # -- flow_edge --
    for e in data["flow_edge"]:
        if e["to_id"] not in facs:
            p.error("flow_edge", f"{e['edge_id']}: to_id={e['to_id']} が facility に無い")
        if e["from_id"] not in facs and e["from_id"] not in srcs:
            p.error("flow_edge", f"{e['edge_id']}: from_id={e['from_id']} が facility にも water_source にも無い")
        if e["from_id"] == e["to_id"]:
            p.error("flow_edge", f"{e['edge_id']}: from_id と to_id が同じ")
        sh = num(e.get("share"))
        if e.get("basis") == BASIS_UNKNOWN:
            if (e.get("share") or "").strip() != "":
                p.error("flow_edge", f"{e['edge_id']}: basis=unknown なら share は空にする"
                                     f"（比率が分かっているなら basis を変える）")
        elif sh is None or not (0 < sh <= 1.0000001):
            p.error("flow_edge", f"{e['edge_id']}: share={e.get('share')!r} が (0, 1] の外")
        if e.get("basis") not in BASIS_ORDER:
            p.error("flow_edge", f"{e['edge_id']}: basis={e.get('basis')!r} が語彙外")
        _check_period(p, "flow_edge", e["edge_id"], e)

    # 同じ to_id × 同時点の share 合計 = 1.0
    _check_share_sum(p, "flow_edge", data["flow_edge"], "to_id")

    # -- zone_assignment --
    for a in data["zone_assignment"]:
        if zone_keys and a["key_code"] not in zone_keys:
            p.error("zone_assignment", f"{a['assignment_id']}: key_code={a['key_code']} が e-Stat の町丁目に無い")
        if a["facility_id"] not in facs:
            p.error("zone_assignment", f"{a['assignment_id']}: facility_id={a['facility_id']} が facility に無い")
        sh = num(a.get("share"))
        if sh is None or not (0 < sh <= 1.0000001):
            p.error("zone_assignment", f"{a['assignment_id']}: share={a.get('share')!r} が (0, 1] の外")
        if a.get("confidence") not in CONFIDENCE_ORDER:
            p.error("zone_assignment", f"{a['assignment_id']}: confidence={a.get('confidence')!r} が語彙外")
        _check_period(p, "zone_assignment", a["assignment_id"], a)

    _check_share_sum(p, "zone_assignment", data["zone_assignment"], "key_code")

    return p, data


def _check_period(p, name, pk, row):
    vf_raw, vt_raw = row.get("valid_from"), row.get("valid_to")
    vf, vt = parse_date(vf_raw), parse_date(vt_raw)
    if (vf_raw or "").strip() and vf is None:
        p.error(name, f"{pk}: valid_from={vf_raw!r} が日付として読めない")
    if (vt_raw or "").strip() and vt is None:
        p.error(name, f"{pk}: valid_to={vt_raw!r} が日付として読めない")
    if vf and vt and vt <= vf:
        p.error(name, f"{pk}: valid_to({vt}) が valid_from({vf}) 以前")
    if not vf:
        p.warn(name, f"{pk}: valid_from が空。いつ時点の数字か分からない")


def _check_share_sum(p, name, rows, group_col, tol=0.005):
    """同じグループ × 同じ有効期間で share の合計が 1.0 になるか。

    期間がずれている行を混ぜて足すと誤検出になるので、(group, valid_from, valid_to) で束ねる。

    basis=unknown（混合比が非公表）の行は share を持たないので合計を見ない。
    ただし**同じ流入先で既知と未知を混ぜるのは禁止**する。混ぜると「合計 1.0」が
    何を意味するのか決められず、片方だけ比率が出るという中途半端な表示になる。
    """
    groups = collections.defaultdict(list)
    for r in rows:
        groups[(r[group_col], r.get("valid_from", ""), r.get("valid_to", ""))].append(r)
    for (gid, vf, vt), rs in sorted(groups.items()):
        unknown = [r for r in rs if r.get("basis") == BASIS_UNKNOWN]
        if unknown:
            if len(unknown) != len(rs):
                p.error(name, f"{group_col}={gid}: basis=unknown の行と比率のある行が混ざっている"
                              f"（{len(unknown)}/{len(rs)} 行）。流入先ごとにどちらかに揃える")
            continue
        total = sum(num(r.get("share")) or 0 for r in rs)
        if abs(total - 1.0) > tol:
            period = f"（{vf or '?'}〜{vt or '現行'}）"
            p.error(name, f"{group_col}={gid}{period}: share の合計が {total:.4f}。1.0 にする"
                          f"（{len(rs)} 行: {', '.join(r[FILES[name]] for r in rs)}）")


# ------------------------------------------------------------------ #
# 再帰合成                                                             #
# ------------------------------------------------------------------ #

def compose(data, as_of=None, max_depth=32):
    """町丁目ごとの水源別ブレンド比率を作る。

    zone_assignment → facility から flow_edge を上流に辿り、share を掛け合わせて
    water_source に着いたところで合算する。卸→末端の 2 段ブレンドもこの再帰で出る。

    戻り値: (rows, unresolved)
      rows       : {key_code, source_id, share, confidence, basis, as_of} のリスト。
                   **share は None になりうる**。経路に basis=unknown（混合比が非公表）の辺が
                   1 本でもあれば、その町丁目の水源はすべて share=None にする。
                   顔ぶれは資料で確定しているが比率が言えない、という状態をそのまま表す。
                   一部の水源だけ比率が出る中途半端な表示にしないため、町丁目単位で揃える。
      unresolved : {key_code: 到達できなかった比率} — 上流が未入力の施設。
                   0 で埋めずにそのまま返し、UI は「不明」と出す（設計図 §6-3）。
    """
    as_of = as_of or datetime.date.today()
    srcs = {s["source_id"] for s in data["water_source"]}

    # to_id ごとに、その時点で有効な入辺を引けるようにする
    inbound = collections.defaultdict(list)
    for e in data["flow_edge"]:
        if active(e, as_of):
            inbound[e["to_id"]].append(e)

    memo = {}

    def mul(a, b):
        """比率の掛け算。どちらかが「不明」なら結果も不明。"""
        return None if a is None or b is None else a * b

    def upstream(node_id, depth, path):
        """node_id に入る水の水源別内訳 {source_id: (share, confidence, basis)} と、
        辿れなかった比率を返す。share は None（＝混合比が非公表）になりうる。"""
        if node_id in srcs:
            return {node_id: (1.0, "high", "measured")}, 0.0
        if node_id in memo:
            return memo[node_id]
        if depth > max_depth or node_id in path:
            # 閉路か深すぎ。validate では水源側しか見ていないので here で拾う
            return {}, 1.0
        edges = inbound.get(node_id, [])
        if not edges:
            return {}, 1.0     # 上流が未入力。不明として持ち上げる
        out, lost = collections.defaultdict(lambda: [0.0, [], []]), 0.0
        for e in edges:
            unknown = e.get("basis") == BASIS_UNKNOWN
            sh = None if unknown else (num(e.get("share")) or 0.0)
            sub, sub_lost = upstream(e["from_id"], depth + 1, path | {node_id})
            # 比率が分からない辺では「上流が丸ごと未入力かどうか」だけを持ち上げる
            lost += sub_lost if unknown else sh * sub_lost
            for sid, (ss, conf, basis) in sub.items():
                acc = out[sid]
                prod = mul(sh, ss)
                acc[0] = None if (acc[0] is None or prod is None) else acc[0] + prod
                acc[1].append(conf)
                acc[2].append(weakest(BASIS_ORDER, [basis, e.get("basis")]))
        if unknown_in(out):
            for v in out.values():
                v[0] = None
        res = ({sid: (v[0], weakest(CONFIDENCE_ORDER, v[1]), weakest(BASIS_ORDER, v[2]))
                for sid, v in out.items()}, min(lost, 1.0))
        memo[node_id] = res
        return res

    def unknown_in(out):
        """1 つでも比率が出せない水源があれば、その節点はまとめて比率なしにする。"""
        return any(v[0] is None for v in out.values())

    per_zone = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, [], []]))
    unresolved = collections.defaultdict(float)
    for a in data["zone_assignment"]:
        if not active(a, as_of):
            continue
        zshare = num(a.get("share")) or 0.0
        sub, lost = upstream(a["facility_id"], 0, frozenset())
        unresolved[a["key_code"]] += zshare * lost
        for sid, (ss, conf, basis) in sub.items():
            acc = per_zone[a["key_code"]][sid]
            prod = mul(zshare, ss)
            acc[0] = None if (acc[0] is None or prod is None) else acc[0] + prod
            acc[1].append(weakest(CONFIDENCE_ORDER, [conf, a.get("confidence")]))
            acc[2].append(basis)

    rows = []
    stamp = as_of.isoformat()
    for key, by_src in per_zone.items():
        # 1 つでも比率の出せない水源があれば、その町丁目は全部まとめて比率なしにする。
        # 片方だけパーセントが出ると、残りが 0% なのか不明なのか読めない。
        mixed = any(v[0] is None for v in by_src.values())
        for sid, (share, confs, bases) in by_src.items():
            if not mixed and share <= 0:
                continue
            rows.append({
                "key_code": key,
                "source_id": sid,
                "share": None if mixed else round(share, 6),
                "confidence": weakest(CONFIDENCE_ORDER, confs),
                "basis": weakest(BASIS_ORDER, bases),
                "as_of": stamp,
            })
    # 比率のある町丁目は share の降順、無い町丁目は source_id 順
    rows.sort(key=lambda r: (r["key_code"], -(r["share"] if r["share"] is not None else 0), r["source_id"]))
    return rows, {k: round(v, 6) for k, v in unresolved.items() if v > 1e-9}
