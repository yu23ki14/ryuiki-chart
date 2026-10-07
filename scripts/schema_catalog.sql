-- 外部ポータルの目録（CKAN 4 インスタンス + e-Stat 7 件）。docs/plans/MCP_EXTERNAL_CATALOG.md §1。
-- scripts/m08_external_catalog.py が流す（CREATE ... IF NOT EXISTS。出典ごとに DELETE → INSERT で冪等）。
-- 値は持たない。「どんなデータがあるか」の定義と、最新を取りに行く URL だけ。
-- D1 の drizzle スキーマ（web/src/db/schema.ts の externalDataset / externalResource）と列を一致させる。

CREATE TABLE IF NOT EXISTS external_dataset (
  dataset_key TEXT PRIMARY KEY,          -- '<source_id>:<dataset_id>'（e-Stat は '<source_id>:<statInfId>'）
  source_id TEXT NOT NULL,
  portal TEXT NOT NULL,                  -- ckan / estat
  dataset_id TEXT NOT NULL,              -- CKAN の UUID（e-Stat は statInfId、境界 GIS は dlserveyId）
  name TEXT,                             -- CKAN の URL 用の名前（e-Stat は NULL）
  title TEXT NOT NULL,
  description TEXT,
  description_truncated INTEGER NOT NULL DEFAULT 0,   -- 収穫時に 800 文字で切ってある（長さがちょうど 800）
  organization TEXT,
  license TEXT,                          -- 空は NULL（不明。除外しない）
  license_url TEXT,
  groups TEXT,                           -- '|' 区切り
  tags TEXT,                             -- '|' 区切り
  n_resources INTEGER NOT NULL DEFAULT 0,
  metadata_modified TEXT,                -- 収穫時点の値（最新は api_url の package_show）
  page_url TEXT NOT NULL,
  api_url TEXT,                          -- CKAN: package_show（UUID 指定）。e-Stat は NULL
  fetched_at TEXT NOT NULL               -- source_registry.fetched_at（出典単位の収穫日）
);
CREATE INDEX IF NOT EXISTS ix_ed_source_modified ON external_dataset(source_id, metadata_modified);
CREATE INDEX IF NOT EXISTS ix_ed_org ON external_dataset(organization);

CREATE TABLE IF NOT EXISTS external_resource (
  resource_key TEXT PRIMARY KEY,         -- '<source_id>:<resource_id>'
  dataset_key TEXT NOT NULL,
  name TEXT,
  format TEXT,                           -- 大文字。'SHP,CSV' のようにカンマ区切りが混ざる
  size INTEGER,
  last_modified TEXT,                    -- 収穫時点の値
  direct_url TEXT,                       -- 直リンク（url が空の行は NULL）
  page_url TEXT,
  sheets_json TEXT                       -- NULL か [{sheet, n_rows, n_cols, header: [...] | null, header_basis?}]
);
CREATE INDEX IF NOT EXISTS ix_er_dataset ON external_resource(dataset_key);
CREATE INDEX IF NOT EXISTS ix_er_format ON external_resource(format);
