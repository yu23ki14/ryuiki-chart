# 奄美 Step 2a: 鹿児島県レッドリストと県条例の指定種（Issue #89）

鹿児島県の赤リスト（平成26年改訂）と県条例の指定希少野生動植物（59種）を取り込む。奄美の出現記録の赤リスト判定は、「鹿児島県版 → 環境省の全国版」の順で付ける。

## 0. 決定（2026-10-10）

1. **県条例の指定種は「赤リスト該当」に含めない**（オーナー決定）。評価の台帳（`taxon_assessment`）に新しい種類 `designated` で持つ。
2. **県版と全国版のどちらで判定したかは別の列に持つ**（オーナー決定）。カテゴリーの文字列は変えない。
   - 新しい列は `organism_records.red_list_source`。値は判定に使った list_id か、全国版を表す値。
   - 神奈川の記録には、今の判定の出典（神奈川県版か全国版か）を入れる。`red_list_category` の値は1件も変えない。
3. **ライセンス**: 県のサイトは「無断転載・改変不可」。種名とカテゴリーという事実だけを抜き出し、出典を明記する（Step 0 の決定）。
   - PDF の原本は `data/raw/`（gitignore 済み）に置き、再配布しない。
4. **版の名前**: `list_year` は 2014 にする。名前は「鹿児島県レッドリスト（平成26年改訂。動物・植物の掲載ページは平成27年度改訂）」。PDF の更新日 2021-11-02 は取得の記録として残す。
5. **亜種は三名法のまま照合する**（亜種名を落とさない）。二名法への縮約は別の PR にする。
6. **件数の検算で止める**: PDF の見出しにある件数と、読んだ行数が一致するまで assert で止める。手で直さず、読み取りの規則を直す。植物で2行の差があり、その原因を特定する。
7. 条例の PDF には指定日の列が無い。指定日の列は作らない。
8. GBIF の学名照合（c24）には、今回は足さない。まず PDF の学名で完全一致させて、件数を出す。

## 1. PDF の実際の構造（設計担当が取得して確認）

### 動物（24ページ）
- URL: `http://www.pref.kagoshima.jp/ad04/kurashi-kankyo/kankyo/yasei/reddata/plant-list4.html` → `documents/53565_20211029173904-1.pdf`
- 構造は「分類群名」→「カテゴリー（n）」→ 1行1種の「和名学名」。和名と学名の間に空白が無い。
- 件数は 802 行（Ⅰ類 184／Ⅱ類 191／準 352／DD 75）。見出しの件数と一致した。

### 植物・藻類（57ページ）
- URL: `plant-list3.html` → `documents/53564_20211029183322-1.pdf`
- 学名のあとに著者名が付く。Ⅰ類は「I 類」のように、ラテン文字と空白で書かれている。
- 件数は 2,010 行。見出しの合計（612／448／806／142）に対して、Ⅱ類と準で1行ずつ多い。

### 両方に共通
- 罫線が無いので、pdfplumber の `extract_text()` で行ごとに読む。
- カテゴリーは4つだけ（絶滅危惧Ⅰ類 → `CR+EN`、Ⅱ類 → `VU`、準絶滅危惧 → `NT`、情報不足 → `DD`）。
- 亜種・地域個体群・注記は、和名の括弧書きで表されている（例: `ミナミメダカ（琉球型）`）。
- 同じ学名が複数の行に出るので、重複の判定は (和名, 学名, カテゴリー) で行う。
- `sp.` や、行をまたぐ和名は、学名を空にして和名だけ残す。

### 条例（1ページ）
- 列は「分類・和名・学名・科名・県カテゴリー」の5つ。
- カテゴリーが「－」の1件（ドウクツベンケイガニ）は、`category_code` を NULL にする。

## 2. 担当 A（収集）

触るファイル:
- `scripts/c29_kagoshima_redlist_2014.py`（新規）
- `scripts/c29b_kagoshima_ordinance_species.py`（新規）
- `docs/LICENSE_MATRIX.md`
- `scripts/tests/test_c29_*.py`

作るもの:
- `data/processed/kagoshima_redlist.csv` と `kagoshima_ordinance_species.csv`。
  - 列は `kanagawa_redlist.csv` と同じにし、`scientific_name_raw`（著者付きの原文）を足す。
  - 学名は、属・種小名・亜種小名のラテン語トークンだけにする。著者名は `scientific_name_raw` に残す。
- `national_category_ja` は、`moe_redlist.csv` と学名が完全に一致したものだけ埋める。
- `register()` で出典を登録する。ライセンスの欄は「事実のみ抽出・出典明記」。

テスト:
- 行の切り分け（和名と学名・著者名・括弧・字形）を単体テストで確かめる。PDF そのものは使わない。

## 3. 担当 B（取り込みと地域ごとの赤リスト）

触るファイル:
- `scripts/c28_redlist_assessments.py`
- `registry/taxon/assessment_list.yaml`
- `registry/taxon/redlist_category_alias.csv`
- `scripts/registry/build_taxon_assessment.py`
- `scripts/regions.py`
- `scripts/m03_organisms.py`
- 原本 `organism_records` の DDL（`red_list_source` 列）と、v2 の b06 の持ち込み
- `web/scripts/build-registry-ts.mjs`
- `web/src/lib/cube/assessment.ts`
- テスト

変更点:
- **list_id**: `kgrl2014`（kind `red_list`、region `jp-46`）と `kgord`（kind `designated`、region `jp-46`）。
  - assessment_id は `kgrl2014_00001` の形にする（`split("_",1)[0]` で list_id を取る既存の規則に合わせる）。
  - `_KNOWN_REGIONS` に `jp-46`、`_KNOWN_LIST_KINDS` に `designated` を足す。
- **c28**: 鹿児島の分を `redlist_assessments` に入れる。新しい表 `pref_redlist_lookup(region_id, taxon_id, list_id, category_ja, category_code)` も作る。
  - `taxa` は変えない（c25 は全件作り直しなので、神奈川の数字を守るため）。
- **regions.py**: 地域ごとに、県の赤リストの引き方を宣言する。神奈川は今の `taxa` の列、奄美は `pref_redlist_lookup` の `kgrl2014`。
- **m03**: `taxa_lookup(conn, rid)` を地域ごとにする。
  - 神奈川は今と同じ `rk or rn`。
  - 奄美は「県の表 → 無ければ全国版」。
  - 文字列の形は c25 に合わせる。`red_list_source` も一緒に返す。
  - 条例の種は入れない。
- **web の assessment.ts**: `redlistSummary`/`changeRows` は、list の region が `jp-14` のものだけで今の出力を保つ。地域で絞るのは #93。
  - `ASSESSMENT_LIST` に region を出す。
- **キューブ**: `red_list_source` を b06 の occurrence まで持ち込むかは、既存の列の扱いに合わせる。
  - D1 の表に出るなら、Drizzle のスキーマと migrations を作り直す。
  - 出さなくても、MCP の `get_records` などで引ける場所があれば、そこまでは通す。

## 4. 神奈川を変えないことの固定

1. m03 を変える前に、原本から基準を作る。
   - 神奈川の2出典の `(record_id, red_list_category, publication_scope)` を並べた SHA-256 と、件数。
   - 現状で赤リスト該当は GBIF 3,769件、iNaturalist 1,239件。
2. 変えた後に m03 を回し、同じハッシュになることを確かめる。
3. `occurrence_agg` の `n_red_list` を地域別に比べる。神奈川は変わらず、奄美だけが動くこと。
4. `redlist_summary`（神奈川の3つの版）が変わらないこと。
5. 奄美の変化を件数で報告する。今は 1,382 件が赤リスト該当で、そのうち 709 件は神奈川の県版だけに載る種。

## 5. 統合（実行の順）

1. c29 → c29b
2. c25（不変であることの確認）
3. c28
4. r01 → `build:registry:ts`
5. m03
6. `build:v2`
7. サンプル
8. 一時 clone での CI 再現
9. b00
