# レジストリ解決レポート（Phase A §A-6）

`scripts/r02_resolution_report.py` が生成する。v1 の原本（`ryuiki.sqlite` / `cells.sqlite` / `derived.sqlite`、いずれも読み取り専用）と `data/db/registry.sqlite` を突き合わせ、語彙レジストリでどこまで解決できるかを数えたもの。**このレポートはレジストリのデータを1行も直さない。**未解決が残ること自体は失敗ではなく、件数と一覧を出すことが合格条件（`docs/COLLECTOR_CONTRACT.md` / `docs/plans/PHASE_A.md` §A-6）。

再生成: `.venv/bin/python3 scripts/r02_resolution_report.py`

## 目標に対する実績（PHASE_A.md §A-6 の表）

| # | 対象 | 目標 | 実績 | 判定 |
|---|---|---|---|---|
| 1 | `measurements` 323,164行 → `variable_id` | 100% | 100.00%（未解決 0行） | OK |
| 2 | `sensor_timeseries` 717,839行 → `variable_id` | 100% | 100.00%（未解決 0行） | OK |
| 3 | `measurements` の site_id 250種 → `place_id` | 100% | 100.00%（未解決 0種 / 行ベースでは 100.00%） | OK |
| 4 | `sensor_timeseries` の site_id 77種 → `place_id` | 100% | 100.00%（未解決 0種 / 行ベースでは 100.00%） | OK |
| 5 | `organism_records` 823,692行 → `taxon_id` | ≥99.8% | 99.8964%（未解決 853行） | OK |
| 6 | 単位が決まる measurement 行（単位欠落 109,078行のうち） | 報告のみ | 104,410行（95.72%）が埋まる。残り 4,668行は未解決 | 報告のみ |
| 7 | `taxa` 8,585行 → `taxon_id` | 報告のみ | GBIF照合(EXACT)あり 2,343行 / registry `status='unresolved'` 6,242行（詳細は§7） | 報告のみ |

100%/≥99.8% を要求する項目（#1〜#5）はすべて目標を満たしている。

## 対応する完了条件（PHASE_A.md §4）

この表の #1〜#5 が満たされていることは、§4 の完了条件2「`reports/registry_resolution.md` が生成され、上表の目標を満たしている」に対応する。#6・#7 は「報告のみ」の項目で、目標達成の可否ではなく **未解決の可視化そのもの** が完了条件（COLLECTOR_CONTRACT.md）。

## 1〜2. measurements / sensor_timeseries → variable_id

- `measurements` 323,164行、`variable_alias`（`source_scope='measurements'`）で全件解決（未解決 0行）。
- `sensor_timeseries` 717,839行、同様に `source_scope='sensor_timeseries'` で全件解決（未解決 0行）。
- 未解決の指標表記（原文）の一覧: `reports/registry_resolution/unresolved_variable_aliases.csv`（0行。0行ならヘッダのみで、未解決が無いことを示す）。

## 3〜4. site_id → place_id

- `measurements` の site_id 250種、`place_source_ref`（`source_id='sites.site_id'`）で全件解決（未解決 0種）。行ベースでは 323,164/323,164行。
- `sensor_timeseries` の site_id 77種、同様に全件解決（未解決 0種）。行ベースでは 717,839/717,839行。
- 未解決の site_id 一覧: `reports/registry_resolution/unresolved_site_ids.csv`（0行。0行ならヘッダのみ）。

## 5. organism_records → taxon_id

- 823,692行中 822,839行（99.8964%）が `taxon_key` 経由で `taxon_id` に解決できる。目標 ≥99.8% を満たす。
- 未解決 853行。全件を `reports/registry_resolution/unresolved_organism_records.csv` に出す。
- 出典別の内訳（全件が同一理由: 分類群情報が空欄で照合材料が無い）:

  | source_id | 未解決行数 |
  |---|---|
  | `gbif_kanagawa_occurrences` | 292 |
  | `inaturalist_kanagawa` | 561 |

## 6. 単位が決まる measurement 行（報告のみ）

- 原本で単位（`unit`）が空の行 109,078行のうち、`variable_alias.unit_id`（無ければ `variable.unit_id`）で 104,410行（95.72%）の単位が決まる。
- 残り 4,668行は変数自体が `needs_review`（下記 §7 の `variable` 一覧を参照）で、単位が決まらない。
- 単位が埋まらない行の内訳（原文の指標表記別）:

  | 原文の指標表記 | 対応する variable_id | 未解決行数 |
  |---|---|---|
  | `流量関連（公式定義未確認のため原表記のまま）` | `common:variable:hydro.flow` | 4,668 |

## needs_review の一覧（place / variable）

- `place.status='needs_review'`: 90件。座標などが原本から確認できず、捏造せず `NULL` のまま登録した地点。一覧: `reports/registry_resolution/needs_review_place.csv`（90行）。
- `variable.status='needs_review'`: 1件。一覧: `reports/registry_resolution/needs_review_variable.csv`（1行）。
  - `common:variable:hydro.flow`（hydro.flow / 流量関連）: description_ja が未設定（unit_id が決まらないため status=needs_review。経緯は registry/variable.yaml のコメント参照）

## 7. taxa → taxon_id（報告のみ）／ status='unresolved' の taxon

- `taxa` 8,585行のうち、`gbif_taxon_key` を持つのは 2,643行。持たない（GBIFに未照合）のは 5,942行。
- `gbif_taxon_key` を持つ 2,643行の内訳: `gbif_match_type='EXACT'`（種階級での一致）2,343行 / `HIGHERRANK`・`FUZZY`（キーはあるが種以下まで一致していない弱い一致）300行。
- レジストリ側 `taxon` テーブルは 41,444行 （`status='accepted'` 35,202 / `status='unresolved'` 6,242）。**`unresolved` の件数は `taxa` の未照合件数（gbif_taxon_key欠落）と一致しない。** レビュー指摘（ADR-0019決定4）を受け、`gbif_match_type='EXACT'` 以外は `gbif_taxon_key` があっても対応する `gbif.<key>` 行に寄せず `status='unresolved'` で taxa 行ごとに個別登録する方針に直したため、`unresolved` は「未照合 5,942行」に「弱い一致 300行」を加えた6,242行になる（実測: `status='unresolved'` 6,242行）。弱い一致を寄せていた旧実装では、GBIF が種以下まで一致させられなかった広い taxon_key（例: kingdom=Animalia）に複数の無関係な種の名前・レッドリストカテゴリが混ざる行ができていた。
- 未照合・弱い一致の内訳（`gbif_match_type` 別。EXACT を除く全件）:

  | gbif_match_type | 件数 | 意味 |
  |---|---|---|
  | `(NULL)` | 5,908 | GBIFへの照会自体が未実施（gbif_taxon_key欠落） |
  | `FUZZY` | 60 | GBIFに照会でき gbif_taxon_key はあるが、種階級までの一致ではない |
  | `HIGHERRANK` | 240 | GBIFに照会でき gbif_taxon_key はあるが、種階級までの一致ではない |
  | `NONE` | 34 | GBIFへ照会したが一致しなかった |

- 全件（6242行）: `reports/registry_resolution/unresolved_taxa.csv`。以下は先頭 40 件（`taxon_id` 昇順の代表例。全件は上記CSV参照）:

  | taxon_id | scientific_name | vernacular_name_ja | taxon_group_ja | gbif_match_type |
  |---|---|---|---|---|
  | `abbottina rivularis` | Abbottina rivularis | ツチフキ | 汽水・淡水魚類 |  |
  | `abelia chinensis var. ionandra` | Abelia chinensis var. ionandra | タイワンツクバネウツギ | 維管束植物 |  |
  | `abelia serrata siebold & zucc. var. serrata` | Abelia serrata Siebold & Zucc. var. serrata | コツクバネウツギ | 維管束植物 | HIGHERRANK |
  | `abelmoschus moschatus var. betulifolius` | Abelmoschus moschatus var. betulifolius | センカクトロロアオイ | 維管束植物 |  |
  | `abrodictyum boninense` | Abrodictyum boninense | ハハジマホラゴケ | 維管束植物 |  |
  | `abroscelis anchoralis` | Abroscelis anchoralis | イカリモンハンミョウ | 昆虫類 |  |
  | `acacia confusa` | Acacia confusa | ソウシジュ（タイワンアカシア） | 植物 |  |
  | `acacia longifolia` | Acacia longifolia | ナガバアカシア | 植物 |  |
  | `acacia mearnsii` | Acacia mearnsii | モリシマアカシア | 植物 |  |
  | `acacia melanoxylon` | Acacia melanoxylon | メラノキシロンアカシア（ブラックウッドアカシア） | 植物 |  |
  | `acalolepta boninensis` | Acalolepta boninensis | オガサワラビロウドカミキリ | 昆虫類 |  |
  | `acalolepta degener` | Acalolepta degener | ヒメビロウドカミキリ | 昆虫類 |  |
  | `acanthaspis cincticrus` | Acanthaspis cincticrus | ハリサシガメ | 昆虫類 |  |
  | `acanthephippium pictum` | Acanthephippium pictum | エンレイショウキラン | 維管束植物 |  |
  | `acanthephippium sylhetense` | Acanthephippium sylhetense | タイワンショウキラン | 維管束植物 |  |
  | `acanthogobius hasta` | Acanthogobius hasta | ハゼクチ | 汽水・淡水魚類 |  |
  | `acanthogobius insularis` | Acanthogobius insularis | ミナミアシシロハゼ | 汽水・淡水魚類 |  |
  | `acanthopagrus pacificus` | Acanthopagrus pacificus | ナンヨウチヌ | 汽水・淡水魚類 |  |
  | `acanthurus achilles` | Acanthurus achilles | アカツキハギ | 魚類（海洋生物） |  |
  | `accipiter gentilis fujiyamae` | Accipiter gentilis fujiyamae | オオタカ | 鳥類 |  |
  | `accipiter gularis iwasakii` | Accipiter gularis iwasakii | リュウキュウツミ | 鳥類 |  |
  | `accipiter nisus nisosimilis` | Accipiter nisus nisosimilis | ハイタカ | 鳥類 |  |
  | `acentrogobius audax` | Acentrogobius audax | ニセツムギハゼ | 汽水・淡水魚類 |  |
  | `acentrogobius caninus` | Acentrogobius caninus | ホクロハゼ | 汽水・淡水魚類 |  |
  | `acentrogobius suluensis` | Acentrogobius suluensis | ホホグロスジハゼ | 汽水・淡水魚類 |  |
  | `acentrogobius viridipunctatus` | Acentrogobius viridipunctatus | キララハゼ | 汽水・淡水魚類 |  |
  | `acer amamiense` | Acer amamiense | アマミカジカエデ | 維管束植物 |  |
  | `acer itoanum` | Acer itoanum | クスノハカエデ | 維管束植物 |  |
  | `acer miyabei` | Acer miyabei | クロビイタヤ | 維管束植物 |  |
  | `acer miyabei f. shibatae` | Acer miyabei f. shibatae | シバタカエデ | 維管束植物 |  |
  | `acer pictum subsp. taishakuense` | Acer pictum subsp. taishakuense | タイシャクイタヤ | 維管束植物 |  |
  | `acer pycnanthum` | Acer pycnanthum | ハナノキ | 維管束植物 |  |
  | `acetabularia caliculus` | Acetabularia caliculus | ホソエガサ | 藻類 |  |
  | `acetabularia ryukyuensis` | Acetabularia ryukyuensis | カサノリ | 藻類 |  |
  | `acheilognathus melanogaster` | Acheilognathus melanogaster | タナゴ | 汽水・淡水魚類 |  |
  | `acheilognathus tabira erythropterus` | Acheilognathus tabira erythropterus | アカヒレタビラ | 汽水・淡水魚類 |  |
  | `acheilognathus tabira tabira` | Acheilognathus tabira tabira | シロヒレタビラ | 汽水・淡水魚類 |  |
  | `acheilognathus tabira tohokuensis` | Acheilognathus tabira tohokuensis | キタノアカヒレタビラ | 汽水・淡水魚類 |  |
  | `achillea alpina subsp. japonica` | Achillea alpina subsp. japonica | キタノコギリソウ | 維管束植物 |  |
  | `achillea alpina subsp. subcartilaginea` | Achillea alpina subsp. subcartilaginea | アソノコギリソウ | 維管束植物 |  |

## 生成ファイル一覧

| ファイル | 行数（ヘッダ除く） | 内容 |
|---|---|---|
| `unresolved_variable_aliases.csv` | 0 | 未解決の指標表記 |
| `unresolved_site_ids.csv` | 0 | 未解決の site_id |
| `unresolved_organism_records.csv` | 853 | taxon_id が付かない occurrence |
| `needs_review_place.csv` | 90 | 座標未確認等の place |
| `needs_review_variable.csv` | 1 | 単位・粒度未確定の variable |
| `unresolved_taxa.csv` | 6242 | GBIF未照合の taxa（全件） |

