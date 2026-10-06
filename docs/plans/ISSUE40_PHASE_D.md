# Issue #40 Phase D — マニフェスト・配布物・公開（設計）

対象: ADR-0012（マニフェスト）/ 0014（応答封筒）/ 0018→0028（公開範囲）/ 0020（更新方式・鮮度）/ 0001（Parquet）/ 0022 決定3 / 0016 Phase D。作成: 2026-10-06。
**設計のみ。コードは変えていない。** 実測は `data/db/{ryuiki,registry,v2}.sqlite` と `data/processed` を読み取り専用で引いた値（2026-10-06）。
issue 本文の行番号・「#子8（注記レビュー）が前提」は古い。現行は `docs/PIPELINE.md`。

前提（メイン決定・オーナー決定。覆さない）: 本番デプロイ・本番 D1 適用は含まない／MCP は「実装してローカルで動く・`web/src/lib/features.ts` で出し分け」まで／
D1 に L2（observation/occurrence/occurrence_place）を入れない／合成データは出さない／画面の定量下限未満は `value_lod`／
**座標も公開範囲も出し分けない（ADR-0028。扱うデータは全て公開済み）**。Phase C（`docs/plans/ISSUE39_PHASE_C.md`、別 worktree）の
`source` / `source_edition` / `license` 表・公開 ID の上に載る。並行して #31（正準単位）・#32（時刻帯 `registry/region.yaml` → `regionTimeZone()`）・#35（`registry/caveat_scope.yaml`）が入る。

## 0. 決定の追記（メイン判断 2026-10-06。本文より優先）

- **J1**: 座標なし出現は **grid01 族に入れず、watershed 族の `place_id NULL` セル（既に画面が扱う形）にだけ入れる**をライブラリ側の規則とする（ADR-0025/0026 に追記）。grid01 に NULL place セルを新設しない。担当 M は最初にサンプルで確認する。画面側に広範な改修が要る場合でも候補は差し替えない（上の規則で回避するため）。b07 の grid01 母集団は「座標あり日付あり行」に限る（座標なし行は `occurrence_agg` に grid01 セルを作らない）。b09 は座標なし日付あり行にも `place_kind='watershed', place_id NULL` の `occurrence_place` 行を作る。
- **J3**: pyarrow は可（バージョン固定）。**duckdb は `requirements.txt` に入れない**。
- **J4**: `core/` 撤回は可。理由を ADR-0001 に書く（ADR-0028 により絞る根拠が無く、同一内容の複製になるため）。
- **J5**: `stale` 閾値は持たない。応答に載せるのは `age_days` と `update_mode` だけ（`expected_refresh_days` も作らない）。
- **J6**: 「ソース追加」で触ってよいのは **`manifests/`・`scripts/adapters/`・`registry/` 配下の宣言ファイル（語彙の追加）・テスト**まで。`scripts/migrate/**`・`scripts/b0*`・`web/src/**` は不可（宣言 yaml も `scripts/migrate/` 配下なので不可）。したがって §4 担当 S の許可リストと §6 J6 を次のとおり改める: `occurrence_cube_declarations.yaml`・`occurrence_period_shapes.yaml`・`period_exceptions.yaml` の**出典ごとの宣言値は、マニフェストの `expected:` ブロック（行数・leaf/year/month 件数・流域の解決/未解決件数・期間形）へ移す**。担当 M が、b07 等の宣言検査を「既存出典の宣言（従来の yaml、変更なし）＋マニフェスト出典の `expected`」の和と突合する形にする。宣言は残る（黙って自動計算にしない）が置き場が manifest になるので、ソース追加で `scripts/migrate/` を触らない。許可リストは `manifests/`・`scripts/adapters/`・`registry/`・`scripts/tests/`・サンプル再生成物。境界検査 CLI はこの許可リストで落とす。

## 1. 現状の実測

### 1.1 「ソースを足す」ときに今どこを触るか（新規ソース＝出現型 1 件を想定して読んだ結果）

マニフェスト（`manifests/`）は**存在しない**。ADR-0012 の `region:` 欄だけが `scripts/migrate/source_regions.yaml` として先取りされている（consumer=occurrence 2 件・observation 1 件）。
ソース固有の知識が共通ライブラリ側に埋まっている箇所（＝ADR-0012 原則1 の言う「ライブラリの欠落」）を数えた:

| # | 箇所 | 実測 | Phase D でどうするか |
|---|---|---|---|
| L1 | `b03_build_observation.py` の `ingest_funcs` 辞書（3 出典を直書き）、`b06_build_occurrence.py` は `src.organism_records` 1 表を直読み（`_SELECT_ORGANISM_RECORDS_SQL`） | 新出典 = 両スクリプトの編集 | マニフェスト駆動の取り込みフックを 1 本足す（担当 M） |
| L2 | `scripts/taxon_namespaces.py` の `TAXON_KEY_SOURCE_NAMESPACE`（b06 が `assert_known_source_ids` で止める） | 新出典 = 辞書へ追記 | adapter が `taxon_id` を直接返す経路（const / registry 検索）では不要にする |
| L3 | 地点→place: `place_source_ref` の `grid01` は **`organism_records` の座標から作られる**（`build_place.py`）。実測 4,087 セル。b06 は未登録セルを `unresolved_place_count` で**止める** | 新出典の座標が既存セル外なら止まる | マニフェストが宣言した place を registry ビルドが登録する経路（担当 M の範囲に `build_place.py` の追加入力を含める） |
| L4 | `b09`: `occurrence_place` は **座標のある記録だけ**（`WHERE lat IS NOT NULL`）。`b07._assert_populations_complete` は「日付あり全行が `occurrence_place` に 1 行」を要求 | **座標なし出現は b07 で止まる**（現状 0 件なので未踏） | 座標なしの日付あり記録に `place_id NULL` の `occurrence_place` 行を作る（ADR-0025 D2「データを落とさない」と同じ扱い。担当 M） |
| L5 | `scripts/migrate/occurrence_cube_declarations.yaml`（leaf/year/month/流域の**宣言件数**）、`source_regions.yaml.expected_row_count`、`period_exceptions.yaml` | 新出典 = 宣言値の更新（コードではなく宣言） | 宣言は残す（「宣言差分を機械検証」の根幹。黙って自動計算にしない）。ただし**どの宣言ファイルを触ってよいか**を境界検査に明記（§4 担当 S） |
| L6 | `scripts/pipeline_inputs.py`・`common.compute_v2_input_fingerprint()`（鮮度判定）は入力 CSV 2 本と import 追跡で洗い出したコードだけを見る | **動的 import の adapter と `manifests/*.yml` は指紋に入らない** → 入力が変わっても「新鮮」と誤判定 | マニフェストと adapter を指紋の入力に明示的に加える（担当 M。わざと変えると古い判定になるテスト必須） |
| L7 | `b00_run_full_gate.py` の `PIPELINE_*`、CI の `full-gate-proof-check` | `manifests/`・`scripts/ingest/`・`scripts/adapters/` が含まれない | パスに加える（担当 M。b00 全量はメインが最後に 1 回） |
| L8 | variable / alias / unit | `registry/variable.yaml`・`variable_alias.csv`（宣言ファイル） | 出現型の候補では不要。観測型を足す将来は宣言追記で足りる（コードではない） |

### 1.2 第 1 候補の選定（原本の未取り込み表から実測）

v2 に入っている出典は measurements 4・sensor_timeseries 6・土地利用 1・organism_records 2。未取り込みで「出現」「観測」の形をした候補を引いた:

| 候補 | 規模 | 実測 | 判定 |
|---|---|---|---|
| **`kanagawa_kuma_sightings`**（`wildlife_sightings`、ADR-0012 の例そのもの） | 400 行（令和4〜8年度。`is_preliminary` 31） | 種は ツキノワグマ 1 種のみ（const で足りる）。`observed_on` 400/400。**`lat`/`lon` は 400/400 が NULL**。`redistributable=1`・license「政府標準利用規約2.0相当（要確認）」。`situation_ja` は 目撃270・痕跡99・捕殺16・錯誤捕獲10・その他3・人身被害1・学習放獣1 | **採用**。理由: 規模が小さく全行を目で見られる／種の解決が要らない／L4（座標なし出現）という**実在のライブラリ欠落をちょうど 1 つ顕在化させる**。欠落を先に 1 回直し（担当 M）、その後で足す（担当 S）。順序が「ライブラリに手を入れずに足せる」の正しい証明になる |
| `biodic_mammal_mesh_kanagawa`（`mammal_mesh`） | 75,240 行、209 メッシュ | `confirmed=0` が大半（不検出）で、`survey_label`（bunken/city/pref…）は**別々の出典レイヤー**。メッシュ中心の grid01 セルのうち registry に既存は **139/209**（70 は L3 で未登録）。和名→taxon は タヌキ・アナグマ が registry に**無い** | 見送り。意味の整理（不検出・レイヤー）が先で、最初の 1 件には重い |
| `moni1000_*`（鳥類・蝶） | 9,433 / 18,396 / 14,529 行 | `redistributable=0`・「要事前アンケート回答」 | 見送り。ADR-0028 で旗は出力を絞らないが、**最初の 1 件に利用条件の議論を持ち込まない**（2 件目以降で扱う） |
| `estat_agri_census` / `estat_census_population` | 6,422 / 806 行 | place が市区町村。**市区町村 place_kind は registry に無い**（ADR-0022 決定4が「作らない」と決定済み） | 見送り（別 Issue） |

注意: ADR-0012 の例の `taxon: common:taxon:gbif.2433433` は **registry に存在しない**（`ursus thibetanus` は `gbif.6163862`〔亜種〕・`gbif.9335699`・`inat.41647`〔species〕・`inat.418146`〔亜種〕。既存の出現記録は inat.41647 に 3 件、inat.418146 に 5 件）。
マニフェストの `const` は**レジストリに実在することをビルドが検査する**（`in_registry`）。どの ID を使うかは担当 S が `canonical_binomial='Ursus thibetanus'` かつ `rank='species'` で機械的に決めて evidence に書く（推測しない）。

### 1.3 配布・応答・更新の現状

- **Parquet**: 依存なし。`.venv` に pyarrow は**無い**（import 失敗を確認）。`duckdb 1.5.5` は `.venv` にあるが `requirements.txt` には載っていない（収集用の任意導入）。`requirements.txt` は PyYAML・pytest のみ。Python 3.13.7・同梱 SQLite 3.49.1。`dist/`・`core/` は存在しない。
- **応答封筒**: `web/src/lib/cube/envelope.ts`（`buildEnvelope`/`buildZoneEnvelope`、`ENVELOPE_SPEC_VERSION="cube-envelope@1"`）は**実装済みだが消費者は AI ツール（`lib/ai/tools.ts`）だけ**。`provenance` は `{source_id,name,license,n_rows}` のみで **`fetched_at` が無い**＝鮮度が載らない。`excluded` は常に 0。`/api/timeseries`・`/api/biota` は封筒を使わず `caveats` キー配列だけを返す。`cite_as` なし。出典名・license は D1 の `source_registry` を毎回 JOIN で引く（rows_read を消費）。
- **MCP**: コード・依存とも**存在しない**（`web/` に MCP の実装なし）。`features.ts` には `EXPLORE_ENABLED` のみ。
- **更新方式**: `update_mode` はどこにも無い。`source_registry.fetched_at` は実測で 2026-08-29〜09-05 の取得日（版履歴は復元不能。Phase C 設計 §2.2 のとおり捏造しない）。`source_registry.redistributable=0` は 33 行、事実表から参照される出典は 13。
- **ADR-0022 決定3の現状**: observation の `region_id` は `place_source_ref('sites.site_id')→place.region_id`（measurements/sensor）と `source_regions.yaml`（土地利用）の混在。実測 observation 1,029,034 行は全て `jp-14`。occurrence は出典（`source_regions.yaml`）。`measurements` の `source_id IS NULL` 2,265 行は**全て `is_synthetic=1`**（b03 が除外）なので region の穴にはならない。

## 2. 決定

### D1. マニフェスト = 宣言（YAML）＋ ソース固有の adapter（Python 短いファイル）。変換 DSL は作らない

ADR-0012 の `map:` 節（`from:`/`const:`/`resolve:` を YAML で書く案）は**採らない**（同 ADR の「表現力を意図的に絞る」「別の言語になる」リスクに従う）。代わりに:

```
manifests/<source_id>.yml          宣言: source / region / target / update_mode / input / edition 参照 / checks / expected
scripts/adapters/<source_id>.py    adapter: def rows(ctx) -> Iterator[dict]    ← ソース固有ロジックはここだけ
scripts/ingest/                    共通ライブラリ（新設。担当 M が 1 回だけ作る）
  manifest.py   読み込み・構造検証（未知キー・必須キー欠落・enum 外は止める。source_regions と同じ流儀）
  api.py        adapter が import してよい唯一の面: Row 型・resolve_place/resolve_taxon/period 展開/censoring・ctx
  runner.py     adapter を回し、共通検査（重複・解決率・期間・checks）、統計、宣言の使用マーキング、b03/b06 の staged_table へ書く
```

- manifest の必須キー: `source`（`source_registry.source_id` と一致）, `region`, `target`（`observation|occurrence` のみ。`feature|place|document` は需要が出るまで書けない＝検証で止める）, `update_mode`（`snapshot|append|revision|static`。Phase C の `source_edition.update_mode` と同じ enum）, `input`（`{table: …}` か `{file: …}`）, `edition`（Phase C の `editions.yaml` の `edition_key` を**参照**するだけ。ADR-0012 のインライン `edition:` は撤回。license も `license_id` 参照）, `adapter`（モジュール名。`builtin` は下記）, `expected_row_count`, `checks`。
- `checks` の語彙は**実装するものだけ**: `not_null` / `unique` / `row_count_between` / `in_registry`（taxon・place・variable・unit のいずれかが registry に実在）/ `date_between`。`in_codelist` は codelist 表が存在しないので入れない（ADR-0012 の例からの意図的な縮小）。
- adapter は共通の列契約の dict を返す（occurrence: `record_key, taxon_id|None, observed_on_raw, lat, lon, attributes{…}`。observation: `variable_alias キー…`）。**adapter の import は `ingest.api` と標準ライブラリだけ**。テストで AST 検査し、`scripts/migrate/` や `sqlite3` の直 import があれば落とす（ライブラリを迂回して共通検査を逃れる経路を塞ぐ）。
- **既存 5 系統（measurements・sensor_timeseries・土地利用・organism_records）はマニフェスト化しない**。変換は `b03`/`b06` のまま。`manifests/<id>.yml` を `adapter: builtin` の**メタデータだけ**（region・update_mode・expected・edition 参照）で置く。理由: 数百万行の出力が 1 ビットも動かない移行は価値より危険が大きい（層3 の指紋を動かさない方針）。`adapter: builtin` は `b03`/`b06` が自分で処理する出典に限り、manifest に無い出典・manifest にあるが誰も処理しない出典はどちらも止める（`source_regions.py` の「未使用宣言も止める」を継承）。
- `source_regions.yaml` は**マニフェストに吸収して撤去**（`region` と `expected_row_count` と `evidence`、`regions:` の utc_offset は #32 の `registry/region.yaml` に移る。utc_offset の置き場は #32 の担当と衝突しないよう、本 Phase は region.yaml の存在を前提にして**重複定義を作らない**）。`consumer` キーは `target` から導くので消える。

### D2. ADR-0022 決定3: 統一する（出典＝マニフェストから決める）

判断: **observation も occurrence と同じく、`region_id` はマニフェストの `region` から決める。** place 経由（`place.region_id`）は決定の根拠から**照合に格下げ**する。

- 理由: place 経由は `common:` の place（grid01/watershed。`region_id NULL`、ADR-0022 決定1）で破綻する形が既に土地利用で出ており（宣言ファイルで回避済み）、新規の出現型は place で決められない（L3/L4）。2 経路を残すと「どちらが正か」を毎回問うことになる。
- 移行は**出力同一**で行う: `b03` の region 決定を manifest に差し替えたうえで、**旧経路（`place.region_id`）の値と全行一致することを実行時に照合し、不一致なら止める**（照合は恒久。マニフェストの region と、place が持つ region が食い違う＝宣言の誤りか place の誤りを検出する）。実測で observation 1,029,034 行が全て `jp-14` なので、一致は自明だが**機械で固定する**。サンプルでも同じ照合が走る。
- ADR-0022 決定3の「未実装」注記を解消し、決定4（地域そのものを表す place・`common:` place→地域の辺）は**引き続き作らない**（需要なし）。

### D3. L2 の Parquet と `dist/`（ADR-0001 の改定を伴う）

- **書き手**: `scripts/d01_build_dist.py`（新設）＋ `scripts/dist/`。入力は `v2.sqlite` と `registry.sqlite`（どちらも読み取り専用で開く）。`web/` からは `pnpm run build:dist`。**`build:v2` には含めない**（v2 の指紋・b00 の全量が動くのを避ける。dist は v2 の派生物）。
- **ライブラリ**: **pyarrow を `requirements.txt` に固定して足す**（`duckdb` は不要。DuckDB は利用者側の読み出し例として README に書くだけ）。理由: duckdb で SQLite を読むには `sqlite_scanner` 拡張が要り、初回に拡張を**ネットから取得**する（CI・オフラインで不安定）。CSV 経由は NULL・型・改行の取り違えの温床。pyarrow は SQLite のバッチ（`fetchmany`）から明示スキーマで `ParquetWriter` に流せる。バージョンは Python 3.13 の wheel があるものを実装担当が選んで固定し、`.venv` と CI の両方で動作確認する（pip の pin は `requirements.txt` の流儀どおり）。
- **CI への影響**: `pip install -r requirements.txt` を使うジョブは 3 つ（registry・reconcile・sample-gate）。pyarrow は manylinux の wheel（数十 MB）で、インストール時間が各ジョブ +数秒〜十数秒。**dist のビルドと検査は sample-gate にだけ足す**（縮小サンプルで dist を作り、§5 の検査を回す）。registry/reconcile ジョブは pyarrow を import しないので影響はインストールのみ。本番サイズの dist（observation 1.03M 行・occurrence 0.82M・occurrence_agg 1.44M・observation_agg 2.0M）は CI で作らず、手元で 1 回（メイン）。
- **`core/` と `dist/` の分離は撤回し `dist/` のみにする（ADR-0001 改定）**: 分離の唯一の理由は「再配布不可・隔離中の版を `dist/` から除く」だったが、ADR-0028 とオーナー決定で `redistributable`/`license_class` は出力を絞る根拠にしない。`core/` を作ると `dist/` と同一内容の複製になる。合成データは v2 に入らない（b03/b06 が除外）ので `dist/` との差分は無い。**将来、出力を絞る根拠が復活したとき（非公開データの取り込み）に再導入する**——その条件を ADR-0001 に書く。
- **レイアウト（決定的・再現可能）**:
  ```
  dist/
    datapackage.json                 Frictionless 記述子。resources[].{path,sha256,bytes,rows,schema} / sources[]（source_edition_id, fetched_at, update_mode, license_id, license_class, redistributable, attribution）/ spec_version / built_from（入力の指紋。時刻は入れない）
    README.md                        読み方（DuckDB の例・検閲・時間の 3 点セット・ADR-0028 の注意）
    observation/source_table=<…>/part-0.parquet      ← 出典（source_table）でパーティション
    occurrence/source_id=<…>/part-0.parquet
    occurrence_place.parquet  observation_agg.parquet  occurrence_agg.parquet
    registry/{place,place_relation,place_source_ref,taxon,taxon_assessment,variable,variable_alias,unit,source,source_edition,license,caveat,caveat_scope}.parquet
  ```
  出典単位のパーティションは ADR-0020 決定2（L2 は出典単位で作り直せる）の**構造だけを先に用意する**もの（§D6）。キューブは全体を 1 ファイル（影響範囲だけの再ビルドは D6 で見送り）。
- **決定性**: 行は主キー順に並べて書く。圧縮 zstd・行グループ長固定・`created_by` はライブラリ版に依存するので**バージョンを pin**。テストは「同じ入力で 2 回作ると `sha256` が一致」を要求し、一致しなければ（ライブラリの非決定性）**ファイルのバイトではなく、行集合のハッシュ**を `datapackage.json` の正とする、とフォールバックを先に決めておく。
- **型**: SQLite の宣言型から `INTEGER→int64, REAL→float64, TEXT→string`。`period_start/period_end` は**文字列のまま**（時刻帯なしローカル時刻。ADR-0024。timestamp 型にして UTC 化する事故を避ける）。値は v2 と 1 ビットも違わないこと（座標・`value_zero`/`value_lod`・`censoring`）を行ハッシュで検査（§5）。
- takedown 手順（ADR-0001 が別 ADR とした分）は**本 Phase の範囲外**。「`dist/` は決定的に作り直せる」ことが撤回の前提になる点だけ記録する。

### D4. 応答封筒と鮮度（ADR-0014 の第 1 段）

- **`envelope.ts` を拡張する（新設しない）**。`provenance[]` に Phase C の `source_edition` 由来で `source_edition_id, fetched_at, update_mode, license_id, license_class, redistributable, attribution` を足し、`coverage` に `oldest_fetched_at / newest_fetched_at`、トップに `cite_as`（出典名・取得日・本サービスの URL 文字列。ホストは未決なので base は設定値）を足す。`spec_version` を `cube-envelope@2` に上げる。
- **鮮度は「取得日と更新方式」を載せるだけ**。`stale: true` のような閾値判定は**作らない**（閾値はオーナーが決めていない。推測で埋めない）。`age_days` は応答時に `fetched_at` から計算して添える。
- **出典メタは D1 を引かない**: 現在 `resolveSourceMeta` は応答ごとに `source_registry` を JOIN している。`source`/`source_edition`/`license` は件数が小さく不変なので、registry の生成物（`generated.ts`/`generated-client.ts`。`web/scripts/build-registry-ts.mjs`）に**焼き込み**、封筒は生成物から引く（rows_read 0）。ADR-0014「毎応答に provenance を載せると rows_read が増える」の懸念への回答。Phase C が `registry.sqlite` に表を作ることが前提。
- `excluded` は**構造を残して常に 0**（ADR-0028 でライセンス・公開範囲による除外は無い。ADR-0014「黙って減らさない」は「減らしていない」が正）。除外が増える変更が入ったらテストが落ちるよう、`by_license>0` を許さない回帰テストを置く。
- **画面用 API**（`/api/timeseries`・`/api/biota` 等）は封筒に置き換えない（ADR-0014「同一経路は強制しない」）。**加算で `freshness`（出典ごとの `fetched_at`・`update_mode`）だけ**を返し、画面の既存フィールドは変えない。注記は現行どおりキー配列＋サーバ側で機械的に付与（メモリの方針どおり、モデル任意のツールにしない）。
- **注記の severity/kind**: Issue 本文の「人手レビューが前提」は #35（`caveat_scope.yaml` の scope_kind を ADR-0013 語彙へ）の完了を依存に置く。Phase D は `severity` と `kind` を**そのまま応答に載せる**だけで、分類の変更は #35 の責務（本設計では変えない）。

### D5. MCP（機能フラグで出し分け、ローカルで動くところまで）

- 第 1 段 5 本（ADR-0014 の `describe_catalog`/`search_registry`/`get_observations`/`get_occurrences`/`export_dataset`）。**第 2 段（`get_geometry`/`get_provenance`/`get_caveats`）は作らない**（封筒が provenance・caveats を同梱するので不要。需要待ち）。
- 実装: `web/src/lib/mcp/`（ツール定義・読み方の規則を description に書く）＋ `web/src/app/api/mcp/route.ts`（Streamable HTTP）。`features.ts` に `MCP_ENABLED = false` を足し、**false の間は route が 404**（`EXPLORE_ENABLED` と同じ流儀。画面ごとに条件を散らさない）。環境変数ではなくこの 1 ファイルで切り替える。
- ツールは**画面・AI と同じ問い合わせ層**（`@/lib/cube`）の関数を呼ぶだけ。新しい SQL を MCP 専用に書かない（ADR-0014「MCP で取れないものは画面にも出ていない」を、層2 の `serving_queries.yaml` と同じ関数を通すことで保つ）。任意 SQL・全表走査は出さない（ツール一覧のスナップショットテストで固定）。`export_dataset` は **`dist/datapackage.json` が指す相対パスと sha256 を返す**だけ（ファイルの配信・R2 は含めない）。
- `get_occurrences` の絞り込みに `license_class`/`redistributable` を**利用者が指定できる引数**として持たせるのは可（ADR-0014 の記述の訂正。**既定は絞らない**。サーバ側が勝手に絞らない。ADR-0028 が「既知の食い違い」として記録した箇所）。
- 依存: `@modelcontextprotocol/sdk`（または Workers 向けの薄い JSON-RPC 実装）。**Workers のバンドルサイズ上限を実測してから選ぶ**（担当 E の最初の作業。超えるなら自前実装。AI ツールのスキーマは `z.tuple` を使わない——メモリの既知の罠）。zod のメジャーが AI SDK 側と衝突しないことも確認する。

### D6. 公開範囲を「機械的に効かせる」の再定義（ADR-0018 の扱い）

ADR-0018 は**置換済み（→ADR-0028）のまま触らない**（`publication_rule` も作らない）。issue の閉じる条件「公開範囲の制約が機械的に効いている」を、ADR-0028 の下では次の **6 つの不変条件**に読み替え、`dist` と応答の両方に対してテストで固定する（それぞれ「わざと壊すと止まる」テストを付ける）:

1. **合成データが出ない**: `dist/` のどの Parquet にも `is_synthetic` 由来の行・`synthetic_*` の出典が無い（`datapackage.json` の sources にも無い）。応答封筒の `provenance` にも出ない。
2. **座標が v2 と 1 ビットも違わない**: `dist/occurrence` の `lat/lon/coordinate_uncertainty_m` が v2 と行ハッシュで一致（ぼかし・丸めの再導入の検知。ADR-0028 決定1）。
3. **旗は出力を絞らない（回帰）**: `redistributable=0` の出典の行が `dist/` に**存在し**、件数が v2 と一致する。`excluded` は常に 0。（絞る実装が入ると落ちる。ADR-0028 決定2 を固定する逆向きの検査）
4. **旗の忠実性**: `dist` の各出典の `license_id/license_class/redistributable/attribution` が registry の `source_edition` と一致する。写像漏れ（`license_class=unknown`）の件数は `datapackage.json` と README に**出す**（黙って埋めない）。
5. **任意 SQL・全表走査が MCP に無い**: ツール一覧と入力スキーマのスナップショット。`EXPLORE_ENABLED` とは独立に成立する。
6. **除外が無いことの明示**: 封筒の `excluded.by_license/by_embargo` が 0、`reasons` が空であることを全ツールの応答で検査。

ADR-0001「ライセンス条件でフィルタ済みの `dist/`」・ADR-0014「公開範囲で絞れる」・ADR-0018 の参照は §3 の改定案で訂正する。

### D7. 更新方式（ADR-0020）— 今やること・残すこと

| 項目 | Phase D | 理由・着手条件 |
|---|---|---|
| `update_mode` の宣言と enum 検証 | **やる** | マニフェスト必須キー。Phase C の `source_edition.update_mode` に写す（全 124 出典。既存は `static`/`snapshot`/`append` を `registry/source/editions.yaml` へ宣言）。**未宣言は止める**（推測で埋めない） |
| 鮮度の算出と応答への同梱 | **やる** | D4。`fetched_at`・`update_mode`・`age_days`。CLI `pnpm run freshness`（出典ごとの一覧）も 1 本足す（担当 M） |
| 出典単位のパーティション＋「入力が変わったパーティションだけ書き直す」 | **やる（dist のみ）** | D3 のレイアウトで、パーティションごとの行ハッシュを `datapackage.json` に持ち、前回と同じなら**書き込みをスキップ**する。ADR-0020 決定2 の最小の一歩で、測れる（スキップ数・所要時間をログ） |
| キューブの影響範囲だけの再ビルド（決定3） | **残す** | b04/b07 は現在 v2 全量を作り直し、層3 の指紋と b00 が全量前提。**着手条件**: (a) 出典が 2 つ目の版を実際に取得して差分更新の需要が出る、かつ (b) `build:v2` の所要が運用に耐えない（実測値を DEPLOYMENT.md に残してから判断）。週次フルチェックとの一致検証が先に要る |
| `snapshot` の差分保存（決定1） | **残す** | 版履歴が復元不能（取得は各 1 回）で差分を取る相手が無い。Phase C の `occurrence_id`/`observation_id` が安定 ID を与えるので、**2 版目を取得した時点**が着手条件 |
| D1 への差分投入（決定4） | **残す** | D1 に載るのは registry と `summary_*`（L2 は入れない）。現状の `db:export` 全投入で足りるかを、最初の本番更新の所要時間（DEPLOYMENT.md に記録）で判断する。着手条件: 全投入が運用上の制約（時間・課金）になったとき |

## 3. ADR 改定案（要点。本文の書き換えは実装 PR と一緒に担当 D が行う）

- **ADR-0012**: ①`map:` の YAML 写像を撤回し「マニフェスト＝宣言、変換＝adapter（短い Python）、adapter が import してよいのは `ingest.api` だけ」に。②`edition`/`license` はインラインでなく Phase C の `source_edition`/`license` 参照。③`target` は observation/occurrence のみ。④`checks` の語彙を実装済みの 5 つに限る。⑤`redistributable` は出典の旗で出力を絞らない（ADR-0028）。⑥既存 5 系統は `adapter: builtin`（メタデータのみ）。⑦ADR-0012 例の `gbif.2433433` は registry に無かった旨の訂正。
- **ADR-0014**: ①封筒に `fetched_at`・`update_mode`・`age_days`・`cite_as`・`oldest/newest_fetched_at`（`cube-envelope@2`）。②`excluded` は構造を残し常に 0（ADR-0028）。③`get_occurrences` の `license_class` 等は利用者指定の絞り込み引数で、既定は絞らない。④画面用 API は封筒でなく加算の `freshness`。⑤MCP は `MCP_ENABLED`（`features.ts`）で出し分け・第 2 段は作らない。
- **ADR-0001**: `core/` と `dist/` の分離を撤回し `dist/` のみ（再導入の条件を明記）。書き手は pyarrow。出典単位のパーティション。決定性の検査。
- **ADR-0020**: 「Phase D 時点の実装範囲」節（D7 の表）を追加。`update_mode` の enum と、残す 3 項目の着手条件。
- **ADR-0022**: 決定3 を「出典（マニフェスト）から決める。place 経由は照合に格下げ」で確定、状態の「未実装」注記を更新。決定4 は変えない。
- **ADR-0016**: Phase D の受け入れ基準に「新ソースが `git diff --stat` で `manifests/`・`scripts/adapters/`・許可した宣言ファイル・テストだけを変える」を追記。ADR-0018 は触らない（置換済み）。ADR-0028 に「公開範囲の再定義＝D6 の 6 不変条件」への参照を 1 行足す。

## 4. 実装の分割（ファイルが衝突しないように）

前提の順序: **Phase C が先にマージされる**（`source_edition`・`edition.py`・`observation_id`/`occurrence_id`・b03 土地利用節）。担当 M・P・E は互いに独立で worktree 並行可。担当 S は M のマージ後。

**担当 M: マニフェスト基盤＋ L4 の修正＋ region 統一**（読む節: 本書 §1.1・D1・D2。`docs/PIPELINE.md` の b03/b06/b09/b07 の段、`docs/adr/0022` 決定3、`scripts/migrate/source_regions.py` 冒頭 docstring）
- 新規: `scripts/ingest/{__init__,manifest,api,runner}.py`、`manifests/<既存出典>.yml`（`adapter: builtin`）、`scripts/freshness.py`（CLI）、テスト `scripts/tests/test_ingest_*.py`。
- 変更: `scripts/b03_build_observation.py`・`scripts/b06_build_occurrence.py`（**取り込みフックと region の出所の差し替えだけ**。既存の `_ingest_*` の中身は触らない）、`scripts/b09_build_occurrence_place.py`（座標なしの日付あり記録に `place_id NULL` 行）、`scripts/b07_build_occurrence_cube.py`（母集団検査の整合のみ）、`scripts/registry/build_place.py`（宣言 place の追加入力）、`scripts/migrate/common.py`（`compute_v2_input_fingerprint` に manifests・adapters を追加）、`scripts/migrate/source_regions.py`/`.yaml`（マニフェストへ吸収して撤去）、`scripts/b00_run_full_gate.py`（`PIPELINE_*` にパス追加）、`web/package.json`（`freshness` スクリプト）。
- 触らない: `web/src/**`、`scripts/dist/**`、`registry/**`（Phase C 側）。**Phase C 担当 B と b03/b06 が衝突する**ので、Phase C マージ後に着手し、衝突しうる箇所（b03 の土地利用節・`source_edition_id` 列）を避ける。
- 完了条件: 出力が 1 ビットも動かない（層2・層3 とも差分 0。region 照合が全行一致）。

**担当 P: L2 → dist Parquet**（読む節: 本書 D3・D6 の 1〜4、`docs/adr/0001`、`docs/PIPELINE.md` の「検証の2層」）
- 新規: `scripts/d01_build_dist.py`、`scripts/dist/{writer,datapackage}.py`、テスト、`.gitignore` に `dist/`。変更: `requirements.txt`（pyarrow 固定）、`.github/workflows/ci.yml` の sample-gate に dist ビルド＋検査の 2 ステップ、`web/package.json`（`build:dist`）。
- 触らない: `scripts/b0*.py`・`scripts/migrate/**`。Phase C の `source_edition` が無い段階では `datapackage.json` の sources を `source_registry` から作り、C マージ後に差し替える（インタフェースは `sources: list[dict]` 1 本）。
- 完了条件: サンプルで dist が生成され、D6 の 1〜4 のテストが緑。本番サイズの所要・容量はメインが 1 回実測。

**担当 E: 封筒・鮮度・MCP**（読む節: 本書 D4・D5・D6 の 5〜6、`docs/adr/0014`、`web/src/lib/cube/envelope.ts`、`web/src/lib/ai/tools.ts` の封筒を作る箇所）
- 新規: `web/src/lib/mcp/*`、`web/src/app/api/mcp/route.ts`。変更: `web/src/lib/cube/envelope.ts`（+テスト）、`web/src/lib/features.ts`（`MCP_ENABLED`）、`web/scripts/build-registry-ts.mjs`（source/edition/license の焼き込み。**`generated*.ts` は生成物なので再生成するだけ**）、`/api/timeseries`・`/api/biota` に加算の `freshness`、`web/package.json`（SDK 依存）。
- 触らない: `scripts/**`、`web/src/lib/cube/{observation,occurrence,series,catalog}.ts` の問い合わせ本体（SQL を MCP 用に増やさない）。
- 完了条件: ローカルで MCP の 5 ツールが応答し、封筒に `fetched_at`・注記・`excluded=0` が載る（`MCP_ENABLED=true` で `pnpm run dev`、false で 404）。層2 のスナップショットは**無変更**（画面側のフィールドは加算のみ）。

**担当 S: 受け入れの実演（kuma 1 件）**（M のマージ後。読む節: 本書 §1.2・D1・§5）
- 新規のみ: `manifests/kanagawa_kuma_sightings.yml`、`scripts/adapters/kanagawa_kuma_sightings.py`、テスト、`scripts/tests/test_adapter_boundary.py`（adapter の import 検査）、`scripts/check_source_add_boundary.py`（PR の `git diff --name-only` が許可リストに収まるかを検査する CLI）。許可リスト: `manifests/`・`scripts/adapters/`・`scripts/tests/`・宣言ファイル（`occurrence_cube_declarations.yaml`・`occurrence_period_shapes.yaml`・`period_exceptions.yaml`・`registry/source/editions.yaml`）・サンプル再生成物。**`scripts/migrate/*.py`・`scripts/registry/*.py`・`scripts/b0*.py`・`web/src/**` が差分に出たら落とす**。
- 出現の写像: `taxon` は const（`in_registry` 検査つき）、`observed_on` は `wildlife_sightings.observed_on`（正規化済み。`observed_on_raw`/年度は evidence）、`lat/lon` は NULL のまま（**補完しない**＝推測で埋めない）、`situation_ja`/`area_kind_ja`/`is_preliminary`/`locality_ja` は attributes。`individual_count` は採用しない（出現の列に無い。ADR-0025 に従い n は記録数）。
- 完了条件: 同 PR の `git diff --stat` が許可リストに収まる／**宣言差分表**（`occurrence` +400、`occurrence_agg` の増分、grid01 `place_id NULL` セルの件数、`summary_*` の変化）を PR に貼り、`data/sample/serving_snapshot.json` の更新を宣言として含める。

**最後（メイン／担当 D）**: ADR 改定・`docs/PIPELINE.md` と CLAUDE.md の更新・`DEPLOYMENT.md` に dist の配信手順（R2 は未実施と明記）。

## 5. 検証

層2（`serving:snapshot`）・層3（b00）はメインが PR 直前に 1 回。途中は触った箇所のテストだけ。

- **M**: 層2・層3 とも**差分 0**（これが「既存の出力を動かしていない」証明）。新規テスト: マニフェスト構造検証（必須キー欠落・未知キー・`target` 外・`update_mode` 外・source が `source_registry` に無い・未使用宣言、をそれぞれ止める）／region 照合（わざと manifest の region を変えると止まる）／座標なし日付あり記録が b09→b07 を通る（フィクスチャ。`place_id NULL` の `occurrence_place` 行が出て母集団検査が通る）／指紋（manifests・adapter を 1 文字変えると `check_v2_fresh.py` が 10 を返す）／adapter の import 検査（`scripts.migrate` を import した adapter が落ちる）。
- **P**: D6 の 1〜4 を dist に対して（サンプルで）。各々「わざと壊す」テスト（合成行を混ぜる・座標を丸める・`redistributable=0` を除外する・license を書き換える、で落ちる）。2 回ビルドの `sha256` 一致またはフォールバック（行ハッシュ）の動作。パーティションのスキップ（入力 1 件変更で書き直しが 1 パーティションだけ）。**本番サイズの dist の所要・容量**はメインが 1 回実測して PR に書く。
- **E**: 封筒の `fetched_at`/`update_mode`/`cite_as` が載る・出典メタの取得で D1 を引かない（`CubeDb` のスパイでクエリ 0）・`excluded>0` を許さない回帰・MCP ツール一覧と入力スキーマのスナップショット・`MCP_ENABLED=false` で 404・任意 SQL ツールが無い。`pnpm run lint`/`tsc --noEmit`/`pnpm run test`。
- **S**: 境界検査の実行結果（PR に貼る）。adapter 単体テスト（全 400 行が出る・種が 1 つ・座標 NULL・`is_preliminary` 31）。b06→b09→b07→b13 を縮小サンプルで通し、層2 の `--mode diff` の before/after 表を貼って snapshot を更新。層3（b00 全量）はメインが 1 回。
- **新規の恒久テスト（受け入れ基準 1 の再発防止）**: adapter が `ingest.api` 以外を import しない（AST）。

## 6. リスクと判断を仰ぐ点

1. **（J1）kuma は座標が全件 NULL**で、grid01 の `place_id NULL` セルが `occurrence_agg`・`summary_*` に初めて現れる（現状 `place_id IS NULL` の grid01 セルは 0）。画面側（`grid.ts`・地図・`summary_grid_catalog`）が NULL place を無視できるかは**未検証**。担当 M の最初の作業として、b09→b07→b13 を縮小サンプルに kuma 相当 400 行を足して通し、`web/src/lib/cube` の読み出しが落ちないか確かめる。落ちて直す箇所が広い場合は、第 1 候補を座標つきの別出典に替える判断をメインに仰ぐ（候補の再選定基準は §1.2。`moni1000_*` は利用条件の整理が先）。
2. **（J2）サンプルとの整合**: `min`/`row_count_between`・`expected_row_count` を持つマニフェストは縮小サンプルで件数が合わない。`--count-overlay`（b03/b06 が持つ仕組み）と同じ流儀でマニフェストの宣言値もオーバーレイ可能にする。kuma 400 行はサンプルに全件入れる（`s01_build_sample.py` の許可リストへ 1 行）。`data/sample/` の再展開は一時ディレクトリの clone で（CLAUDE.md の禁止事項）。
3. **（J3）pyarrow の導入**: wheel サイズ・CI 時間・`.venv` 差異。代案は duckdb（sqlite_scanner のネット取得が不安定）。**オーナーに確認する点**: 依存を 1 つ増やしてよいか（既定は「よい」で進める）。
4. **（J4）`core/` 撤回**は ADR-0001 の中核の変更。ADR-0028 の帰結として設計したが、オーナーが「`core/` は内部の原本として別に持つ」を望むなら、同一内容の複製を作るだけなので後から足せる（`dist/` のレイアウトは変わらない）。
5. **（J5）`stale` 閾値**は作らない。更新頻度の期待値（出典ごとの「この頻度で更新される」）を持つか、はオーナー判断。持つなら `update_mode` とは別に `expected_refresh_days` をマニフェストに足す（後からの加算で済む）。
6. **（J6）宣言ファイルを人が触る**: L5 の宣言件数は kuma 追加ごとに更新が要る。「manifest + adapter だけ」の厳密解釈（宣言ファイルも触らない）なら、宣言をマニフェストの `expected` から導出する設計にする必要があるが、**宣言を自動計算に変えると「宣言差分を機械検証する」安全網が弱まる**ので採らない。許可リストに宣言ファイルを含める解釈を、メインが受け入れ基準として承認すること。
7. **（J7）動的 import の adapter はコード指紋の自動追跡の外**（L6）。マニフェストが指す adapter を明示列挙して指紋に入れる設計だが、adapter が間接的に import する先は `ingest.api` 経由のみ（import 検査で保証）なので追跡漏れは起きない、という前提に依存する。
8. **（J8）MCP の Workers 適合**（バンドル上限・SDK の zod 版）は着手してみないと分からない。担当 E の最初の半日で結論を出し、不適合なら自前の JSON-RPC 最小実装に切り替える（ツール定義は SDK 非依存に書く）。
9. **Phase C との結合**: 本設計は `source_edition`・`update_mode` 列・`edition.py` に依存する。Phase C が未マージの間、担当 P・E は `source_registry` で仮実装できるが、**担当 M は Phase C マージ後に着手**する（b03/b06 の編集が衝突するため）。
10. **スコープ外（申し送り）**: 本番デプロイ・本番 D1 適用・R2 への `dist/` 配信・takedown 手順・公開 URI の解決エンドポイント（Phase C J2）・`feature|place|document` の target。
