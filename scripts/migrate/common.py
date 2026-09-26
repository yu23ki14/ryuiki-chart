"""b03/b04/b05/b10（Phase B ファクトとキューブ、および文書/品質ワークフローの
v1射影）が共有する薄い土台。

- 読み取り専用オープンと YAML 読み込みは `scripts/reconcile/common.open_readonly`/
  `load_yaml` をそのまま使う（同じ規約を2箇所に書かない。既に b01/b02 が
  使っている実装。`scripts/migrate/period.py` はここから `load_yaml` を引く）。
- 出力 sqlite は毎回ゼロから作り直す（`fresh_sqlite`）。前回実行の残骸（WAL/SHM
  側車ファイルを含む）が残ったまま次の実行が古い行を引きずる事故を避ける。
  `fresh_sqlite` は書き込み先が読み取り専用の原本そのものでないことも検査する
  （`reject_protected_source_db` 参照）。**b03/b04 は `--out` を `sqlite3.connect`
  で直接開き `fresh_sqlite` を経由しない**ため、それぞれの `main()` が引数
  パース直後に同じ検査を個別に呼ぶ。
- 実行時間とテーブルごとの行数を `[12.3s] ラベル / N行` の形で出す（`timed_step`）。
- `AVG()`/`SUM()`（b04・b05・b10）または `FULL OUTER JOIN`（`assert_grouped_totals_match`
  経由。b07・b08）を使うスクリプトは、どちらも SQLite 3.43 以降が前提
  （`AVG()`/`SUM()` は加算アルゴリズムの正しさ、`FULL OUTER JOIN` は機能自体の
  対応のため——3.39で足りる `FULL OUTER JOIN` 単体の最小版ではなく、他の
  スクリプトと同じ3.43に揃える）。`require_sqlite_version()` を**各スクリプトの
  構築関数の先頭**で呼ぶ（モジュール読み込み時点ではない——
  `require_sqlite_version` の docstring 参照）。
- 段階間の指紋（`record_stage_fingerprint`/`assert_stage_fingerprint_fresh`/
  `track_reads`/`assert_all_reads_verified`。Issue #37 #1）: あるテーブルが
  「今の上流テーブルから作られた状態」であることと、「実際に読んだ表を
  検証し忘れていないか」を、次の段が読み込み時に機械で確認する。詳細は
  各関数の直前のモジュールコメント参照。
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
_SCRIPTS = ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from reconcile.common import load_yaml, open_readonly  # noqa: E402,F401  (b03/b04/b05/b10 から re-export)
import pipeline_inputs  # noqa: E402  (v2 入力指紋が data/processed の sha256 を再利用する)

# `built_from` / `spec_version` に書く定数。**成果物ごとに別の定数を持つ**
# （2026-09-24 コードレビュー指摘: 以前は `SPEC_VERSION` という1つの定数を
# `b04_build_cube.py`（`observation_agg`）・`b07_build_occurrence_cube.py`
# （`occurrence_agg`）・`b09_build_occurrence_place.py`（`occurrence_place`）の
# 3本が共有していた。`observation_agg` の次元キーだけが変わったときにこの
# 定数を上げると、スキーマの変わっていない `occurrence_agg`/`occurrence_place`
# の行にも「版が上がった」という事実と違う記録が付いてしまう）。
# バージョンを上げるのは、その成果物自身の変換ロジック（キーの構成や
# 集計方法）を変えたとき＝過去に作ったものと比較できなくなるとき。

# `scripts/b04_build_cube.py`（`observation_agg`）専用。2026-09-24:
# ADR-0009 決定4（検閲値の zero/lod 併記）で次元キーから `imputation` を
# 外し（13列→12列）、`value` を `value_zero`/`value_lod` の2列に分けた。
# 過去のキーとは比較できないため v2 に上げた。
OBSERVATION_AGG_SPEC_VERSION = "phase-b-fact-slice/v2"

# `scripts/b07_build_occurrence_cube.py`（`occurrence_agg`）・
# `scripts/b09_build_occurrence_place.py`（`occurrence_place`）専用。
# どちらも今回のキー変更の対象外なので v1 のまま据え置く。
OCCURRENCE_SPEC_VERSION = "phase-b-fact-slice/v1"

# `record_stage_fingerprint`/`record_stage_fingerprints`（段階間の指紋、
# Issue #37 #1）の `spec_version` 引数の既定値。**成果物ごとの `built_from`/
# `spec_version`（上の2定数）とは別の軸**——`pipeline_fingerprint.spec_version`
# は「指紋機構そのものの記述用メタデータ」で、どの機械検証にも使わない
# （2026-09-25 現在。読むのは人だけ）。`observation`/`occurrence`（基底表）・
# `scripts/b05_project_v1.py`/`scripts/b08_project_occurrence_v1.py`/
# `scripts/b11_project_place_v1.py` の v1 射影各表のように、自分の行に
# `spec_version` 列を埋め込まない表はこの既定値のまま記録する。
# **`observation_agg`/`occurrence_agg`/`occurrence_place` のように自分の行に
# `spec_version` を埋め込む表は、ここではなく成果物ごとの値
# （`OBSERVATION_AGG_SPEC_VERSION`/`OCCURRENCE_SPEC_VERSION`）を呼び出し側が
# 明示的に渡す**（2026-09-25 main マージ時の判断: 「成果物ごとの版番号を
# そのまま使う」——`observation_agg` の指紋だけが空 v1 の既定値のまま取り
# 残されて実際の v2 と食い違って見える、という事態を避ける）。
FINGERPRINT_SPEC_VERSION = "phase-b-fact-slice/v1"

# v2 キューブ（`observation_agg`/`occurrence_agg`）の鮮度判定で使う CLI 終了コード
# （`scripts/check_v2_fresh.py`。`scripts/r01_build_registry.py` の
# `EXIT_FRESH`/`EXIT_STALE` と同じ流儀: 0=新鮮、10=古い、それ以外=判定不能）。
# Issue #48 PR-0。
V2_CHECK_EXIT_FRESH = 0
V2_CHECK_EXIT_STALE = 10

# D1 に載せるキューブ表と、それぞれの spec_version。値は上の
# `OBSERVATION_AGG_SPEC_VERSION`/`OCCURRENCE_SPEC_VERSION` を直接引く——
# ここで複製しない。`scripts/check_v2_fresh.py`・
# `web/scripts/seed-d1-local.mjs`（Python の `scripts/check_v2_fresh.py` を
# 子プロセスとして呼ぶ）が読む唯一の正本（コードレビュー指摘: 以前は
# `web/scripts/seed-d1-local.mjs` にこの2値の手書きの写しを持っていたが、
# b03/b04 が spec_version を上げても JS 側の写しは自動で追随しないため、
# 黙ってずれた状態のまま「新鮮」と誤判定する穴があった）。
V2_CUBE_SPEC_VERSIONS = {
    "observation_agg": OBSERVATION_AGG_SPEC_VERSION,
    "occurrence_agg": OCCURRENCE_SPEC_VERSION,
}

# SQLite 3.43 未満では2つの理由でパイプラインが壊れる: (1) AVG()/SUM() の
# 加算アルゴリズムが素朴な左→右加算に落ち、平均が黙って壊れる（b04・b05・
# b10）。(2) FULL OUTER JOIN（`assert_grouped_totals_match` が使う。SQLite
# 3.39 で追加）自体が使えず `sqlite3.OperationalError` で落ちる（b07・b08）。
# 元は b04 だけに書かれていたが、他のスクリプトでも同じ「3.43 以降が前提」
# というリスクがあるため共通ヘルパへ切り出した。3.39 で足りる FULL OUTER
# JOIN 単体の最小版ではなく、AVG()/SUM() の要件に合わせて 3.43 で統一する
# （パイプライン全体を1つの基準で揃える）。バージョン・件数の実測は
# docs/plans/PHASE_B_DOCUMENTS.md §2 の1箇所にまとめてある（ここでは繰り返さない）。
MIN_SQLITE_VERSION = (3, 43, 0)


def require_sqlite_version(min_version: tuple[int, int, int] = MIN_SQLITE_VERSION) -> None:
    """`sqlite3.sqlite_version_info` が `min_version` 未満なら `SystemExit` で止まる。

    **呼び出し側（b04/b05/b07/b08/b10）は各スクリプトの構築・射影関数の先頭
    （`build_cube`/`build_projections`/`build_documents_projection`/
    `build_org_norm_projection`/`build_occurrence_cube_projections`/
    `build_all_projections`）でこれを呼ぶこと。モジュール読み込み時点
    （トップレベル）では呼ばない。** 古い SQLite の環境で `import` した瞬間に
    `SystemExit` が飛ぶと、`pytest` は複数のテストファイルを import してから
    収集するため、無関係な1ファイルの import 失敗がスイート全体の収集を
    止めてしまう（守りたい状況（古い環境）でこそ壊れる形だった——コード
    レビュー指摘。実測は `docs/plans/PHASE_B_DOCUMENTS.md` §2 参照）。関数の
    先頭で呼べば、CLI からの実行でも関数の直接呼び出しでも同じガードが効き、
    `import` 自体は安全になる。

    `assert` にしない理由は `python -O`/`PYTHONOPTIMIZE=1` では `assert` が
    丸ごと消え、まさにこのガードが要る場面で無効化されてしまうため
    （`scripts/tests/test_b04_build_cube.py::test_min_sqlite_version_guard_is_systemexit_not_assert`
    参照）。
    """
    if sqlite3.sqlite_version_info < min_version:
        raise SystemExit(
            f"sqlite3（Python 同梱、バージョン {sqlite3.sqlite_version}）が古すぎる。"
            f"SQLite {'.'.join(map(str, min_version))} 以降が必要——それより前は "
            "AVG()/SUM() が Kahan-Babuška-Neumaier 加算ではなく素朴な左→右加算に落ちて"
            "平均値が黙って変わる（b04/b05/b10）、または FULL OUTER JOIN 自体が使えず"
            "OperationalError で落ちる（b07/b08）。実測は docs/plans/PHASE_B_DOCUMENTS.md "
            "§2 参照。sqlite3 CLI のバージョンではなく、この Python が import する "
            "sqlite3 モジュール（標準ライブラリに静的リンクされた版）のバージョンを見ている。"
        )


class MigrationError(Exception):
    """b03/b04/b05/b10 が「黙って捨てず・黙って推測せず」止まるときに投げる例外。

    データの中身に起因する想定外（alias/place が解決できない、value_grain と
    period_grain が宣言されていない食い違い方をしている等）はすべてこれを使う。
    プログラムのバグ（引数の誤り等）は通常の例外のままにして区別する。
    """


# `reject_protected_source_db` が保護する読み取り専用の原本（`--out` に誤って
# これらのパスを渡されたときに拒む）。
_PROTECTED_SOURCE_DB_NAMES = ("ryuiki.sqlite", "cells.sqlite", "derived.sqlite")


def assert_distinct_realpaths(path, protected: dict[str, object], *, message_for) -> None:
    """`path` の実パス（`os.path.realpath`、symlink を解決済み）が
    `protected`（ラベル -> パス）のどれとも一致しないことを確認する。一致すれば
    `message_for(label, resolved_other_path)` が組み立てた文言で `MigrationError`
    を投げる。

    **書き込み先のパスに対する検査であり、読み取り専用で開く経路
    （`attach_readonly`・`open_readonly`）は対象外**（読み取り専用で開くこと
    自体は他方を傷つけない）。`reject_protected_source_db`（原本3つ、固定の
    ファイル名）と `scripts/b11_project_place_v1.py` の
    `_assert_out_path_distinct_from_inputs`（射影の入力2つ、呼び出し側が渡す
    可変のパス）が、どちらもこのヘルパを呼ぶ（コードレビュー指摘: 同じ
    realpath 比較のロジックが2か所に別々にあった）。

    worktree ではこれらは symlink（CLAUDE.md「worktree の運用」）なので、
    パス文字列の比較ではなく実パスで比べる。ファイルが存在しない場合でも
    `realpath` は正規化したパスを返すため、原本がまだ無い環境（CI 等）でも
    判定できる。
    """
    resolved = os.path.realpath(str(path))
    for label, other in protected.items():
        other_resolved = os.path.realpath(str(other))
        if resolved == other_resolved:
            raise MigrationError(message_for(label, other_resolved))


def reject_protected_source_db(path: pathlib.Path) -> None:
    """`path`（書き込み先として使うつもりのパス）が `data/db/ryuiki.sqlite`/
    `cells.sqlite`/`derived.sqlite`（symlink 越しも含む）と同じ実体を指して
    いたら `MigrationError` で止まる。

    `fresh_sqlite` は内部でこれを呼ぶので、`--out` が `fresh_sqlite` を経由する
    スクリプトは自動的に保護される。**b03/b04 は `--out` を `sqlite3.connect`
    で直接開き `fresh_sqlite` を経由しないため、それぞれの `main()` が引数
    パース直後にこれを個別に呼ぶ**（コードレビュー指摘: `fresh_sqlite` 経由
    だけでは b03/b04 の `--out` が保護されておらず、原本に直接書き込む事故が
    起こりうる状態だった）。
    """
    protected = {name: ROOT / "data" / "db" / name for name in _PROTECTED_SOURCE_DB_NAMES}
    assert_distinct_realpaths(
        path, protected,
        message_for=lambda _label, other: (
            f"{path} は読み取り専用の原本（{other}）と同じ実体を指している。"
            "書き込み先（--out）に原本のパスを渡していないか確認すること。"
        ),
    )


@contextlib.contextmanager
def timed_step(label: str):
    """`with timed_step("観測を読み込む") as info: ... info["n"] = 件数` の形で使う。

    ブロックを抜けるときに `[12.3s] label / N件` を標準出力に出す
    （`scripts/b01_derived_baseline.py` が完了時に件数を出す流儀を、
    ステップ単位に広げたもの）。`info["n"]` を設定しなければ件数無しで出す。
    """
    t0 = time.perf_counter()
    info: dict = {"n": None}
    try:
        yield info
    finally:
        elapsed = time.perf_counter() - t0
        n = info.get("n")
        suffix = f" / {n:,}件" if n is not None else ""
        print(f"[{elapsed:.1f}s] {label}{suffix}")


def fresh_sqlite(path) -> sqlite3.Connection:
    """`path` の出力 sqlite を毎回作り直して書き込み用に開く。

    既存ファイルと WAL/SHM 側車ファイルを先に消してから作る。前回実行の残骸が
    残ったままだと、b03〜b05 を2回実行してのバイト一致確認（受け入れ条件2）が
    「たまたま同じ内容が残っていただけ」で偽陽性になりうるため、必ずゼロから作る。
    `uri=True` で開く（ATTACH で読み取り専用 DB を `file:...?mode=ro` として
    付けられるようにする。`open_attached_readonly` 参照）。

    **`path` が読み取り専用の原本そのものを指していたら、消す前に
    `MigrationError` で拒む**（`reject_protected_source_db` 参照。`--out` に
    原本のパスを誤って渡すと、以降の `unlink()` が100MB超で再生成できない
    原本を消してから失敗する——コードレビュー指摘）。
    """
    p = pathlib.Path(path)
    reject_protected_source_db(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-shm", "-wal"):
        sidecar = pathlib.Path(str(p) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    conn = sqlite3.connect(f"file:{p}", uri=True)
    conn.execute("PRAGMA journal_mode=DELETE")  # 出力ファイルを単一ファイルのまま完結させる
    return conn


def _staging_table_name(table: str) -> str:
    return f"{table}__building"


@contextlib.contextmanager
def staged_table(
    conn: sqlite3.Connection, table: str, create_sql: str, params=(), *,
    fingerprint_inputs: dict[str, str] | None = None,
    fingerprint_spec_version: str = FINGERPRINT_SPEC_VERSION,
):
    """`table`（`observation`/`observation_agg` のような本番テーブル）を
    「作業用テーブルに作る → 呼び出し側が全部挿入・検証する → 本番名に差し替える」
    の手順で作り直す（A-1）。

    `fingerprint_inputs`（Issue #37 #1・/code-review 指摘の根本対応）:
    `None`（既定）なら今までどおり指紋の記録はしない（呼び出し側が `with`
    ブロックの外で別途 `record_stage_fingerprint()` を呼ぶ設計のまま）。
    **辞書（空 `{}` でもよい）を渡すと、差し替え（DROP+RENAME）と同じ明示
    トランザクション内で `record_stage_fingerprint(conn, table,
    spec_version=fingerprint_spec_version, inputs=fingerprint_inputs)` も
    実行し、1つの `conn.commit()` で確定する**——「表の差し替えのコミットと
    指紋の記録が別コミットなので、その間でプロセスが落ちると『内容は新しいが
    指紋は古い（前回のまま）』状態が残ってしまう」という穴（/code-review
    指摘）をこれで塞ぐ。差し替えの DDL と指紋の記録がどちらも成功しないと
    コミットされない（片方が失敗すればロールバックで本番テーブルも元に戻る
    ——`with` ブロック内の検証失敗時と同じ「本番はそのまま」を保つ）。

    `fingerprint_spec_version`（既定 `FINGERPRINT_SPEC_VERSION`）: `table` が
    自分の行に `spec_version`/`built_from` 列を埋め込む成果物（`observation_agg`
    → `OBSERVATION_AGG_SPEC_VERSION`、`occurrence_agg`/`occurrence_place` →
    `OCCURRENCE_SPEC_VERSION`）なら、呼び出し側がその値をそのまま渡すこと
    （2026-09-25 main マージ時の判断。`FINGERPRINT_SPEC_VERSION` 定義の
    コメント参照——「成果物ごとの版番号をそのまま使う」）。埋め込み列を
    持たない基底テーブル（`observation`/`occurrence`）は既定のままでよい。

    以前の b03/b04 は `replace_table`（DROP+CREATE、本番名に対して実行）を検証
    より先に呼んでいた。`dest.commit()` を出典ごと・ステップごとに呼んでいた
    ため、検証に失敗しても、それより前に呼ばれた `commit()` の分だけは既に
    確定してしまっており、本番テーブルは新しい（まだ全部の検証を通っていない）
    内容に差し替わっていた。ここでは DDL・DML を**作業用の別名**
    （`f"{table}__building"`）に対してだけ行い、本番名（`table`）に触る DDL は
    `with` ブロックが例外なく終わったとき（＝全検証を通過したとき）にしか
    実行しない。

    **明示的に `commit()`/`rollback()` を呼ぶ（DDL が暗黙にコミットすることに
    頼らない）。** Python 3.6 以降の `sqlite3` モジュールは、DML（INSERT 等）の
    直前にだけ暗黙のトランザクションを開始し、DDL（CREATE/DROP/ALTER）の
    前に自動でコミットすることは**しない**（それより前の Python の挙動だった。
    実測: `executemany` の後に `DROP TABLE` するだけでは、そのままプロセスを
    `close()` すると `DROP` 自体も取り消される——保留中の DML トランザクションに
    DDL が相乗りするだけで、コミットされないため）。そのためここでは各ステップ
    （作業用テーブルの準備・失敗時の破棄・成功時の差し替え）の前後で
    `conn.commit()`/`conn.rollback()` を明示的に呼び、呼び出し側が `with`
    ブロックの中でコミットしたかどうかに依存しない。

    使い方:

        with common.staged_table(conn, "observation", CREATE_SQL) as staging:
            conn.executemany(f'INSERT INTO "{staging}" ...', rows)
            ... # 検証。失敗したら例外を投げる
        # ここまで来たら差し替え済み（本番テーブル名 "observation" で読める）

    - `with` ブロックで例外（検証失敗を含む）が起きたら、`conn.rollback()`
      （呼び出し側が積んだ未コミットの INSERT 等を破棄する）→ 作業用テーブルを
      `DROP` → `conn.commit()`（`DROP` を確定させる）の順で片付けてから、同じ
      例外をそのまま再送出する。**本番テーブルには一切触れない。**
    - ブロックが正常に終わったら、`conn.commit()`（呼び出し側が積んだ最後の
      未コミット分を確定させる）のあと、`DROP TABLE IF EXISTS`（本番テーブルを
      消す）と `ALTER TABLE ... RENAME TO`（作業用テーブルを本番名にする）を
      **明示の `BEGIN`〜`COMMIT` で1つのトランザクションにする**（コードレビュー
      指摘。SQLite は DDL をトランザクションに入れられる）。`conn.commit()` の
      直後は開いているトランザクションが無いため、この2つの DDL を裸のまま
      実行すると**それぞれが独立に即座確定する別々の操作**になる——`DROP` が
      確定した直後（`RENAME` の前）にプロセスが死ぬと（Ctrl-C・SIGKILL・OOM・
      停電）、本番テーブルは消えたまま戻らず、次回実行は残った作業用テーブルを
      起動時に `DROP` するため、前回の正しいデータが失われる（レビューで
      `os._exit()` を使って再現・修正を確認済み）。明示のトランザクションに
      包めば、この間にプロセスが死んでもコミットされておらず、再起動後の
      SQLite が未コミットの変更を自動的に巻き戻す（`DROP` も無かったことになり、
      本番テーブルは元のまま）。`with` ブロックの中で例外が起きた場合と同様、
      この2つの DDL の間で何か（通常の Python 例外）が起きたら `conn.rollback()`
      で本番テーブルを元に戻し、作業用テーブルも `DROP` する（`with` ブロックの
      失敗時と同じ「本番はそのまま・作業用は残さない」を保つ）。
      （SQLite の `RENAME` はテーブルに張ったインデックスをそのまま引き継ぐ
      ——`CREATE INDEX`/`CREATE UNIQUE INDEX` は `with` ブロック内で作業用
      テーブル名に対して行えば、差し替え後もそのまま有効に残る。ただし
      **インデックス自体の名前**は `table`（本番名）に依存させないこと——
      差し替えの前後でインデックス名は変わらないため、本番名を埋め込むと
      「作業用テーブルに対する索引なのに本番名を名乗る」中途半端な状態が
      差し替え前に一時的に生まれる）。
    - この関数の呼び出し時点で、前回のクラッシュで残った同名の作業用テーブルが
      あれば、作り始める前に `DROP` する（starting-state のクリーンアップ）。

    `create_sql` は `{table}` プレースホルダを含む文字列
    （例: `f"CREATE TABLE {{table}} (...)"`）にしておくこと——ここで作業用の
    テーブル名を埋め込む。
    """
    staging = _staging_table_name(table)
    conn.execute(f'DROP TABLE IF EXISTS "{staging}"')
    conn.execute(create_sql.format(table=f'"{staging}"'), params)
    conn.commit()
    try:
        yield staging
    except BaseException:
        conn.rollback()
        conn.execute(f'DROP TABLE IF EXISTS "{staging}"')
        conn.commit()
        raise
    conn.commit()
    # 差し替え（DROP + RENAME）を1つの明示トランザクションにする——コード
    # レビュー指摘。裸の DDL 2文のままだと、間でプロセスが死んだときに
    # 「本番テーブルが消えたまま戻らない」窓が生まれる（docstring 参照）。
    conn.execute("BEGIN")
    try:
        conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.execute(f'ALTER TABLE "{staging}" RENAME TO "{table}"')
        if fingerprint_inputs is not None:
            # 差し替えと同じトランザクション内で指紋も記録する（上の
            # docstring 参照）。RENAME 直後なので `table` は既に本番名。
            record_stage_fingerprint(
                conn, table, spec_version=fingerprint_spec_version, inputs=fingerprint_inputs,
            )
    except BaseException:
        conn.rollback()  # 本番テーブル（と指紋）を元に戻す（まだ確定していない）
        conn.execute(f'DROP TABLE IF EXISTS "{staging}"')  # 作業用テーブルも残さない
        conn.commit()
        raise
    conn.commit()


def replace_table(conn: sqlite3.Connection, table: str, create_sql: str, params=()) -> None:
    """`table` を作り直す（`DROP TABLE IF EXISTS` の後に `create_sql` を実行するだけ）。

    b04/b05 は `observation`/`observation_agg` を同じ `data/db/v2.sqlite` に同居
    させる（design.md D8）。ファイル全体を作り直す `fresh_sqlite` は他のスクリプトが
    既に書いたテーブル（例: b03 が作った `observation`）まで消してしまうため使えない。
    「出力は毎回作り直す」という要件を、ファイル単位ではなく**テーブル単位**で
    満たすのがこの関数の役割（b04 が `observation_agg` だけを、b05 が射影先の
    3テーブルだけを作り直す）。

    `params` は `create_sql`（`CREATE TABLE ... AS SELECT ...` の形）内の `?` に
    バインドする値。`CREATE TEMP TABLE ... AS SELECT` でも通常の SELECT と同様に
    バインドパラメータが使える（レビュー指摘: `built_from`/`spec_version` を
    文字列で SQL に埋め込むと、値がアポストロフィを含んだときに構文エラーになる。
    `scripts/b04_build_cube.py` 参照）。
    """
    conn.execute(f'DROP TABLE IF EXISTS "{table}"')
    conn.execute(create_sql, params)


def attach_readonly(conn: sqlite3.Connection, path, alias: str) -> None:
    """書き込み用の `conn`（`fresh_sqlite` で開いたもの）に、読み取り専用の別
    sqlite ファイルを ATTACH する。原本を一切書き換えないことを型ではなく
    実行時に保証する（`mode=ro` の URI で開くので、書き込もうとすると
    sqlite3 が例外を投げる）。
    """
    p = pathlib.Path(path)
    if not p.exists():
        raise FileNotFoundError(f"sqlite ファイルが無い: {p}")
    conn.execute(f"ATTACH DATABASE 'file:{p}?mode=ro' AS {alias}")


def existing_tables(db_path) -> set[str]:
    """`db_path`（sqlite ファイル）が持つテーブル名の集合を、読み取り専用の
    新規接続で返す。`scripts/b08_project_occurrence_v1.py`・
    `scripts/b11_project_place_v1.py` がそれぞれ同型の実装を別々に持っていた
    もの（`_assert_prerequisites`/`_assert_rollup_prerequisites` が「必要な
    テーブルが有るか」を `fresh_sqlite` の前に確かめるのに使う）を1箇所に
    集約した（コードレビュー指摘。`attach_readonly`/`assert_attached_table_exists`
    と同じ「同型の検証は共通ヘルパに寄せる」方針）。
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def _table_exists(conn: sqlite3.Connection, table: str, *, schema: str | None = None) -> bool:
    """`table`（`schema` が None なら `conn` 自身、そうでなければ ATTACH 済みの
    別名 `schema` 越し）が存在するかどうか。`assert_attached_table_exists`
    （無ければ即エラーにする版）と `_read_pipeline_fingerprint_row`（無くても
    エラーにせず `None` を返す版）が共有する（/simplify 指摘: 同型の存在確認が
    複数箇所に別々にあった）。
    """
    master = f"{schema}.sqlite_master" if schema else "sqlite_master"
    row = conn.execute(f"SELECT 1 FROM {master} WHERE type = 'table' AND name = ?", (table,)).fetchone()
    return row is not None


def assert_attached_table_exists(conn: sqlite3.Connection, alias: str, table: str, *, hint: str) -> None:
    """`ATTACH`（`attach_readonly` 等）した `alias` に `table` が存在することを
    確認する。無いと素の `sqlite3.OperationalError`（no such table）になり原因が
    分かりにくいため（`scripts/b05_project_v1.py` の
    `_assert_place_relation_table_exists`・`scripts/b11_project_place_v1.py` の
    `_assert_place_watershed_table_exists` が同型の検証を別々に持っていたものを
    1箇所に集約した。Phase B `phase-b/place-attributes`、main へのリベース時）。

    `hint` は「テーブルが無いときに何をすべきか」を示す1文（呼び出し元ごとに
    文言が違うため呼び出し側から渡す。`raise_on_group_by_duplicates` の
    `build_message` と同じ、文言を1つのテンプレートに揃えない方針）。
    """
    if not _table_exists(conn, table, schema=alias):
        raise MigrationError(f"{alias} に {table} テーブルが無い。{hint}")


def resolve_registry_db(cli_value: str | None, default: pathlib.Path) -> pathlib.Path:
    """`--registry-db` > `RYUIKI_REGISTRY_DB` 環境変数 > `default`、の優先順位。
    `scripts/r01_build_registry.py` と同じ環境変数を見る（CLAUDE.md の規約）。

    b03/b05 が一字一句同じ実装を持っていた（レビュー指摘）ものをここに1つ置く。
    既定値だけがスクリプトごとに違うため `default` を引数で受ける。
    """
    if cli_value is not None:
        return pathlib.Path(cli_value)
    env = os.environ.get("RYUIKI_REGISTRY_DB")
    if env:
        return pathlib.Path(env)
    return default


def raise_on_group_by_duplicates(conn: sqlite3.Connection, sql: str, params: tuple, build_message) -> None:
    """`GROUP BY ... HAVING <集計> > 1` の形で重複を検出する `sql` を実行し、
    1行でも返れば `build_message(dup_rows)` が組み立てた文言で
    `MigrationError` を投げる（`scripts/b05_project_v1.py` の
    `place_lookup`/`site_zone_lookup` の一意性検証・ゾーン番号の衝突検証・
    `assert_alias_is_function` 等と、`scripts/b08_project_occurrence_v1.py` の
    `place_mesh_lookup` の単射検証はどれもこの同じ形——クエリを実行し、重複が
    見つかったら特定の文言で止める——だったものを1箇所に集約した
    （/simplify 指摘2）。

    サンプル件数の絞り込み（`LIMIT n`）を入れるかどうか・`COUNT(*)` か
    `COUNT(DISTINCT ...)` か・メッセージの文言は、すべて呼び出し側に委ねる
    （呼び出し元それぞれの検証は意味も重要度も違うため、文言を1つの
    テンプレートに揃えない——既存テストが見ているメッセージはこの関数を
    導入しても1文字も変わらない）。
    """
    dup = conn.execute(sql, params).fetchall()
    if dup:
        raise MigrationError(build_message(dup))


def assert_dimension_key_unique(
    conn: sqlite3.Connection, staging: str, dim_columns: list[str], *,
    index_name: str, table_label: str, cause_hint: str,
) -> None:
    """`staging`（`staged_table` の作業用テーブル）に `dim_columns` の
    `COALESCE(col, '')` 式で `CREATE UNIQUE INDEX` を張り、次元キーの一意性を
    確認する（`scripts/b04_build_cube.py`〔C-3〕と `scripts/b07_build_occurrence_cube.py`
    がほぼ一字一句同じ実装を持っていたものを1箇所に集約した。/simplify 指摘1）。

    索引は検証用の使い捨て——成功しても検証後に `DROP INDEX` する（固定名の
    索引を本番テーブルまで残すと、次回実行が同じ固定名で索引を作ろうとした
    ときに名前衝突で壊れる）。重複が無ければ索引の作成が成功するだけで済み、
    `GROUP BY` で全行を読み直すより速い（b04 実測: 約12.9秒。モジュール
    docstring 以上の詳細は `scripts/b04_build_cube.py` の「次元キーの一意性
    検証（C-3）」節参照——ここでは実装だけを持つ）。

    **`dim_columns` の生の列に索引を張ってはいけない**。NULL がありうる列
    （`obs_stat`/`taxon_id` 等）に対して、SQL の一意制約は NULL 同士を
    「等しくない」と扱うため、`col IS NULL` の行が2つあっても
    `CREATE UNIQUE INDEX` は重複として検出しない——`GROUP BY`（NULL 同士を
    同じグループにまとめる）となら検出結果が食い違う。`COALESCE(col, '')`
    で NULL を空文字に正準化した式に索引を張ることで、`GROUP BY` と同じ
    「NULL 同士は同じ値」という扱いに揃える。

    `index_name` は呼び出し元ごとに別の固定名にすること（同じ接続で複数の
    `staged_table` を並行して扱う場合の名前衝突を避ける）。`table_label`/
    `cause_hint` はエラーメッセージに使う（`table_label` の次元キーが一意で
    ない旨＋`cause_hint`〔原因の手がかり〕）。
    """
    key_cols = ", ".join(dim_columns)
    key_exprs = ", ".join(f"COALESCE({c}, '')" for c in dim_columns)
    try:
        conn.execute(f'CREATE UNIQUE INDEX {index_name} ON "{staging}" ({key_exprs})')
    except sqlite3.IntegrityError:
        dup = conn.execute(
            f'SELECT {key_cols}, COUNT(*) c FROM "{staging}" GROUP BY {key_exprs} HAVING c > 1 LIMIT 5'
        ).fetchall()
        raise MigrationError(f"{table_label} の次元キーが一意でない行がある（例: {dup}）。{cause_hint}")
    else:
        conn.execute(f'DROP INDEX IF EXISTS "{index_name}"')


@contextlib.contextmanager
def _materialized_join_tables(conn: sqlite3.Connection, left_sql: str, right_sql: str, key_columns: list[str]):
    """`left_sql`/`right_sql`（それぞれ `key_columns + value_columns` の並びで
    `GROUP BY` 済みの行を返す `SELECT` 文字列）の結果を一時テーブルに実体化し、
    結合キー（`key_columns` を `COALESCE` で NULL 安全にしてから `'|'` で
    連結した1列 `__k`）に `UNIQUE INDEX` を張る。`with` を抜けるときに一時
    テーブルを必ず消す。戻り値は一時テーブル名のペア `("__agtm_l", "__agtm_r")`。

    `assert_grouped_totals_match()`/`count_grouped_totals_mismatches()` が
    共有する「一時テーブル＋一意索引」の安全策（/simplify 指摘5）。**最初の
    実装は `WITH` 句のサブクエリを複数列の `IS`（NULL-safe）条件で直接
    `FULL OUTER JOIN` していたが、SQLite のクエリプランナは `IS` を使う JOIN
    条件にインデックスを使わず、ネストループ（両側とも約32,000行なら最大
    約10億回の比較）に落ちる**——実測で2分経っても終わらず、明確な性能事故に
    なった（`scripts/b05_project_v1.py` の `_alias_lookup_sql` が「NULL を
    含みうる列を `IS` で JOIN すると自動インデックスが効かない」と書いている
    問題と同じ根）。単一の計算済み列への通常の `=` ならインデックスを使う
    （実測: 実データ約32,000行×32,000行で0.15秒）。
    """
    key_expr = " || '|' || ".join(f"COALESCE({c}, '')" for c in key_columns)
    conn.execute("DROP TABLE IF EXISTS __agtm_l")
    conn.execute("DROP TABLE IF EXISTS __agtm_r")
    try:
        conn.execute(f"CREATE TEMP TABLE __agtm_l AS SELECT {key_expr} AS __k, sub.* FROM ({left_sql}) sub")
        conn.execute(f"CREATE TEMP TABLE __agtm_r AS SELECT {key_expr} AS __k, sub.* FROM ({right_sql}) sub")
        conn.execute("CREATE UNIQUE INDEX __agtm_l_key ON __agtm_l (__k)")
        conn.execute("CREATE UNIQUE INDEX __agtm_r_key ON __agtm_r (__k)")
        yield "__agtm_l", "__agtm_r"
    finally:
        conn.execute("DROP TABLE IF EXISTS __agtm_l")
        conn.execute("DROP TABLE IF EXISTS __agtm_r")


def assert_grouped_totals_match(
    conn: sqlite3.Connection,
    left_sql: str,
    right_sql: str,
    key_columns: list[str],
    value_columns: list[str],
    build_message,
    *,
    sample_limit: int = 20,
) -> None:
    """`left_sql`/`right_sql`（それぞれ `key_columns + value_columns` の並びで
    `GROUP BY` 済みの行を返す `SELECT` 文字列）を SQL の `FULL OUTER JOIN` で
    直接突き合わせ、キーの欠落・値の食い違いを最大 `sample_limit` 件だけ
    `build_message` に渡して `MigrationError` にする（SQLite 3.43 以降が前提。
    CLAUDE.md の「キューブは SQLite 3.43 以降」参照——`FULL OUTER JOIN` 自体は
    3.39 で入ったが、このコードベースの前提バージョンはそれより新しい）。

    `scripts/b07_build_occurrence_cube.py` の系列ごとの Σn 突合と
    `scripts/b08_project_occurrence_v1.py` の「キューブが今の L2 の分割か」の
    突合はどちらも「2つの GROUP BY 結果を比べ、系列（複数列のキー）ごとの
    粒度で食い違いをサンプルする」という同型の処理だった。以前はどちらも
    両方の GROUP BY 結果を Python の `dict` に展開してから `set` 演算で
    突き合わせており、系列数が約32,000にもなると Python 側の実行時間が
    支配的だった（/simplify 実測: この Python 側だけで b07 約3.6秒・b08
    約2.4秒）。比較そのものを SQL 側で行うことで、Python 側は食い違った行
    （最大 `sample_limit` 件）の整形だけになる（/simplify 指摘3）。

    系列の粒度はそのまま保つ（合計だけを比べない）——系列間で数字が入れ替わる
    壊れ方（ある系列の分が別の系列に付け替わり、全体の合計は変わらない）を
    検出できなくなるのを避けるため。

    「一時テーブル＋一意索引」の実体化は `_materialized_join_tables()` に
    集約してある。キーの比較は NULL 安全（`taxon_id` 等が NULL を取りうる
    ため、素の `=` では NULL 同士が一致しない）。`build_message(rows)` の
    `rows` は `(key_columns..., <value>_l, <value>_r 各 value_columns ごと)`
    の並びのタプルのリスト（片側にしか無いキーは無い方の値が `None`）。
    """
    with _materialized_join_tables(conn, left_sql, right_sql, key_columns) as (lt, rt):
        key_select = ", ".join(f"COALESCE(l.{c}, r.{c}) AS {c}" for c in key_columns)
        value_select = ", ".join(f"l.{c} AS {c}_l, r.{c} AS {c}_r" for c in value_columns)
        mismatch_cond = " OR ".join(f"l.{c} IS NOT r.{c}" for c in value_columns)
        sql = f"""
        SELECT {key_select}, {value_select}
        FROM {lt} l FULL OUTER JOIN {rt} r ON l.__k = r.__k
        WHERE ({mismatch_cond}) OR l.__k IS NULL OR r.__k IS NULL
        LIMIT {sample_limit}
        """
        rows = conn.execute(sql).fetchall()
    if rows:
        raise MigrationError(build_message(rows))


def count_grouped_totals_mismatches(
    conn: sqlite3.Connection,
    left_sql: str,
    right_sql: str,
    key_columns: list[str],
    value_columns: list[str],
) -> int:
    """`assert_grouped_totals_match()` と同じ「一時テーブル＋一意索引」の
    安全な `FULL OUTER JOIN`（`_materialized_join_tables()` を共有）で、
    片方にしかないキー・値が食い違うキーの**総数**を返す（/simplify 指摘5）。

    `assert_grouped_totals_match()` は最大 `sample_limit` 件で打ち切って
    無条件に `MigrationError` を投げるのに対し、こちらは「ある個数だけ
    食い違いが発生する」ことを織り込んだ検証（宣言済みの期待値と実測件数を
    突き合わせる）に使う——`scripts/b08_project_occurrence_v1.py` の
    `_measure_keys_changed_vs_exact`（`org_watershed_year` と
    `org_watershed_year_exact` の突合、宣言値 1,091）が最初の呼び出し元。
    """
    with _materialized_join_tables(conn, left_sql, right_sql, key_columns) as (lt, rt):
        mismatch_cond = " OR ".join(f"l.{c} IS NOT r.{c}" for c in value_columns)
        sql = f"""
        SELECT COUNT(*) FROM {lt} l FULL OUTER JOIN {rt} r ON l.__k = r.__k
        WHERE ({mismatch_cond}) OR l.__k IS NULL OR r.__k IS NULL
        """
        return conn.execute(sql).fetchone()[0]


# ---------------------------------------------------------------------------
# 段階間の指紋（Issue #37 #1。`scripts/b08_project_occurrence_v1.py` の
# `_assert_cube_is_current_l2_partition`——`occurrence_agg` が「今の occurrence
# の分割」であることを SQL の集計突合で直接確かめる仕組み——を、集計関係が
# 無いテーブル対（`observation` → `observation_agg`・`occurrence` →
# `occurrence_agg`/`occurrence_place`・`observation_agg`/`site_var` 等 →
# v1_projection*.sqlite の各テーブル）にも広げられる形に一般化したもの。
#
# **設計の穴とその修正（コードレビュー指摘）**: 当初の実装は「`table` 自身の
# 現在の内容が、`table` 自身が最後に記録した指紋と一致するか」（以下 (a)）
# だけを見ていた。これは「壊れた/指紋を記録する前に落ちた入力」は検出するが、
# 「**下流が古い上流から作られたまま**」（例: b03 だけ作り直し、b04 を
# 忘れて b05 を実行——b05 は `observation_agg` 自身の指紋とは一致するので
# (a) だけでは通ってしまう。`observation_agg` が古い `observation` から
# 作られたままなのに）を検出できない。これを塞ぐため、各段は「そのテーブルを
# 作るときに読んだ上流テーブルの、その時点の指紋」も**系譜**として記録し
# （`inputs` 列、`{上流テーブル名: 指紋}` の JSON）、消費側は (a) に加えて
# (b)「系譜に記録された各上流の指紋が、**上流テーブル自身が今記録している
# 自己指紋**と一致するか」も確認する。
#
# 設計判断（`docs/plans/PHASE_B_FACT_SLICE.md` 該当項目参照）:
# - `_assert_cube_is_current_l2_partition` 自体（occurrence_agg ⇔ occurrence の
#   Σn 突合）は**そのまま残す**——集計の正しさまで検証する、ここより強い
#   チェックなので二重化しない。ここで足すのは「集計関係が無い、あるいは
#   別ファイルに分かれているテーブル対」を埋める汎用の指紋機構。
# - 指紋の中身は「`table`（`schema` が付けば ATTACH 済みの別名越し）の全列・
#   全行を rowid の物理順のまま読み、行区切り・列区切りの制御文字を挟んで
#   sha256 に畳み込んだもの」。`scripts/reconcile/common.compute_fingerprint`
#   （b01/b02 が使う、sqlite/JSON 両対応でキー列ソート込みの全行正準化ハッシュ）
#   を再利用しない——あちらは異なるフォーマット間の比較のための数値許容誤差・
#   キー順ソートまで持つ重い実装で、207万行規模で数十秒かかる（同モジュール
#   ベンチ参照）。ここは常に「同じ sqlite ファイルを、直前に自分が書いたのと
#   同じ接続」で読み直すだけなので、ソートも数値の正準化も要らない——
#   `staged_table`/`fresh_sqlite` がテーブルを毎回まるごと作り直す（インクリ
#   メンタルな追記が無い）という既存の前提により、物理走査順は同じビルド
#   ロジックに対して安定する。
# - 保存場所は「テーブルを持つ出力ファイルそのものの中」の `pipeline_fingerprint`
#   メタ表（`table_name` を主キーに1行）。`scripts/r01_build_registry.py` の
#   `registry_build`（ファイル1つに1行）と同じ発想だが、`v2.sqlite` は
#   `observation`/`observation_agg`（さらに `occurrence`/`occurrence_agg`/
#   `occurrence_place`）を同じファイルに同居させるため、行の主キーをファイル
#   単位ではなく**テーブル単位**にした。
# - **(b) の系譜チェックは上流テーブルの生データを再走査しない**——上流
#   テーブル自身の `pipeline_fingerprint` 行（自己指紋）を読むだけの安い
#   操作（`read_recorded_fingerprint`）。上流の内容が変わっていれば、上流
#   自身が次に読まれたとき（あるいは既に）その差分が検出されるので、
#   ここでは「上流の自己申告どうしが食い違っていないか」だけを確かめれば
#   十分——実測は `docs/plans/PHASE_B_FACT_SLICE.md` 該当項目参照（(a) の
#   全件走査だけがコストで、(b) は無視できる）。
# - **(b) は再帰的に上流の上流もたどる**（/code-review 指摘: 1段しか遡らない
#   と「2段以上前の入力から古いまま作られている」を見逃す——例: b03 だけ
#   別内容で作り直し、b04・b05 を忘れて b11 を実行すると、`site_var` が記録
#   した `observation_agg` の指紋は、まだ作り直されていない `observation_agg`
#   自身の自己申告とは一致してしまうため、1段だけの比較では通ってしまう）。
#   `_assert_lineage_fresh` が `inputs` を辿りながら、各上流の `inputs` を
#   さらに辿る——`visited` 集合で同じノードを2度たどらない。各段は安い参照
#   （上流の生データは読まない）のままなので、チェーンが何段あってもコストは
#   ほぼ変わらない。
# - 系譜の上流テーブルがどの schema にあるかは `upstream_schemas`
#   （`{上流テーブル名: schema}`。未指定のキーは `table` と同じ schema と
#   みなす）で呼び出し側が指定する。`upstream_schemas=None` を渡すと (b) 自体を
#   行わない（呼び出し側が上流ファイルを開いていない等の理由で検証範囲外に
#   したことを明示する——`b0X` 各ファイルの呼び出し箇所のコメント参照）。
# - 検証は「次にそのテーブルを読む段の先頭」で行う（b04 が `observation` を、
#   b05 が ATTACH した `cube.observation_agg` を、というように）。記録が
#   無ければ「この機構より前に作られた出力」として、内容が食い違っていれば
#   「作り直された後、消費側が再実行されていない」として、どちらも
#   `MigrationError` で止める——`rebuild_hint` に次に実行すべきスクリプトを
#   案内する（既存の `_assert_prerequisites`/`_assert_no_stale_taxon_ids` 等と
#   同じ文言の作法）。
# ---------------------------------------------------------------------------

PIPELINE_FINGERPRINT_TABLE = "pipeline_fingerprint"

_CREATE_PIPELINE_FINGERPRINT_SQL = f"""
CREATE TABLE IF NOT EXISTS {PIPELINE_FINGERPRINT_TABLE} (
  table_name TEXT PRIMARY KEY,
  fingerprint TEXT NOT NULL,
  spec_version TEXT NOT NULL,
  inputs TEXT NOT NULL DEFAULT '{{}}'
)
"""


def _fingerprint_table_columns(conn: sqlite3.Connection, table: str, schema: str | None) -> list[str]:
    pragma_db = f"{schema}." if schema else ""
    columns = [r[1] for r in conn.execute(f"PRAGMA {pragma_db}table_info({table})")]
    if not columns:
        qualified = f"{schema}.{table}" if schema else table
        raise MigrationError(f"{qualified} が無い（指紋を計算できない）。")
    return columns


def compute_table_fingerprint(conn: sqlite3.Connection, table: str, *, schema: str | None = None) -> str:
    """`table`（`schema` が None なら `conn` 自身が開いているファイル、そうで
    なければ ATTACH 済みの別名 `schema` 越し）の全列・全行から軽量な内容指紋を
    計算する（上のモジュールコメント参照）。

    `PRAGMA table_info` で列名を毎回発見する（呼び出し側に列名の宣言を持たせ
    ない——将来テーブルに列が増えても、この関数はそのテーブルの現在の全列を
    自動的に指紋に含める）。行は `SELECT <全列> FROM <table>` の物理走査順
    （`ORDER BY` を付けない）のまま読む——`staged_table`/`fresh_sqlite` が
    テーブルを毎回まるごと作り直す設計のため、同じビルドロジックに対しては
    安定する（ソートのコストを払わない）。戻り値は `"sha256:<hex>:<行数>"`
    （行数を末尾に持つことで、内容が同じでも行の重複/欠落だけで変わる
    ケースを取りこぼさない——ハッシュ自体も行区切りの制御文字を挟むため
    既に行数に敏感だが、念のため人が読んでも分かる形で残す）。

    **フルスキャンする（(a) のコスト）。系譜チェック（(b)）はこの関数を
    呼ばない**——`read_recorded_fingerprint` が代わりに使われる。
    """
    columns = _fingerprint_table_columns(conn, table, schema)
    qualified = f"{schema}.{table}" if schema else table
    col_list = ", ".join(columns)
    hasher = hashlib.sha256()
    n = 0
    for row in conn.execute(f"SELECT {col_list} FROM {qualified}"):
        # 1行分をまとめて1つの bytes にしてから hasher.update() を1回だけ呼ぶ
        # （/simplify 指摘D: 以前は列ごとに update() を呼んでいた。バイト列・
        # ハッシュ結果は変えない——列区切り〔Unit Separator〕を各値の後に、
        # 行区切り〔Record Separator〕を最後に置く並びは今までどおり。
        # `bytes.join()`（リスト内包表記）で組み立てるのが最速だった——
        # ジェネレータ式や `bytearray` への逐次 `+=` は Python 側のオーバー
        # ヘッドで元の列ごと update() より遅くなる実測結果が出たため使わない。
        # 0列の行（実運用では起きない）は `parts` が空になり `\x1f` を挟む
        # 相手が無いので分岐する。実測はモジュール docstring「フル走査の
        # コスト」参照）。
        parts = [b"\x00" if value is None else str(value).encode("utf-8", "surrogatepass") for value in row]
        row_bytes = (b"\x1f".join(parts) + b"\x1f\x1e") if parts else b"\x1e"
        hasher.update(row_bytes)
        n += 1
    return f"sha256:{hasher.hexdigest()}:{n}"


def _schema_is_attached(conn: sqlite3.Connection, schema: str) -> bool:
    """`schema` という別名が `conn` に ATTACH 済みかどうか。`PRAGMA database_list`
    で確認する——ATTACH されていない別名に対して `SELECT ... FROM
    <別名>.sqlite_master` を投げると素の `sqlite3.OperationalError`
    （`unknown database`）になるため、事前にここで弾く。
    """
    return any(row[1] == schema for row in conn.execute("PRAGMA database_list"))


def _read_pipeline_fingerprint_row(
    conn: sqlite3.Connection, table: str, *, schema: str | None = None,
) -> tuple[str, str] | None:
    """`table` の `pipeline_fingerprint` 行を `(fingerprint, inputs の JSON
    文字列)` で返す。`schema` が ATTACH されていない・メタ表が無い・該当行が
    無い、のいずれでも `None`（例外を投げない）。`read_recorded_fingerprint`/
    `read_recorded_inputs`/`assert_stage_fingerprint_fresh` の (a) が共有する
    （/simplify 指摘: 「`pipeline_fingerprint` の有無を確かめて1行読む」処理が
    3箇所に別々にあった）。存在確認は `_table_exists` を再利用する。
    """
    if schema is not None and not _schema_is_attached(conn, schema):
        return None
    if not _table_exists(conn, PIPELINE_FINGERPRINT_TABLE, schema=schema):
        return None
    meta_prefix = f"{schema}." if schema else ""
    row = conn.execute(
        f"SELECT fingerprint, inputs FROM {meta_prefix}{PIPELINE_FINGERPRINT_TABLE} WHERE table_name = ?", (table,)
    ).fetchone()
    return row if row else None


def read_recorded_fingerprint(conn: sqlite3.Connection, table: str, *, schema: str | None = None) -> str | None:
    """`table`（`schema` 越し）が自分自身について最後に記録した指紋を読むだけの
    安い操作（`table` の生データは一切読まない）。見つからなければ `None`
    （例外を投げない——呼び出し側が「見つからない」を判断材料にする）。
    """
    row = _read_pipeline_fingerprint_row(conn, table, schema=schema)
    return row[0] if row else None


def read_recorded_inputs(conn: sqlite3.Connection, table: str, *, schema: str | None = None) -> dict[str, str]:
    """`table` が自分自身について記録した系譜（`{上流テーブル名: 消費時点の
    上流指紋}`）を読む。見つからなければ `{}`（呼び出し側の呼び出し順次第では
    「まだ何も記録されていない」ことがあるため、例外にはしない）。
    """
    row = _read_pipeline_fingerprint_row(conn, table, schema=schema)
    if row is None or not row[1]:
        return {}
    return json.loads(row[1])


def record_stage_fingerprint(
    conn: sqlite3.Connection, table: str, *,
    spec_version: str = FINGERPRINT_SPEC_VERSION, inputs: dict[str, str] | None = None,
) -> str:
    """`table`（`conn` 自身が開いているファイルの本番テーブル）の指紋を計算し、
    同じファイルの `pipeline_fingerprint` メタ表（無ければ作る）に記録する
    （`table_name` で upsert）。戻り値は計算した指紋。

    `inputs`（`{上流テーブル名: そのテーブルを作るときに読んだ上流の指紋}`）は
    系譜——省略時は `{}`（上流を持たない基底テーブル。`observation`/
    `occurrence` のように原本 DB から直接作るもの）。ここに書く指紋の値は
    「消費した時点で確認できていた上流の指紋」であればよく、呼び出し側は
    通常 `assert_stage_fingerprint_fresh()` の戻り値（(a) で確認済みの現在値）
    をそのまま渡す——ここで改めて上流を読み直す必要は無い。

    呼び出し側（b03/b04/b06/b07/b09/b05/b08/b11）は、そのテーブルへの本番の
    書き込みが確定した**後**（`staged_table` の `with` ブロックの外、または
    `fresh_sqlite` で全テーブルを書き終えた後）に呼び、続けて `conn.commit()`
    すること（`staged_table` 自身の内部コミットとは別に、この INSERT 自体の
    コミットが要る）。
    """
    conn.execute(_CREATE_PIPELINE_FINGERPRINT_SQL)
    fingerprint = compute_table_fingerprint(conn, table)
    inputs_json = json.dumps(inputs or {}, sort_keys=True, ensure_ascii=False)
    conn.execute(
        f"INSERT INTO {PIPELINE_FINGERPRINT_TABLE} (table_name, fingerprint, spec_version, inputs) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(table_name) DO UPDATE SET fingerprint = excluded.fingerprint, "
        "spec_version = excluded.spec_version, inputs = excluded.inputs",
        (table, fingerprint, spec_version, inputs_json),
    )
    return fingerprint


def record_stage_fingerprints(
    conn: sqlite3.Connection, tables, *,
    spec_version: str = FINGERPRINT_SPEC_VERSION, lineage: dict[str, dict[str, str]] | None = None,
) -> dict[str, str]:
    """`tables`（テーブル名のイテラブル）それぞれについて `record_stage_fingerprint`
    を呼ぶバッチ版（/simplify 指摘: 「作った表を1つずつ回して記録する」ループが
    `scripts/b05_project_v1.py` に1つ・`scripts/b08_project_occurrence_v1.py`
    に3つ、別々にあった）。`lineage`（`{表名: inputs}`）を渡すと、対応する表は
    その `inputs` で記録する——`lineage` に無い（または渡さなかった）表は
    `inputs=None`（系譜無し）。戻り値は `{表名: 記録した指紋}`。
    """
    lineage = lineage or {}
    return {
        table: record_stage_fingerprint(conn, table, spec_version=spec_version, inputs=lineage.get(table))
        for table in tables
    }


def assert_stage_fingerprint_fresh(
    conn: sqlite3.Connection, table: str, *,
    schema: str | None = None, rebuild_hint: str,
    upstream_schemas: dict[str, str] | None = None,
) -> str:
    """`table`（`schema` が None なら `conn` 自身、そうでなければ ATTACH 済みの
    別名 `schema` 越し）が「今の上流から作られた状態」であることを確認する。
    戻り値は (a) で確認した `table` 自身の現在の指紋
    （呼び出し側が自分の出力の `inputs` に再利用できる——上流を読み直させない
    ため）。

    (a) `table` の現在の内容が、`table` 自身が最後に記録した指紋と一致するか
        （フルスキャン。以前からの検証）。
    (b) `table` が記録した系譜（`inputs`、`record_stage_fingerprint` 参照）を
        **再帰的に**たどり、途中のどの上流についても「上流テーブル自身が今
        記録している自己指紋」（生データは読まない安い参照）と、その下流が
        消費時点に記録した値が一致するかを確認する（`_assert_lineage_fresh`）
        ——上流が `table` の構築後に作り直されたのに `table` が再構築されて
        いない、という穴を塞ぐ。**1段だけでなく系譜の系譜も辿る**——/code-review
        指摘: 1段しか遡らないと「2段以上前の入力から古いまま作られている」
        （例: b03 だけ作り直し、b04・b05 を忘れて b11 を実行）を見逃す。
        `upstream_schemas`（`{上流テーブル名: schema}`）で上流テーブルの
        居場所を指定する（未指定のキーは、その上流を記録した段と同じ
        `schema`——同一ファイル内で完結する対はこれで足りる）。**`upstream_schemas`
        が `None` なら (b) 自体を行わない**——上流ファイルを呼び出し側が
        開いていない等の理由で検証範囲外にした場合に明示的に使う（各
        呼び出し箇所のコメントに理由を書くこと）。`inputs` が空（系譜が
        無い基底テーブル、またはチェーンの末端）なら、そこで再帰は自然に
        止まる。

    以下のいずれでも `MigrationError` で止まる（`rebuild_hint` に案内する
    再実行手順を続ける——系譜の途中で見つかった食い違いも同じ `rebuild_hint`
    を使う。呼び出し側は「このチェーン全体を作り直す正しい手順」を渡すこと
    〔例: b11 の `site_var` チェックなら「b04 の後に b05 を再実行すること」
    ——実際に古かったのが `observation`↔`observation_agg` の1段目でも
    `observation_agg`↔`site_var` の2段目でも、この手順で直る〕）:
    - `pipeline_fingerprint` メタ表自体が無い（この機構が入る前に作られた
      出力、または指紋を記録する前にプロセスが落ちた壊れた出力）。
    - `table_name` の行が無い、または (a) 記録済みの指紋と現在の指紋が
      食い違う（このテーブルが作り直された後、それを消費する側の再実行が
      漏れている疑いがある）。
    - (b) 系譜上のどこかの上流の自己指紋が見つからない（上流に指紋の記録が
      無い、または `upstream_schemas` の指定先が ATTACH されていない）、
      または系譜に記録した消費時点の値と食い違う（その上流が作り直された
      後、その下流の再構築が行われていない疑いがある）。
    """
    qualified = f"{schema}.{table}" if schema else table
    row = _read_pipeline_fingerprint_row(conn, table, schema=schema)
    if row is None:
        raise MigrationError(
            f"{qualified} の指紋が記録されていない"
            f"（{PIPELINE_FINGERPRINT_TABLE} が無い、この機構が入る前に作られた古い出力、"
            "または ATTACH されていない可能性がある）。" + rebuild_hint
        )
    recorded, inputs_json = row
    current = compute_table_fingerprint(conn, table, schema=schema)
    if current != recorded:
        raise MigrationError(
            f"{qualified} の内容が記録済みの指紋と一致しない（記録={recorded}, 現在={current}）。"
            f"{table} が作り直された後、それを消費する側の再実行が漏れている可能性がある。"
            + rebuild_hint
        )

    if upstream_schemas is not None:
        inputs = json.loads(inputs_json) if inputs_json else {}
        _assert_lineage_fresh(
            conn, qualified, inputs, schema, upstream_schemas, rebuild_hint, visited={(schema, table)},
        )
    return current


def _assert_lineage_fresh(
    conn: sqlite3.Connection, current_qualified: str, inputs: dict[str, str], current_schema: str | None,
    upstream_schemas: dict[str, str], rebuild_hint: str, visited: set[tuple[str | None, str]],
) -> None:
    """`current_qualified`（`inputs` を記録したテーブルの表示用の名前）が
    記録した系譜 `inputs` の各上流について (b) を確認し、**上流自身の系譜も
    再帰的にたどる**（`assert_stage_fingerprint_fresh` の docstring 参照。
    /code-review 指摘: 1段しか遡らないと2段以上前の入力の古さを見逃す）。

    上流の生データは一切読まない——`read_recorded_fingerprint`/
    `read_recorded_inputs` がそれぞれ上流自身の `pipeline_fingerprint` 行を
    読むだけの安い参照。`visited`（`(schema, table)` の集合）で同じノードを
    2度たどらない（多重参照での重複チェックを避ける。循環は本来起きない
    はずだが、`visited` があるので万一あっても無限再帰しない）。
    """
    for upstream_table, consumed_fp in inputs.items():
        upstream_schema = upstream_schemas.get(upstream_table, current_schema)
        key = (upstream_schema, upstream_table)
        qualified_upstream = f"{upstream_schema}.{upstream_table}" if upstream_schema else upstream_table
        upstream_current = read_recorded_fingerprint(conn, upstream_table, schema=upstream_schema)
        if upstream_current is None:
            raise MigrationError(
                f"{current_qualified} の系譜（inputs）に記録された上流 {qualified_upstream} 自身の"
                "指紋が見つからない（ATTACH されていない、または指紋がまだ記録されていない）。"
                + rebuild_hint
            )
        if upstream_current != consumed_fp:
            raise MigrationError(
                f"{current_qualified} は上流 {qualified_upstream} の指紋 {consumed_fp} を消費した"
                f"状態のままだが、{qualified_upstream} は現在 {upstream_current} を自己申告している"
                f"（{qualified_upstream} が作り直された後、{current_qualified} 以降の再構築が"
                "行われていない可能性がある）。" + rebuild_hint
            )
        if key in visited:
            continue
        visited.add(key)
        upstream_inputs = read_recorded_inputs(conn, upstream_table, schema=upstream_schema)
        if upstream_inputs:
            _assert_lineage_fresh(
                conn, qualified_upstream, upstream_inputs, upstream_schema, upstream_schemas, rebuild_hint, visited,
            )


# ---------------------------------------------------------------------------
# occurrence の縦線（b07/b08/b09）が共有する指紋チェック（/simplify 指摘:
# b07・b09 が一字一句同じ `assert_stage_fingerprint_fresh(conn, "occurrence",
# ...)` 呼び出しを別々に持っていた）。`occurrence` は基底テーブル（系譜を
# 持たない）なので `upstream_schemas` は渡さない。
# ---------------------------------------------------------------------------

def assert_occurrence_fingerprint_fresh(conn: sqlite3.Connection, *, schema: str | None = None) -> str:
    """`occurrence`（`schema` が None なら `conn` 自身、b08 のように ATTACH
    済みの別名越しなら `schema="cube"` 等）の (a) 自己一致を確認し、現在の
    指紋を返す。`b06_build_occurrence.py` を再実行するよう案内する。
    """
    return assert_stage_fingerprint_fresh(
        conn, "occurrence", schema=schema,
        rebuild_hint="scripts/b06_build_occurrence.py を再実行すること。",
    )


# ---------------------------------------------------------------------------
# v2 キューブの鮮度判定（Issue #48 PR-0）。`scripts/check_v2_fresh.py`（CLI）が
# 公開し、`web/scripts/seed-d1-local.mjs`（シード直前の拒否）・
# `web/scripts/ensure-v2.sh`（db:setup/entrypoint の作り直し判定）が読む。
#
# **ここで見るのは `pipeline_fingerprint.spec_version` だけ**——`table` 自身の
# 内容が記録済み指紋と一致するか（self-consistency）は見ない。それは
# `assert_stage_fingerprint_fresh` の役目であり、そちらは「原本や上流表から
# 見て古いか」という重い検証。こちらは「そもそも今のスキーマ・スペックで
# 書かれた表か」という、軽いが PR #26 以前の13列キー（`pipeline_fingerprint`
# 表自体が無い、または `spec_version` が古いまま）を確実に検出できる形の
# 検査に絞る。列集合そのものもここでは見ない——D1 に実際に投入する側
# （`web/src/db/schema-cube.ts`）と、シード先 D1 自身の `PRAGMA table_info`
# を直接突き合わせるのは `web/scripts/seed-d1-local.mjs` の役目（Python 側は
# D1 のスキーマを知らないし、知る必要も無い）。
#
# **これだけでは「v2.sqlite の外側」の鮮度は分からない**——`spec_version` は
# パイプラインの版が変わったときにしか上がらないため、原本・`data/processed`
# の入力・パイプライン自身のコードだけが変わった場合はここでは検出できない
# （以前の `web/scripts/ensure-v2.sh` はこの穴を手書きの `V2_INPUTS` の mtime
# 走査で埋めていた——手書きゆえの漏れ・symlink の lstat mtime・「mtime は
# 新しいが中身は古い」を見逃す弱点があった。/simplify 指摘1）。
# `compute_v2_input_fingerprint()`/`check_v2_pipeline_fresh()`（下）が、
# `scripts/registry/common.py` の `compute_input_fingerprint()`（レジストリの
# `--check-fresh` が使う「ビルドの論理＋手書きの入力を決まった順で連結して
# sha256」という発想）を v2 パイプライン（b03/b06/b09、外部入力を直接読む3段）
# に適用したもの——mtime 走査をやめ、入力の中身の指紋一本に揃える。
# ---------------------------------------------------------------------------

def check_v2_cube_spec_fresh(conn: sqlite3.Connection, table: str, expected_spec_version: str) -> list[str]:
    """`table`（`observation_agg`/`occurrence_agg`。`conn` は v2.sqlite 自身）の
    `pipeline_fingerprint.spec_version` が `expected_spec_version`
    （呼び出し元が `V2_CUBE_SPEC_VERSIONS` から渡す）と一致するか判定する。

    戻り値: 問題点の一覧（1件1行、日本語）。空なら新鮮。
    """
    if not _table_exists(conn, PIPELINE_FINGERPRINT_TABLE):
        return [f"{PIPELINE_FINGERPRINT_TABLE} 表が無い（段階間の指紋が導入される前の出力）"]
    row = conn.execute(
        f"SELECT spec_version FROM {PIPELINE_FINGERPRINT_TABLE} WHERE table_name = ?", (table,)
    ).fetchone()
    if row is None:
        return [f"{PIPELINE_FINGERPRINT_TABLE} に {table!r} の記録が無い"]
    (spec_version,) = row
    if spec_version != expected_spec_version:
        return [f"{table}.spec_version = {spec_version!r}、期待値 {expected_spec_version!r}"]
    return []


def check_v2_cube_fresh(conn: sqlite3.Connection) -> list[str]:
    """`V2_CUBE_SPEC_VERSIONS` の全表について `check_v2_cube_spec_fresh` を行い、
    問題点をまとめて返す（空なら新鮮）。`scripts/check_v2_fresh.py` が使う。
    """
    problems: list[str] = []
    for table, expected_spec_version in V2_CUBE_SPEC_VERSIONS.items():
        problems.extend(check_v2_cube_spec_fresh(conn, table, expected_spec_version))
    return problems


# ---------------------------------------------------------------------------
# v2 パイプラインの「入力＋コードの中身」の指紋（Issue #48 PR-0 /simplify 指摘1）。
#
# 上の `check_v2_cube_fresh` は v2.sqlite 自身の中身（`pipeline_fingerprint.
# spec_version`）だけを見る。ここで足すのは、v2.sqlite の**外側**——読み取り
# 専用の原本（`ryuiki.sqlite`）・`data/processed` の入力・`registry.sqlite`・
# v2 パイプライン自身のコード（段のスクリプトと、それが import する
# `scripts/` 配下のモジュール・読む YAML 宣言）——が最後にビルドしたときから
# 変わっていないかを見る指紋。
#
# **大きい原本（ryuiki.sqlite 828MB）はフルスキャンしない。**
# `scripts/registry/common.py` の `_hash_organism_records_freshness()`
# （organism_records に対して同じ判断を既にしている）に倣い、v2 が読む4表
# （measurements・sensor_timeseries・organism_records・sites）はどれも
# 「行数＋最大rowid」の軽い代理指標にする。実測（scripts/tests/test_migrate_common.py
# のベンチ参照）: `compute_table_fingerprint()`（全内容ハッシュ、行ごとに
# Python でハッシュに畳み込む）は measurements で約3.1秒・sensor_timeseries で
# 約3.8秒かかる（organism_records は列名に SQL 予約語 `order` を含むため
# そのままでは実行できない——量以前に使えない）。r01 が個々の起動のたびに
# 828MB を読み直さない判断をしているのと同じ理由で、ここも代理指標に倒す
# （代理指標は4表合計で約40ms）。`data/processed` の入力2つ（geojson・CSV）は
# 数十MB以下なので `pipeline_inputs.sha256_file()`（`scripts/pipeline_inputs.py`。
# 既存の実装をそのまま再利用——`scripts/b00_run_full_gate.py`/
# `scripts/s01_build_sample.py` と同じキーの取り方に揃える理由でここでも
# 使う）で内容ハッシュする。
#
# **registry.sqlite の内容も丸ごとはハッシュしない。** `scripts/r01_build_registry.py`
# が既に `registry_build.input_fingerprint` として「レジストリ自身の入力の
# 指紋」を記録済みなので、ここではその値を読むだけ（`_registry_input_fingerprint`。
# `assert_stage_fingerprint_fresh` の (b) 系譜チェックが上流の自己申告値だけを
# 読んで生データを読み直さないのと同じ発想）。
#
# **コードの対象ファイルは手書きの一覧にしない。** v2 パイプライン5段
# （`V2_PIPELINE_STAGE_MODULES`）を実際に import し、その結果 `sys.modules` に
# 載った `scripts/` 配下のファイルを機械的に洗い出す（`_v2_pipeline_code_files()`）
# ——`scripts/migrate/*.py`・`scripts/registry/common.py`・
# `scripts/reconcile/{common,datasource}.py`・`scripts/taxon_namespaces.py` が
# 手書きの一覧を保守せずに漏れなく対象へ入る。**フレッシュなサブプロセス**
# （`sys.executable -c ...`）で行う——同じプロセス内で `sys.modules` を見ると、
# 呼び出し元自身（`check_v2_fresh.py` 等）や他のテストが先に import した
# 無関係なモジュールまで拾ってしまい、ビルド時（b03/b06/b09 のいずれかの
# プロセス内、`__main__` が違う）と鮮度確認時（`check_v2_fresh.py` プロセス内）
# とで発見結果が食い違いうる。サブプロセスなら常に「指定した5モジュールと
# その推移的な import だけ」に閉じるので決定論的（実測: `-I -S`〔サイト
# パッケージ無し〕で約76ms、PyYAML 無しでも成功する——`scripts/reconcile/common.py`
# が yaml を遅延 import する設計のおかげで、v2 パイプライン5段の import 自体は
# PyYAML を要求しない。`scripts/tests/test_check_v2_fresh.py` の
# `test_cli_does_not_import_yaml` がこれを壊さないことを確認する）。
# YAML 宣言（`period_exceptions.yaml`・`source_regions.yaml` 等）は import では
# 見つからない（実行時に `load_yaml()` でパスから読むだけ）ため、
# `scripts/migrate/*.yaml` を丸ごと glob で足す（`occurrence_watershed_v1_declarations.yaml`
# のような v1 専用の宣言も混じるが、v2 に無関係な宣言が変わったときに余計な
# 作り直しが起きるだけで安全側——`scripts/registry/common.py` の
# `_fingerprint_source_paths()` が `registry/` 配下を丸ごと対象にしているのと
# 同じ判断）。
# ---------------------------------------------------------------------------

# v2 パイプラインが実際に読み取る ryuiki.sqlite の表（b03: measurements/
# sensor_timeseries、b06: organism_records、b09: sites）。
V2_RYUIKI_TABLES = ("measurements", "sensor_timeseries", "organism_records", "sites")

# v2 パイプラインが実際に読み取る data/processed の入力（b03: 土地利用CSV、
# b09: 流域 GeoJSON）。
V2_PROCESSED_FILES = ("nlni_w12_watersheds.geojson", "nlni_l03b_landuse_by_watershed.csv")

# v2 パイプラインの5段（`scripts/` 直下、モジュール名で import する）。
V2_PIPELINE_STAGE_MODULES = (
    "b03_build_observation",
    "b04_build_cube",
    "b06_build_occurrence",
    "b07_build_occurrence_cube",
    "b09_build_occurrence_place",
)

PIPELINE_INPUT_FINGERPRINT_TABLE = "pipeline_input_fingerprint"

_CREATE_PIPELINE_INPUT_FINGERPRINT_SQL = f"""
CREATE TABLE IF NOT EXISTS {PIPELINE_INPUT_FINGERPRINT_TABLE} (
  component TEXT PRIMARY KEY,
  value TEXT NOT NULL
)
"""

_ABSENT = "absent"


def _ryuiki_table_proxy(ryuiki_db: pathlib.Path) -> dict[str, str]:
    """`V2_RYUIKI_TABLES` それぞれの「行数＋最大rowid」の代理指標
    （モジュールコメント「大きい原本はフルスキャンしない」参照）。
    `ryuiki_db` が無ければ（原本の無い環境）各表を `_ABSENT` として返す
    ——クラッシュしない。**表単位でも同様**——b03/b06/b09 それぞれのテストが
    使う最小フィクスチャの `ryuiki.sqlite` は、そのテストが実際に読む表しか
    持たない（例: b09 のフィクスチャは `sites` だけで `measurements` を
    持たない）ため、ファイルはあっても個々の表が無いことがある。
    """
    if not ryuiki_db.exists():
        return {f"ryuiki.{t}": _ABSENT for t in V2_RYUIKI_TABLES}
    conn = sqlite3.connect(f"file:{ryuiki_db}?mode=ro", uri=True)
    try:
        out: dict[str, str] = {}
        for t in V2_RYUIKI_TABLES:
            if not _table_exists(conn, t):
                out[f"ryuiki.{t}"] = _ABSENT
                continue
            count, max_rowid = conn.execute(f"SELECT COUNT(*), MAX(rowid) FROM {t}").fetchone()
            out[f"ryuiki.{t}"] = f"count={count};max_rowid={max_rowid}"
        return out
    finally:
        conn.close()


def _processed_file_hashes(processed_dir: pathlib.Path) -> dict[str, str]:
    """`V2_PROCESSED_FILES` それぞれの内容 sha256（`pipeline_inputs.sha256_file`
    を再利用——キーの取り方は `data/processed/<name>` の `<name>` 部分だけ、
    `pipeline_inputs.SOURCE_FILE_KEYS` とは別の名前空間でよい。ここでの用途は
    「v2 が最後に読んだときと同じ中身か」の比較だけで、`full_gate_proof.json`
    とキーを揃える必要が無いため）。ファイルが無ければ `_ABSENT`。
    """
    out: dict[str, str] = {}
    for name in V2_PROCESSED_FILES:
        p = processed_dir / name
        out[f"processed.{name}"] = pipeline_inputs.sha256_file(p) if p.exists() else _ABSENT
    return out


def _registry_input_fingerprint(registry_db: pathlib.Path) -> str:
    """`registry.sqlite` 自身が記録した `registry_build.input_fingerprint`
    （`scripts/r01_build_registry.py` が書く）を読むだけ——registry.sqlite の
    中身を読み直さない（モジュールコメント参照）。
    """
    if not registry_db.exists():
        return _ABSENT
    conn = sqlite3.connect(f"file:{registry_db}?mode=ro", uri=True)
    try:
        if not _table_exists(conn, "registry_build"):
            return "no-registry_build-table"
        row = conn.execute("SELECT input_fingerprint FROM registry_build").fetchone()
        return row[0] if row else "no-registry_build-row"
    finally:
        conn.close()


def _v2_pipeline_code_files(root: pathlib.Path) -> list[str]:
    """v2 パイプライン5段（`V2_PIPELINE_STAGE_MODULES`）が実際に import する
    `scripts/` 配下のファイルを、フレッシュなサブプロセスで機械的に洗い出す
    （モジュールコメント参照）。戻り値は `root` からの相対パス文字列（`/` 区切り）
    のソート済みリスト——`scripts/migrate/*.yaml`（YAML 宣言）は含まない
    （呼び出し側の `_v2_pipeline_code_fingerprint()` が別途足す）。
    """
    scripts_dir = (root / "scripts").resolve()
    probe = f"""
import importlib, json, pathlib, sys
sys.path.insert(0, {str(scripts_dir)!r})
for name in {V2_PIPELINE_STAGE_MODULES!r}:
    importlib.import_module(name)
scripts_dir = pathlib.Path({str(scripts_dir)!r})
files = set()
for m in list(sys.modules.values()):
    f = getattr(m, "__file__", None)
    if not f:
        continue
    p = pathlib.Path(f).resolve()
    try:
        rel = p.relative_to(scripts_dir)
    except ValueError:
        continue
    if "__pycache__" in p.parts:
        continue
    files.add(rel.as_posix())
print(json.dumps(sorted(files)))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", probe], capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise MigrationError(
            "v2 パイプラインのコード対象ファイルの機械的な洗い出しに失敗した"
            f"（終了コード {result.returncode}）:\n{result.stderr}"
        )
    return [f"scripts/{rel}" for rel in json.loads(result.stdout)]


def _v2_pipeline_code_fingerprint(root: pathlib.Path) -> str:
    """v2 パイプラインのコードの中身の sha256——import で機械的に見つけた
    `.py`（`_v2_pipeline_code_files()`）と、`scripts/migrate/*.yaml`（YAML 宣言、
    glob。モジュールコメント参照）の両方を、決まった順（相対パス文字列で
    ソート）で連結する（`scripts/registry/common.py` の
    `compute_input_fingerprint()` と同じ形）。
    """
    py_files = _v2_pipeline_code_files(root)
    yaml_files = [
        p.relative_to(root).as_posix() for p in sorted((root / "scripts" / "migrate").glob("*.yaml"))
    ]
    h = hashlib.sha256()
    for rel in sorted(py_files + yaml_files):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update((root / rel).read_bytes())
        h.update(b"\0")
    return f"sha256:{h.hexdigest()}"


def compute_v2_input_fingerprint(
    *,
    ryuiki_db: pathlib.Path | None = None,
    registry_db: pathlib.Path | None = None,
    processed_dir: pathlib.Path | None = None,
    root: pathlib.Path | None = None,
) -> dict[str, str]:
    """v2 パイプライン（b03/b04/b06/b07/b09）の「外側」の入力＋コードの指紋を
    ラベル付きの辞書で返す（モジュールコメント参照）。空でない値を返す各キーは
    `diff_v2_input_fingerprint()` が個別に比較するので、どの入力が変わったかが
    人にも分かる（1本のハッシュに潰さない）。

    引数を省略するとリポジトリの既定パス（`root` 配下）を使う——`registry_db`
    は `resolve_registry_db()` と同じ優先順位（明示 > `RYUIKI_REGISTRY_DB` 環境変数
    > 既定）。テストは一時ディレクトリのパスを明示して渡すことで、原本や
    registry.sqlite が無い環境でも決定論的に確認できる（渡したパスが実在
    しなければ `_ABSENT` 系の値になり、記録時・確認時で同じ非存在パスを渡す
    限り一致する）。
    """
    base = root or ROOT
    ryuiki_db = pathlib.Path(ryuiki_db) if ryuiki_db is not None else base / "data" / "db" / "ryuiki.sqlite"
    registry_db = (
        pathlib.Path(registry_db) if registry_db is not None
        else resolve_registry_db(None, base / "data" / "db" / "registry.sqlite")
    )
    processed_dir = pathlib.Path(processed_dir) if processed_dir is not None else base / "data" / "processed"

    out: dict[str, str] = {}
    out.update(_ryuiki_table_proxy(ryuiki_db))
    out.update(_processed_file_hashes(processed_dir))
    out["registry.input_fingerprint"] = _registry_input_fingerprint(registry_db)
    out["code"] = _v2_pipeline_code_fingerprint(base)
    return out


def record_v2_input_fingerprint(conn: sqlite3.Connection, components: dict[str, str]) -> None:
    """`compute_v2_input_fingerprint()` が返した辞書を `v2.sqlite` の
    `pipeline_input_fingerprint` メタ表（無ければ作る）に upsert する。

    **既存の `pipeline_fingerprint.inputs`（段階間の指紋の系譜）とは別の表に
    する**——`inputs` は `_assert_lineage_fresh()` が「値=上流テーブル名」として
    再帰的にたどる専用の形式で、ここに raw input/コードの指紋を紛れ込ませると
    `scripts/b05_project_v1.py`/`scripts/b08_project_occurrence_v1.py`
    （`upstream_schemas={"observation": "cube"}` 等で `observation`/`occurrence`
    の `inputs` を再帰的にたどる）が `"ryuiki.measurements"` のようなキーを
    上流テーブル名と誤認し、対応する `pipeline_fingerprint` 行が無いとして
    `MigrationError` で落ちる（実際に踏んで気づいた設計ミス）。呼び出し側
    （`b03_build_observation.py`/`b06_build_occurrence.py`/
    `b09_build_occurrence_place.py`）は、本番テーブルへの差し替えが確定した
    後（`staged_table` の `with` ブロックの外）にこれを呼び、`conn.commit()`
    すること（`record_stage_fingerprint` と同じ利用規約）。
    """
    conn.execute(_CREATE_PIPELINE_INPUT_FINGERPRINT_SQL)
    for component, value in components.items():
        conn.execute(
            f"INSERT INTO {PIPELINE_INPUT_FINGERPRINT_TABLE} (component, value) VALUES (?, ?) "
            "ON CONFLICT(component) DO UPDATE SET value = excluded.value",
            (component, value),
        )


def read_v2_input_fingerprint(conn: sqlite3.Connection) -> dict[str, str] | None:
    """`pipeline_input_fingerprint` の内容を辞書で返す。表が無ければ `None`
    （この機構が入る前の v2.sqlite、または PR #26 以前の13列キーの実物）。
    """
    if not _table_exists(conn, PIPELINE_INPUT_FINGERPRINT_TABLE):
        return None
    rows = conn.execute(f"SELECT component, value FROM {PIPELINE_INPUT_FINGERPRINT_TABLE}").fetchall()
    return dict(rows)


def diff_v2_input_fingerprint(recorded: dict[str, str] | None, current: dict[str, str]) -> list[str]:
    """`recorded`（`read_v2_input_fingerprint()`）と `current`
    （`compute_v2_input_fingerprint()` を今の入力で計算し直したもの）を
    キーごとに比べ、食い違いを1件1行（日本語）で返す（空なら新鮮）。
    """
    if recorded is None:
        return [f"{PIPELINE_INPUT_FINGERPRINT_TABLE} 表が無い（この機構が入る前の v2.sqlite）"]
    problems: list[str] = []
    for key in sorted(set(recorded) | set(current)):
        rv, cv = recorded.get(key, "<記録なし>"), current.get(key, "<今回は対象外>")
        if rv != cv:
            problems.append(f"{key}: 記録={rv!r} / 現在={cv!r}")
    return problems


def check_v2_pipeline_fresh(
    conn: sqlite3.Connection,
    *,
    ryuiki_db: pathlib.Path | None = None,
    registry_db: pathlib.Path | None = None,
    processed_dir: pathlib.Path | None = None,
    root: pathlib.Path | None = None,
) -> list[str]:
    """`check_v2_cube_fresh()`（spec_version の一致）と、入力＋コードの指紋の
    比較（`diff_v2_input_fingerprint()`）を合わせた、v2.sqlite の鮮度判定の
    唯一の入口（`scripts/check_v2_fresh.py` が使う）。空なら新鮮。
    """
    problems = check_v2_cube_fresh(conn)
    current = compute_v2_input_fingerprint(
        ryuiki_db=ryuiki_db, registry_db=registry_db, processed_dir=processed_dir, root=root,
    )
    problems.extend(diff_v2_input_fingerprint(read_v2_input_fingerprint(conn), current))
    return problems


# ---------------------------------------------------------------------------
# 読み取りの機械監査（Issue #37 #1、Tier 1。/simplify 指摘A）: 段階間の
# 指紋（上）は「検証した表が新鮮か」を確認するが、「その段が実際に読んだ
# 表**全部**を検証したか」は、これまで人が SQL を目で追って `_assert_
# prerequisites`/`assert_stage_fingerprint_fresh` の呼び出しを書き足す
# 前提に頼っていた。b05 が `cube.observation` を検証せずに読んでいた
# コードレビュー指摘（Issue #37、Turn3）は、まさにこの「新しい JOIN を
# 足したのに検証を足し忘れる」形の見落としだった。`track_reads`/
# `assert_all_reads_verified` はこれを機械的に検出する——ATTACH 先の
# 実表を実際に SELECT した瞬間を `sqlite3.Connection.set_authorizer` で
# 捕まえ、`declared`（その段が検証済みとして宣言する表名の集合）に
# 無ければ止める。
#
# **粒度は表単位ではなく段単位**（`declared` はその段が書く出力全体で
# 共有する1つの集合）。出力テーブルごとに「どの入力を読んだか」を
# 正確に対応づけるのは、複数の出力を1つの接続・1回の走査で作る
# 現状の構造（例: b05 の13テーブル、b08 の10テーブル）とは相性が悪く、
# 非現実的（per-table 精度が要るなら、まず出力ごとに接続を分けるという
# 大きな構造変更が要る）。段単位の粗さで十分——「検証していない表を
# 読んでいる」という見落としそのものは、どの出力テーブルの分か特定
# できなくても検出できれば実害を防げる。per-table の自動導出（Tier 2）は
# 別 Issue に切り出す（`docs/plans/PHASE_B_FACT_SLICE.md` 該当項目参照）。
#
# **対象外の自動判定**: `schema` が `main`（自分自身の出力ファイル。
# 一時テーブルも含む）の読み取りは対象外。ATTACH 先のスキーマは、その
# ファイルが `pipeline_fingerprint` テーブルを持つ（=この指紋機構の
# 対象）ときだけ検査する——原本（`ryuiki.sqlite`/`cells.sqlite`）と
# `registry.sqlite`（`registry_build` という別の一括指紋機構を持つ。
# `scripts/r01_build_registry.py`）はどちらも `pipeline_fingerprint` を
# 持たないため、ハードコードした除外リストを書かなくても自動的に
# 対象外になる。
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def track_reads(conn: sqlite3.Connection):
    """`with track_reads(conn) as reads:` の間に `conn` がコンパイルする
    SQL 文が実際に読む `(schema, table)` の組を `reads`（集合）に集める。

    `sqlite3.Connection.set_authorizer` の `SQLITE_READ` イベントを使う——
    文の**コンパイル時**に発火する（実行時に行ごとに発火するのではない。
    同じ文を何度実行しても1回しか記録されない代わり、`EXPLAIN` のように
    実行されない文でも記録されうる。ここでは「build 関数の本体が読みうる
    表の集合」を知りたいだけなので十分）。`CREATE TEMP TABLE x AS SELECT
    ... FROM cube.observation` のように一時テーブルを作る文も、その
    `SELECT` が参照する実表への読み取りとして記録される——一時テーブルを
    経由して間接的に読んだ実表も、依存グラフを個別に手で追わずに拾える
    （この機構の要）。

    `with` を抜けると authorizer を解除する。ネストして呼ばない前提
    （authorizer は接続に1つしか設定できない）。

    **Python 3.10 以下では `set_authorizer(None)` で解除できない**
    （/code-review 指摘。`None` を渡して解除する対応は Python 3.11 で
    追加された——それより前は `None` がそのままコールバックとして
    登録され、以後そのコネクションで実行する文が全て
    `sqlite3.DatabaseError: not authorized` になる。実測: システムの
    Python 3.10.12〔SQLite 3.37.2〕で再現・確認した。3.10 以下では
    代わりに「常に許可する」コールバックに差し替える——「原本の無い
    環境」の受け入れ基準（pass/skip だけになる）に、SQLite 3.10 系の
    venv も含まれるため、ここで壊すと以降の全クエリが失敗し `pytest`
    が大量に落ちる）。
    """
    reads: set[tuple[str, str]] = set()

    def authorizer(action, arg1, arg2, db_name, _trigger_or_view):
        if action == sqlite3.SQLITE_READ:
            reads.add((db_name or "main", arg1))
        return sqlite3.SQLITE_OK

    conn.set_authorizer(authorizer)
    try:
        yield reads
    finally:
        if sys.version_info >= (3, 11):
            conn.set_authorizer(None)
        else:
            conn.set_authorizer(lambda *_args: sqlite3.SQLITE_OK)


_SQLITE_CATALOG_TABLES = frozenset({"sqlite_master", "sqlite_temp_master", "sqlite_schema"})


def assert_all_reads_verified(
    conn: sqlite3.Connection, reads: set[tuple[str, str]], declared: set[str], *, context: str,
) -> None:
    """`track_reads` が集めた `reads` のうち、`main`（自分自身の出力
    ファイル）以外で、かつ ATTACH 先が `pipeline_fingerprint` を持つ
    （=この指紋機構の対象）表が、`declared`（その段が (a) を検証済みとして
    渡す表名の集合。`pipeline_fingerprint` 自身は除く）に含まれることを
    確認する。含まれない表があれば、検証を足し忘れている疑いとして
    `MigrationError` で止める（`context` は診断メッセージに出す段の名前、
    例 `"b05_project_v1.build_projections"`）。

    `sqlite_master` 等の SQLite カタログ表（`_SQLITE_CATALOG_TABLES`）は
    常に対象外——`_table_exists`/`assert_stage_fingerprint_fresh` 自身が
    テーブルの有無を確かめるのに読む（検証対象のデータそのものではない。
    `track_reads` は「検証中に発生した読み取り」も一緒に拾ってしまうため、
    ここで弾く）。

    **呼び出し順の注意**: `with track_reads(conn) as reads:` を抜ける前に
    この関数を呼ぶ場合、authorizer はまだ有効なので、この関数自身の
    `_table_exists` 呼び出しが新たな `SQLITE_READ` を発生させ、`reads`
    （元の集合そのもの）に書き足す——それを同じ集合に対して走査すると
    `RuntimeError: Set changed size during iteration` になる（実測で踏んだ）。
    そのため最初に `reads` をコピーしてから走査する。
    """
    reads = set(reads)
    undeclared = sorted(
        (schema, table)
        for schema, table in reads
        if schema != "main"
        and table != PIPELINE_FINGERPRINT_TABLE
        and table not in _SQLITE_CATALOG_TABLES
        and _table_exists(conn, PIPELINE_FINGERPRINT_TABLE, schema=schema)
        and table not in declared
    )
    if undeclared:
        names = "、".join(f"{schema}.{table}" for schema, table in undeclared)
        raise MigrationError(
            f"{context}: {names} を読んでいるが、(a) の検証済み表として宣言されて"
            "いない（新しい JOIN・SELECT を足したのに、対応する検証か `declared` への"
            "追加を忘れた可能性がある）。assert_stage_fingerprint_fresh 等で検証してから"
            "declared に加えるか、意図的に対象外にするならその理由をコードのコメントに"
            "書いた上で declared に加えること。"
        )
