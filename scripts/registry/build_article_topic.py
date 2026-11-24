"""article_topic（記事の話題の語彙）を作る（Issue #130、docs/plans/TATSUGO_KOHO.md §4）。

`registry/article_topic.yaml` を読み、形を検査して `article_topic` 表に入れるだけ。原本 DB には触れない
（`src` は他のビルダーと形を揃えるための引数で使わない。`--files-only` でもそのまま動く）。
`scripts/m13_tatsugo_koho.py` は同じ yaml を `load_topics()` で直接読む（registry.sqlite に依存しない）。
"""
from __future__ import annotations

import pathlib
import re
import sqlite3

import yaml

from . import common

ARTICLE_TOPIC_YAML = common.ROOT / "registry" / "article_topic.yaml"
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class TopicError(ValueError):
    pass


def load_topics(path: pathlib.Path | None = None) -> dict[str, dict]:
    """{topic_id: {"ja": ..., "note": ...}}。形が不正なら TopicError。`other` が必須（どれにも当たらない記事の受け皿）。"""
    doc = yaml.safe_load((path or ARTICLE_TOPIC_YAML).read_text(encoding="utf-8"))
    topics = (doc or {}).get("topics")
    if not isinstance(topics, dict) or not topics:
        raise TopicError("article_topic.yaml: topics が無い")
    for tid, e in topics.items():
        if not isinstance(tid, str) or not _ID_RE.match(tid):
            raise TopicError(f"article_topic.yaml: topic_id {tid!r} は英小文字・数字・_ だけ")
        if not isinstance(e, dict) or not isinstance(e.get("ja"), str) or not e["ja"].strip():
            raise TopicError(f"article_topic.yaml: {tid} に ja（表示名）が無い")
        extra = set(e) - {"ja", "note"}
        if extra:
            raise TopicError(f"article_topic.yaml: {tid} に未対応のキー {sorted(extra)}")
    if "other" not in topics:
        raise TopicError("article_topic.yaml: other が無い（どれにも当たらない記事の受け皿）")
    return topics


def build(conn: sqlite3.Connection, src: dict[str, sqlite3.Connection] | None = None) -> dict[str, int]:
    rows = [(tid, e["ja"], e.get("note")) for tid, e in sorted(load_topics().items())]
    n = common.insert_many(conn, "article_topic", ["topic_id", "name_ja", "note"], rows)
    return {"article_topic": n}
