# P-2 taxon_assessment — ias_species の除外規則: origin 基準との差（受け入れ基準6）

`scripts/b08_project_occurrence_v1.py` の `_measure_ias_origin_delta()` が `ias_species` 構築時に実測した値。除外規則は `registry/taxon/assessment_scope_exclusions.yaml`（v1 互換の固定7種）のままで、このレポートは「origin_ja に『国内由来』を含む行をすべて除外する規則に変えたらどうなるか」を実測しただけ——ias_species の出力は変えない（ADR-0016「再現してから変える」の順序。P-2 オーナー決定A）。

- v1 互換の固定7種（除外済み）: `Apis mellifera, Cervus nippon, Morus australis, Nyctereutes procyonoides, Plantago asiatica, Rumex japonicus, Trypoxylus dichotomus`
- origin 基準（`origin LIKE '%国内由来%'` を binom 単位で全行に適用。同じ binom に国外由来の別掲載が1件でもあれば除外しない）で除外される distinct binom（`org_norm` に記録があるものだけ）: **16**
- 差分（origin 基準では除外されるが、v1 互換の固定7種には無い＝v1 に誤って残っている行）: **10**

| binom | org_norm 件数(n) |
|---|---:|
| Pseudorasbora parva | 179 |
| Plestiodon japonicus | 43 |
| Bufo japonicus | 36 |
| Fejervarya kawamurai | 12 |
| Mustela itatsi | 9 |
| Martes melampus | 5 |
| Ficus microcarpa | 2 |
| Coreoperca kawamebari | 1 |
| Dicentra peregrina | 1 |
| Tachysurus nudiceps | 1 |

Pelodiscus sinensis（ニホンスッポン）・Sus scrofa（イノシシ）は origin 基準でも除外されない（同じ binom に国外由来の別掲載があるため、上記の `MIN(...)` 判定が「全行が国内由来」にならない）。

