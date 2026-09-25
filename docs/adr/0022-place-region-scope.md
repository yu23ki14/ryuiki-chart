# ADR-0022: `place.region_id` は ID のスコープと一致させ、所在は `place_relation` の辺で表す

- 状態: 承認済（一部未実装: 決定3〔`observation`/`occurrence` の region 決め方の統一〕は
  「既知の結合」のまま見送り。下記2026-09-25追記参照。決定4〔地域そのものを表す place〕も
  需要が無いため未着手のまま。決定1・2は `scripts/registry/build_place.py`/
  `r01_build_registry.py` の `_assert_region_id_scope_invariant()` で実装・検証済み）
  / 日付: 2026-09-15
- 関連: ADR-0002（多地域）, ADR-0004（識別子）, ADR-0006（place）, ADR-0011（キューブ）, ADR-0012（マニフェスト）

## 背景（実測）

`docs/plans/PHASE_B_INTAKE.md` #4（Phase A の申し送り）が指摘したとおり、
`scripts/registry/build_place.py` は `place.region_id` に**全行 `"jp-14"`** を代入していた。
一方、同じ行の `place_id` は place_kind ごとに違うスコープで発行されている
（`scripts/registry/common.place_id()` の `scope` 引数）。実際に `data/db/registry.sqlite`
を数えると次の食い違いが出る。

```
scope   place_kind  region_id  件数
common  grid01      jp-14      4,083   ← ADR-0004 規約0 と矛盾
common  watershed   jp-14        377   ← 同上（相模川は山梨県にもまたがる）
jp-14   site        jp-14        495
jp-14   zone        jp-14          5
```

ADR-0004 規約0は「地域固有だと分かっているものだけ `region_id` をスコープにする」
「レジストリ（`variable`/`taxon`/`unit`）と、県境をまたぐ実体（相模川・多摩川のような流域）は
常に `common`」と定めている。`watershed`（相模川水系は山梨県にもまたがる）と `grid01`
（`organism_records` の座標から機械的に作った、本アプリ独自の0.01度グリッド。県境という
概念自体を持たない）は、`place_id` の発行時点でどちらも `scope="common"` を選んでいた
（`registry/README.md` の「逸脱: `place_kind='grid01'`」参照）。それにもかかわらず
`region_id` 列だけは「Phase A の対象地域は神奈川県だけだから」という理由で無条件に
`"jp-14"` が入っていた。

ADR-0006 は `place` に `region_id` 列を置いたが、この列が「所在（地理的にどこにあるか）」
なのか「登録した地域（どの地域の収集作業がこの place を作ったか、管理主体）」なのかを
明記していなかった。`place_relation` も ADR-0006 が予告したまま実装されておらず、
「地点はどのゾーンに属すか」のような包含関係を機械的に辿る手段が無かった
（`sites.zone` という v1 の列にしか無い）。

本 ADR はこの2点（`region_id` の意味、`place_relation` の最初の実装）を明確にする。

## 決定

### 1. `place.region_id` は ID のスコープと一致させる

`place_id` は常に `<scope>:place:<kind>.<local_key>` の形（ADR-0004）。`region_id` は
この `<scope>` をそのまま複製する: `scope="common"` なら `region_id=NULL`、それ以外
（例: `scope="jp-14"`）なら `region_id=<scope>`。

- `scripts/registry/common.py` に `region_id_for_scoped_id(scoped_id) -> str | None` を
  置き、`build_place.py` は `place_id()` が返した ID からこの関数で `region_id` を導出する
  （`REGION_ID` 定数を region_id 列に直接代入しない）。「scope を変えたのに region_id 列だけ
  古い値のまま」という食い違いが構造的に起きないようにするため、値のコピーではなく
  **発行済み ID からの導出**にする。
- **`scripts/r01_build_registry.py` がこの不変条件をビルドのたびに機械的に検証する**
  （`_assert_region_id_scope_invariant()`。1行でも崩れたらビルドを止める）。
  `build_place.py` 以外の経路（将来の別モジュール、手動の INSERT）がこの不変条件を
  破っていないかを、生成後の DB に対して独立に確かめる。

実測（本 PR、`data/db/registry.sqlite` 再生成後）: `common -> NULL` が **4,460件**
（grid01 4,083 + watershed 377）、`jp-14 -> jp-14` が **500件**（site 495 + zone 5）。
site/zone の `region_id` は変わらない（元々 scope=`jp-14` で発行していたので、旧実装の
「全行 jp-14」と結果が一致していた）。

### 2. 所在は `place_relation(parent_id, child_id, relation='within', fraction, basis)` で表す

ADR-0006 が定義した `place_relation` を実装する。本 PR で作る辺は**地点→ゾーンの1種類だけ**
（`child_id`=地点の `place_id`、`parent_id`=ゾーンの `place_id`、`relation='within'`）。
出典は `sites.zone`（v1 の `zone_year`/`zone_clim` が `JOIN sites ... WHERE s.zone IS NOT NULL`
で使っている列）。

- **`fraction` は NOT NULL。** 全体を含む関係には `1.0` を入れる。「NULL＝全体」のような
  暗黙の意味を持たせない——ADR-0011 の「`fraction` があるものは加重する」を、値の有無で
  分岐せず常に同じ式（`SUM(value * fraction) / SUM(fraction)`）で書けるようにするため。
  地点は1つのゾーンに完全に含まれる（複数ゾーンにまたがらない）ので、この辺は常に `1.0`。
- ゾーン側の `parent_id` は `place_source_ref(source_id='sites.zone')` 相当の対応
  （`build_place.py` が zone place を作る際に組み立てる `{ゾーン番号: place_id}` の対応表）
  を引いて解決する。`registry/place/zone.yaml` に無いゾーン番号が現れたら、黙って捨てず
  例外を投げてビルドを止める。
- 実測（本 PR）: 辺数は **290件**。`sites.zone IS NOT NULL` の地点数（290件）と一致する。
- **`source_edition_id`（ADR-0006 が挙げる列）はまだ持たない。** 出典の版管理
  （`source_registry`/`source_edition`、ADR-0005）自体が Phase C の仕事であり、いま作る
  唯一の辺（地点→ゾーン）の出典は `registry/place/zone.yaml` という手書きファイル1つに
  固定されていて、版を切り替える必要が今は無い。
- `(parent_id, child_id, relation)` の一意性は DDL の `UNIQUE` 制約ではなく
  `scripts/r01_build_registry.py` 側の Python 表明で検証する（`variable_alias` の
  `(dataset, alias, source_id)` 一意性と同じ流儀。`registry/README.md` 参照）。

### 3. `observation.region_id` は将来 place からではなく出典（マニフェスト）から決める

`scripts/b03_build_observation.py` は現在 `place_source_ref(source_id='sites.site_id')` →
`place.region_id` の経路で `observation.region_id` を埋めている。地点（`jp-14:place:site.*`）
に紐づく観測だけを扱っているあいだは、地点の `region_id` が本 ADR で変わらないため結果は
一致する（受け入れ条件7で実測確認済み）。

しかし `common:` の place に紐づくファクト（例: 生物出現 `occurrence` → `grid01` メッシュ）が
`observation`/`occurrence` に入る時点で、この経路は破綻する——`grid01` の `region_id` は
`NULL`（決定1）であり、機械的なグリッドがそもそも「どの地域の収集作業で登録されたか」
（マニフェストが持つべき情報、ADR-0012）を表していないため、place 経由では地域を確定できない。
**この PR ではコードを変えない。** 既知の結合（今は結果が一致するが、いずれ直す必要がある
接続点）として、ここに明記するだけにとどめる。

**2026-09-22 追記（occurrence で先に実装。[ADR-0025](0025-occurrence-fact-and-cube.md) D1）**:
`scripts/b06_build_occurrence.py`（`occurrence`）は、本決定が予告したとおり
出典（`organism_records.source_id`）から `region_id` を決める最初の実装になった
（`scripts/migrate/source_regions.py`・`source_regions.yaml`。ADR-0012 のマニフェストが
本来持つべき `region:` 欄を、この宣言ファイルとして先取りしている）。**`observation`
（`scripts/b03_build_observation.py`）側は変更していない**——地点に紐づく観測だけを
扱っているあいだは `place` 経由の結果が一致するため、直す理由が今は無い（この段落が
明記した「既知の結合」はそのまま残っている）。両者を将来1本の経路（ADR-0012 マニフェスト
本体）に揃えるかどうかは別途判断する。

**2026-09-25 追記**: `observation`（place 経由）と `occurrence`（出典の宣言から）で region の
決め方が違う、という上記の「既知の結合」をいつ・どちらに揃えるかは、**Phase D（#40）の
マニフェスト実装時に判断する**（ADR-0012 のマニフェスト本体が `region:` 欄を正式に持つように
なった時点で、`observation`/`occurrence` のどちらの経路を正とするか、あるいは両方を残すかを
決める）。それまでは本節が明記したとおり、地点に紐づく観測だけを扱っているあいだは結果が
一致するため、コードは変更しない。

### 4. 地域そのものを表す place、および `common:` place → 地域の空間的な所在の辺は作らない

`prefecture` のような「地域そのもの」を表す `place_kind` も、`common:` の place
（watershed/grid01）から地域への所在の辺（空間演算で `fraction` を算出する必要がある）も、
**この PR では作らない。** 使う側（地域単位のロールアップ、例: 「神奈川県内の流域だけ集計する」）
が実際に現れたときに、解決に使ったポリゴンの版を `basis` に記録して作る
（ADR-0006 の「点→place の解決規約」3 と同じ考え方: 解決に使った版を必ず残す）。
今回はまだ需要が無いものを先回りして作らない。

## 影響

- **良い**: `region_id` が ID のスコープという1つの事実から機械的に決まるので、
  「scope は変えたが region_id は直し忘れた」という食い違いが構造的に起きなくなる
  （r01 が毎回検証もする）。「地点はどのゾーンに属すか」が `place_relation` を辿れば
  答えられるようになり、ADR-0011 のロールアップ集計（`zone_year`/`zone_clim` 相当）の
  土台ができる。
- **コスト**: `place.region_id` の値が変わる（`common:` スコープの4,460件が `"jp-14"` から
  `NULL` になる）。本 PR で調査した限り、web 側にこの値を読む消費者はまだ無い（後述）ので
  実害は無いが、将来 place を直接参照するコードを書くときは `region_id=NULL` を
  「地域不明」ではなく「地域非依存（common）」として扱う必要がある。
- **注意**: 決定3の「既知の結合」は本 ADR を書いた時点では顕在化しない負債である。
  `occurrence`/`grid01` をファクト化するときに必ず読み直すこと。

## 検討した代替案

- **所在（地理的な位置）を単一列で持つ**: `region_id` を「その place が地理的にどこに
  あるか」という意味の列として使う案。県境をまたぐ流域（相模川は山梨県にもまたがる）を
  どちらかの県に寄せるか、複数県にまたがることをどう表すかが決まらない。単一列では
  1:1にしかならず、1:N（1つの流域が複数地域にまたがる）を表せない。却下。
- **登録した地域（管理主体）を表す**: 「この place をどの地域の収集作業が登録したか」という
  意味にする案。現状の値（`common:` の place にも `jp-14` が入っている）をそのまま追認でき、
  移行コストがゼロという利点はある。しかし ADR-0004 規約0
  （`common` の実体に地域を埋めない。レジストリと県境をまたぐ実体は常に `common`）と
  正面から矛盾し、将来 山梨県を対象地域に加えたときに同じ流域（相模川水系）が
  `jp-14` 版と `jp-19`（山梨県）版の2回登録されうる。ID の意味（規約0がスコープに
  込めた「昇格したら ID が変わらない」という不変性）を壊すため却下。
