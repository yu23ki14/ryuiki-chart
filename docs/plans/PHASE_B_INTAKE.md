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
| 1 | ~~`variable_alias.source_scope` が出典（`source_edition_id`）ではなくテーブル名~~ **解決済み（本PR、`phase-b/alias-source-key`）** | ADR-0010 決定1は `source_edition_id` を持つ設計だが、計画 §A-1 の列定義がテーブル名だったため実装もそれに従った | 20 alias が `grain='mixed'` になっている（`env_kousui_sample`/`env_kousui_annual`、`jma_daily`/`jma_monthly` が同じ alias に相乗り）。BOD の検体値行に `stat=mean` が付くなど、キューブ化（行ごとに grain/stat が要る）で誤った集計を招く。**→ 実測すると28 alias、さらに一次資料調査（`docs/plans/PHASE_B_ALIAS_STAT_SOURCES.md`）で `mixed` は0件に解消。詳細は本ファイル末尾の追記を参照** |
| 2 | `caveat_scope` の `scope_kind` が `table`/`table_prefix`/`cell`/`cell_table`（`/simplify` 指摘で `table_synthetic` は撤去し `priority` 列に分離済み）のまま（ADR-0013 本来の `variable`/`place`/`source_edition`/`observation_set`/`dataset`/`taxon` になっていない） | v1 テーブルへの暫定接続として計画どおり実装した。`observation`/`occurrence` 統合（ADR-0007）はまだ無い | `observation` 統合後、v1 のテーブル名スコープが意味を失う。またテーブル→注記の対応表は `registry/` ではなく `scripts/registry/build_caveat.py` の Python 定数にあり、`registry/README.md` の「正は常に registry/」と少しズレている |
| 3 | caveat の `severity`/`kind` は Phase A で新たに付けた判断（14件、うち blocking 7件。本文の禁止表現から機械的に分類） | 消費者（応答に警告を出す仕組み）がまだ無いので、付けても挙動は変わらない | ADR-0013 決定1により blocking は将来応答の警告になる。人がレビューする前に消費者を付けると、機械分類の誤りがそのままユーザー向けの警告文になる。`cells.notes` 由来の `kind`（`footnote`/`comparability`/`survey_scope`、127件）は ADR-0013 の enum 外だが原本値のまま残してある（これは正しい判断。enum 拡張か写像は Phase B で決める） |
| 4 | `common:` スコープの place（watershed・grid）にも `region_id='jp-14'` が入っている | Phase A では place の列だけ用意し、値は既存の派生データをそのまま流した | ADR-0004 規約0（`common` の実体に地域を埋めない）と ADR-0006 の `region_id` 列の使い方が少し矛盾する。`place_relation` を作る前に「登録した地域（管理主体）」なのか「所在（地理的な位置）」なのかを定義しないと、地域フィルタが誤って `common` の実体を除外/包含する |
| 5 | 原表記スケールの単位10件（`0.1ppm`/`0.1℃` 等、`ucum=null`） | 換算しないことを `name_ja` に明記する方針（推測で埋めない）を Phase A で優先した | キューブで並べると値が10倍ずれる。alias に `scale_to_canonical` のような列を持たせて正準単位に寄せる設計が要る。相模原の OX が単位不明（`unitId=null`）のままなのは正しい判断（推測しない） |
| 6 | `domain.ts`（`VARIABLE_SHORT` 等）の完全一致テストが Phase A の間だけ正しい。`primaryAlias()` が `GENERATED_VARIABLE_ALIASES` の並び順（= CSV の行順）に依存する | domain.ts をレジストリの薄い層にする（§A-8）ところまでが Phase A のスコープで、13ファイルの利用側の書き換えは対象外 | レジストリに `name_ja`/`description_ja`/`higher_is_worse` を1つ足すと `domain.test.ts` が赤くなる（静かに壊れるのではなく、うるさく落ちる＝設計としては正しいが、語彙を育てるたびにテスト更新が要る）。`primaryAlias()` の「fiscal_year でない行を優先」ヒューリスティックも、CSV に `primary` 列が無いために行順へ依存したまま |
| 7 | ~~`generated.ts` の陳腐化ガード（`generated.test.ts`）が CI で効かない~~ **解決済み（本PR）** | `data/db/registry.sqlite`（15GB の原本から作る）を CI に置けないため、無い環境では skip する設計にした（この判断自体は妥当） | そもそもこのリポジトリに CI が無いので、レジストリと生成物がずれても誰も気づかない。`r01 → build-registry-ts → git diff --exit-code` を1ジョブにする CI が Phase B で要る。**→ `scripts/r01_build_registry.py --files-only`（原本DB無しで unit/variable/variable_alias とファイル由来の caveat/caveat_scope だけを作る）を新設し、`.github/workflows/ci.yml` の `registry` ジョブに組み込んだ。`generated.test.ts` は CI でも registry.sqlite（`RYUIKI_REGISTRY_DB` で指すファイル）が作れるので skip されず走る。書き込み先は正規の `data/db/registry.sqlite` とは別ファイル（既定 `registry_files_only.sqlite`）にしてある——独立レビューで指摘された事故（`--files-only` が正規のレジストリを154 alias のスタブで上書きしてしまう）を踏まえた修正** |
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

## #1・#7 を解決した本PR（`phase-b/alias-source-key`）で分かった新しい事実

`variable_alias` を `(alias, source_scope)` 117行から `(dataset, alias, source_id)` 154行に
分割し、`.github/workflows/ci.yml` を新設した。作業中に判明した事実を以下に残す。

### grain='mixed' は 20 ではなく 28 だった、さらに調査で 0 になった

- 実測すると `grain='mixed'` の alias は申し送りに書いた20ではなく **28**
  （measurements 12 / sensor_timeseries 16）だった。
- `(dataset, alias, source_id)` に分割した直後の時点では、28 alias のうち23 alias
  （env_kousui_annual/sample の組み合わせ、jma_daily/jma_monthly の組み合わせ）は
  source_id ごとに書式が単一になり `mixed` が解消したが、`atsugi_river_water_quality`
  の5組（pH / BOD / COD / DO / SS）だけは同じ source_id 内で日付と年が混在しており、
  最初の実装では `grain_rule` 列（`measured_on_precision`）を新設してこの5組を
  `grain='mixed'` のまま残した。
- しかしその後、`atsugi_river_water_quality` の一次資料（原本xlsx全19本のB3セル
  「※数値は日間平均値です。」）を直接確認したところ、**この「混在」は統計量の混在では
  なく日付精度の混在**であり、統計量としては全期間・pH含む全5項目で `stat='mean'` が
  確定することが分かった。日付精度自体は `grain` が表す対象ではない（`grain` は集計の
  時間粒度であり、`measured_on` の表記精度ではない）ため、**`grain='day'` で確定し、
  `grain_rule` 列は不要と判断して作らなかった**。最終的に `grain='mixed'` の行は
  **0件**になった（詳細な一次資料と引用は `docs/plans/PHASE_B_ALIAS_STAT_SOURCES.md` §4）。

### `atsugi_river_water_quality` は月粒度まで復元できる（本PRでは着手しない）

- `measured_on` が2005年度以降「年だけ」になるのは、`scripts/m05_tier1.py` の
  `measured_on = sampled_on or fiscal_year` というフォールバックの副作用であり、
  レジストリが表すべき「値の意味」の問題ではなかった。
- `source_ref` 列（`{resource_url}#{month_label}:{site_raw}:{variable_ja}` の形、例:
  `.../kougai_kasen_r02data.xlsx#令和2年4月:相模川:pH`）には**月ラベルが全19年度×12ヶ月
  欠落なく残っている**ことを確認済み。`measured_on` の生成ロジックを直せば、原本の
  再収集なしに `grain='month'` まで引き上げられる。
- **ADR-0016 の順序どおり「v1 の再現」を先に確認してから直すこと**（Phase B の
  受け入れ基準はまず v1 の数値を再現できること。先に直すと移行の誤りと意図的な変更が
  区別できなくなる）。日付そのもの（2005年度以降の採水日）は「8〜9日」のような
  2日レンジ表記のため原本に確定情報が無く、月より細かい粒度には永久に復元できない。

### `measurements.source_id IS NULL` 2,265行は全部 `is_synthetic=1`

`(dataset, alias, source_id)` に分割する際、`source_id` が空の組が5つ出てくる
（`pH` / `気温` / `水温` / `浮遊物質量 SS` / `溶存酸素量 DO`）。実測でこの2,265行は
すべて `is_synthetic=1`（合成データ）であることを確認した。「出典未記録」という
意味であり、収集漏れではない。

### `env_kousui_sample_kanagawa`（検体値）16 alias の stat は point だが、自動モニターの日間平均値が混在しうる

環境省公共用水域水質「検体値」ファイル利用説明書より、レコード=1回の採水・分析
（`stat='point'`）であることを確定した一方、調査区分コード5/6（水質自動モニターに
よる日間平均値）が仕様上同じレコード形式で混在しうることも分かった。ダウンロードした
実データの列に調査区分コードが無く、行ごとに区別する情報が残っていない
（`docs/plans/PHASE_B_ALIAS_STAT_SOURCES.md` §3.2）。データ品質の改善タスクとして
起票できるが、原本側に区別情報が無いため収集スクリプトを直しても解決しない可能性が高い。

### 健康項目27種の列レイアウトが未確認（`cn` は特に要注意）

健康項目（cd, cn, pb 等27項目）は環境基準の評価方法（全シアンを除き年間平均値、
全シアンは最高値）が国立環境研究所の一次資料で確定したが、`zip_create` API のCSVが
項目ごとに1列しか持たず、その1列が実際にどちらの統計量を格納しているかを記載した
資料が見つからなかった。特に `cn`（全シアン）は他の26項目と異なる統計量（最高値）で
ある可能性が高いが、確認できていないため `stat` は空のまま維持した
（`docs/plans/PHASE_B_ALIAS_STAT_SOURCES.md` §2.4）。列レイアウトを確認できる一次資料
（`zip_create` API 自体のドキュメント等）が見つかれば、Phase B 以降で埋められる。

### `common:variable:hydro.flow`（`流量関連（公式定義未確認のため原表記のまま）`）の公式定義が判明（着手できる状態）

環境省 公共用水域水質**検体値**データファイル利用説明書（国立環境研究所, 平成27年4月,
`MK_manu.pdf`）の一般項目ファイルレイアウトに「流量」項目ID `090700`、単位 `m3/s` と
明記されていた。該当する `measurements` 全4,668行はすべて `env_kousui_sample_kanagawa`
から来ており、他 source_id には出現しない（`docs/plans/PHASE_B_ALIAS_STAT_SOURCES.md`
§3.3）。

- **やること**: `registry/variable.yaml` の `common:variable:hydro.flow` の
  `name_ja`（現在「流量関連（公式定義未確認のため原表記のまま）」）と `unit_id`
  （現在 `null`）と `status`（現在 `needs_review`）を確定値に更新する。
- **なぜ本PRでやらないか**: `variable.yaml` の `name_ja` を直すと `generated-client.ts`
  の `VARIABLE_SHORT` の値が変わり、本PRの受け入れ条件「`generated-client.ts` の
  差分が0行」が壊れる。これは「移行」ではなく「意図的な語彙の修正」なので別PRにする。
- 行数・出典行数（4,668行）・根拠（`MK_manu.pdf` 項目19）はすべて確認済みなので、
  次のPRはこの節を読むだけで着手できる。

### 水生生物保全項目（全亜鉛・ノニルフェノール・LAS）の環境基準は確定、API列との対応は未確認

環境省告示（別表２イ表備考「基準値は、年間平均値とする。」）で環境基準としては
年間平均値と確定したが、`zip_create` API のCSV列がその基準値と同一の集計方法で
作られていることを直接記載した資料（列レイアウト表）は見つからなかった。列名に
他の接尾辞（`_max` 等）が無いこと、生活環境項目と同じ「素の列名＝mean」パターンと
整合することから可能性は高いが、「確定」ではなく「高確度の一致」として `stat='mean'`
を維持した（`docs/plans/PHASE_B_ALIAS_STAT_SOURCES.md` §2.3）。
