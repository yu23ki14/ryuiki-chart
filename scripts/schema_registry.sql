-- 語彙レジストリ(docs/plans/PHASE_A.md §A-1, docs/adr/0004/0006/0010/0013/0019)の DDL。
-- web/src/db/schema-registry.ts の drizzle 定義から生成した web/drizzle/migrations/ 配下の
-- マイグレーションと列・索引を一致させてある。
-- スキーマを変えるときは両方を更新すること(正は drizzle 側。ここは追随する)。
-- 例外: place_relation・place_watershed(いずれも下記)はまだ web/src/db/schema-registry.ts
-- に無い。D1 に載せる消費者がまだ無いため意図的に見送っている(ADR-0022, ADR-0006)。
--
-- scripts/r01_build_registry.py が起動時にこれを流して data/db/registry.sqlite を作る。
-- CREATE TABLE IF NOT EXISTS なので再実行しても安全。中身(行)は scripts/registry/build_*.py
-- が入れる(このファイルは器だけ)。

-- 単位。symbol は人間向けの原表記、ucum は UCUM 準拠のコード。
CREATE TABLE IF NOT EXISTS unit (
  unit_id TEXT PRIMARY KEY,
  symbol TEXT,
  ucum TEXT,
  name_ja TEXT,
  quantity_kind TEXT
);

-- 正準の指標。measurements.variable / sensor_timeseries.datastream の出典別名は
-- variable_alias 側に持ち、ここには名前から単位・粒度・統計量を剥がした後の
-- 正準形だけを置く(ADR-0010)。
CREATE TABLE IF NOT EXISTS variable (
  variable_id TEXT PRIMARY KEY,
  code TEXT,
  name_ja TEXT,
  name_en TEXT,
  theme TEXT,
  unit_id TEXT,
  value_type TEXT,
  default_stat TEXT,
  higher_is_worse INTEGER,
  description_ja TEXT,
  status TEXT
);

-- 出典表記 -> 正準 variable の対応。alias が v1 の measurements.variable /
-- sensor_timeseries.datastream の生の文字列。エイリアスは「出典 × 表記」で解決する
-- (docs/adr/0010-variable-registry.md 決定1)。dataset は alias がどの v1 テーブルの
-- 表記かを表し (measurements / sensor_timeseries)、source_id は v1
-- source_registry.source_id (空 = 出典未記録。is_synthetic=1 の行)。
-- 同じ (dataset, alias) でも source_id が違えば grain/stat が異なりうるため、
-- PK は別に自動採番の id を持つ。source_id は source_registry/source_edition
-- (ADR-0005) が入る Phase C で source_edition_id に置き換わる暫定形
-- (docs/plans/PHASE_B_INTAKE.md #1/#9 と同じ性質の暫定接続点)。
-- grain/stat は一次資料調査 (docs/plans/PHASE_B_ALIAS_STAT_SOURCES.md) 済みで、
-- (dataset, alias, source_id) の組ごとに固定 1 値に決まる (atsugi_river_water_quality
-- の「日付書式の混在」も統計量としては全期間 mean/day で確定するため、行ごとに決まる
-- 宣言的な列は不要と判断した)。
CREATE TABLE IF NOT EXISTS variable_alias (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  alias TEXT NOT NULL,
  dataset TEXT,
  source_id TEXT,
  variable_id TEXT,
  unit_id TEXT,
  stat TEXT,
  grain TEXT,
  note TEXT
);
CREATE INDEX IF NOT EXISTS ix_variable_alias_alias ON variable_alias(alias);
CREATE INDEX IF NOT EXISTS ix_variable_alias_variable ON variable_alias(variable_id);
CREATE INDEX IF NOT EXISTS ix_variable_alias_dataset_alias_source ON variable_alias(dataset, alias, source_id);

-- 空間単位(ADR-0006)。Phase A で登録するのは集計軸として実在するものだけ
-- (site / watershed / mesh3 / zone)。geometry_ref は持たない(点→place の解決も含め
-- Phase B 以降)。region_id は place_id 自身のスコープ(<scope>:place:...)と一致させる
-- (ADR-0022 決定1。common なら NULL、地域固有なら region_id、例: jp-14)。
CREATE TABLE IF NOT EXISTS place (
  place_id TEXT PRIMARY KEY,
  region_id TEXT,
  place_kind TEXT,
  name_ja TEXT,
  lat REAL,
  lon REAL,
  elevation_m REAL,
  area_km2 REAL,
  definition_ref TEXT,
  status TEXT
);
CREATE INDEX IF NOT EXISTS ix_place_kind ON place(place_kind);

-- 空間単位どうしの関係(ADR-0006)。Phase B(phase-b/region-scope, ADR-0022)で新設。
-- 最初に作った辺は「地点 -> ゾーン」(parent_id=ゾーンの place_id, child_id=地点の
-- place_id, relation='within')。Phase B `phase-b/place-attributes`(P-1a)で
-- 「地点 -> 流域」(sites.watershed 由来)を追加し、現在は2種類。fraction は
-- NOT NULL とし、全体を含む関係には 1.0 を入れる("NULL=全体"のような暗黙の意味を
-- 持たせない。ADR-0011 の「fraction があるものは加重する」を常に同じ式で書ける
-- ようにするため)。ADR-0006 が挙げる source_edition_id 列はまだ持たない: 出典の
-- 版管理(source_registry/source_edition, ADR-0005)自体が Phase C の仕事で、いま
-- 作っている辺(地点->ゾーンは registry/place/zone.yaml、地点->流域は
-- data/processed/nlni_w12_watersheds.jsonl)の出典はそれぞれ単一の手書き/配布
-- ファイルに固定されており、版を切り替える必要が今は無い(ADR-0022 決定3)。
-- (parent_id, child_id, relation) の一意性は DDL の UNIQUE 制約ではなく
-- scripts/r01_build_registry.py 側の Python 表明で検証する(variable_alias の
-- (dataset, alias, source_id) 一意性と同じ流儀。registry/README.md 参照)。
-- web の D1(schema.ts/schema-registry.ts)にはまだ載せない: 消費者がまだ無く、
-- D1 は捨てて作り直せる配信キャッシュ(ADR-0001)なので、使う側が現れてから足す。
CREATE TABLE IF NOT EXISTS place_relation (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  parent_id TEXT NOT NULL,
  child_id TEXT NOT NULL,
  relation TEXT NOT NULL,
  fraction REAL NOT NULL,
  basis TEXT
);
CREATE INDEX IF NOT EXISTS ix_place_relation_parent ON place_relation(parent_id);
CREATE INDEX IF NOT EXISTS ix_place_relation_child ON place_relation(child_id);

-- v1 の出典側識別子(sites.site_id / watershed_meta.watershed_id / mlat,mlon 等)から
-- place への対応。「v1 を動かさずに並走させる」ための接続点(PHASE_A.md §A-3)。
-- external_key からの逆引きが主な引き方。
CREATE TABLE IF NOT EXISTS place_source_ref (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  place_id TEXT,
  external_key TEXT,
  source_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_place_source_ref_external ON place_source_ref(external_key);
CREATE INDEX IF NOT EXISTS ix_place_source_ref_place ON place_source_ref(place_id);

-- kind 固有の属性サテライト(ADR-0006 §「place の属性」、ADR-0011「place_attribute」
-- カテゴリの具体形、Phase B `phase-b/place-attributes`)。place 本体の列は増やさず、
-- watershed だけが持つ属性(旧 derived.watershed_meta の残り4列)をここに置く。
-- water_system_code は v1 の水系コード(旧コード、10桁未満)をそのまま文字列で持つ
-- (親 place(water_system)+place_relation にする案は今回の再現には過剰なので採用しない。
-- ADR-0006 追記参照)。main_rivers は主要河川が無い流域(143/377)向けの空文字列を
-- そのまま持つ(JSONL の生値・v1 とも NULL ではなく空文字列。丸めない)。
-- 1 place_id につき高々1行(1:1)。place と同様に web の D1(schema.ts/schema-registry.ts)
-- にはまだ載せない: place_relation と同じ理由で、消費者がまだ無い。
CREATE TABLE IF NOT EXISTS place_watershed (
  place_id TEXT PRIMARY KEY,
  water_system_code TEXT,
  water_system_category TEXT,
  main_rivers TEXT,
  data_year INTEGER
);

-- 分類群レジストリ(ADR-0019。taxon_id の名前空間分割・分類補完は Phase B
-- phase-b/occurrence-registry。決定と理由の正は ADR-0019 の日付付き追記、
-- 実測の正は docs/plans/PHASE_B_OCCURRENCE.md。ここには列の意味だけ書く)。
--
-- taxon_id は出典ごとに名前空間を分ける: GBIF 由来は common:taxon:gbif.<GBIFのtaxonKey>、
-- iNaturalist 由来は common:taxon:inat.<iNatのtaxon.id>(GBIFのtaxonKeyとは無関係な
-- 別の数値空間)、taxa(v1)由来で GBIF 未照合のものは common:taxon:ryuiki-taxa.<taxaの主キー>。
-- 名前空間の対応の正は scripts/common.py の TAXON_KEY_SOURCE_NAMESPACE。
-- gbif_taxon_key 列は本物の GBIF taxonKey のときだけ埋める(iNat 由来行は常に NULL)。
-- accepted_taxon_id は status='synonym' のときに正の taxon を指す
-- (ADR-0004 規約2: ID は不変、実体が変わったら新 ID を作り旧 ID は残す)。
--
-- kingdom/phylum/class/order/family/classification_basis/canonical_binomial/
-- taxon_group は v1 (org_norm) の分類補完規則を taxon 単位でレジストリのビルダー側に
-- 移したもの。classification_basis は class の解決経路 ('source'=出典が直接持つ /
-- 'binomial_match'=同じ二名法キーの他記録からの多数決 /
-- 'genus_match'=同じ属の他記録からの多数決 / 'no_match'=解決不能。
-- taxon.status='unresolved' と紛らわしいため 'unresolved' から改名)。
-- order/family は多数決による補完をしない。taxon_group は
-- registry/taxon/taxon_group.yaml から機械的に生成した日本語ラベル。
-- status は 'accepted'/'unresolved' に加え、分類の多数決が不確か(同数、または
-- 属が複数classにまたがる)な taxon だけ 'needs_review' を持つ(accepted/unresolved
-- どちらの行にも起こりうる)。
CREATE TABLE IF NOT EXISTS taxon (
  taxon_id TEXT PRIMARY KEY,
  scientific_name TEXT,
  canonical_binomial TEXT,
  rank TEXT,
  kingdom TEXT,
  phylum TEXT,
  class TEXT,
  "order" TEXT,
  family TEXT,
  classification_basis TEXT,
  taxon_group TEXT,
  gbif_taxon_key TEXT,
  vernacular_name_ja TEXT,
  status TEXT,
  accepted_taxon_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_taxon_gbif_key ON taxon(gbif_taxon_key);
CREATE INDEX IF NOT EXISTS ix_taxon_binomial ON taxon(canonical_binomial);

-- 版ごとの分類群の評価(ADR-0019 の最小形。P-2、2026-09-23追記。
-- docs/adr/0019-taxon-registry.md の日付付き追記 / docs/plans/PHASE_B_TAXON_ASSESSMENT.md)。
-- v1 の redlist_assessments(2,884行、rl2020/rdb2022p/rl2026 の3版)と
-- taxa.ias_category 由来の外来種評価(moe_ias_2015、v1 は data/processed/moe_ias_list.csv
-- 由来)を、同じ「あるリストがある分類群に付けた評価」という構造に統合したもの。
-- D1(web/src/db/schema-registry.ts)には載せない(taxon の分類列と同じ判断。
-- 使う側〔web〕がまだ無い——registry/README.md「place.region_id と place_relation」
-- と同じ理由)。
--
-- list_id は registry/taxon/assessment_list.yaml のコードリスト。
-- category_code/prev_category_code は registry/taxon/redlist_category.yaml +
-- redlist_category_alias.csv で正規化したコード(list_id='moe_ias_2015' の行は
-- 専用のコードリストを持たないため常に NULL。category_raw だけを持つ)。
-- category_raw/prev_category_raw/national_category_raw は原表記を無加工で残す
-- (正規化は alias を引くキーにだけ使う。category_raw 自体は改行・空白を含め
-- そのまま)。prev はその版の文書が自分で書いている「前回区分」の原表記であり、
-- 版どうしを JOIN して導いたものではない(ADR-0019 決定5への例外。理由は
-- docs/adr/0019-taxon-registry.md 追記参照)。
-- taxon_id は解決できた分だけ埋める(学名の完全一致 → 二名法一致の順。
-- 解決できない行は NULL のまま——Phase B の再現(v1は名前を文字列で運ぶ)には
-- 不要な診断用の列)。origin は外来種リストの由来区分(moe_ias_list.csv の
-- origin_ja。レッドリスト側の行は常に NULL)。
CREATE TABLE IF NOT EXISTS taxon_assessment (
  assessment_id TEXT PRIMARY KEY,
  list_id TEXT NOT NULL,
  list_year INTEGER,
  taxon_id TEXT,
  scientific_name_raw TEXT,
  vernacular_name_ja_raw TEXT,
  taxon_group_ja TEXT,
  taxon_subgroup_ja TEXT,
  family_ja TEXT,
  category_raw TEXT,
  category_code TEXT,
  prev_category_raw TEXT,
  prev_category_code TEXT,
  national_category_raw TEXT,
  origin TEXT,
  source_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_taxon_assessment_list ON taxon_assessment(list_id);
CREATE INDEX IF NOT EXISTS ix_taxon_assessment_taxon ON taxon_assessment(taxon_id);

-- 注意事項(ADR-0013)。caveat_id は web/src/lib/ai/caveats.ts が今返しているキー文字列を
-- そのまま使う(common:caveat:<key>)。cells.notes 由来は common:caveat:cells.<note の主キー>。
--
-- 計画(PHASE_A.md §A-1)では caveat 単体に scope_kind/scope_ref を持たせる7テーブル構成
-- だったが、A-5 の実装時に「1つの注記が複数のテーブルに掛かる」(例: censored は
-- measurements/meas_year/meas_month など9テーブルに掛かる)ことが分かり、caveat_id を
-- 主キーにしたままでは1:Nを表せなかった。そのため caveat は注記そのものに絞り、
-- スコープは caveat_scope に切り出した(計画の7テーブル→8テーブルの逸脱。
-- 理由の詳細は scripts/registry/build_caveat.py の docstring)。
CREATE TABLE IF NOT EXISTS caveat (
  caveat_id TEXT PRIMARY KEY,
  severity TEXT,
  kind TEXT,
  title_ja TEXT,
  body_ja TEXT,
  quote TEXT
);

-- caveat が掛かる範囲。1注記に対して複数行になりうる(1:N)。scope_kind は「一致方法」だけを
-- 表す(table/table_prefix/cell/cell_table)。「渡されたテーブルの中でどれを先頭に出すか」という
-- 優先規則は scope_kind ではなく priority 列が持つ(既定0。大きいほど優先)。
-- caveatsForTables() の順序復元の方法は scripts/registry/build_caveat.py の docstring 参照。
CREATE TABLE IF NOT EXISTS caveat_scope (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  caveat_id TEXT,
  scope_kind TEXT,
  scope_ref TEXT,
  sort_order INTEGER,
  priority INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_caveat_scope_scope ON caveat_scope(scope_kind, scope_ref);
CREATE INDEX IF NOT EXISTS ix_caveat_scope_caveat ON caveat_scope(caveat_id);

-- ビルドの指紋(phase-b/registry-atomic)。「在る」ことと「正しい」ことを区別するための
-- 1行だけのメタ表。UNIQUE 制約は持たせず、r01 側の運用(INSERT 前に DELETE FROM)で
-- 単一行を保証する(他の複合キーと同じく、この程度の不変条件のために表自体の設計を
-- 複雑にしない)。web/src/db/schema-registry.ts(D1)には載せない: place_relation と同じ
-- 理由で、D1 側に消費者がいない(この表を読むのは r01 --check-fresh だけ)。
-- input_fingerprint は scripts/registry/common.py の compute_input_fingerprint()
-- (ビルドの論理 + registry/ 配下の手書き入力から算出した sha256)。
-- mode は 'full'(原本DBを読む通常ビルド) / 'files_only'(--files-only、CI用)。
-- 実行時刻は持たない(決定論。他のキューブ生成物と同じ理由)。
CREATE TABLE IF NOT EXISTS registry_build (
  input_fingerprint TEXT NOT NULL,
  mode TEXT NOT NULL
);
