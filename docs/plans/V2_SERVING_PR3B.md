# Issue #48 PR-3b「生物系の切り替え（値が動く）」実装設計

前提: ブランチ `feat/48-pr3b`（main = PR-3a マージ済み、`9a08646`）。実測は 2026-10-05 に `data/db/v2.sqlite`（PR-3a の `occurrence_agg` 1,437,598 セル・summary 4表入り）・`registry.sqlite`（`taxon` 41,454・`taxon_assessment` 3,313、`vernacular_ja_basis` 入り）・`ryuiki.sqlite`・`derived.sqlite` を `mode=ro` で読んだもの（§付録）。重い処理は一切回していない。PR-2 設計書（`V2_SERVING_PR2.md`）の形をなぞる。

## 0. 要点（先に読む）

1. **PR-3a のセルだけで、生物系の v1 表のほぼ全部が「値が動かずに」再現できる。** 実測（v1 表 vs `occurrence_agg`＋`taxon` からの再集計、キー単位の完全一致）: `species_year2` 116,899 行・`mesh_year` 37,043 行・`mesh_all` 4,083 行・`mesh_species` 4,086 行・`species_mesh_year` 276,163 行・`effort_year` 57 行・`org_group_year` 1,166 行は**差 0**。`redlist_change` 2,884 行は `taxon_assessment`＋`registry/taxon/redlist_category.yaml` から**差 0**（assessment_id 単位）。`ias_species` 173 行は `taxon_assessment.binom`（新設列、§2.4）で結合すれば**差 0**（`taxon_id` 結合だと 50 行しか出ない）。動くのは次の4つ（＋種数の定義が1か所）だけ:
   - **流域のメモ化の退役**（`watershed_memo`）: `org_watershed_year` の n/alien/redlist が動くキー 1,085（値差 992＋v1 のみ 54＋v2 のみ 39）、`watershed_rollup` の `org_n` が動く流域 185/287（`org_redlist_n` 44・`org_alien_n` 48）。
   - **月セルの所属**（`month_cell_membership`）: `species_month` 9,997 キー中 19 キー（12 種、Σn 388,983→388,843）。
   - **和名の表示名**（`vernacular_label_rule`、D4）: §1 の表。
   - **日付の無い記録の除外**（`undated_excluded`、新規）: 概況の生物レコード数が 823,692→816,856（−6,836）。
   - ＋**種数の定義**（`species_n_definition`）は `org_watershed_year` だけ（v1 は学名全文の DISTINCT、v2 は `taxon_id`。画面の読み手なし、138 キーが定義だけで動く）。画面に出る種数（`effort_year`/`org_group_year`/`mesh_*`）は v1 と同じ「二名法キー（binom）の DISTINCT」で作るので動かさない（D1）。
2. **罠: PR-3a が足した第3索引 `ix_occurrence_agg_kind_grain_period` が、taxon 引きの問い合わせの計画を壊す。** `json_each(binoms) JOIN taxon JOIN occurrence_agg` が 100 秒以上かかった（`ix_occurrence_agg_taxon_period` ではなく `(place_kind, grain)` の全走査＋`taxon` の主キー引きを選ぶ。`ANALYZE` の無い D1 でも同じ）。**taxon 引きは `INDEXED BY ix_occurrence_agg_taxon_period` を必ず付ける**と 20〜300ms（§4）。EXPLAIN をテストで固定する（§5 U2）。
3. **全表走査は 1〜2.8 秒かかるので summary を足す**（PR-2 の「事前計算が要る」と同じ判断）。`effort_year`・`org_group_year`・`mesh_all`/`mesh_species`・種カタログ。**種数を v1 と同じ binom 単位で数えるには `taxon.canonical_binomial` を引く必要がある**ので、b13 が `registry.sqlite` を読み取り専用 ATTACH して作る summary 4表を新設する（D1。`taxon_id` 単位のままだと種数が +8%（中央値）〜+41%（最大）動く）。
4. **「検証が本番の経路を通っているか」**: serving-diff の v2 アダプタは §2 の `lib/cube` 関数をそのまま呼ぶ。生 SQL を持たない（PR-2 §8.4 の自動テストを生物系にも拡張）。説明の鎖は「v1 →(規則)→ 独立に組んだ中間点 →(=)→ v2」で、中間点は L2（`occurrence`/`occurrence_place`・registry・`ryuiki.sqlite`）から serving-diff が別 SQL で再計算するか、b08 が書く `org_watershed_year_exact`（`v1_projection_occurrence.sqlite`）を読む。
5. **作業は4単位・4 worktree**（U1 パイプライン＋registry、U2 `lib/cube`、U3 画面/API/AI、U4 serving-diff）。U2 が最初のコミットで型だけ出し、U3・U4 はそれに載る。重い検証は PR 直前に1回ずつ（§5.3）。

## 決めてほしいこと（最小限）

| # | 論点 | 推奨 |
|---|---|---|
| D1 | 画面に出る種数・メッシュ種数・年×分類群の件数を v1 と同じ **binom 単位**で作るために、b13 が `registry.sqlite` の `taxon` を ATTACH（読み取り専用）して summary 4表（種カタログ・年×分類群・年・グリッド）を作ってよいか。やめると `taxon_id` 単位になり、`effort_year.species_n` が全57行で動く（中央値 +8%、2024年 5,460→7,475）、`mesh_species.species_n` が 4,086 中 2,088 セルで動く | **採用**。「summary は taxon_id 粒度のまま」（`aggregations/serving.yaml` の注記）の例外になるが、これらは最終粒度の表で再集計しないので非加法の問題は起きない。`species_n_definition` は流域×年だけに残る |
| D2 | `/map` の流域ポリゴンと `get_overview` の流域ロールアップは、**生物件数（`org_n`/`org_alien_n`/`org_redlist_n`）だけ**を cube に切り替え、面積・重心・`site_n`・土地利用は v1 の `watershed_rollup` を PR-4 まで読み続けてよいか（土地利用の行き先は設計書のどこにも無い） | **採用**（混成にして PR-4 で土地利用を決める。流域外 83,515 件は `get_overview` に `outside_watershed_n` として出す） |
| D3 | 概況の「生物レコード」を、日付の無い記録（6,836 件）を含めない件数にしてよいか（`occurrence_agg` は日付ありの分割。L2 は D1 に入れない）。`/api/biota?kind=effort` の `totals`（records/gbif/inat）も同じ | **採用**（home・`get_overview` の表記を「日付のある生物レコード」にする。差は `undated_excluded` として serving-diff が `ryuiki.sqlite` から数える） |
| **D4** | **記録由来の和名補完（`taxon.vernacular_ja_basis='records'`、12,024 件、種以下）を表示名に使うか** | **使う**（下の表）。使わないと n≥80 の 1,702 種中 1,417 種（83%）、/biota の既定の増減表の 138 種中 80 種の名前が変わり、和名を失うのは 1,233／60 種。使うと 423／26 種に収まる。併せて `taxa` 由来の地域・亜種名が種の表示名になる事故 2 種（ホンドタヌキ・カブトムシ）を `registry/taxon/vernacular_ja.csv` の上書きに足す（54→56 件） |

### D4 の判断材料: 表示名がどう変わるか（実測）

定義（binom 単位。同じ binom の taxon が複数あるので、**件数 `n` が最大の taxon の値**を代表にする。同数は taxon_id の昇順）:

- **v1**: `NAME_JA[binom] ?? species2.en_name ?? binom`（`en_name` は `MAX(vernacular_name)`＝記録のどれかの俗名。言語は混在）。
- **v2・補完を使う**: `NAME_JA ?? taxon.vernacular_name_ja（basis が override/taxa/records のどれでも）?? vernacular_name_en ?? binom`。
- **v2・補完を使わない**: `NAME_JA ?? vernacular_name_ja（basis が override/taxa だけ）?? vernacular_name_en ?? binom`。
- 分類: 日本語＝かなを含む／英名等＝ラテン文字／中国語等＝漢字のみ／学名のみ＝名前が無い（binom そのもの）。

**件数（binom 単位、名前の文字列が v1 と変わる数）**

| 母集団 | 全体 | うち 日本語を失う | n≥80 の上位種 | うち 日本語を失う | /biota 既定の増減表（A=2018–20, B=2022–24, 全分類群） | うち 日本語を失う | 外来種 171（名前列は `name_ja` なので画面影響なし） |
|---|---|---|---|---|---|---|---|
| 種数 | 23,618 | | 1,702 | | 138 | | 171 |
| **使う（推奨）** | **2,345**（9.9%） | 1,142（学名のみへ）＋108（英名へ）＝1,250 | **423**（24.9%） | 31（学名のみ 17＋英名 14） | **26** | 4 | 32（0） |
| **使う・改訂（採用。種の階級の和名を優先）実測** | **2,837**（12.0%） | 日本語→日本語以外 1,313（旧規則 2,113） | **424**（24.9%） | 31（旧規則 183） | | | |
| 使う・旧（件数最大の taxon を代表）実測 | 3,276（13.9%） | 2,113 | 568（33.4%） | 183 | | | |

改訂の実測（v1 の `species2.en_name` 基準、`/tmp` の独立再計算と serving-diff の `label_moved` が一致）: 旧規則は全体 3,276・n≥80 568（上表の 2,345・423 は過小見積もり）。新規則で日本語を失う件数は全体 2,113→1,313、n≥80 183→31。種より下の階級（亜種・変種・品種）の和名が選ばれる種は 694（うち種階級の taxon が別に存在するもの 373・n≥80 は 45）で、そのうち v1 と同じ名前 446、v1 が日本語以外だったもの 211（亜種名が付く側に回る。例: Abelia chinensis=タイワンツクバネウツギ、Acacia longifolia=ナガバアカシア）、v1 と別の日本語になるのは 37（旧規則でも同じ 34）。逆戻りは旧規則比で 3 件。
| 使わない | 11,578（49.0%） | 11,057（学名のみ 9,017＋英名 2,040）＋漢字のみ 226 | 1,417（83.3%） | 1,233（英名 683＋学名のみ 550） | 80 | 60 | 107（82） |

**遷移の内訳（n≥80。全体の件数は括弧内）**

| v1 → v2 | 使う | 使わない |
|---|---|---|
| 日本語 → 日本語（別の文字列） | 218（605） | 10（58） |
| 中国語等（漢字のみ）→ 日本語 | 139（167） | 2（4） |
| 中国語等 → 英名・学名のみ | 0（63） | 137（226） |
| 日本語 → 学名のみ | 17（1,142） | 550（9,017） |
| 日本語 → 英名 | 14（108） | 683（2,040） |
| 英名 → 英名（別の文字列） | 33（75） | 34（76） |
| 学名のみ → 日本語／英名 | 0／1（126／5） | 0／1（108／5） |
| 英名 → 日本語 | 1（53） | 0（43） |

**代表例（n≥80 は件数の多い順。「使う」の列は補完込み、「使わない」は補完なし）**

1. **日本語→日本語（v1 の名前が変種・亜種の名前だった。改善寄り）** 218 件: Houttuynia cordata ヤエドクダミ→ドクダミ／Trifolium repens モモイロシロツメクサ→シロツメクサ／Viola grypoceras ミドリタチツボスミレ→タチツボスミレ／Oxalis corniculata ホシザキカタバミ→カタバミ／Campanula punctata ヤマホタルブクロ→ホタルブクロ／Carex leucochlora メアオスゲ→アオスゲ／Stachyurus praecox ハチジョウキブシ→キブシ／Equisetum arvense ミモチスギナ→スギナ／Setaria viridis ムラサキハマエノコロ→エノコログサ／Polystichum ×（属＋記号）ヨコハマイノデ→ドウリョウイノデ。括弧付きの注記が絡む変化（「モリチャバネゴキブリ（幼虫）」→「モリチャバネゴキブリ」など）が 12 件。
2. **中国語名等から改善** 139 件: Dryopteris erythrosora 红盖鳞毛蕨→ベニシダ／Veronica persica 阿拉伯婆婆纳→オオイヌノフグリ／Taraxacum officinale 药用蒲公英→セイヨウタンポポ／Dryopteris uniformis 同形鳞毛蕨→オクマワラビ／Oenothera rosea 粉花月见草→ユウゲショウ／Aucuba japonica 青木→アオキ／Polystichum polyblepharum 棕鳞耳蕨→イノデ／Callicarpa japonica 日本紫珠→ムラサキシキブ／Oplismenus undulatifolius 求米草→コチヂミザサ／Acer palmatum 鸡爪槭→イロハモミジ。
3. **和名を失う（使う場合）17 件（日本語→学名のみ）**: いずれも `Rhinogobius Gill,`・`Tritoma Fabricius,`・`Deparia Hook.`・`Boehmeria Jacq.`・`Pterophyta`・`Amphibalanus Pitombo,`・`Somena Walker,`・`Athemus Lewis,`・`Mycena (Pers.)`・`Neotriplax Lewis,` のように、**属以上の記録の学名の先頭2語が「属＋著者名」になった binom**。v1 はその binom に混ざった別の種の和名（ヨシノボリ（黒色大型B）・ムツホシチビオオキノコ…）を出していたので、v1 の名前のほうが誤り。
4. **日本語→英名（使う場合）14 件**: Magnoliopsida ハマヒエガエリ→Dicots／Fungi さび病→Fungi Including Lichens／Plantae ホソアオゲイトウ×オオホナガアオゲイトウ→Plants／Coccinellidae ルイヨウマダラテントウ→Lady Beetles／Poaceae イネ科の一種→grasses／Asteraceae タンポポ属の雑種→Sunflowers, Daisies, Asters, and Allies など。**科・綱・界の binom に種の和名が付いていた v1 の誤りが直る**（v2 は種以下にしか補完しない）。
5. **英名→英名** 33 件: Parus cinereus Japanese Tit→Asian Tit／Milvus migrans Tobi→Black Kite／Horornis diphone Japanese Bush Warbler ssp cantans→Japanese Bush Warbler／Ardea alba Western Great Egret→Great Egret／Anas platyrhynchos Northern Mallard→Mallard／Yungipicus kizuki Japanese Pygmy Woodpecker (nippon)→Japanese Pygmy Woodpecker／Motacilla grandis Seguro-Sekirei→Japanese Wagtail／Actitis hypoleucos Iso-Shigi→Common Sandpiper／Cisticola juncidis Zitting Cisticola (Far Eastern)→Zitting Cisticola／Mergus merganser Goosander→Common Merganser。ローマ字名や亜種注記が消える方向。
6. **和名を失う（使わない場合）** n≥80 で 1,233 件。日本語→英名 683: Motacilla alba ハクセキレイ→White Wagtail／Spodiopsar cineraceus ムクドリ→White-cheeked Starling／Anas zonorhyncha カルガモ→Eastern Spot-billed Duck／Streptopelia orientalis キジバト→Oriental Turtle-Dove／Phalacrocorax carbo カワウ→Great Cormorant／Hirundo rustica ツバメ→Barn Swallow／Anas crecca コガモ→Green-winged Teal／Lanius bucephalus モズ→Bull-headed Shrike／Monticola solitarius イソヒヨドリ→Blue Rock-Thrush／Phoenicurus auroreus ジョウビタキ→Daurian Redstart。日本語→学名のみ 550: Carex leucochlora メアオスゲ／Atractomorpha lata オンブバッタ／Microlepia marginata フモトシダ／Patanga japonica ツチイナゴ／Thelypteris japonica ハリガネワラビ／Aulacophora nigripennis クロウリハムシ／Aster ageratoides ヤマシロギク など（全部 `Carex leucochlora` のような学名表示になる）。
7. **学名のみ→日本語（全体 126。n≥80 は 0）**: Tongeia filicaudis ムシャクロツバメシジミ／Reishia clavigera イボニシ／Ophiocordyceps entomorrhiza オサムシタンポタケ／Coriolopsis glabrorigens コガネカワラタケ／Ceriagrion melanurum キイトトンボ。英名→日本語 53: Scolopax rusticola Yama-Shigi→ヤマシギ／Bletilla striata Hyacinth orchid→シラン／Cygnus olor Mute Swan→コブハクチョウ／Nuphar japonica East Asian yellow water-lily→コウホネ。
8. **`taxa`（RL/外来種リスト）由来と記録由来の食い違い**: `vernacular_ja_basis in (taxa, override)` の taxon に、記録由来の候補が別にあって一致しないものは **taxon 単位で 38 件**（taxa 35・override 3。うち n≥80 の binom は 6）。PR-3a 設計書の「n≥80 で 108 件」は再現できなかった（定義が違うと思われる。ここの 38 が taxon レジストリ上の実数）。n≥80 の 6 件: Columba livia カワラバト（ドバト）［override］⇔ ドバト／Nyctereutes procyonoides **奥尻島・屋久島のタヌキ**［taxa］⇔ タヌキ（v1 は ホンドタヌキ）／Hestina assimilis アカボシゴマダラ大陸亜種（名義タイプ亜種）⇔ アカボシゴマダラ／Bidens pilosa オオバナセンダングサ［override］⇔ コセンダングサ／Trypoxylus dichotomus **北海道・沖縄のカブトムシ本土亜種**［taxa］⇔ カブトムシ（v1 は カブトムシ）／Abelia spathulata ベニバナノツクバネウツギ⇔ベニバナツクバネウツギ。**前の2つ（タヌキ・カブトムシ）は種の表示名が地域個体群の名前になる実害**で、n≥80 の外にも「伊豆諸島のニホントカゲ」「シラホシハナムグリ名義タイプ亜種」「伊豆諸島などのアズマヒキガエル」のように同種の問題がある（全体の件数は §9-3 の確認事項）。

**D4 の推奨の根拠**: 補完を使うと、v1 より悪くなるのは「属以上の binom に付いていた誤った種の和名が消える」だけで、その他の変化は改善か中立。使わない場合は名前が変わる種が 83%（n≥80）・58%（/biota の既定の表）に及び、その大半が日本語から英名・学名への置き換えで、実質的に「和名表示をやめる」決定になる。残る危険（`taxa` 由来の地域名）は上書き 2 件で塞ぎ、全体の洗い出しを §9-3 に残す。

---

## 1. 範囲と非範囲

- 範囲: `/biota`（4タブ）・`/map`（`/api/geo/mesh`・`/api/geo/watersheds`）・home の生物部分（努力量図・レッドリスト図・「生物レコード」）、AI の `get_biota_trend`・`get_redlist`・`get_overview` の生物部分。
- 非範囲（PR-4）: `overviewStats` の生物以外の列・`landuseHighlight`・`landuse_change`・`watershed_rollup` の土地利用と `site_n`（D2）、`/api/nature`、`doc_series`。v1 表自体の撤去（PR-5）。`web/src/lib/queries.ts` の v1 関数は serving-diff の v1 側が呼ぶので**残す**（画面・API・AI からの import だけをやめる）。

## 2. 対応表: v1 の呼び出し → `lib/cube`

方針は PR-2 と同じ: **画面・API・AI・serving-diff の v2 アダプタは同じ公開関数を呼ぶ。** summary を読むものは `catalog.ts`、セルを引くものは新設の `occurrence.ts`、レッドリストは新設の小さな `assessment.ts`。全関数が `CubeDb` を第1引数に取り、`IN (...)` に ID を並べず `json_each(?)` で渡す（`assertD1Compatible` が検査、上限 `MAX_ID_LIST`＝1000）。

### 2.1 新しい summary 4表（U1。D1）

`aggregations/serving.yaml` に宣言し、b13 が `v2.sqlite` に作る。**b13 の語彙拡張は4つだけ**: (a) `join: {taxon: registry}`（`registry.sqlite` を `ATTACH ... mode=ro` して `taxon_id` で結合。結合先の列を `group_by`/`count_distinct`/`max` に使える）、(b) `group_by` に `expr: year_of_period_start`、(c) `group_by` 列の `coalesce: '未判定'`、(d) 保存則（Σn 一致）は結合前のキューブ側と比べる（結合で行が増減しない＝`taxon` は主キー結合）。`pipeline_fingerprint.inputs` に `{occurrence_agg, registry:taxon}` を持たせ、`check_v2_fresh.py` が `registry.sqlite` の指紋を既に見ているので、registry が古ければ summary も古いと判定される。`SUMMARY_SPEC_VERSION` を `serving-summary/v3` に上げる。

| 表 | 粒度（key） | 列 | 行数（実測の見積もり） | 使う画面 |
|---|---|---|---|---|
| `summary_species_catalog` | `binom`（`taxon.canonical_binomial`、taxon_id NULL は含まない） | `taxon_group`（taxon の MAX。v1 の `MAX(taxon_group)` と同じ規則）・`class`/`family`（MAX）・`n`・`n_red_list`・`n_alien`・`n_places`（grid01 の DISTINCT）・`y_from`・`y_to`・`n_years`（DISTINCT 年） | 23,618（v1 `species2` と同数） | 種カタログ・n≥80 の足切り・増減表の分類群・概況の種数 |
| `summary_group_year` | `(year, taxon_group, source_id)`（taxon_id NULL のセルは `taxon_group='未判定'`） | `n`・`n_binom`・`n_places` | 約 1,200（v1 `org_group_year` は 1,166） | `/biota` 努力量・分類群別推移 |
| `summary_effort_year` | `year` | `n`・`n_binom`・`n_places`（`n_inat`/`n_gbif` は `summary_group_year` の `source_id` 別の `SUM(n)` から引く。n は加法なので正確） | 約 230（年 1800〜2026） | 努力量・home |
| `summary_grid_catalog` | `place_id`（grid01） | `n`・`n_red_list`（**年 1970〜2026 の窓を焼く**。v1 `mesh_all` の窓。窓外 33,859 件は 1,067 グリッドに散る）・`n_binom`・`n_red_binom`（窓なし。v1 `mesh_species` が窓なし） | 4,086（窓内で n>0 は 4,083＝v1 `mesh_all`） | `/map` メッシュ通年 |

`summary_taxon_catalog`（PR-3a、`taxon_id` 粒度）は表示名の代表 taxon（件数最大）を選ぶために使う。年に窓（1970〜2026）が要る問い合わせは lib 関数の WHERE で掛ける（`summary_group_year`/`summary_effort_year` は全年を持つ）。

### 2.2 `lib/cube` に足す公開関数

型と列名は U2 が最初のコミットで確定する（以下は設計の約束）。

**`catalog.ts`（summary を読む）**

| 関数 | 中身 | v1 の対応 |
|---|---|---|
| `speciesCatalog(db, {group?, limit?, withNames?})` | `summary_species_catalog` の `ORDER BY n DESC, binom`。`withNames` で §2.3 の表示名を付ける | `speciesList` |
| `taxonGroupYears(db, {from=1990, to=2026})` | `summary_group_year` を `(year, taxon_group)` に畳む（`n`＝SUM、**`mesh_n`＝MAX over source。v1 の癖を保つ**） | `taxonGroupYears` |
| `effortYears(db, {from=1990, to=2026})` | `summary_effort_year` ＋ `summary_group_year` の source 別 n | `effortYears` |
| `gridCatalog(db)` | `summary_grid_catalog`（n>0）。`placeId → (mlat, mlon)` の変換ヘルパ `gridCellOfPlaceId`（`common:place:grid01.3520_13900` → 3520, 13900）を同じ層に置く | `meshAll`（`mesh_all ⋈ mesh_species`） |
| `occurrenceTotals(db)` | `{records, species, grids, gbif, inat}`。`records`/`gbif`/`inat` は `summary_effort_year`/`summary_group_year` の SUM、`species` は `summary_species_catalog` の行数、`grids` は `summary_grid_catalog` の n>0 の行数（日付ありのみ。D3） | `biotaTotals`・`overviewStats` の `n_org`/`n_species` |
| `watershedOccurrence(db)` | `summary_watershed_occurrence`（`place_id` NULL の行は `outsideWatershed` として別に返す）＋ `watershedIdOfPlaceId`/`placeIdOfWatershedId`（`common:place:watershed.nlni-<id>` ⇔ v1 の `<id>`。統合テストで `place_source_ref` と一致を確かめる） | `watershed_rollup` の `org_n`/`org_alien_n`/`org_redlist_n`（`org_watershed`） |
| `iasSpecies(db)` | `taxon_assessment`（`list_id='moe_ias_2015' AND in_scope=1`）の `binom` で `summary_species_catalog` と結合。`n_since_2020` だけは `occurrence_agg` を `INDEXED BY ix_occurrence_agg_taxon_period` で引く（173 種で 167ms） | `iasSpecies` |

**`occurrence.ts`（セルを読む。第1引数 `CubeDb`、`binoms` は `json_each(?)`）**

| 関数 | 中身 | v1 の対応 |
|---|---|---|
| `speciesYears(db, binoms, {from=1990, to=2026})` | grid01×(year, survey_period) のセルを `taxon` 経由で binom に束ね、`(binom, year, n, mesh_n=COUNT(DISTINCT place_id))`。**年は `substr(period_start,1,4)`**（実測で v1 の `substr(observed_on,1,4)` と全キー一致） | `speciesYears` |
| `speciesMonths(db, binoms)` | grid01×month のセル、`period_start >= '2018-01-01'`、`substr(period_start,6,2)` で畳む。**n≥80 の足切りは `summary_species_catalog.n` で掛ける**（v1 の `species_month` と同じ。足切りを外す変更はしない） | `speciesMonths` |
| `speciesMeshYears(db, binom)` | grid01×year のセルを `(year, place_id)` で。`place_id → (mlat, mlon)`。n≥80 のみ（v1 の `species_mesh_year` と同じ） | `speciesMeshYears` |
| `speciesShareTrend(db, group, a, b)` | セルを taxon_id ごとに期間 A/B で SUM → `taxon` で binom に束ね → `summary_species_catalog.taxon_group = ?` → `HAVING n_a>=40 AND n_b>=20`。`total_a`/`total_b` は同じ集合の合計。表示名は §2.3 | `speciesShareTrend` |
| `meshByYear(db, year)` | grid01×(year, survey_period) の `period_start` 範囲＋`taxon` で `species_n=COUNT(DISTINCT canonical_binomial)`・`rl_n=SUM(n_red_list)`。**`ix_occurrence_agg_kind_grain_period` を使う**（62ms） | `meshByYear` |
| `watershedYears(db, {placeId?})` | watershed×(year, survey_period) の `place_id IS NOT NULL` を `(place_id, year)` で。`species_n=COUNT(DISTINCT taxon_id)`。**画面の読み手は無い**（v1 の `org_watershed_year` も無かった）。serving-diff の `watershed_year` が唯一の呼び手で、cells→summary の一貫性の確認を兼ねる（§6-5） | `org_watershed_year` |
| `speciesLabels(db, binoms, {records})` | §2.3 | `species2.en_name`＋`speciesLabel()` |

**`assessment.ts`（レッドリスト）**: `redlistSummary(db)`・`redlistFlows(db, listYear, group?)`・`redlistSpecies(db, listYear, direction?, group?, limit)`。`taxon_assessment`（`list_id in (rl2020, rdb2022p, rl2026)`、2,884 行）を読み、**カテゴリ名と順位は生成定数**（`registry/taxon/redlist_category.yaml` → `generated-client.ts` の `REDLIST_CATEGORY`、`assessment_list.yaml` → `ASSESSMENT_LIST`。D1 に表は足さない）で引き、`direction`（悪化/改善/横ばい/前回記載なし）を TS で付ける（`prev_category_code='not_listed'` は順位 NULL＝前回記載なし。v1 の b12 と同じ規則）。1 版は最大 1,033 行なので行を取って TS で畳む。実測で v1 `redlist_change` と assessment_id 単位に全列一致。

**`caveats.ts`**: `facetsForOccurrence({ places: ('grid01'|'watershed')[], ias?: boolean })` を足す。`dataset=organism_records`（`organismSite`/`effort`/`regimes`/`gbifCutoff`/`share`）を常に、`place_kind=grid01`（`share`/`effort`）を grid01 を引くときに、`source_id=moe_ias_list`（`isAlien`）を IAS のときに積む。いずれも `registry/caveat.yaml`・`build_caveat.py` に既にある v2 facet。v1 表名ベースの `tables:` は使わない（危険16件 #1 の再発防止）。

### 2.3 表示名（D4）の実装

`speciesLabels(db, binoms, {records: boolean})`: binom → taxon（`ix_taxon_binomial`）→ `summary_taxon_catalog.n` が最大の taxon を代表にし、`NAME_JA[binom]`（クライアントの生成定数）→ `vernacular_name_ja`（`records: false` なら `vernacular_ja_basis in ('override','taxa')` のものだけ）→ `vernacular_name_en` → binom の順に返す。API は `{binom, label}` を返し、UI の `speciesLabel(binom, enName)` は第2引数に `label` を渡す形にする（`NAME_JA` が先に勝つ規則は変えない）。**`records: true` を既定にし、定数 `USE_RECORD_VERNACULAR`（1箇所、`lib/cube/occurrence.ts`）で切り替える**——D4 を覆されたとき、serving-diff の `vernacular_label_rule` の期待値と画面が1行で揃う。

### 2.4 registry（U1）

- `taxon_assessment` に **`binom` 列**（`binom_of(scientific_name_raw)`＝`scripts/registry/build_taxon_assessment.py` の既存関数）を足す（`schema_registry.sql`・`web/src/db/schema-registry.ts`・テスト）。IAS は `taxon_id` が 346/429 しか解決せず、結合すると 50 行になる。binom 結合で v1 の 173 行・n が全一致（実測）。
- `web/scripts/lib/registry-codegen.mjs`・`build-registry-ts.mjs` に `REDLIST_CATEGORY`・`ASSESSMENT_LIST` を足し、`generated-client.ts`/`generated.ts` を再生成する。
- D4 採用なら `registry/taxon/vernacular_ja.csv` に Nyctereutes procyonoides=ホンドタヌキ・Trypoxylus dichotomus=カブトムシを足す（`vernacular_ja_basis='override'`、54→56）。

### 2.5 画面・API・AI ごとの対応

| 呼び出し元 | v1 | v2（`lib/cube`） | 値が動く要因 |
|---|---|---|---|
| `/api/biota?kind=effort`（努力量タブ、IAS タブの分母） | `taxonGroupYears`・`effortYears`・`biotaTotals` | `taxonGroupYears`・`effortYears`・`occurrenceTotals` | `undated_excluded`（totals のみ） |
| `kind=trend`（増減表） | `speciesShareTrend` | `speciesShareTrend`（`label` 付き） | `vernacular_label_rule` |
| `kind=species`（年・月） | `speciesYears`＋`speciesMonths` | 同名 | `month_cell_membership`（月） |
| `kind=mesh`（種×メッシュ×年） | `speciesMeshYears` | 同名 | なし |
| `kind=ias` | `iasSpecies` | `iasSpecies` | なし（`taxon_assessment.binom` 前提） |
| `kind=redlist` | `redlistFlows`・`redlistSpecies`・`redlistSummary` | `assessment.ts` の3関数 | なし |
| `kind=list` | `speciesList` | `speciesCatalog({withNames})` | `vernacular_label_rule`（読み手は UI に無いが API として残す） |
| `/api/geo/mesh`（`year` 無し／有り） | `meshAll`／`meshByYear` | `gridCatalog`／`meshByYear`（`gridCellOfPlaceId`） | なし（`rl_species_n` は通年のみ、v1 と同じ） |
| `/api/geo/watersheds` | `watershedRollup`（全列） | v1 `watershedRollup` の `org_*` を除く列＋`watershedOccurrence`（D2） | `watershed_memo` |
| home | `effortYears`・`redlistSummary`・`overviewStats.n_org` | `effortYears`・`assessment.redlistSummary`・`occurrenceTotals().records` | `undated_excluded` |
| AI `get_biota_trend` groups／share／species | `taxonGroupYears`＋`effortYears`／`speciesShareTrend`／`speciesYears`＋`speciesMonths` | 同名。`caveats` は `facetsForOccurrence`、`provenance.tables` は `summary_group_year` 等の実際に読んだ表 | `vernacular_label_rule`（share の `label`）・`month_cell_membership` |
| AI `get_redlist` | `redlistSummary`・`redlistFlows`・`redlistSpecies` | `assessment.ts`。`tables: ['taxon_assessment']` | なし |
| AI `get_overview` | `overviewStats`・`watershedRollup` | `overviewStats` の生物以外の列＋`occurrenceTotals`（`n_org`/`n_species`）、流域は D2 の混成（`org_n` 順位が変わりうる）、`outside_watershed_n` を足す。`caveats` は `caveatKeysForTables`（生物以外）∪ `caveatKeysForFacets(facetsForOccurrence)` | `undated_excluded`・`watershed_memo` |

AI の入力 `binoms` は `.max(100)` を足す（lib は 1,000 で例外）。`describe_schema`/`table-meta.ts` に summary 4表の説明を足す。

## 3. 値が動く点の全列挙と serving-diff での数え方

serving-diff の道具（`serving_queries.yaml` の `known`、`classify.ts` の `explainColumnChain`）は PR-2 のまま使う。**新しい規則は5つ、新しい問い合わせ ID は 16 個。**

### 3.1 新しい既知の系統（規則）

| 規則 | 動く点 | 実測 | 説明の鎖（独立な中間点） |
|---|---|---|---|
| `watershed_memo` | v1 は「バケット（緯度経度3桁）の代表記録の流域」を全記録に使う（ADR-0026）。v2 は記録自身の流域 | `org_watershed_year`: n/alien/redlist が動く 1,085 キー（値差 992・v1 のみ 54・v2 のみ 39）、b08 の宣言は moved records 11,306・mixed buckets 741・vs-exact キー 1,091（species_n を含む数え方）。`watershed_rollup`: `org_n` が動く流域 185/287（Σ\|差\|＝16,062）、`org_redlist_n` 44（79）、`org_alien_n` 48（81）。v2 の合計は 733,341＋流域外 83,515（v1 の合計は 732,707） | v1 →(memo)→ **`org_watershed_year_exact`/`org_watershed_exact`**（`v1_projection_occurrence.sqlite`。b08 が L2 から別 SQL で組む。**無ければ b08 を1回回す**、115 秒）→(=)→ v2。v1→exact の段が `watershed_memo`、exact→v2 は一致が要る（一致しなければ unexplained） |
| `species_n_definition` | `org_watershed_year.species_n`: v1＝学名全文の DISTINCT／v2＝`taxon_id` の DISTINCT | n/alien/redlist が同じで species_n だけ違うキー 138（全体で species_n が違うのは 1,061。binom 定義にすると 2,809 に増えるので `taxon_id` を採る） | 同じキーを L2（`occurrence`）から `COUNT(DISTINCT scientific_name)` と `COUNT(DISTINCT taxon_id)` で再計算し、前者＝v1・後者＝v2 を確かめる |
| `month_cell_membership` | v1 の月は `substr(observed_on,6,2)`（記録ごと）。v2 の月セルは「同一月に収まる記録」だけ（ADR-0024）、'Z' の記録は地域の UTC オフセット換算 | `species_month` 9,997 キー中 19 キー・12 種・Σn −140（上限は PR-3a の 838。内訳: 月をまたぐ日区間の 157 記録、'Z' で月がずれる約 10 記録） | L2 `occurrence` の `period_raw`/`period_start`/`period_end`/`period_grain` から、キー（binom, 月）ごとに「v1 が入れて v2 が入れない件数」−「v2 が入れて v1 が入れない件数」を独立 SQL で数え、v1＋差＝v2 を確かめる |
| `vernacular_label_rule` | 表示名（D4）。種の名前の選び方が変わる | §1 の表 | registry の `taxon`・`vernacular_ja.csv`・`summary_taxon_catalog` から期待ラベルを serving-diff が再計算（lib を通さない）。v2 のラベルが再計算と一致するときだけ説明。**カテゴリ別の件数（`label_moved`）をレポートに出す**（日→日・中→日・日→英・日→学名・英→英…） |
| `undated_excluded` | `occurrence_agg` は日付ありの分割。日付の無い記録は生物レコード数・gbif/inat 数に入らない | 823,692→816,856（−6,836）、gbif 658,360→651,768（−6,592）、inat 165,332→165,088（−244）。種数 23,618・メッシュ（窓内）4,083 は不変 | `ryuiki.sqlite` の `organism_records` から `observed_on` が NULL または 4 桁未満の件数を source ごとに数え、v1−v2 と一致を確かめる |

`declared`（`expected_diffs.yaml` の `species2`: Sirosporium celtidis の `cls`）は `species_catalog` で使う（v2 は `taxon.class` の決定論的なタイブレークで Dothideomycetes、v1 は Sordariomycetes）。**v1 = v2 になる問い合わせ**（表の「なし」）は `known` を空にして、1件でも差が出れば unexplained にする。

### 3.2 新しい問い合わせ ID（`serving_queries.yaml`、v1 は `queries.ts` を無変更で呼ぶ）

| id | key | 比較列 | 既知の系統 |
|---|---|---|---|
| `effort_years` | year | n, species_n, mesh_n, n_inat, n_gbif | （なし） |
| `taxon_group_years` | year, taxon_group | n, mesh_n | （なし） |
| `species_catalog`（v1 は limit 無制限で全 23,618 行。タイブレークで境界の行が食い違わないよう上位 N は比べない） | binom | n, n_red_list?, y_from, y_to, n_years, mesh_n / label: taxon_group, cls, family, label | `declared`（Sirosporium）、`vernacular_label_rule` |
| `species_labels`（v1 `NAME_JA ?? en_name ?? binom` vs v2 `speciesLabels`） | binom | label: label | `vernacular_label_rule` |
| `species_years`（params: binom。n≥80 の 1,702 種） | year | n, mesh_n | （なし） |
| `species_months`（同 1,702 種） | month | n | `month_cell_membership` |
| `species_mesh_years`（同 1,702 種） | year, mlat, mlon | n | （なし） |
| `species_share_trend`（params: group×期間 2 組） | binom | n_a, n_b, total_a, total_b / label | `vernacular_label_rule` |
| `mesh_all` | mlat, mlon | n, rl_n, species_n, rl_species_n | （なし） |
| `mesh_by_year`（params: year 1970〜2026） | mlat, mlon | n, species_n, rl_n | （なし） |
| `ias_species` | ias_category, binom | n, mesh_n, y_from, y_to, n_since_2020 / label: name_ja, taxon_group | （なし） |
| `redlist_summary`／`redlist_flows`（params: list_year×group）／`redlist_species`（同） | list_year, … | n／n／（順位など） | （なし） |
| `biota_totals` | （1行） | records, species, mesh, gbif, inat | `undated_excluded` |
| `watershed_rollup`（本番経路。v1 `watershed_rollup` の `org_*` vs `watershedOccurrence`） | watershed_id | org_n, org_alien_n, org_redlist_n | `watershed_memo` |
| `watershed_year`（セル検証。v1 `org_watershed_year` vs `watershedYears`） | watershed_id, year | n, species_n, alien_n, redlist_n | `watershed_memo`、`species_n_definition` |

v1 側の「束ね」は PR-2 の `*_by_variable` のような束ねが要らない（binom は v1 のキーそのもの）ので `merge-v1.ts` は触らない。

### 3.3 変異（`--mutate`）の追加

| 変異 | 種別 | 何を狂わせるか | 期待 |
|---|---|---|---|
| `memo_rule_off` | 分類器 | `watershed_memo` を無効化 | `watershed_rollup`/`watershed_year` が unexplained>0 |
| `species_n_rule_off` | 分類器 | `species_n_definition` を無効化 | `watershed_year` が unexplained>0 |
| `month_rule_off` | 分類器 | `month_cell_membership` を無効化 | `species_months` が unexplained>0 |
| `label_rule_off` | 分類器 | `vernacular_label_rule` を無効化 | `species_labels`/`species_catalog`/`species_share_trend` が unexplained>0 |
| `undated_rule_off` | 分類器 | `undated_excluded` を無効化 | `biota_totals` が unexplained>0 |
| `label_wrong` | 行（v2） | v2 の1ラベルを、再計算と食い違う別の名前に差し替える | **規則が有効でも** `species_labels` が unexplained>0（規則が「ラベルが何でも説明する」穴になっていないことを見る） |
| `drop_species_rows` | 行（v2） | v2 の `species_years` の1種ぶんを落とす | row_only_in_v1 → unexplained>0 |
| `inflate_n` | 行（v2） | `effort_years`・`mesh_by_year`・`ias_species` の n に +1 | 説明できる規則が無い → unexplained>0 |
| `month_off_by_one`（既存を `species_months` にも適用） | 行 | 月を1つずらす | unexplained>0 |

`rowMutationAppliesTo` の宣言表（`mutations.ts`）に上の対象 ID を足す（表に無い名前は「全問い合わせに効く」になるので、`inflate_n` 等は必ず対象を書く）。

### 3.4 受け入れ表（PR 本文に貼る）

| # | コマンド（重い検証、PR 直前に1回） | 期待 |
|---|---|---|
| 1 | `pnpm run serving:diff --v1compat-db data/db/v2_v1compat.sqlite --mutate all`（imputation は zero。生物系は imputation に依らないので lod の再実行は不要。PR-2 の測定値系 26 問い合わせの回帰も同じ実行で見る） | 既存 26＋新規 16 の全問い合わせで `unexplained=0`・rotten=0。全変異が OK（§3.3 の期待どおり落ちる） |
| 2 | レポート `reports/serving_switch_diff.md` に、規則ごとの `moved`（キー数）を出す | `watershed_memo`＝§3.1 の値、`month_cell_membership`＝19 前後、`vernacular_label_rule`＝§1 のカテゴリ別、`undated_excluded`＝1 行、`species_n_definition`＝138 前後。**「差 0」の問い合わせ（effort/group/mesh/ias/redlist/species_years…）は 0 のまま** |
| 3 | `.venv/bin/python3 scripts/b00_run_full_gate.py` | 33 表 一致25／宣言のみ8／不一致0／宣言済み差分20（b08/b02 は無変更）。`reports/full_gate_proof.json` を一緒にコミット（`aggregations/`・`scripts/registry/`・`scripts/schema_registry.sql`・`scripts/b13_*` に触れるため） |
| 4 | `cd web && pnpm run db:reset`、画面と AI のスモーク | summary 4表が seed され、/biota 4 タブ・/map・home・AI 3 ツールが動く |
| 5 | `pnpm test`・`npx tsc --noEmit`・`pnpm lint`・`pytest scripts/tests -q`（`test_s04_*` の証明鮮度だけは b00 後に緑） | 緑 |

## 4. 性能

実測は Python `sqlite3`（コールド、`taxon` は registry を ATTACH、索引は D1 と同じ）。D1 の 1 クエリ 1 往復・バインド 100 個の制限は `json_each(?)` 1 個で回避（`queryChunked` は GROUP BY を伴う集計に使えないので使わない）。

| 問い合わせ | 時間 | 返る行 | 備考 |
|---|---|---|---|
| 種カタログ上位300（`taxon`⋈`summary_taxon_catalog`、binom 束ね） | 107〜140ms | 300 | summary_species_catalog なら O(1)（D1 採用後は 1ms 級） |
| speciesYears 1／5／10 種（`INDEXED BY ix_occurrence_agg_taxon_period`） | 20／81／146ms | 35／164／328 | **INDEXED BY 無しは 100 秒超** |
| speciesMonths 5 種 | 75ms | 60 | 同上 |
| speciesMeshYears（最多の種） | 21ms | 2,591 | 同上 |
| 300 種の n_years/mesh_n（binom 厳密） | 956〜1,495ms | 300 | これが種カタログに summary_species_catalog が要る理由。UI の読み手は無いが API `kind=list` を O(1) に保つ |
| meshByYear（2022） | 62ms | 1,452 | `ix_occurrence_agg_kind_grain_period` が正しく効く（計画を確認済み） |
| speciesShareTrend 鳥類／被子植物 | 270／277ms | 84／21 | 同索引で期間範囲を引き、taxon で束ねる |
| IAS 171 種の n_since_2020・mesh_n・年範囲 | 167ms | 171 | v1 と n・mesh_n・y_from・y_to が一致（2 種の差は同じ binom が2カテゴリに載る重複の畳み方の違いで、実装では (category, binom) で返す） |
| **全表走査（summary が要る理由）** | 年×分類群 1.7〜2.0s／effort 0.8〜2.2s／mesh_all 1.1s＋mesh_species 2.3s | 1,166／57／4,083／4,086 | 画面の初回表示で 3 本直列になる。summary 化で各 ≤10ms |
| watershed×year 全体 | 1.8s | 10,684 | `watershedYears` は画面に出ないので問題なし（serving-diff だけ） |

1 画面あたりの D1 問い合わせ数（summary 化後）: /biota 努力量＝3（group_year・effort・totals）／増減表＝1〜2／種の推移＝2（years・months）／メッシュ＝1／外来種＝1（＋種を選ぶと mesh 1）／レッドリスト＝2〜3／/map メッシュ＝1／/map 流域＝2（`watershedOccurrence`＋v1 `watershedRollup`）／home 生物部分＝3。いずれも 1 本 ≤300ms。**生物系の taxon 引き・place 引きの SQL は全部 `INDEXED BY` を付ける**（place 引きは `ix_occurrence_agg_place_period`）。D1 の行読み取りは増減表・メッシュ年で 10 万〜50 万行／回だが、画面が年1回選ぶ操作なので問題ない（月 25 億行の込み枠に対して）。容量は summary 4表で +3MB 程度。`db:reset` の rows written は +約 3 万行。

## 5. 作業の分け方

### 5.1 並行単位（worktree、ファイル衝突なし）

| 単位 | 触るファイル | 読むべき節 | 依存 |
|---|---|---|---|
| **U1 パイプライン＋registry** | `aggregations/serving.yaml`、`scripts/b13_build_summary.py`、`scripts/migrate/common.py`（`SUMMARY_SPEC_VERSION` v3・`V2_SUMMARY_TABLES` を8表に）、`scripts/check_v2_fresh.py`（必要なら）、`scripts/registry/build_taxon_assessment.py`・`scripts/schema_registry.sql`（`binom` 列）、`registry/taxon/vernacular_ja.csv`（D4）、`web/src/db/schema-cube.ts`（summary 4表）・`web/src/db/schema-registry.ts`（`binom`）、`web/scripts/lib/registry-codegen.mjs`・`build-registry-ts.mjs`・`web/src/lib/registry/generated*.ts`（再生成）、`scripts/tests/test_b13_build_summary.py`・`test_registry_taxon*.py`・`test_cube_index_parity.py` 周辺 | 本書 §2.1・§2.4、`V2_SERVING_PR3A.md` §5・§6・§9、`V2_SERVING_PR2.md` §4 | なし |
| **U2 `lib/cube`** | `web/src/lib/cube/{catalog,occurrence(新),assessment(新),caveats,index}.ts`、`__fixtures__`、各 `.test.ts`、`web/src/lib/registry/lookup-client.ts`（`speciesLabel` の第2引数） | 本書 §2.2・§2.3・§4、`V2_SERVING_PR2.md` §2.1 | U1 の列名（§2.1 で合意済み）。**最初のコミットで型だけ出す** |
| **U3 画面/API/AI** | `web/src/app/api/biota/route.ts`、`api/geo/mesh/route.ts`、`api/geo/watersheds/route.ts`、`app/page.tsx`、`components/biota/BiotaExplorer.tsx`、`components/HomeHighlights.tsx`、`components/map/MapPage.tsx`（必要なら）、`web/src/lib/ai/tools.ts`（3 ツール）・`ai/links.ts`・`page-context.ts`、`web/src/lib/table-meta.ts` | 本書 §2.5・§2.3 | U2 の型 |
| **U4 serving-diff** | `web/serving_queries.yaml`、`web/scripts/lib/serving/{adapters-v1,adapters-v2,classify,mutations,report,normalize}.ts`＋各テスト、`web/scripts/serving-diff.mts`（ドメイン `binom_n80`・`group`・`list_year`・`year`）、`reports/serving_switch_diff*` | 本書 §3、`V2_SERVING_PR2.md` §3・§8.4 | U2 の公開関数 |

統合順: U1 → `cd web && pnpm run build:v2` を**1回**（registry の `binom`・summary が新鮮になる。b08 の `org_watershed_year_exact` は `b08` を単独で1回）→ U2 → U3 ‖ U4 → §5.4 のチェック → 重い検証。`pnpm run db:generate` は統合者が1回（`0008_*`、summary 4表＋`taxon_assessment.binom`。**NOT NULL 列に既定値なしで ALTER しない**、PR-3a の教訓）。担当エージェントは `drizzle/migrations` を触らない。

### 5.2 各単位の速い検証（秒〜1分）

- U1: `pytest scripts/tests/test_b13_build_summary.py scripts/tests/test_registry_taxon_assessment.py scripts/tests/test_cube_index_parity.py scripts/tests/test_check_v2_fresh.py`（フィクスチャのみ）。b13 の実データ実行は1回だけ、4表の行数（23,618／≈1,200／≈230／4,086）と保存則の出力を目視。
- U2: `pnpm vitest run src/lib/cube`（フィクスチャ）。**EXPLAIN の固定テスト**（taxon 引きが `ix_occurrence_agg_taxon_period`、メッシュ年が `ix_occurrence_agg_kind_grain_period` を使うこと）。実 DB の統合テストは `effort`/`mesh_year` の1年・1種だけ。
- U3: `pnpm exec tsc --noEmit`・`pnpm vitest run src/lib/ai`・`pnpm run dev` で /biota（努力量・増減・外来種・レッドリスト）と /map の目視。
- U4: `pnpm vitest run scripts/lib/serving`・`pnpm run serving:diff --only effort_years,species_labels,watershed_rollup`（数十秒）。

### 5.3 PR 直前に1回だけ回す重い検証

§3.4 の 1〜5 の順（b00 の後に `test_s04_*`）。メインが裏で1回回し、エージェントには待たせない。/code-review と /simplify は同時に回して指摘をまとめて直し、直した箇所だけ再確認する。

### 5.4 統合の最初のチェックポイント「検証が本番の経路を通っているか」

自動1件＋レビュー6項目（PR-2 §8.4 の生物系版）。

- 自動: `adapters-v2.test.ts` に「`adapters-v2.ts` のソースに `occurrence_agg`/`summary_`/`taxon_assessment` の文字列が無い（生 SQL を持たない）」を足す。
- レビュー: (1) `adapters-v2.ts` の生物系の全 `case` が §2.2 の公開関数だけを呼び、画面・API・AI と**同じ関数・同じ既定値**（窓 1990〜2026・n≥80・`records` の定数）で呼んでいる対応表を PR 本文に貼る。(2) 表示名の選び方は `speciesLabels` の1箇所で、`species_labels`・`species_catalog`・`species_share_trend`・UI が全部そこを通る。(3) 期待値の再計算（`watershed_memo`/`month_cell_membership`/`vernacular_label_rule`/`undated_excluded`）が `lib/cube` を import していない（正解を v2 で作らない）。(4) `INDEXED BY` が `occurrence.ts` の全 taxon 引き・place 引きにあり、EXPLAIN テストが緑。(5) `check_v2_fresh.py` が summary 4表の無い（PR-3a 時点の）`v2.sqlite` を exit 10 にする（手で1回）。(6) `seed-d1-local.mjs` の入力に v1compat が無く、summary 4表の列が `schema-cube.ts` と完全一致している（seed の完全一致検査）。

## 6. 危険・未決事項

1. **第3索引によるプランナの誤選択**（§0-2）。`INDEXED BY` とテストで塞ぐ。D1 では `ANALYZE` を当てられないので計画はクエリ文面で決める。`INDEXED BY` は索引が無いと実行時エラーになるので、索引名は定数 1 箇所にして `test_cube_index_parity.py`・Drizzle の索引名と一致させる。
2. **b13 が registry を読む**（D1）。実行順は r01 → … → b13 で既に registry が先。CI の `sample-gate` は `--files-only` の registry を使うが、`taxon` の `canonical_binomial`/`taxon_group` は `ryuiki.sqlite`（サンプル）から作るので、サンプルで b13 が通るか U1 が最初に確かめる（通らなければ `data/sample` に `taxon` の再現を足す、または b13 の join を registry の有無で縮退させず**止める**）。`s01` の再実行が要るなら `declaration_counts.yaml` は手で編集しない。
3. **`taxa` 由来の地域・亜種名**（D4）。上書き 2 件では塞がらない同種（伊豆諸島のニホントカゲ・シラホシハナムグリ名義タイプ亜種・伊豆諸島などのアズマヒキガエル…）が n<80 にある。U1 が `vernacular_ja_basis='taxa'` かつ名前に「島」「亜種」「の」＋種名を含むものを数え、n 上位を `vernacular_ja.csv` に足す（全件の自動除外はしない）。優先順位を `override > records > taxa` に変える案は、`taxa` 35 件の食い違いのうち「ベニバナノツクバネウツギ」のような正式名が負けるので採らない。
4. **v1 の癖を保つもの**: `taxonGroupYears` の `mesh_n` は source 別の MAX（和集合ではない）。`mesh_all` の窓と `mesh_species` の窓なしの非対称。`species_month`/`species_mesh_year` の n≥80 足切り。いずれも「v1 と一致」を守るため保ち、直すなら別の変更として値の動きを数える。
5. **`watershed_year` の読み手が serving-diff だけ**。画面の経路検証にはならないが、b07/b08 が既に cells＝exact を毎ビルド検証しており、本番経路の `watershed_rollup`（summary 経由）が通っていれば足りる。`watershedYears` を残すか、PR-4 まで外すかは U2 が判断してよい（外す場合 `watershed_year` は L2 からの再計算との比較に切り替える）。
6. **`taxon_group` が複数ある binom 22 件**（taxon ごとの group が割れる）: v1 は `MAX(taxon_group)`。`summary_species_catalog` は MAX、`summary_group_year` は taxon 単位（v1 の `org_group_year` は記録単位でこれと一致を実測済み）。両方を保つ。
7. **`class`/`family`**: Sirosporium の 1 件（declared）以外に `family` が割れる binom が 1 件ある。`species_catalog` で最初に出たら宣言を足す前に原因を見る（`declared_rot` の対象にする）。
8. **ADR 追記**: ADR-0026（流域のメモ化の退役）・ADR-0019（D4 の採否）・ADR-0011（summary 4表の追加と registry join の但し書き）・ADR-0029（5規則）。`docs/plans/V2_SERVING.md` の PR-3b 節の状態を更新（U4 が担当）。
9. **本番へは出さない**（v1 撤去が終わるまで本番にデプロイしない）。D1 への投入は PR-5。

---

## 付録: 実測の記録（2026-10-05、読み取り専用）

**再現（v1 表 vs セル。年は `substr(period_start,1,4)`、窓 1970〜2026、grid01×{year, survey_period}）**

```
species_year2   116,899 / 116,899  差0（n, mesh_n=binom 単位の DISTINCT place）   v2 SQL 2.8s
mesh_year        37,043 /  37,043  差0（n, species_n=DISTINCT canonical_binomial, rl_n）  2.0s
mesh_all          4,083 /   4,083  差0                                                     1.1s
mesh_species      4,086 /   4,086  差0（species_n, rl_species_n）                           2.3s
species_mesh_year 276,163 / 276,163 差0（n≥80 の種）                                       2.9s
effort_year          57 /      57  差0（species_n は canonical_binomial）                  2.2s
org_group_year    1,166 /   1,166  差0（taxon_id NULL は '未判定' に畳む。畳まないと 31 キーが割れる）  2.0s
species2 vs summary_taxon_catalog（binom 束ね）: 23,618 行、n・y_from・y_to・taxon_group が全行一致（n_years/mesh_n は taxon 単位の合算ができない: binom の 6,456 件が複数 taxon）
species_month     9,997 / 9,997   n が違うのは 19 キー（12 種）、Σn 388,983→388,843   1.4s
org_watershed_year 10,699(v1) / 10,684(v2): v1 のみ 54・v2 のみ 39・値差 1,130（n 989・species_n 1,061・alien 78・redlist 61）
  species_n を binom 定義にすると 2,809 キーが動く（taxon_id 定義 1,061）
watershed_rollup: 287 流域。org_n 185 流域が動く（Σ|差| 16,062）、redlist 44（79）、alien 48（81）。v2 合計 733,341＋流域外 83,515
redlist_change   2,884 行: taxon_assessment＋redlist_category.yaml から全列（cur/prev の label/code/rank・direction・名前・分類群・科・national）一致
ias_species        173 行: taxon_id 結合は 50 行（binom 結合は 173 行・n・mesh_n・y_from・y_to・n_since_2020 全一致）
```

**種数の定義の差（`taxon_id` を採った場合）**: `effort_year.species_n` 57/57 行が動く（比の中央値 1.078・最大 1.411、2010年 1,732→1,859、2024年 5,460→7,475）、`mesh_species.species_n` 2,088/4,086 セル（Σ 318,996→367,394）、`org_group_year.species_n` 333/1,166 行。

**窓と日付**: 年 1800〜2026。1970 未満・2026 超のセルは 23,353（33,859 件、1,067 グリッド）。日付無し記録 6,836（`organism_records` 823,692 と `occurrence_agg` の合計 816,856 の差）。source 別: gbif 658,360→651,768、inat 165,332→165,088。

**表示名（D4）**: binom 23,618／n≥80 1,702／増減表既定 138／IAS 171。分類別の v1 の名前: 日本語 11,662・ラテン文字 4,449・漢字のみ 230・学名のみ 7,276・その他 1。補完込みの v2: 日本語 10,758・ラテン文字 4,518・学名のみ 8,342。補完なしの v2: 日本語 760・ラテン文字 6,555・学名のみ 16,303。taxon の `vernacular_ja_basis` 内訳: override 54・records 12,024・taxa 8,570・NULL 20,806（PR-3a 統合後）。同じ binom の taxon が別々の和名を持つ n≥80 の binom は 334。`species` 階級優先の代表選び（件数優先との差 46 件・n≥80）は件数の少ない種の名前（Acer mono フタゴヤマ等）が勝つ例があるので採らず、件数最大を採る。

**性能**: §4 の表。`json_each(binoms) JOIN taxon JOIN occurrence_agg`（INDEXED BY 無し）は 100 秒超で打ち切り。計画は `SEARCH a USING INDEX ix_occurrence_agg_kind_grain_period (place_kind=? AND grain=?)` → `SEARCH t USING INDEX sqlite_autoindex_taxon_1`。`INDEXED BY ix_occurrence_agg_taxon_period` の 300 種 binom 厳密集計は 1.5s。

**手元の生成物**: `data/db/v1_projection_occurrence.sqlite` は 13 表のみで `org_watershed_year_exact`/`org_watershed_exact` が無い（b08 の旧版）。`watershed_memo` の鎖を回す前に b08 を単独で1回（約 115 秒）。`v2.sqlite` は PR-3a の summary 2表だけ（4表は U1 後）。

---
## 設計責任者の決定（2026-10-05）
- D1〜D3 は推奨どおり採用。**D4 はオーナーが「使う」と決定**（記録由来の和名補完を表示名に使う。タヌキ・カブトムシの上書き2件を足し、§6-3 の洗い出しを U1 で行う）。
- 並行: U1 と U2 を同時に始める（U2 は §2.1 の列名で書き、型を最初にコミットする）。U3・U4 は U2 の型が出たら同時に始める。
- 全担当共通: スキル（/simplify・/code-review 等）やサブエージェントを起動しない。重い検証（build:v2 の全量・b00・serving-diff の全量・CI 再現）は回さない。`drizzle/migrations` を生成・コミットしない。worktree には原本だけを1ファイルずつ symlink し、生成物は worktree 内に書く。`git add -A` を使わない。
