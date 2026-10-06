# taxon_assessment — 外来種の除外規則（Issue #34 で出典の属性ベースに切り替え済み）

以前は v1 互換の固定7種だけを除外し、「origin_ja に『国内由来』を含む行をすべて除外したら」の差（10種）を
診断としてここに出していた（ADR-0016「再現してから変える」）。v1 撤去後の Issue #34 で、規則を出典の属性に
切り替えた。このレポートは切り替え時の実測（`organism_records` 823,692 行を b06 で `occurrence` にした結果）を残す。

**規則**（`registry/taxon/assessment_scope_exclusions.yaml` の `rules:`）: moe_ias_2015 の binom（二名法）の掲載行が
すべて `origin_ja` に「国内由来」を含むなら、その binom は外来種として数えない（同じ binom に国外由来の別掲載が
1件でもあれば数える。Sus scrofa・Pelodiscus sinensis・Cuora flavomarginata）。固定7種の宣言は併用し、
Apis mellifera（国外由来だが掲載学名が亜種）だけが規則の外。行は消さず、`taxon_assessment.in_scope=0` と
`scope_reason` に理由を残す。**`n_alien`（外来種として数える記録）は `occurrence.is_alien_in_scope` の合計**で、
原表記の `is_alien` は変えない。

- 規則に該当する binom: **27**（固定7種のうち6種を含む）。除外は 27 + Apis mellifera = **28** binom（`in_scope=0` は 28 行）。
- 記録のある除外種: 17（固定7種 + 新規10種）。記録 3,334 件のうち、元の `is_alien=1` は 380 件。
- `n_alien`: **3,721 → 3,341**（-380、-10.2%。キューブ `occurrence_agg` の年セル合計は 3,717 → 3,337）。
  固定7種の 351 件は、以前は `n_alien` に数えられていた（除外は `iasSpecies` の一覧だけに効いていた）。新規10種は 29 件。

| binom | 区分 | scope_reason | 記録数 | 元の is_alien=1 | is_alien_in_scope=1 |
|---|---|---|---:|---:|---:|
| Nyctereutes procyonoides | 固定7種 | domestic_origin | 1,324 | 1 | 0 |
| Plantago asiatica | 固定7種 | domestic_origin | 375 | 48 | 0 |
| Trypoxylus dichotomus | 固定7種 | domestic_origin, subspecies_binomial_contraction | 371 | 202 | 0 |
| Morus australis | 固定7種 | domestic_origin | 309 | 0 | 0 |
| Apis mellifera | 固定7種（規則外） | subspecies_binomial_contraction | 305 | 0 | 0 |
| Rumex japonicus | 固定7種 | domestic_origin | 202 | 37 | 0 |
| Cervus nippon | 固定7種 | domestic_origin | 157 | 63 | 0 |
| Pseudorasbora parva（モツゴ） | 新規 | domestic_origin | 180 | 10 | 0 |
| Plestiodon japonicus（ニホントカゲ） | 新規 | domestic_origin | 43 | 0 | 0 |
| Bufo japonicus（ニホンヒキガエル） | 新規 | domestic_origin | 37 | 0 | 0 |
| Fejervarya kawamurai | 新規 | domestic_origin | 12 | 7 | 0 |
| Mustela itatsi | 新規 | domestic_origin | 9 | 6 | 0 |
| Martes melampus | 新規 | domestic_origin | 5 | 3 | 0 |
| Ficus microcarpa | 新規 | domestic_origin | 2 | 1 | 0 |
| Coreoperca kawamebari | 新規 | domestic_origin | 1 | 0 | 0 |
| Dicentra peregrina | 新規 | domestic_origin | 1 | 1 | 0 |
| Tachysurus nudiceps | 新規 | domestic_origin | 1 | 1 | 0 |

moe リスト上は新規の除外が 21 binom あるが、記録があるのは上の 10 種（291 件）。残り 11 種に記録は無い。
以前の診断レポートの件数（モツゴ 179・ヒキガエル 36）は v1 の `org_norm.binom` 上の値で、`occurrence` の値
（180・37）とは各1件ずれる。v2 の定義は上の表（`occurrence` 上の `scientific_name` の二名法）が正。
