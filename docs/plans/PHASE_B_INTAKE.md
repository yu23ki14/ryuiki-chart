# Phase B 申し送り — Phase A で見つけたが直さなかったもの

対象: ADR-0016 の Phase A / 作成: 2026-09-06

**これは Phase A の作業中に出た申し送りであり、ADR の決定ではない。**
ここに書いた「Phase B でやること」はレビュー時点での推奨であって、Phase B の設計者が
状況を見て変えてよい。ADR 化が要るものはそのつど ADR を書く。

## 読み方

各項目に「なぜ Phase A で直さなかったか」と「放置すると何が高くつくか」を1行ずつ付ける。
Phase A の判断が誤りだったという意味ではない——**計画どおり「移すだけ、直さない」を守った結果**
残ったものがほとんどで、直すこと自体は Phase B 以降のスコープだった。

## 一覧

| # | 何 | なぜ Phase A で直さなかったか | 放置すると何が高くつくか |
|---|---|---|---|
| 1 | `variable_alias.source_scope` が出典（`source_edition_id`）ではなくテーブル名 | ADR-0010 決定1は `source_edition_id` を持つ設計だが、計画 §A-1 の列定義がテーブル名だったため実装もそれに従った | 20 alias が `grain='mixed'` になっている（`env_kousui_sample`/`env_kousui_annual`、`jma_daily`/`jma_monthly` が同じ alias に相乗り）。BOD の検体値行に `stat=mean` が付くなど、キューブ化（行ごとに grain/stat が要る）で誤った集計を招く |
| 2 | `caveat_scope` の `scope_kind` が `table`/`table_prefix`/`table_synthetic` のまま（ADR-0013 本来の `variable`/`place`/`source_edition`/`observation_set`/`dataset`/`taxon` になっていない） | v1 テーブルへの暫定接続として計画どおり実装した。`observation`/`occurrence` 統合（ADR-0007）はまだ無い | `observation` 統合後、v1 のテーブル名スコープが意味を失う。またテーブル→注記の対応表は `registry/` ではなく `scripts/registry/build_caveat.py` の Python 定数にあり、`registry/README.md` の「正は常に registry/」と少しズレている |
| 3 | caveat の `severity`/`kind` は Phase A で新たに付けた判断（14件、うち blocking 7件。本文の禁止表現から機械的に分類） | 消費者（応答に警告を出す仕組み）がまだ無いので、付けても挙動は変わらない | ADR-0013 決定1により blocking は将来応答の警告になる。人がレビューする前に消費者を付けると、機械分類の誤りがそのままユーザー向けの警告文になる。`cells.notes` 由来の `kind`（`footnote`/`comparability`/`survey_scope`、127件）は ADR-0013 の enum 外だが原本値のまま残してある（これは正しい判断。enum 拡張か写像は Phase B で決める） |
| 4 | `common:` スコープの place（watershed・grid）にも `region_id='jp-14'` が入っている | Phase A では place の列だけ用意し、値は既存の派生データをそのまま流した | ADR-0004 規約0（`common` の実体に地域を埋めない）と ADR-0006 の `region_id` 列の使い方が少し矛盾する。`place_relation` を作る前に「登録した地域（管理主体）」なのか「所在（地理的な位置）」なのかを定義しないと、地域フィルタが誤って `common` の実体を除外/包含する |
| 5 | 原表記スケールの単位10件（`0.1ppm`/`0.1℃` 等、`ucum=null`） | 換算しないことを `name_ja` に明記する方針（推測で埋めない）を Phase A で優先した | キューブで並べると値が10倍ずれる。alias に `scale_to_canonical` のような列を持たせて正準単位に寄せる設計が要る。相模原の OX が単位不明（`unitId=null`）のままなのは正しい判断（推測しない） |
| 6 | `domain.ts`（`VARIABLE_SHORT` 等）の完全一致テストが Phase A の間だけ正しい。`primaryAlias()` が `GENERATED_VARIABLE_ALIASES` の並び順（= CSV の行順）に依存する | domain.ts をレジストリの薄い層にする（§A-8）ところまでが Phase A のスコープで、13ファイルの利用側の書き換えは対象外 | レジストリに `name_ja`/`description_ja`/`higher_is_worse` を1つ足すと `domain.test.ts` が赤くなる（静かに壊れるのではなく、うるさく落ちる＝設計としては正しいが、語彙を育てるたびにテスト更新が要る）。`primaryAlias()` の「fiscal_year でない行を優先」ヒューリスティックも、CSV に `primary` 列が無いために行順へ依存したまま |
| 7 | `generated.ts` の陳腐化ガード（`generated.test.ts`）が CI で効かない | `data/db/registry.sqlite`（15GB の原本から作る）を CI に置けないため、無い環境では skip する設計にした（この判断自体は妥当） | そもそもこのリポジトリに CI が無いので、レジストリと生成物がずれても誰も気づかない。`r01 → build-registry-ts → git diff --exit-code` を1ジョブにする CI が Phase B で要る |
| 8 | `taxon.accepted_taxon_id` が全行 NULL | `taxa` 側 GBIF 未照合 5,908 件を捨てず `unresolved` として登録することを優先し、受理名解決は範囲外にした | 原因は `scripts/c24_taxon_crosswalk.py` が GBIF の `acceptedUsageKey` を取得しておらず、`accepted_scientific_name` 列が実は「一致したノード自身の学名」を転記しているだけだったこと。`status='SYNONYM'` 376件のうち学名が食い違う252件はすべて著者引用の有無だけの差で、別分類群への受理名解決ではない。列名と実態が食い違っており、埋めるときに誤用されうる罠 |
| 9 | `place_source_ref.source_id` が `'sites.site_id'` のような文字列リテラルで、`source_registry` の ID ではない | 「v1 を動かさずに並走させる」接続点として、既存の列名をそのまま記録する設計を計画どおり採用した | ADR-0006 は `source_edition_id` を想定している。`source_registry`/`source_edition`（ADR-0005）が実装される Phase C で置換が要る |
| 10 | GBIF 弱一致 300件（HIGHERRANK 240 / FUZZY 60）を `unresolved` に倒した | Phase A は「未解決を可視化する」ことが合格条件で、再照合はスコープ外 | 近傍の GBIF キーは `data/processed/taxon_crosswalk.csv` から `taxa.taxon_id` で引ける状態のまま埋もれている。GBIF の高次分類 API を使った再照合が Phase B でできる |
| 11 | `place_kind='grid01'` が ADR-0006 のコードリストに無い | `mesh_all` の実体が3次メッシュ（30秒×45秒）ではなく独自の0.01度グリッドだと実装時に判明し、実態に合わせて改名した（`mesh3` のまま偽って登録するより正直な選択） | ADR-0006 のコードリストにコードを足すか、実体を本物の3次メッシュに作り直すかを Phase B で決めないと、`place_kind` のコードリスト運用が形骸化する |
| 12 | `<出典名前空間>` と `<local>` の区切りが同じ `-`（例: `jp-14:place:site.jiban-chinka-12-1`）なので機械的に分解できない | ADR-0004 の例（`env-pubwater-0142`）自体が持つ曖昧さで、Phase A の実装の問題ではない | 名前空間とローカルキーを文字列分割で取り出す処理を書くと、`-` を含むローカルキーで誤分割する。ADR 側の課題なので Phase C で ADR-0004 を改定してから直す |

## 優先度（アドバイザーの助言）

上の12件のうち、**Phase B の最初に着手すべきは #1・#6・#7**。理由:

- #1（`source_scope`→`source_edition_id`）は `(alias, source_id)` を鍵にして grain/stat を
  確定させるだけで、`lookup.ts` の `primaryAlias()` のヒューリスティックが不要になる
  （#6 の「静かな経路」も同時に塞げる）。alias 行は公開 ID ではない（autoincrement）ので
  今変えても ADR-0004 は壊れない。
- #6 の残り（13ファイルの利用側をレジストリ直読みに切り替え、`domain.ts`/`domain.test.ts` を撤去）は、
  レジストリに語彙を足すたびにテストが赤くなる運用を早めに解消する。
- #7（CI）が無いと、#1・#6 の作業自体が「生成物を再生成し忘れる」を繰り返す土台になる。

#3（severity/kind の人手レビュー）は、blocking の消費者（応答の警告）を実装する**前に**
必ず終わらせること。順序を逆にしない。

#2・#4・#9・#12 は ADR 側の議論が先に要る（Phase B の実装だけでは決まらない）。
#5・#8・#10・#11 はデータ品質の改善タスクとして独立に起票できる。
