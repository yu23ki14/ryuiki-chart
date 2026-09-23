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

**「11」との差についての注記（/code-review 指摘15。2026-09-24訂正）**:
`p2_brief.md`の「origin を基準にすると v1 には誤って残る行が11ある」は、
この機能に着手する前の探索段階（Fableサブエージェントによる見積もり）の数値。
**実装時に実際にビルドして計測した結果は10であり、これが正しい**
（以前の版はここで「11との差はorg_normの絞り込みに由来すると推測される」と
書いていたが、これは検証していない当て推量だった——/code-review で指摘され、
下記のとおり数え方の変種を機械的に総当たりしたが、どの変種でも11にはならない
ことを確認したため、推測の記述を削除する）。

「国内由来」の判定基準・集計範囲を変えた4通りの数え方（`org_norm`/
`taxon_assessment` の実データに対する機械集計、2026-09-24実測）:

| 数え方 | 件数 |
|---|---:|
| moe_ias_2015 の全binomのうち、**全行**が国内由来（org_normの記録有無を問わない） | 27 |
| ↑のうち固定7種の外 | 21 |
| moe_ias_2015 の全binomのうち、全行が国内由来 **かつ org_norm に記録がある** | 16 |
| ↑のうち固定7種の外（=`delta_binoms`、実装値） | **10** |
| moe_ias_2015 の全binomのうち、**いずれか1行でも**国内由来（org_normの記録有無を問わない） | 30 |
| ↑のうち org_norm に記録がある | 18 |
| ↑のうち固定7種の外 | 12 |

**11になる規則は存在しない**（10と12の間に「11」を作る自然な境界が無い）。
除外リストそのものは変えていないため、どの数字を使っても受け入れ基準・
`ias_species`の出力（受け入れ基準2）には影響しない——このレポート
（`reports/phase_b_taxon_assessment.md`）は診断専用であり、実装が採用する
基準は「全行が国内由来 かつ org_norm に記録がある」（10）で一貫している。

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

`/code-review` 対応後の件数（§11参照）。

```
scripts/tests 全体（.venv、SQLite 3.49.1）: 475件成功
原本の無い一時 clone（.gitignore済み data/db 無し）+ requirements.txtだけの
  venv（Python 3.13.7、CIと同じ）: 475件成功
古いSQLite（システム既定 python3.10、sqlite3モジュール3.37.2）の同clone: 失敗0
  （`ias_species`はFULL OUTER JOIN/AVG()/SUM()を使わないため3.43未満でも
  スキップせず実行する——/code-review指摘14。それ以外の3.43依存テストは
  従来どおりスキップ）
`scripts/r01_build_registry.py --files-only`・`web/scripts/build-registry-ts.mjs`
  も同clone環境で成功、generated.ts/generated-client.tsのgit diff 0行
```

CI（`.github/workflows/ci.yml`のreconcileジョブ）に、`taxon_assessment`の語彙
4ファイル（`redlist_category.yaml`/`redlist_category_alias.csv`/
`assessment_list.yaml`/`assessment_scope_exclusions.yaml`）の構造検証ステップを
追加した（既存の`expected_diffs.yaml`等と同じ流儀。原本DB・moe_ias_list.csvは
使わない）。

## 8. 設計からの逸脱

`/code-review`対応（§11）で当初の設計から変更した4点は、そちらに逸脱として
記録した（ADR-0019 2026-09-24追記と同内容）。初回実装時点で唯一あった逸脱
（`ryuiki.sqlite`への直接ATTACHをb08に持たせたこと）は、§11の対応1で
解消済み（射影はレジストリだけを読む設計に戻した）——現時点で残る設計からの
逸脱は無い。

## 9. 未決

なし（設計どおりに実装でき、受け入れ基準1〜6すべてが実測で満たされた）。

## 10. 既知の負債

- `taxon_assessment.taxon_id`の解決率（60.6%）は診断用で、これを使う消費者は
  まだ無い（Phase Bの再現には不要）。将来taxon_idベースの分析が必要になったら、
  現在の「完全一致→二名法一致、曖昧なら解決しない」という保守的な規則を
  見直す余地がある（ambiguousな候補から件数最多を選ぶ等）。
- `binom_of()`（`scripts/registry/build_taxon_assessment.py`。b08 が import
  して使う——/code-review指摘12で一本化済み）と
  `scripts/registry/build_taxon.py._binom()`は、同じ規則の意図的な重複の
  ままである（レジストリのビルド時パッケージ内で完結させるため。3箇所目の
  重複が出たら共通化を検討する）。
- 残り3テーブル（`watershed_rollup`・`landuse_watershed`/`landuse_change`、
  P-1b）は本PRのスコープ外（`docs/plans/PHASE_B_RECONCILIATION.md` §8参照）。
- `taxon_assessment` は list の種類ごとに使われない列が増える形になっている
  （`origin` は`moe_ias_2015`だけ、`prev_category_*`/`national_category_*`は
  redlist系3リストだけが持つ）。現状は「redlist系」「外来種系」の2種類なので
  実害は無いが、**3つ目の種類（例: 別の評価体系）が来たら、共通列＋種類別の
  拡張テーブルに分けることを検討する基準**にする（申し送り。/simplify 指摘9）。

## 11. `/code-review` 15件の反映（`phase-b/taxon-assessment`、2026-09-24）

初回実装（§1〜10、HEAD `7b9db7e`）に `/code-review` をかけて15件の指摘を
受け、すべて反映した。**3表（`redlist_map`/`redlist_change`/`ias_species`）
と既存12表（`org_norm`等occurrence系10表・`org_watershed`/`org_watershed_year`）
の値は1ビットも変わっていない**——修正後に同じ実データからビルドし直し、
`scripts/b02_derived_compare.py`が修正前と同じ「一致2/宣言済み差分0」
（redlist_map/redlist_change）・「一致11/宣言済み差分のみ2/不一致0」（13表）
を返すことを確認した（行数もテーブルごとに完全一致）。既存の観測系11表・
`watershed_meta`のゲートも不変（`scripts/b03〜b05`/`b11`は本ラウンドで
一切変更していない）。

### 反映した指摘（要約）

1. **和名の畳み込みをレジストリ側に移した**（§8「設計からの逸脱」参照。
   `taxon_assessment.vernacular_name_ja_resolved`列を新設、b08は
   `ryuiki.sqlite`へのATTACHをやめてレジストリだけを読む）。
2. **`redlist_change`の`not_listed`→NULL変換を cur側・prev側で対称にした**
   （`scripts/b12_project_taxon_v1.py._v1_compat()`が`(code, label, rank)`の
   3つ組を返すように変更。以前は出力行の組み立てで`prev_code`だけ個別に
   ガードしており、`cur_code`は素通ししていた。実データでは今回側に
   `'―'`が0件のため出力は変わらない）。
3. **`ias_species`の`WHERE category_raw IS NOT NULL AND category_raw <> ''`
   フィルタを追加**（v1の`WHERE ias_category IS NOT NULL AND
   ias_category<>''`と同じ条件。実データでは空の区分が0件のため出力は
   変わらない）。
4. **taxaに対応する行が無い／`vernacular_name_ja`がNULLのケースを明示的に
   扱う**: 対応が無ければ止める（黙って空文字に丸めない）、NULLなら
   `vernacular_name_ja_resolved`もNULLのまま（`""`に丸めない）。実データでは
   429行全件でtaxa照合が成功し全件非NULLのため、この分岐は将来データの
   防御（実測は§2参照）。
5. **除外宣言の`scientific_name`が二名法（空白区切り2語）であることを
   検証する**ようにした（`load_assessment_scope_exclusions()`）。実物の
   7種はすべて2語のため出力は変わらない。
6. **除外宣言の`list_id`が`assessment_list.yaml`に実在することを検証する**
   ようにした。実物の7種はすべて`moe_ias_2015`のため出力は変わらない。
7. **外来種の`assessment_id`をCSV行順から内容（学名の正規化＋区分＋和名の
   組。sha256先頭12桁を添える）由来に変えた**（`_ias_assessment_id()`）。
   `assessment_id`はredlist_map/redlist_change/ias_speciesのどの出力列にも
   現れないため、この変更は3表の値に一切影響しない。
8. **`redlist_list_ids()`を`assessment_list.yaml`の`kind='red_list'`から
   導出する**共有関数にし、`build_taxon_assessment.py`と`b12`の両方の
   ハードコードされた3件のタプルを置き換えた。
9. **`assessment_list.yaml`の`codelist`を実際の分岐（`_category_code_for_list()`）
   に、`region`/`redlist_category.yaml`の`scope`を既知の地域ID集合に対する
   検証に使うようにした**。実データではredlistの3リストは`codelist:
   redlist_category`・moe_ias_2015は`codelist: null`、scope/regionは
   すべて`common`/`jp-14`/`jp`のいずれかのため出力は変わらない。
10. **二名法の出どころ（`taxa.scientific_name` vs `moe_ias_list.csv`自身の
    `scientific_name`）が一致することを機械検証する**ようにした（実測:
    429行全件一致。§2参照）。
11. **未知の原表記でビルド全体を止める判断（ADR-0019決定2からの意図的な
    逸脱）を、ADR-0019の追記に明記した**（2026-09-24追記）。
12. **`binom_of()`をb08から`registry.build_taxon_assessment`のものへ一本化した**
    （3つ目の複製を作らない）。
13. **`build_ias_species_projection()`の戻り値を`(table_counts, diagnostics)`
    の2要素タプルに変えた**（兄弟関数と同じ形。以前は行数と診断値を1つの
    dictに混ぜていた）。
14. **`test_b08_ias_species.py`のSQLiteバージョンによるスキップを外した**
    （`ias_species`の経路は`FULL OUTER JOIN`/`AVG()`/`SUM()`を使わないため、
    3.43未満でも実際に走ることを確認した）。
15. **origin基準との差「11」と実測「10」の食い違いについて、根拠のない
    推測（「org_normの絞り込みに由来すると推測される」）を削除し、4通りの
    数え方を実測で総当たりした結果（27/21/16/10/30/18/12）に置き換えた**
    （§4「受け入れ基準6」参照。11になる数え方は存在しない）。

### 実測（`data/db/ryuiki.sqlite`/`registry.sqlite`/`v2.sqlite`、2026-09-24）

```
taxon_assessment: 3,313行（redlist 2,884 / moe_ias_2015 429、不変）
  moe_ias_2015: 429/429行がtaxaと学名一致（vernacular_name_ja_resolvedを解決）
redlist_map: 44行（不変） / redlist_change: 2,884行（不変） / ias_species: 173行（不変）

b02 --tables redlist_map,redlist_change: 一致2 / 宣言済み差分0 / 不一致0（不変）
b02 --tables (13表): 一致11 / 宣言済み差分のみ2 / 不一致0（不変）
既存11表・watershed_metaのゲート: 不変
r01 full build・--check-fresh: fresh（EXIT=0）
generated.ts/generated-client.ts: git diff 0行
pytest: 475件成功（原本の無い一時clone・古いSQLiteどちらも失敗0）
```
