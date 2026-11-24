-- 龍郷町「広報たつごう」（docs/plans/TATSUGO_KOHO.md §3）。scripts/m13_tatsugo_koho.py が cells.sqlite に作る。
-- documents（既存。1 PDF ファイル＝1行）に、号・号⇔ファイル・記事・話題・地名を足す。
-- D1 側の Drizzle スキーマ（web/src/db/schema.ts）は列を一致させる。
CREATE TABLE IF NOT EXISTS periodical_series (
  series_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, title TEXT, publisher TEXT, region_id TEXT,
  listing_urls TEXT, license TEXT, agreement_note TEXT
);
CREATE TABLE IF NOT EXISTS periodical_issues (
  issue_id TEXT PRIMARY KEY, series_id TEXT NOT NULL, source_id TEXT NOT NULL, region_id TEXT NOT NULL,
  kind TEXT NOT NULL,            -- monthly / supplement
  year_month TEXT NOT NULL,      -- YYYY-MM（合併号は若い方）
  year_month_to TEXT,            -- 合併号だけ（2019-05）
  fiscal_year INTEGER,           -- 4月始まりの年度
  issued_on TEXT, issued_on_raw TEXT, label_raw TEXT, listing_url TEXT,
  headlines TEXT,                -- 令和2年度以降の「主な記事」の見出し原文（JSON 配列）
  n_files INTEGER, n_pages INTEGER, note TEXT,
  FOREIGN KEY(series_id) REFERENCES periodical_series(series_id)
);
CREATE INDEX IF NOT EXISTS ix_periodical_issues_source ON periodical_issues(source_id);
CREATE INDEX IF NOT EXISTS ix_periodical_issues_ym ON periodical_issues(year_month);
CREATE TABLE IF NOT EXISTS periodical_issue_files (
  doc_id TEXT PRIMARY KEY, issue_id TEXT NOT NULL, part_no INTEGER NOT NULL,
  page_offset INTEGER NOT NULL,  -- 号内通しページ = ファイル内ページ + page_offset
  link_text_raw TEXT, download_url TEXT,
  FOREIGN KEY(doc_id) REFERENCES documents(doc_id),
  FOREIGN KEY(issue_id) REFERENCES periodical_issues(issue_id)
);
CREATE INDEX IF NOT EXISTS ix_periodical_issue_files_issue ON periodical_issue_files(issue_id, part_no);
CREATE TABLE IF NOT EXISTS document_articles (
  article_id TEXT PRIMARY KEY, issue_id TEXT NOT NULL, doc_id TEXT NOT NULL, source_id TEXT NOT NULL, region_id TEXT NOT NULL,
  kind TEXT NOT NULL,            -- article / unsegmented / cover_toc
  page_from INTEGER NOT NULL, page_to INTEGER NOT NULL,                 -- ファイル内ページ
  issue_page_from INTEGER NOT NULL, issue_page_to INTEGER NOT NULL,     -- 号内通しページ
  title TEXT, section TEXT, body_text TEXT, body_sha256 TEXT, event_dates TEXT,
  doc_sha256 TEXT, extractor TEXT, confidence REAL, verified_by TEXT, unreadable_reason TEXT, extracted_at TEXT,
  FOREIGN KEY(issue_id) REFERENCES periodical_issues(issue_id),
  FOREIGN KEY(doc_id) REFERENCES documents(doc_id)
);
CREATE INDEX IF NOT EXISTS ix_document_articles_issue ON document_articles(issue_id);
CREATE INDEX IF NOT EXISTS ix_document_articles_doc ON document_articles(doc_id, page_from);
CREATE INDEX IF NOT EXISTS ix_document_articles_source ON document_articles(source_id);
CREATE TABLE IF NOT EXISTS document_article_topics (
  article_id TEXT NOT NULL, topic_id TEXT NOT NULL, extractor TEXT, confidence REAL,
  PRIMARY KEY (article_id, topic_id),
  FOREIGN KEY(article_id) REFERENCES document_articles(article_id)
);
CREATE INDEX IF NOT EXISTS ix_document_article_topics_topic ON document_article_topics(topic_id);
CREATE TABLE IF NOT EXISTS document_article_places (
  article_id TEXT NOT NULL, place_raw TEXT NOT NULL, place_type TEXT,
  place_id TEXT,                 -- place 表に在るものだけ。集落などは NULL
  match_method TEXT, confidence REAL,
  PRIMARY KEY (article_id, place_raw),
  FOREIGN KEY(article_id) REFERENCES document_articles(article_id)
);
CREATE INDEX IF NOT EXISTS ix_document_article_places_place ON document_article_places(place_id);
