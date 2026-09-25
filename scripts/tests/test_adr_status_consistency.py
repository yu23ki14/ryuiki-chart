"""docs/adr/README.md の一覧表と、各 ADR ファイル自身の `- 状態:` 行が食い違っていないかを
機械的に検証する。

Issue #36 のレビューで実際に起きた2つの事故の再発防止:

1. ADR-0026 が README の一覧表に載っていなかった（ファイルはあるのに一覧に無い）。
2. ADR-0011 の状態が README・ADR ファイル本体・status-review-2026-09-25.md の3か所に
   別々の文言で書かれ、修正が1か所だけに反映されて残り2か所とずれた。

このテストが検証するのは3点だけ（docs/adr/README.md の「状態の判定基準」節が定めた役割分担
どおり、状態の正は各 ADR ファイルの `- 状態:` 行で、README は状態語 + 一部未実装の有無だけを
持つ）:

1. 各 ADR ファイルの状態語（提案中/承認済/却下/置換済）と「一部未実装」の有無が、
   README の対応する行と一致すること。
2. README の一覧に、docs/adr/ にある全ての ADR ファイルが漏れなく載っていること
   （逆に README にだけあってファイルが無い行も無いこと）。
3. 状態語が許される語彙（`提案中`/`承認済`/`却下`/`置換済(→ADR-XXXX)`）の中にあること。

`check_consistency()` は実ファイルからもテスト用の小さな fixture ディレクトリからも呼べる
形にしてあり、後半のテストは fixture を使って「1行だけ壊すと検出できる」ことを確認する
（変異テスト）。
"""
from __future__ import annotations

import pathlib
import re

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_ADR_DIR = _REPO_ROOT / "docs" / "adr"
_README_PATH = _ADR_DIR / "README.md"

# ADR ファイル自身の `- 状態: <...> / 日付: <...>` 行（複数行に折り返されていてもよい）。
_ADR_STATUS_RE = re.compile(r"-\s*状態:(.*?)/\s*日付:", re.DOTALL)

# README の一覧表の行: `| [0004](0004-identifiers.md) | <決定> | <状態> |`
# 決定・状態の各セルは "|" を含まない前提（テーブル行として壊れる）。
_README_ROW_RE = re.compile(r"^\|\s*\[(\d{4})\]\([^)]+\)\s*\|[^|]+\|([^|]+)\|\s*$", re.MULTILINE)

_SIMPLE_WORDS = {"提案中", "承認済", "却下"}
_REPLACED_RE = re.compile(r"^置換済\(→ADR-\d{4}\)")


def base_status_and_partial_flag(raw: str) -> tuple[str, bool]:
    """状態を表す文字列から基底の状態語と「一部未実装」の有無を取り出す。

    認識できない語なら AssertionError で止まる（黙って None や空文字を返さない
    ——語彙の逸脱を検出すること自体がこの関数の役目のため）。
    """
    text = raw.strip()
    partial = "一部未実装" in text
    cut_positions = [p for p in (text.find("（"), text.find("(")) if p != -1]
    head = text[: min(cut_positions)].strip() if cut_positions else text
    if head in _SIMPLE_WORDS:
        return head, partial
    m = _REPLACED_RE.match(text)
    if m:
        return m.group(0), partial
    raise AssertionError(f"認識できない状態語: {raw!r}")


def adr_numbers_and_paths(adr_dir: pathlib.Path) -> dict[str, pathlib.Path]:
    """`docs/adr/NNNN-*.md` を番号 → パスの辞書にする（README.md・status-review-*.md は
    ファイル名が4桁の数字で始まらないので自然に除外される）。"""
    return {p.name[:4]: p for p in sorted(adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md"))}


def parse_adr_status(path: pathlib.Path) -> tuple[str, bool]:
    text = path.read_text(encoding="utf-8")
    m = _ADR_STATUS_RE.search(text)
    if not m:
        raise AssertionError(f"{path.name}: '- 状態: ... / 日付:' 行が見つからない")
    return base_status_and_partial_flag(m.group(1))


def parse_readme_rows(readme_path: pathlib.Path) -> dict[str, str]:
    text = readme_path.read_text(encoding="utf-8")
    return dict(_README_ROW_RE.findall(text))


def check_consistency(adr_dir: pathlib.Path, readme_path: pathlib.Path) -> list[str]:
    """食い違いを文字列のリストで返す（空リストなら一致）。

    例外にせずリストで返すのは、1件だけ壊した変異テストで「ちょうど1件検出される」ことまで
    assert しやすくするため。
    """
    problems: list[str] = []
    files = adr_numbers_and_paths(adr_dir)
    readme_rows = parse_readme_rows(readme_path)

    for number in sorted(set(files) - set(readme_rows)):
        problems.append(f"{number}: README の一覧に行が無い")

    for number in sorted(set(readme_rows) - set(files)):
        problems.append(f"{number}: README に行があるが ADR ファイルが無い")

    for number in sorted(set(files) & set(readme_rows)):
        file_base, file_partial = parse_adr_status(files[number])
        readme_base, readme_partial = base_status_and_partial_flag(readme_rows[number])
        if (file_base, file_partial) != (readme_base, readme_partial):
            problems.append(
                f"{number}: ADRファイルの状態={file_base}"
                f"{'（一部未実装）' if file_partial else ''} が "
                f"README={readme_base}{'（一部未実装）' if readme_partial else ''} と食い違う"
            )
    return problems


def _is_allowed_word(base: str) -> bool:
    return base in _SIMPLE_WORDS or bool(_REPLACED_RE.match(base))


# ---------------------------------------------------------------------------
# 実データ（docs/adr/）に対する検証
# ---------------------------------------------------------------------------


def test_readme_and_adr_status_lines_are_consistent():
    problems = check_consistency(_ADR_DIR, _README_PATH)
    assert problems == [], "\n".join(problems)


def test_readme_lists_every_adr_file():
    """ADR-0026 が README の一覧に載っていなかった事故の再発防止。"""
    files = adr_numbers_and_paths(_ADR_DIR)
    readme_rows = parse_readme_rows(_README_PATH)
    assert files, "docs/adr/ に ADR ファイルが1つも見つからない（glob パターンの確認）"
    assert set(readme_rows) == set(files)


def test_all_status_words_are_in_allowed_vocabulary():
    files = adr_numbers_and_paths(_ADR_DIR)
    for number, path in files.items():
        base, _ = parse_adr_status(path)
        assert _is_allowed_word(base), f"{number}: 未知の状態語 {base!r}"

    readme_rows = parse_readme_rows(_README_PATH)
    for number, cell in readme_rows.items():
        base, _ = base_status_and_partial_flag(cell)
        assert _is_allowed_word(base), f"{number}: README の未知の状態語 {base!r}"


def test_base_status_and_partial_flag_rejects_unknown_word():
    with pytest.raises(AssertionError):
        base_status_and_partial_flag("謎の状態")


# ---------------------------------------------------------------------------
# 変異テスト（小さな fixture で、check_consistency が実際に壊れを検出できることを確認する）
# ---------------------------------------------------------------------------


def _write_adr_fixture(tmp_path: pathlib.Path, number: str, status_line: str) -> pathlib.Path:
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir(exist_ok=True)
    path = adr_dir / f"{number}-fixture.md"
    path.write_text(
        f"# ADR-{number}: テスト用\n\n- 状態: {status_line} / 日付: 2026-09-25\n",
        encoding="utf-8",
    )
    return adr_dir


def _write_readme_fixture(adr_dir: pathlib.Path, number: str, status_cell: str) -> pathlib.Path:
    path = adr_dir / "README.md"
    path.write_text(
        "# ADR\n\n"
        "| # | 決定 | 状態 |\n"
        "|---|---|---|\n"
        f"| [{number}]({number}-fixture.md) | テスト用の決定 | {status_cell} |\n",
        encoding="utf-8",
    )
    return path


def test_check_consistency_passes_when_matching(tmp_path):
    adr_dir = _write_adr_fixture(tmp_path, "9001", "承認済（一部未実装: X）")
    readme = _write_readme_fixture(adr_dir, "9001", "承認済（一部未実装）")
    assert check_consistency(adr_dir, readme) == []


def test_check_consistency_detects_mismatched_status_word(tmp_path):
    """README の状態語そのものを書き換えて壊れることを確認する
    （実際の修正フローと同じ「1行書き換える→検出される→戻す」の変異テスト）。
    """
    adr_dir = _write_adr_fixture(tmp_path, "9001", "承認済（一部未実装: X）")
    readme = _write_readme_fixture(adr_dir, "9001", "提案中")  # 意図的に食い違わせる
    problems = check_consistency(adr_dir, readme)
    assert len(problems) == 1
    assert "9001" in problems[0]

    # 戻せば緑に戻ることも確認する（壊れっぱなしの fixture を残さない）。
    readme = _write_readme_fixture(adr_dir, "9001", "承認済（一部未実装）")
    assert check_consistency(adr_dir, readme) == []


def test_check_consistency_detects_missing_partial_flag(tmp_path):
    adr_dir = _write_adr_fixture(tmp_path, "9001", "承認済（一部未実装: X）")
    readme = _write_readme_fixture(adr_dir, "9001", "承認済")  # 「一部未実装」が抜けている
    problems = check_consistency(adr_dir, readme)
    assert len(problems) == 1


def test_check_consistency_detects_adr_file_missing_from_readme(tmp_path):
    """ADR-0026 が一覧から漏れていた事故そのものの再現。"""
    adr_dir = _write_adr_fixture(tmp_path, "9001", "承認済")
    readme_path = adr_dir / "README.md"
    readme_path.write_text(
        "# ADR\n\n| # | 決定 | 状態 |\n|---|---|---|\n",  # 9001 の行が無い
        encoding="utf-8",
    )
    problems = check_consistency(adr_dir, readme_path)
    assert any("9001" in p and "README" in p for p in problems)


def test_check_consistency_detects_stray_readme_row_without_file(tmp_path):
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    readme = _write_readme_fixture(adr_dir, "9002", "承認済")  # 9002 のファイルは作らない
    problems = check_consistency(adr_dir, readme)
    assert any("9002" in p and "ファイルが無い" in p for p in problems)
