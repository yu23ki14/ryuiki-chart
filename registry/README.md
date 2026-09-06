# 語彙レジストリ（`registry/`）

Phase A（`docs/plans/PHASE_A.md`, ADR-0016）の成果物。v1 のファクト（`measurements` /
`organism_records` / `sensor_timeseries` 等）は一切書き換えず、`unit` / `variable` /
`place` / `taxon` / `caveat` という語彙だけを別枠で並走させたもの。

## このディレクトリの中身：手書き vs 生成物

**`registry/` 配下はすべて手書き（Git 管理・レビュー対象）。** ここには生成物は置かない。

| ファイル | 中身 |
|---|---|
| `unit.yaml` | 単位28件。`unit_id` を各行が明示する（後述） |
| `variable.yaml` | 正準指標85件 |
| `variable_alias.csv` | 出典表記→正準 `variable_id` の対応117件 |
| `place/zone.yaml` | Ridge to Reef ゾーン(1-5)の操作的定義 |
| `place/site_supplement.csv` | `sites` テーブルに無い観測地点の補完（143件） |
| `taxon/vernacular_ja.csv` | 人手確認済みの和名54件（`domain.ts` の `NAME_JA` の複製） |
| `caveat.yaml` | 注記14件（`domain.ts` の `DATA_CAVEATS`/`BIOTA_CAVEATS` 等の移設） |

**生成物はここには置かない。** `data/db/registry.sqlite`（gitignore 済み）が唯一の生成物で、
`scripts/r01_build_registry.py` が上記の手書きファイルと、読み取り専用の原本
（`data/db/ryuiki.sqlite` / `cells.sqlite` / `derived.sqlite`）から毎回ゼロから作り直す。
`registry.sqlite` の中身に対して「これが正しい」という判断はしない。正は常にこのディレクトリと
原本側。ADR-0001 の「D1 はいつ捨てて作り直してもよい」がレジストリにも適用される。

## 再構築の手順

```bash
pip install -r requirements.txt          # PyYAML のみ（レジストリビルド専用の依存）
.venv/bin/python3 scripts/r01_build_registry.py   # data/db/registry.sqlite を作る
cd web && pnpm run db:setup              # migrate + seed。registry.sqlite も4本目のソースとして乗る
```

`r01_build_registry.py` は原本3ファイル（ryuiki / cells / derived）を読み取り専用で開き、
一切書き換えない。実行時間は実測で約9秒（8テーブル・52,057行）。2回連続で実行しても
`registry.sqlite` の中身（テーブルごとの行数・全行を安定な順序で並べたハッシュ）は同一になる
（決定論的な再生成）。

## テーブルとID規約（ADR-0004 の Phase A での具体形）

8テーブル：`unit` / `variable` / `variable_alias` / `place` / `place_source_ref` /
`taxon` / `caveat` / `caveat_scope`。DDL は `scripts/schema_registry.sql`
（= `web/src/db/schema-registry.ts` の drizzle 定義から生成）。

計画時点（PHASE_A.md §A-1）は `caveat` 単体7テーブル構成だったが、実装時に「1つの注記が
複数テーブルに掛かる」ことが分かり、スコープを `caveat_scope` に切り出して8テーブルにした
（1:N を表現するため。詳細は `scripts/registry/build_caveat.py` のdocstring）。

| entity | ID の形 | 例 |
|---|---|---|
| unit | `common:unit:<slug>` | `common:unit:mg_per_l` |
| variable | `common:variable:<theme>.<name>` | `common:variable:water.bod` |
| place | `<scope>:place:<kind>.<namespace>-<local>` | `jp-14:place:site.env-pubwater-0142` |
| taxon（GBIF照合） | `common:taxon:gbif.<taxon_key>` | `common:taxon:gbif.2480932` |
| taxon（GBIF未照合） | `common:taxon:ryuiki-taxa.<taxa.taxon_id>` | 元の `taxa` 由来の識別子をそのまま使う |
| caveat | `common:caveat:<key>` | `common:caveat:censored` |
| caveat（cells.notes由来） | `common:caveat:cells.<note_id\|rowid>` | `common:caveat:cells.42` |

`scope` の既定は `common`（レジストリと県境をまたぐ実体）。地域固有と分かっているものだけ
`region_id`（例 `jp-14`）をスコープにする（ADR-0004 規約0）。`place_source_ref` が
v1 側の識別子（`sites.site_id` / `watershed_meta.watershed_id` / `mlat,mlon` / `sites.zone`）
から `place_id` を引く接続点で、「v1 を動かさずに並走させる」を成立させている。

ビルドの最後に `unit_id` / `variable_id` / `place_id` / `taxon_id` / `caveat_id` の一意性を
assert する（`scripts/r01_build_registry.py` の `_assert_id_uniqueness`）。SQLite の
PRIMARY KEY 制約により挿入時点でも保証されるが、4モジュールが同じ DB に同居する統合作業の
受け入れ基準として明示的に確認している。

## `status='needs_review'` / `'unresolved'` が意味すること

**黙って埋めない・落とさないという契約**（`docs/COLLECTOR_CONTRACT.md`）。レジストリは
「分からない・決められない」ことをデータとして残すのであって、推測で埋めた値を正とはしない。

- `place.status='needs_review'`: 座標などが原本に無く、捏造せず `NULL` のまま登録した行
  （例: 収集スクリプト自身が緯度経度を持たない観測地点90件）。
- `taxon.status='unresolved'`: `taxa`（神奈川県RL等・和名中心）のうち GBIF の
  `taxon_key` に照合できなかった5,942件。学名の語彙として存在はするが分類群として
  解決できていないことを示す。
- `variable`/`unit` 側で単位や粒度が決まらない場合も同様に `needs_review` を使う
  （ADR-0010）。

これらの件数が0になることをゴールにしない。**件数と一覧が可視化されていることがゴール**
（実測値は `scripts/registry/build_taxon.py` 等の各 `build()` が実行時に print する。
`reports/registry_resolution.md` として恒常的なレポートに出す仕事は A-6 で、本統合の
時点ではまだ実装していない）。
