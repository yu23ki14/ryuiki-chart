# Phase B taxon_assessment（P-2）— レッドリストと外来種の評価

対象: ADR-0016 の Phase B / 状態: **実装済み（`phase-b/taxon-assessment`）**
作成: 2026-09-23 / 関連: [ADR-0019](../adr/0019-taxon-registry.md)（2026-09-23追記）、
[ADR-0002](../adr/0002-multi-region.md)、`docs/plans/PHASE_B_RECONCILIATION.md`

オーナー決定の控え（`o2_p2_decisions.md` の「P-2」節）を実装した記録。決定そのものは
ADR-0019 の追記に一本化してあり、ここには**実測とファイルの対応だけ**を書く
（同じ経緯を何箇所にも複製しない、という既存ドキュメントの流儀に合わせた）。

## 1. 対象と縦線の切り方

v1 の3表を、同じ構造（`list_id` × `taxon` の評価）を持つレジストリテーブル
`taxon_assessment`（`registry.sqlite`、D1には載せない）に統合してから射影し直した。

| v1 テーブル | 行数 | 入力 | 射影スクリプト |
|---|---:|---|---|
| `redlist_map` | 44 | `registry/taxon/redlist_category.yaml` + `redlist_category_alias.csv`（`taxon_assessment` を経由しない静的語彙） | `scripts/b12_project_taxon_v1.py` |
| `redlist_change` | 2,884 | `taxon_assessment`（list_id ∈ {rl2020, rdb2022p, rl2026}） | 同上 |
| `ias_species` | 173 | `taxon_assessment`（list_id='moe_ias_2015'）+ `org_norm`（binom結合）+ `ryuiki.taxa`（表示名） | `scripts/b08_project_occurrence_v1.py`（occurrence の縦線に同居。`org_norm` の binom と結合する必要があるため） |

## 2. `taxon_assessment` の構築（`scripts/registry/build_taxon_assessment.py`）

r01 の実行順で `taxon`（A-4）の直後に置く（taxon_id 解決が `registry.taxon` を読むため）。

- **入力**: `ryuiki.redlist_assessments`（2,884行、3版）と
  `data/processed/moe_ias_list.csv`（429行）。後者は `ryuiki.taxa` を経由しない
  ——`scripts/c25_taxa_table.py` が `origin_ja`（除外7種の根拠）を落としているため。
  指紋（`scripts/registry/common.py`）にこの CSV を追加した。
- **カテゴリー正規化**: `registry/taxon/redlist_category.yaml`（12コード。IUCN 準拠
  8コード + 神奈川県独自の RA/AT + `not_listed`）+ `redlist_category_alias.csv`
  （45行 = v1の44行 + `'―' → not_listed`）。**実測**: v1の44行の `raw→label/code/rank`
  と1件残らず一致することをスクリプトで突き合わせ済み。正規化（改行・半角/全角空白の
  除去）で変わる行数は今回側`category_ja`で**0**、前回側`category_prev_ja`で**8**
  （すべて alias に想定どおり解決）。未知の原表記は0件（あれば `ValueError` で止まる）。
- **taxon_id 解決**（学名完全一致 → 二名法一致の順、曖昧なら NULL。診断用の列で
  Phase B の再現には不要）: 実測（`data/db/registry.sqlite`、2026-09-23）
  ```
  taxon_assessment 総行数        3,313（redlist 2,884 / moe_ias_2015 429）
  taxon_id 解決     2,008 / 3,313 (60.6%)
    list_id 別: rl2020 942/1,031・rdb2022p 0/1,033（原本に scientific_name が
    無い）・rl2026 720/820・moe_ias_2015 346/429
  redlist（学名がある1,851行のうち） 1,662 (89.8%)
  ```
- **`prev_category_code`**: `'―'`（247行）は `not_listed` として明示的に持つ
  （黙ってNULLに落とさない。ADR-0019追記参照）。

## 3. `redlist_map`/`redlist_change`（`scripts/b12_project_taxon_v1.py`）

`taxon_assessment` は3,313行だが redlist_map（44行）はこれを経由しない静的語彙
（`taxon_assessment` の実データ行数に依存しない）。小さい表（合計2,928行）なので、
`INSERT ... SELECT` ではなく Python の dict で組み立てて `executemany` で書く
（YAML/CSV という SQLite の外にある語彙を引く必要があるため。既存の10万行超の
射影とは意図的に違う設計——モジュール docstring参照）。

**`not_listed`（v1に無かったコード）は `redlist_map` には出さず、`redlist_change`の
出力列（`prev_label`/`prev_code`/`prev_rank`）では NULL に戻す**——registry の
`taxon_assessment`は「'―'を黙って落とさない」を守り、v1互換の射影は「v1のバイト列を
再現する」を守る、という責務の分離。

### 受け入れ基準1（実測）

```
$ .venv/bin/python3 scripts/b02_derived_compare.py \
    --candidate data/db/v1_projection_taxon.sqlite --tables redlist_map,redlist_change
一致: 2 / 宣言済み差分のみ: 0 / 不一致: 0
EXIT=0
```

## 4. `ias_species`（`scripts/b08_project_occurrence_v1.py`）

v1（`web/scripts/build-biota.mjs` 234-257行）: `taxa.ias_category` を二名法で
`org_norm` に `(binom, ias_category)` GROUP BY・`MAX(vernacular_name_ja)`・
静的7種除外で結合。

- **入力の切り替え**: `taxa.ias_category` ではなく `taxon_assessment
  (list_id='moe_ias_2015')` から binom（学名の先頭2語、v1と同じ規則をSQL版で
  意図的に重複）を作る。
- **除外7種**: `registry/taxon/assessment_scope_exclusions.yaml`
  （`scripts/registry/build_taxon_assessment.load_assessment_scope_exclusions()`
  が構造・実測件数〔domestic_origin 6件・subspecies_binomial_contraction 2件、
  Trypoxylus dichotomus は両方——distinct 7種〕を検証済み。b08 はこの関数を
  そのまま import して使う）。
- **表示名（`name_ja`）の設計からの逸脱（設計時に想定していなかった依存）**:
  v1の`MAX(vernacular_name_ja)`は、`taxa`テーブルが既に済ませた**3出典
  （`kanagawa_redlist.csv` → `moe_redlist.csv`〔国レッドリスト、本PRのスコープ外〕
  → `moe_ias_list.csv` の順、`scripts/c25_taxa_table.py`）をまたいだ「同じ学名の
  最初の非空和名が勝つ」畳み込みの結果**を読んでいた。実測で1件（*Coreoperca
  kawamebari* オヤニラミ）が不一致になった: moe_ias_list.csv 単体の和名は
  「近畿地方以東のオヤニラミ」だが、v1は国レッドリスト（`moe_redlist.csv`、
  本PRでは一切読んでいないファイル）の「オヤニラミ」を先に採用していた。
  3出典の畳み込みを再実装する代わりに、**`ryuiki.sqlite`の`taxa.vernacular_name_ja`
  （畳み込み済みの結果そのもの）を直接読む**設計に切り替えた——`b10_project_documents_v1.py`
  が原本を直接ATTACHする前例に倣う。副作用として `b08` が初めて `ryuiki.sqlite`
  への依存を持つ（`--ryuiki-db` 引数、既定 `data/db/ryuiki.sqlite`。既存の
  `cube-db`/`registry-db` と並ぶ3つ目の読み取り専用ATTACH）。
- **カテゴリーの畳み込み**: moe_ias_list.csv 内で学名が重複する行（実測1組:
  `'Bufo spp.'`）は、`c25_taxa_table.py.touch()`と同じく「最後に処理した行の
  category が勝つ」（この1組は2行とも同じcategoryのため実害は無い）。

### 実測（`data/db/ryuiki.sqlite`/`registry.sqlite`、2026-09-23）

```
ias_species                  173行（v1と一致）
```

### 受け入れ基準2（実測）

```
$ .venv/bin/python3 scripts/b02_derived_compare.py \
    --candidate data/db/v1_projection_occurrence.sqlite \
    --tables org_norm,org_group_year,effort_year,species2,species_year2,species_month,\
mesh_year,mesh_all,mesh_species,species_mesh_year,org_watershed,org_watershed_year,ias_species
一致: 11 / 宣言済み差分のみ: 2 / 不一致: 0
EXIT=0
```
「宣言済み差分のみ2」は`org_norm`/`species2`の`cls`列（F2、O-1a/O-1bから既存。
本PRでは増やしていない）。

### 受け入れ基準3（既存ゲートが変わらないことの確認）

```
occurrence（823,692行）・occurrence_agg（471,060行）・occurrence_place: 行数不変
  （scripts/b08_project_occurrence_v1.py 以外は本PRで一切変更していない）
b03→b04→b05（既存11表）: 一致5 / 宣言済み差分のみ6 / 不一致0（変更なし）
watershed_meta（b11）: 一致1 / 宣言済み差分のみ0 / 不一致0（変更なし）
```

### 受け入れ基準6: origin基準との差（実測レポート）

`reports/phase_b_taxon_assessment.md`（`_measure_ias_origin_delta()`が構築時に
書く）参照。**実測は10種**（brief記載の概算「11」とは異なる——後述）:

```
v1互換の固定7種（除外済み）: Apis mellifera, Cervus nippon, Morus australis,
  Nyctereutes procyonoides, Plantago asiatica, Rumex japonicus, Trypoxylus dichotomus
origin基準（origin_jaに「国内由来」を含む行をbinom単位で全行に適用。同じbinomに
  国外由来の別掲載が1件でもあれば除外しない）で除外されるdistinct binom
  （org_normに記録があるものだけ）: 16
差分（origin基準では除外されるが、v1互換の固定7種には無い）: 10
  Pseudorasbora parva(179) / Plestiodon japonicus(43) / Bufo japonicus(36) /
  Fejervarya kawamurai(12) / Mustela itatsi(9) / Martes melampus(5) /
  Ficus microcarpa(2) / Coreoperca kawamebari(1) / Dicentra peregrina(1) /
  Tachysurus nudiceps(1)
```

Pelodiscus sinensis（ニホンスッポン）・Sus scrofa（イノシシ）は同じbinomに国外由来の
別掲載があるため、origin基準でも除外されない（brief記載どおりの実測結果）。

**「11」との差についての注記**: `p2_brief.md`の「origin を基準にすると v1 には
誤って残る行が11ある」は、この機能に着手する前の探索段階（Fableサブエージェントに
よる見積もり）の数値。実装時に実際にビルドして計測したところ**10**だった
（本ドキュメントの数値が実測の正）。10件全種がorg_normに記録を持ち候補になっており、
brief記載の4種（Pseudorasbora parva/Plestiodon japonicus/Bufo japonicus/
Mustela itatsi）を含むため、見積もり時と実装時で対象集合の認識自体は一致している
——差は「org_normに実際に記録があるものだけを数える」という本実装の絞り込み
（`_measure_ias_origin_delta()`のdocstring参照。記録が無ければorigin基準に
変えてもias_speciesの行として現れようがないため）に由来すると推測されるが、
見積もり時の計算過程が残っていないため確証はない。除外リストそのものは
変えていないため、この差はどちらの数字でも受け入れ基準・ias_speciesの出力に
影響しない。

## 5. r01 の不変条件（`scripts/r01_build_registry.py`）

- `ID_UNIQUENESS_CHECKS` に `("taxon_assessment", "assessment_id")` を追加。
- `_assert_taxon_assessment_invariants()`: `taxon_assessment.list_id` が
  `assessment_list.yaml`に、`category_code`/`prev_category_code`（NULLでなければ）が
  `redlist_category.yaml`にあることを検証（構築時に既に保証済みだが、レジストリ
  全体の受け入れ基準として生成後のDBに対しても再確認する——既存の
  `_assert_region_id_scope_invariant()`等と同じ考え方）。

## 6. r01 フルビルド・`--check-fresh`（受け入れ基準4）

```
$ RYUIKI_REGISTRY_DB=<worktree>/data/db/registry.sqlite .venv/bin/python3 scripts/r01_build_registry.py
...
  taxon_assessment: 3,313 行
...
  taxon_assessment 不変条件OK: list_id/category_code とも既知の語彙内（3,313 件）
▶ 正規パスへ置き換えた: .../data/db/registry.sqlite

$ ... scripts/r01_build_registry.py --check-fresh
✔ 新鮮: .../data/db/registry.sqlite（mode=full, fingerprint=...）
EXIT=0
```

`web/scripts/build-registry-ts.mjs` を再生成しても `generated.ts`/`generated-client.ts`
の `git diff` は**0行**（`taxon_assessment`はD1に載せないため、これらの生成物が
読む語彙〔unit/variable/place/taxon/caveat〕を本PRは一切変えていない）。

## 7. pytest（受け入れ基準5）

新規23件（`test_registry_taxon_assessment.py` 14件・`test_b12_project_taxon_v1.py`
4件・`test_b08_ias_species.py` 5件）+ 既存438件 = **461件**。

```
scripts/tests 全体（.venv、SQLite 3.49.1）: 461件成功
原本の無い一時 clone（.gitignore済み data/db 無し）+ requirements.txtだけの
  venv（Python 3.13.7、CIと同じ）: 461件成功
古いSQLite（システム既定 python3.10、sqlite3モジュール3.37.2）の同clone: 358件
  成功・103件スキップ（3.43未満をスキップする既存の仕組みのまま。失敗0）
`scripts/r01_build_registry.py --files-only`・`web/scripts/build-registry-ts.mjs`
  も同clone環境で成功、generated.ts/generated-client.tsのgit diff 0行
```

CI（`.github/workflows/ci.yml`のreconcileジョブ）に、`taxon_assessment`の語彙
4ファイル（`redlist_category.yaml`/`redlist_category_alias.csv`/
`assessment_list.yaml`/`assessment_scope_exclusions.yaml`）の構造検証ステップを
追加した（既存の`expected_diffs.yaml`等と同じ流儀。原本DB・moe_ias_list.csvは
使わない）。

## 8. 設計からの逸脱

- **§4に記載した`ryuiki.sqlite`への新規ATTACH**（`ias_species`の表示名解決）。
  brief決定3は「入力は`ryuiki.taxa`ではなく`moe_ias_list.csv`」としていたが、
  これは`origin_ja`（除外の根拠）の出所についての決定であり、v1互換の表示名
  （3出典の畳み込み結果）まで`moe_ias_list.csv`単体で再現できるとは想定して
  いなかった。`taxa.vernacular_name_ja`を読み手として引用するのみで、
  `taxon_assessment`の構築（`build_taxon_assessment.py`）は引き続き
  `moe_ias_list.csv`を直接読み、`taxa`を経由しない——decision3の核（origin_jaの
  出所）は変えていない。

## 9. 未決

なし（設計どおりに実装でき、受け入れ基準1〜6すべてが実測で満たされた）。

## 10. 既知の負債

- `taxon_assessment.taxon_id`の解決率（60.6%）は診断用で、これを使う消費者は
  まだ無い（Phase Bの再現には不要）。将来taxon_idベースの分析が必要になったら、
  現在の「完全一致→二名法一致、曖昧なら解決しない」という保守的な規則を
  見直す余地がある（ambiguousな候補から件数最多を選ぶ等）。
- `scripts/b08_project_occurrence_v1.py`の`_binom()`/`_c25_norm_id()`は
  `scripts/registry/build_taxon.py`/`build_taxon_assessment.py`の同名規則と
  意図的に重複させた（呼び出し側パッケージを跨いだ共有ヘルパ化は本PRのスコープ外。
  3箇所目の重複が出たら共通化を検討する）。
- origin基準の「11」と実測「10」の差（§4末尾）は、見積もり時の計算過程が
  残っていないため完全な説明ができていない。除外リストの是正自体が
  ADR-0016の順序で後回しになっているため、実害は無い。
- 残り3テーブル（`watershed_rollup`・`landuse_watershed`/`landuse_change`、
  P-1b）は本PRのスコープ外（`docs/plans/PHASE_B_RECONCILIATION.md` §8参照）。
