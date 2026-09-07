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
| `place/site_supplement.csv` | `sites` テーブルに無い観測地点の補完（143件）。`place_local` 列は、
  `site_id` の局番コード部分（`"__"` の後ろ）が空文字で自動導出できない行にだけ
  明示の local を持たせる列（後述「空の局番コード」参照）。他の142行は空欄 |
| `taxon/vernacular_ja.csv` | 人手確認済みの和名54件（`domain.ts` の `NAME_JA` の複製） |
| `caveat.yaml` | 注記14件（`domain.ts` の `DATA_CAVEATS`/`BIOTA_CAVEATS` 等の移設） |

**生成物はここには置かない。** `data/db/registry.sqlite`（gitignore 済み）が唯一の生成物で、
`scripts/r01_build_registry.py` が上記の手書きファイルと、読み取り専用の原本
（`data/db/ryuiki.sqlite` / `cells.sqlite` / `derived.sqlite`）から毎回ゼロから作り直す。
`registry.sqlite` の中身に対して「これが正しい」という判断はしない。正は常にこのディレクトリと
原本側。ADR-0001 の「D1 はいつ捨てて作り直してもよい」がレジストリにも適用される。

## 再構築の手順

```bash
pip install -r requirements.txt          # PyYAML のみ（レジストリビルド専用の依存。ホストの .venv 向け）
cd web
pnpm run build:registry                  # data/db/registry.sqlite を作る
                                          # （scripts/run-python.sh が .venv/bin/python3 があれば
                                          #  それを、無ければ python3 を使う。$RYUIKI_PYTHON で明示も可）
pnpm run db:setup                        # migrate + seed。registry.sqlite も4本目のソースとして乗る
                                          # （registry.sqlite が無ければ predb:setup フックが
                                          #  build:registry を先に走らせるので、上の行は省略してもよい）
```

コンテナ（`docker compose up`）では `web/Dockerfile` が apt の `python3-yaml` を入れているので
`pip install` は不要。`docker-entrypoint.sh` が起動時に `registry.sqlite` の有無を見て
無ければ同じ `build:registry` を走らせる（`web/scripts/ensure-registry.sh`）。

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
| place（namespace あり） | `<scope>:place:<kind>.<namespace>-<local>` | `jp-14:place:site.env-pubwater-0142` |
| place（namespace 無し） | `<scope>:place:<kind>.<local>` | `common:place:grid01.3500_13900`（後述） |
| taxon（GBIF照合） | `common:taxon:gbif.<taxon_key>` | `common:taxon:gbif.2480932` |
| taxon（GBIF未照合） | `common:taxon:ryuiki-taxa.<slug(taxa.taxon_id)>` | 元の `taxa` 由来の識別子を後述のスラッグ化を通したもの |
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

### `local_key` のスラッグ化（ADR-0004 規約4）

レビューで、ID に空白（`taxon_id` 5,685件）・コロン（`local_key` 内に221件。
`<scope>:<entity>:<local_key>` の3分割が曖昧になる）・非ASCII文字（`place_id` 7件。
例: `jp-14:place:site.atsugi-river-中津川`）がそのまま入っていることが指摘された
（ADR-0004 規約4「公開 ID は URI に解決できる形にする」に反する）。

`scripts/registry/common.py` の `slugify_local_key()` に1箇所で実装し、
`place_id()` / `taxon_id_unresolved()` の `local` 部分がここを必ず通る:

- 空白列 → `_`
- `:` → `.`（`local_key` 内の `:` が3分割を曖昧にするのを防ぐ）
- `/` → `_`
- 連続する `_`/`.` は1文字に畳み、前後の `_`/`.` は落とす
- それでも残る非ASCII文字・URI的に安全でない記号は UTF-8 バイト列を percent-encode
  する（`abelia chinensis var. ionandra` → `abelia_chinensis_var._ionandra`、
  `atsugi_river_water_quality__中津川` の `中津川` → `%E4%B8%AD%E6%B4%A5%E5%B7%9D`
  のように）。**元の文字列は捨てない** — 実際には `taxon.scientific_name` /
  `taxon.vernacular_name_ja` / `place.name_ja` / `place_source_ref.external_key`
  のいずれかに元の生の文字列がそのまま残っている（実測で全件確認済み。
  percent-encode 後の ID は識別子としてのみ使い、人が読む名前はこれらの列を見る）。
- 別々の元キーが同じ slug に潰れた場合は例外を投げる（`seen` 引数。
  `place_id()` は `place_kind`・`namespace` の組ごとに、`taxon_id_unresolved()` は
  taxon 全体で1つの名前空間として衝突を見る）。実測ではこの経路での衝突は無かった
  （`gbif_taxon_key` の重複による衝突1件は方針2の EXACT 限定と無関係な既知の事象で、
  `build_taxon.py` のモジュール docstring 参照）。

### 逸脱: `place_kind='grid01'`（ADR-0006 のコードリストからの逸脱）

`mesh_all`（4,083件）は `mlat`/`mlon` が1刻み（= 0.01度刻み）で、国土地理院の
標準地域メッシュ（3次メッシュ。緯度30秒×経度45秒）とは刻み幅が違う独自グリッド
であることを実測で確認した。当初 `place_kind='mesh3'` としていたのを ADR-0006 の
コードリストの語（標準地域メッシュを指す）と混同しないよう `grid01` に改め、ID も
`common:place:mesh3.grid01-<mlat>_<mlon>` から `common:place:grid01.<mlat>_<mlon>`
に変えた（`place_id()` に `namespace=None` を渡すと `<namespace>-` を省ける形を
追加した）。`place_source_ref.external_key` も `mesh3:{mlat},{mlon}` から
`grid01:{mlat},{mlon}` に変更した。

これは ADR-0006 のコードリスト（`site`/`watershed`/`mesh3`/`municipality`/…）に
`grid01` という値を追加する逸脱であり、ADR 本体は編集していない。**Phase B 以降で
ADR-0006 のコードリストに `grid01` を正式に追記するか、将来別地域が本物の3次
メッシュを登録する時点で `mesh3` と `grid01` を明確に書き分けるかを判断する**
申し送りとする。

## `status='needs_review'` / `'unresolved'` が意味すること

**黙って埋めない・落とさないという契約**（`docs/COLLECTOR_CONTRACT.md`）。レジストリは
「分からない・決められない」ことをデータとして残すのであって、推測で埋めた値を正とはしない。

- `place.status='needs_review'`: 座標などが原本に無く、捏造せず `NULL` のまま登録した行
  （例: 収集スクリプト自身が緯度経度を持たない観測地点90件）。
- `taxon.status='unresolved'`: `taxa`（神奈川県RL等・和名中心）のうち、対応する
  GBIF の taxon 概念そのものとして扱えなかった6,242件（実測値。従来5,942件と
  報告していたが、レビュー指摘を受けて300件増えた）。内訳:
  - GBIF に `taxon_key` を持たない5,942件（内訳: 照会自体が未実施5,908件 /
    照会したが一致しなかった`gbif_match_type='NONE'` 34件）。
  - `gbif_taxon_key` はあるが `gbif_match_type` が `HIGHERRANK`/`FUZZY`
    （種以下まで一致していない弱い一致）の300件。**当初はこれらも
    `common:taxon:gbif.<key>` に寄せていたが、GBIF が種以下まで一致させられず
    属・科・時に kingdom まで遡った結果、同じキーに複数の無関係な種の
    `taxa` 行が衝突し（例: key=1 = Animalia に CR/EN の昆虫5種を含む10件が載る）、
    そのキーが `organism_records` に出現しない場合はレジストリ行の学名が
    たまたま代表に選ばれた taxa 側の種名になる（ID の実体は属・科・kingdom
    なのに名前は種）という事故が約200件で起きていた。ADR-0019決定4
    「`gbif_match_type` が弱いものは捨てずに `status='unresolved'` で保持する」
    に沿って、EXACT（種階級での一致）のときだけ寄せる方針に直した。**
  学名の語彙として存在はするが分類群として解決できていないことを示す。
- `variable`/`unit` 側で単位や粒度が決まらない場合も同様に `needs_review` を使う
  （ADR-0010）。

これらの件数が0になることをゴールにしない。**件数と一覧が可視化されていることがゴール**
（実測値は `scripts/registry/build_taxon.py` 等の各 `build()` が実行時に print する。
`reports/registry_resolution.md` として恒常的なレポートに出す仕事は A-6 で、本統合の
時点ではまだ実装していない）。

## レビューで見つかった細かい誤り（事実誤認）

- **`variable_alias.csv` の `pH` の `grain`**: `mean`/`fiscal_year` 系のエイリアス同様
  `day` としていたが、原本 `measurements` を数え直すと `pH` は4桁 `measured_on`
  （年度代表値。768行）と日付（採水個別値。34,165行）が同じ表記で混在していた。
  他のエイリアスの `grain` も原本の `measured_on`/`phenomenon_time` の書式分布と
  機械的に突き合わせて確認したが、不一致は `pH` のみだった（`measurements` 58種・
  `sensor_timeseries` 59種、計117エイリアス全件を確認）。`pH` を `mixed` に直した。
- **空の局番コードを `"unknown"` で埋めていた件**: `build_place.py` の
  `_site_place_id()` が `local or "unknown"` として `site.yokohama-waterlevel-unknown`
  という ID を機械的に作っていた。ID は不変（ADR-0004規約2）なのに、空文字を
  理由に自動生成した値がそのまま固定される捏造キーだった。`site_supplement.csv`
  の新設 `place_local` 列（該当する `yokohama_river_waterlevel__` の1行にだけ値を
  持たせた）で明示させ、`place_local` も無い場合は例外を投げるように直した
  （`docs/COLLECTOR_CONTRACT.md`「黙って埋めない」に沿う）。
