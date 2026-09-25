# ADR-0026: 点→流域の解決は記録×place のサテライトに直接持ち、v1 のメモ化の癖は射影の式で再現する

- 状態: 承認済（一部未実装: D4〔`occurrence_agg` への反映〕は0025と同じくO-2bへ。D1〜D3は
  `scripts/b09_build_occurrence_place.py`/`b08_project_occurrence_v1.py` で実装済み、本文
  「実測」節で機械検証6件・完全一致を確認済み） / 日付: 2026-09-23
- 関連: ADR-0006（place）, ADR-0007（observation/occurrence）, ADR-0011（キューブ）,
  ADR-0013（caveat）, ADR-0022（place.region_id）, ADR-0024（時刻帯・時刻ラベル）,
  ADR-0025（occurrence ファクトとキューブ）

## 背景

`docs/plans/PHASE_B_OCCURRENCE.md` F3 が実測したとおり、v1
（`web/scripts/build-geo.mjs`）の流域割り当ては次の2段構えになっている。

1. 記録ごとの座標を国土数値情報 W12（1977年版、377面）へ ray-casting の
   点内包判定にかける。
2. 座標を0.001度に丸めたバケットで判定結果をメモ化し、「バケットに最初に
   来た記録（≒rowid順の走査で最初に来た記録）の判定結果」を同じバケットの
   全記録に配る。

ADR-0006 の「点→place の解決規約」規約2は「解決の最小単位は3次メッシュ
（`mesh3`。本リポジトリでは `grid01`）。より細かい単位に勝手に丸めない。
流域・行政区は `place_relation` を辿って導く」としていたが、これを
grid01→流域の `place_relation`（面積加重や多数決でのロールアップ）で近似
しようとすると、実測で著しい精度劣化になることが分かった
（`docs/plans/PHASE_B_OCCURRENCE.md` F3 実測: 4,086セル中1,145〔28%〕が
2流域以上にまたがり記録の54%を含む。セル中心規則で20.0%、セル多数決で
7.7%の記録が別流域に、`species_n` は10,699行中6,056行が変わる）。

## 決定

### D1. `occurrence_place`: 記録×place の直接解決サテライト

```
occurrence_place(record_id, place_kind, place_id NULL可, method, built_from, spec_version)
UNIQUE (record_id, place_kind)
```

`scripts/b09_build_occurrence_place.py` が `occurrence`（L2、b06）の座標を
`data/processed/nlni_w12_watersheds.geojson`（W12 1977年版、377面。**`web/public/geo/`
ではない**——あちらは配信用の生成物で、元が無いと古い実体を使い続ける）へ
点内包判定で直接解決する。

- **母集団は座標のある全記録**（`occurrence.lat IS NOT NULL AND lon IS NOT NULL`。
  日付の無い記録も含む——ADR-0007 原則1）。実測では823,692行全件に座標がある。
- **解決規則**: 入るポリゴンがちょうど1つ → 解決。0 → `place_id=NULL` の行
  （座標はあるがどの流域にも入らない）。**2つ以上、または浮動小数点で判定が
  際どい（境界上）→ 止める**（推測で割り当てない。実測ではどちらも0件）。
- `coordinate_uncertainty_m` は解決の条件にしない（F4・ADR-0006 規約4の改定
  と同じ判断——`organism_records` は75%がこの値NULLで、文字どおり適用すると
  解決不能行が急増する）。
- `method='point_in_polygon:even_odd'`、`built_from` はポリゴン版の指紋
  （`f"occurrence+nlni_w12_watersheds.geojson@sha256:{digest16}"`）。
- **PIP は純 Python**（`scripts/migrate/point_in_polygon.py`。
  `web/scripts/build-geo.mjs:112-165` の移植: 0.02度 bbox グリッド → 外環の
  even-odd → 穴、MultiPolygon 対応）。**shapely は入れない**（実測: distinct
  座標224,282件で GEOS と不一致0、約9秒。CI は `requirements.txt`
  〔PyYAML・pytest だけ〕しか入れないため、新しい重い依存を持ち込まない）。
- **v1 の0.001度メモ化はここでは一切行わない**——`occurrence_place` が持つのは
  常に「正確な」点内包判定の結果。v1 の癖の再現は射影側（D3）の責務。

**機械検証**（実データで全通過。実測は下記「実測」節）:

1. GeoJSON の `watershed_id` 集合 == registry の
   `place_source_ref(source_id='watershed_meta.watershed_id')` の
   external_key 集合。食い違えばレジストリと GeoJSON の版がずれている疑いで
   止まる。
2. 際どい交差（even-odd 判定で `|x - x_cross| < 1e-9`）があった distinct
   座標は `fractions.Fraction` で厳密に再判定し、float 版と食い違えば止まる。
3. 一致ポリゴンが2つ以上の distinct 座標が1件でもあれば止まる（無条件の
   停止条件）。
4. 宣言（`scripts/migrate/occurrence_place_declarations.yaml`）: ポリゴン数・
   `place_id` NULL の記録数・解決した記録数を実測と突き合わせ、式の検算
   （座標あり総数 − NULL = 解決）も行う。
5. `UNIQUE(record_id, place_kind)` の行数が座標あり行数と一致する。
6. **P-1a が入れた site→watershed の辺（`sites.watershed`。
   `scripts/m01_sites.py` が shapely の `contains`/`intersects` で機械的に
   決定した値。`place_relation` の地点→流域の辺278件の元）と、この PIP を
   直接突き合わせる**（座標を持つ全352地点）。食い違えば止まる——独立した
   実装（v1 の shapely ベースの判定と、このモジュールの純 Python ray-casting）
   が同じ入力（同じ GeoJSON）で同じ結論に達することを、実データで機械的に
   確認する。

### D2. v1 互換の射影（`org_watershed_year`/`org_watershed`）は L2 から、v1 の癖を順序に依らない式で再現する

`scripts/b08_project_occurrence_v1.py` が `occurrence` と `occurrence_place`
から v1 の2表を作る。**`occurrence_place` には v1 の割当を一切焼き込まない**
——ADR-0024（時刻ラベルの日割り）・ADR-0025 D3（`yr`/`mo` の v1 の式）と同じ
「v1 の癖はキューブ/レジストリ側の正しいデータに焼き込まず、射影の式に置く」
原則。

v1 の「バケットに最初に来た記録の結果を配る」という走査順依存の挙動は、
次の**順序に依らない同値な定式化**で再現する（実測: 完全に一致することを
Python で個別に検証済み——後述「実測」節）:

- バケット = `(CAST(FLOOR(lon*1000+0.5) AS INT), CAST(FLOOR(lat*1000+0.5) AS INT))`
  （JS の `Math.round(x*1000)` と同じ丸め。神奈川県内〔正の経緯度〕限定のため
  符号による差異は問題にならない）。
- 代表 = そのバケットの中で**v1 の母集団**
  （`occurrence.period_raw IS NOT NULL AND lat IS NOT NULL`）の
  `MIN(source_row_id)`（`organism_records.rowid`）。**全行〔日付の無い記録も
  含む〕で代表を選ぶと結果が変わる**——実測で69バケット変わる。必ず日付あり
  の母集団で選ぶこと。
- 記録の流域 = **代表記録自身**の `occurrence_place` の解決結果（NULL を
  含む）。代表以外の記録自身の `occurrence_place` は使わない——それが
  v1のメモ化の癖を再現するということ。

`org_watershed_year` の集計規則（v1 の SQL どおり）:
`n=COUNT(*)`、`species_n=COUNT(DISTINCT CASE WHEN scientific_name<>'' THEN
scientific_name END)`（binom ではなく**学名の全文**の DISTINCT。v1 の癖）、
`alien_n=SUM(is_alien)`、`redlist_n`（RL 原表記が NULL でも `''` でもない
件数）。**年のフィルタは無い**（1800–2026 が入る）。`org_watershed` は v1と
同じく `org_watershed_year` から `SUM`/`MIN`/`MAX` で積み上げる（L2 を
読み直さない）。流域 ID（v1形、`'83030-0001'` の形）は
`place_source_ref(source_id='watershed_meta.watershed_id')` から復元する。

**機械検証**（記録単位で実測し、宣言〔`scripts/migrate/
occurrence_watershed_v1_declarations.yaml`〕と突き合わせる。食い違えば止まる。
**キー1件ずつの宣言済み差分〔`scripts/reconcile/expected_diffs.yaml`〕には
しない**——1,091件のキーを列挙してもレビューできるゴミ箱にしかならない。
下記「宣言済み差分にしなかった理由」参照）:

- `memo_moved_records`（メモの結果と代表以外の記録自身の正確な結果が食い違う
  記録数。内訳: 両方とも流域に解決したが値が違う`ws_to_ws`／メモは解決した
  が記録自身は解決しない`v1_assigned_exact_unassigned`／その逆
  `v1_unassigned_exact_assigned`）。
- `memo_mixed_buckets`（バケット内で記録自身の正確な結果が2種類以上に分かれる
  バケット数）。
- `org_watershed_year_keys_changed_vs_exact`（メモ方式の `org_watershed_year`
  と、記録自身の正確な結果だけで同じ式を集計し直した「正確な」相当を
  `(watershed_id, year)` で突き合わせ、キーが片方にしか無い、またはキーは
  両方にあるが値のいずれかが違う、のどちらかに該当するキー数）。
- **保存則**: `Σ org_watershed_year.n` + `v1_unassigned_exact_assigned` −
  `v1_assigned_exact_unassigned` = `occurrence_place` で「日付があり・
  watershed に解決した」記録数。3つを独立に計算して等式で検証する。

## D3. ADR-0006 規約2の改定（点→place の解決規約）

旧規約2「解決の最小単位は3次メッシュ（`mesh3`）。より細かい単位に勝手に
丸めない。流域・行政区は `place_relation` を辿って導く」を、次のように改定
する（`docs/adr/0006-place-registry.md` に追記）:

1. **機械グリッド（grid01）には常に解決し `occurrence.place_id` に持つ**
   （現行どおり。ADR-0006 の2026-09-22追記、F4）。地点（site）への丸めは
   引き続き禁止。
2. **ポリゴンで定義される面の place（watershed、将来の municipality/
   town_block）には、座標から点内包判定で直接解決してよい**。対応は
   記録×place のサテライト（`occurrence_place`、place_kind ごとに高々1面）
   に持ち、解決に使ったポリゴンの版を規約3の `basis` として記録する
   （`occurrence_place.built_from` が相当）。
3. **grid01 経由の `place_relation`（セル中心規則・多数決等のロールアップ）
   で流域を近似しない**（実測は「背景」節参照）。
4. 解決規則は D1 のとおり（ちょうど1つ→解決、0→NULL、2つ以上・境界上→
   止める）。
5. `place_relation` は place どうしの関係（地点→ゾーン・地点→流域）に限る。
   ADR-0011 の `roll_up_to`（`fraction` 加重のロールアップ）も面→面の関係
   だけに適用する——占有面積のような部分的な包含がある場合の概念であり、
   点の帰属先を面積加重で「推定」する用途には使わない。
6. `place_kind` のコードリストに `grid01` を正式に追加する
   （`docs/plans/PHASE_B_INTAKE.md` #11/#16 を閉じる。以前は
   `scripts/registry/build_place.py` の逸脱として申し送りしていた）。

### D4. キューブへの反映（O-2b、本 PR のスコープ外）

`occurrence_agg`（ADR-0025 D2）は `place_kind` を鍵に既に持っており、今は
常に `'grid01'`。`place_kind='watershed'` のセルを `occurrence_place` から
足す設計・実装は **O-2b**（別 PR）に送る。ADR-0025 D2 の「O-2 への申し送り」
節がこの依存を先取りして明記済み。

## 宣言済み差分にしなかった理由

O-2a の設計初期には「1,091件の変化した `(watershed_id, year)` キーを
`scripts/reconcile/expected_diffs.yaml` に1件ずつ宣言する」案も検討した。
却下した理由:

1. **ゲートが完全一致で緑になる**（実測: `org_watershed_year`/`org_watershed`
   はどちらも宣言なしで v1 と完全一致——射影の式自体がメモの癖を過不足なく
   再現しているため）。宣言済み差分の仕組みは「再現できない既知のバグ」を
   免除するためのものであり、完全一致する2表にキーの列挙を持ち込む理由が
   無い。
2. 1,091件のキー列挙は、レビューできる情報量を持たない「ゴミ箱」になる
   （`docs/UNDATAFIED_TIERS.md` 等が言う「宣言済み差分 > データを曲げる」
   という原則は、免除にも際限があるべきという前提に立つ）。
3. 代わりに**記録単位で実測して式で検算する**（`memo_moved_records`・
   `memo_mixed_buckets`・`org_watershed_year_keys_changed_vs_exact`・保存則）
   ことで、「v1 の癖の再現が壊れていないか」を毎回のビルドで機械的に確認
   できる——キーの列挙より遥かに強い保証になる。

## 実測（`data/db/ryuiki.sqlite`/`registry.sqlite`/
`data/processed/nlni_w12_watersheds.geojson`、2026-09-23。ローカル実行）

```
occurrence_place
  母集団（座標あり occurrence）  823,692
  解決（ちょうど1つの流域に一致） 737,407
  NULL（どの流域にも入らない）    86,285
  2つ以上に一致                       0
  際どい交差（|x-x_cross|<1e-9）      0（際どい交差自体が実データに無い。
                                       最短の余裕は約4.4e-9度）
  site→watershed 辺との突き合わせ  352地点、食い違い0
  distinct 座標                  224,282（PIP 実行時間 約9〜11秒）

org_watershed_year / org_watershed（v1 との突合。b02 --tables org_watershed,
org_watershed_year）
  一致（宣言なしで完全一致）        2/2
  org_watershed_year 行数          10,699（v1 と一致）
  org_watershed 行数                  287（v1 と一致）

memo_moved_records                11,306
  ws_to_ws                          9,428
  v1_assigned_exact_unassigned        622
  v1_unassigned_exact_assigned      1,256
memo_mixed_buckets                    741
org_watershed_year_keys_changed_vs_exact  1,091
保存則: 732,707（Σn） + 1,256 − 622 = 733,341
  = occurrence_place（watershed、日付あり、NOT NULL）733,341  ✓
```

## 影響

- **良い**: 流域への解決が `place_relation` のロールアップ近似を経由せず、
  記録単位で正確になった。v1 との差分は「メモ化の癖」という1つの既知の原因
  にすべて還元でき、記録単位の実測で機械的に検証できる。将来
  municipality/town_block のようなポリゴン面を足すときも同じパターン
  （`occurrence_place` に `place_kind` を増やすだけ）を使い回せる。
- **コスト**: `occurrence_place` は823,692行のサテライト表を追加で持つ
  （`occurrence` 本体とほぼ同じ行数）。v1 互換の射影（`org_watershed_year`/
  `org_watershed`）はキューブ（`occurrence_agg`）を経由せず `occurrence`/
  `occurrence_place` を直接読むため、O-1b の年キー8表とは独立した実行経路
  になる（実行順 b06 → b09 → b07 → b08。b07/b09 の順序は入れ替え可能——
  互いに依存しない）。
- **リスク**: `occurrence_place` に持つのは watershed だけ（O-2a の時点）。
  `place_kind='grid01'` の解決は引き続き `occurrence.place_id`/`place_kind`
  （ADR-0025 D1）にあり、`occurrence_place` には無い——2つの解決の置き場が
  異なることに注意（grid01 は「常に解決する機械グリッド」でファクト本体の
  列、watershed は「入るかどうかが記録に依存する面」でサテライト表、という
  設計上の非対称性が理由。D3の改定1・2参照）。
- **申し送り（境界上0件の前提）**: 境界上の点が実測0件（機械検証2）なのは
  **今回のデータ（W12 流域どうしの隣接が疎）に固有**——市区町村のように面
  どうしが辺を共有するデータでは実際に止まりうる。そのときの復旧の方針
  （座標を人手で確認して宣言に例外を足す等）は O-2b 以降、実際に境界上の
  点に出会ってから決める。
- **申し送り（v1 の JS 版との関係）**: 点内包判定の JS 版
  （`web/scripts/build-geo.mjs`）は v1 の照合相手として残り続ける。境界判定・
  `Fraction` による厳密判定は Python 側（`scripts/migrate/point_in_polygon.py`）
  にしか無いため、両者はこの先さらに離れる。いつ収束させる（JS 版を廃止する）
  かは v1 パイプライン自体の廃止計画（未策定）に委ねる。

## 検討した代替案

- **grid01→流域の `place_relation`（セル中心/多数決）で近似する**: D3で
  却下した理由のとおり、実測で著しい精度劣化（「背景」節参照）。却下。
- **`occurrence_place` に v1 のメモ化結果を焼き込む**（`occurrence_place`
  自体をバケット単位の割当にする）: 「正確な解決」という `occurrence_place`
  の意味が失われ、O-2b のキューブ（`occurrence_agg` の `place_kind='watershed'`
  セル）も不正確な入力から作られることになる。ADR-0024/0025 と同じ理由で
  却下。
- **1,091キーを `expected_diffs.yaml` に列挙する**: 「宣言済み差分にしな
  かった理由」節で却下。
