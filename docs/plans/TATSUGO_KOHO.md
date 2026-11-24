# 龍郷町「広報たつごう」のデータモデル（Issue #130）

状態: 設計（コードなし）。実装は #131（取得・記事切り分け）と、#132（ベクトル検索）が依存する。
対象: 龍郷町（`jp-46`）の広報誌。月刊 175 冊、PDF 180 ファイル、2012-04〜2026-11。

## 0. 決定の要点

| # | 決めたこと |
|---|---|
| 1 | `documents` は今の意味のまま（1 PDF ファイル＝1行）。広報誌の 180 ファイルを 180 行で足す。 |
| 2 | 号は新表 `periodical_issues`（176 行＝月刊 175＋別冊 1）、号⇔ファイルは `periodical_issue_files`（180 行）。 |
| 3 | 記事は新表 `document_articles`。話題は `document_article_topics`、地名は `document_article_places`（どちらも 1 記事に複数）。 |
| 4 | 話題語彙は `registry/article_topic.yaml`（7 語）。 |
| 5 | 表の置き場は `cells.sqlite`（新 `scripts/m13_tatsugo_koho.py` が作る）。D1 へは既存の `SOURCES` 経由で、Drizzle の `schema.ts` に表を足す。 |
| 6 | 出典は `registry/source/access.yaml` に `tatsugo_koho_amami` を 1 つ。`records: [periodical_issues, document_articles]` を推奨（`documents: [180件]` にしない）。 |
| 7 | 取り下げは、版管理した除外リストを m13 が読んで原本から外し、D1 は専用スクリプトで該当行だけ消し、Vectorize は同じ記事 ID から消す。 |
| 8 | 定型の表は #131 のサンプル調査待ち。入れるなら既存の `cells`。 |

数字の確認: 2012-04〜2026-11 は 176 か月。2019-04・05 の合併号で 1 冊減って月刊 175 冊。
ファイルは 175＋分割で増える 4（2018-08・2023-07・2024-12・2026-02 が各 2 ファイル）＋別冊 1（2015-02）＝180。
Issue の数字と一致するので、これを検算に使う（§8）。別冊は月刊の 175 冊に数えず、号の表では別の行（`kind='supplement'`）にする。

## 1. 用語とモデルの全体像

```
periodical_series (1)  広報たつごう（発行者・権利・合意の原文）
        │ series_id
periodical_issues (176)         号。月刊・合併号・別冊
        │ issue_id
periodical_issue_files (180)    号 ⇔ ファイル。part_no と通しページへのオフセット
        │ doc_id
documents (+180)                1 PDF＝1行（既存。sha256・n_pages はファイル単位）
        │ doc_id
document_articles (数千)        記事。ページ範囲はファイル内と号内通しの両方
   ├─ document_article_topics   話題（registry の語彙）
   └─ document_article_places   地名（原文＋結べるものだけ place_id）
```

- 既存の `cells`・`notes`・`document_notes`・`document_cells` は変えない。広報誌の文書には `notes` を数行（ライセンスの注記）だけ足す。
- 記事は #132 のチャンクの上位単位。チャンクは `chunk_id = <article_id>#<seq>`（記事 1 に対しチャンク 1 以上）。`document_articles` にチャンクの表は作らない（#132 の持ち物）。

## 2. 識別子の規則（実装: m スクリプト）

### 2.1 doc_id（ファイル）

- 基本: `tatsugo_koho_YYYYMM`（例 `tatsugo_koho_201712`）。
- 分割ファイル: `tatsugo_koho_YYYYMM_p1`・`_p2`（番号は号内の並び順。リンク文の「前編・後編」「その1・その2」等ではなく、ファイルの並びで決める。リンク文の原文は `link_text_raw` に残す）。分割があるかは索引 HTML の同じ号に 2 リンクあるかで決める。
- 合併号（2019-04・05）: 1 ファイル。doc_id は `tatsugo_koho_201904`（若い方の月）。`periodical_issues.year_month='2019-04'`、`year_month_to='2019-05'`。2019-05 の doc_id・issue_id は作らない。
- 別冊（2015-02）: doc_id `tatsugo_koho_201502_sp1`。号の行も `issue_id='tatsugo_koho_201502_sp1'`（`kind='supplement'`）。同月の月刊号 `tatsugo_koho_201502` と衝突しない。別冊が今後増えたら `_sp2`。
- ファイル名（`koho7.pdf` 等）は ID に使わない。号はリンク文から決める（Issue の方針どおり）。保存名は `local_path` に残すだけ。

### 2.2 issue_id（号）

- 月刊・合併号: doc_id から `_pN` を除いたもの（`tatsugo_koho_201808`）。別冊は doc_id と同じ。
- 号の ID は `documents` の doc_id と名前空間が重なるが、`periodical_issue_files` で明示的に結ぶので混同しない（単独ファイルの号は issue_id＝doc_id）。

### 2.3 article_id（記事）

安定性の要件は「同じ PDF・同じ記事なら、再抽出しても変わらない／記事の切り方が変わったら ID が変わって分かる」。

```
article_id = <doc_id>:<page_from(ファイル内, 3桁)>:<h8>
h8 = sha256( NFKC(title) の空白除去 )[:8]
```

- 同じ記事なら、抽出器の版・本文の読み取り改善・分類の付け直しがあっても ID は変わらない（ID の材料はファイルと開始ページと見出しだけ）。
- 見出しが取れないとき（`kind='unsegmented'`・見出し無しの囲み）は `h8 = sha256(本文の先頭 40 文字)[:8]`。それも無ければ `h8 = 'untitled'` に同ページ内の連番を足す（`untitled2` 等）。
- 同じ ID が衝突したら m13 が止まる（黙って連番にしない）。
- 切り方が変わると（開始ページや見出しが変わる）ID が変わる。m13 は旧原本との差分を「消えた ID／増えた ID／同じ ID で `body_sha256` が変わったもの」で報告する（§8.3）。同じ ID で本文だけ変わったものは `body_sha256` の変化で気づく。
- `document_articles.doc_sha256` を持つ。PDF が差し替わった（町が号を訂正）ときは全記事で `doc_sha256` が古くなるので、検査で止める。

## 3. D1 スキーマ（実装: m スクリプト＋D1 スキーマ）

DDL の原本は `scripts/schema_tatsugo_koho.sql`（m13 が `cells.sqlite` に作る）。D1 側は `web/src/db/schema.ts` に Drizzle で同じ列を足し、`pnpm run db:generate`（マイグレーション SQL は手で書かない）。`web/src/lib/table-meta.ts` の `TABLE_ORIGIN` に `cells` 由来として追加。CLAUDE.md の「61 テーブル」「60 表」の数字は実測で直す。

### 3.1 periodical_series（1 行）

| 列 | 内容 |
|---|---|
| series_id (PK) | `tatsugo_koho` |
| source_id | `tatsugo_koho_amami`（access.yaml の出典 ID。articles/issues の `source_id` はここから） |
| title | 広報たつごう |
| publisher | 龍郷町 |
| region_id | `jp-46` |
| listing_urls | 索引 HTML の URL の JSON 配列（`idx-kohoshi.html`・`kohotatsugo.html`・`koho2020`〜`koho2026`） |
| license | 町の記載と合意の原文（§7.1） |
| agreement_note | 取り下げ依頼の連絡先は書かない。合意の日付と経緯だけ |

series を表にするのは、ライセンスと合意の原文を 1 か所に置いて `documents.license` へ複写するため。他の定期刊行物（別の町）を足すときも同じ形で足せる。

### 3.2 periodical_issues（176 行）

| 列 | 内容 |
|---|---|
| issue_id (PK) | §2.2 |
| series_id, source_id, region_id | 出典での絞り込み用（`source_id` は get_records の既定の絞り列。索引あり） |
| kind | `monthly` / `supplement` |
| year_month | `YYYY-MM`（号の月）。合併号は若い方 |
| year_month_to | 合併号だけ `2019-05`。他は NULL |
| fiscal_year | 4 月始まりの年度（`year_month` から換算） |
| issued_on | `YYYY-MM-DD`。年度ページに「○月号（○日発行）」がある令和 2 年度以降だけ。無ければ NULL（月初で補わない） |
| issued_on_raw | 「○月号（○日発行）」の原文 |
| label_raw | リンク文の原文（「広報たつごう ○年○月号」） |
| listing_url | その号が載っている年度ページの URL |
| headlines | 令和 2 年度以降の「主な記事」の見出し原文（JSON 配列）。それ以前は NULL |
| n_files, n_pages | `periodical_issue_files`・`documents` からの集計値ではなく、m13 が入れた値（検査で突き合わせ） |
| note | 合併号・別冊の説明など |

`headlines` は HTML 由来で PDF の抽出とは独立している。令和 2 年度以降は「記事の取りこぼし検算」（§8）の突合先。

### 3.3 periodical_issue_files（180 行）

| 列 | 内容 |
|---|---|
| doc_id (PK) | `documents.doc_id` |
| issue_id | 号 |
| part_no | 1 始まり。単独ファイルは 1 |
| page_offset | 号内通しページ ＝ ファイル内ページ ＋ `page_offset`。part 1 は 0、part 2 は part 1 の `n_pages` |
| link_text_raw | 分割のリンク文の原文 |
| download_url | 元 PDF の URL（`documents.url` と同じ。突合のために持つ） |

「号内通しページ」は PDF のページ番号を号の中で通したもの。紙面に印字されたページ番号（表紙が p.1 とは限らない）は持たない。出典の表記（`p.○`）は号内通しページを使い、PDF URL に `#page=ファイル内ページ` を付ける（§6.3）。見開き PDF（1 ページに 2 面）の可能性がある。#131 のサンプル調査で分かったら、`periodical_series` か `periodical_issues.note` に「1 PDF ページ＝何面」と書き、ページの数え方をここで確定する。

### 3.4 documents（既存・180 行を足す）

列はそのまま。値の入れ方:

- `publisher`＝「龍郷町」、`url`＝元 PDF の URL、`local_path`＝`data/raw/tatsugo_koho/<保存名>`、`doc_sha256`・`n_pages`・`fetched_at`＝ファイルごと、`fiscal_year`＝号の年度（分割ファイルは同じ値）。
- `title`＝「広報たつごう ○年○月号」。分割ファイルは「…（その1）」を足す。
- `license`＝§7.1 の原文（`NO_LICENSE` ではない。本文を載せる）。

### 3.5 document_articles（数千行）

| 列 | 内容 |
|---|---|
| article_id (PK) | §2.3 |
| issue_id, doc_id | 記事が載っているファイルと号 |
| source_id, region_id | 出典の絞り列・地域の絞り列（issues と同じ値の複写。Vectorize のメタデータにもなる） |
| kind | `article` / `unsegmented` / `cover_toc`（表紙・目次・奥付。話題は付けない） |
| page_from, page_to | **ファイル内ページ**（1 始まり、両端含む）。 |
| issue_page_from, issue_page_to | **号内通しページ**。`page_from + page_offset` と常に一致（検査）。出典の `p.○` に使う |
| title | 見出し（読めなければ NULL） |
| section | 紙面の区分の原文（お知らせ／特集／町長コラム 等）。語彙にしない（原文のまま） |
| body_text | 本文の全文（#130 の決定により載せる）。要約は持たない。読めないときは NULL |
| body_sha256 | 正規化した `body_text` の sha256。差分検知・#132 の埋め込みキャッシュの鍵 |
| event_dates | 記事中の日付の JSON 配列（`[{raw, iso}]`。和暦の原文を残す。年が決められないものは `iso` を NULL にする） |
| doc_sha256 | 抽出元の PDF の sha256（古さの検査） |
| extractor | 例 `pdfplumber:0.11+rule:v1`、`ocr:<engine>:<ver>+rule:v1` |
| confidence | 0〜1。切り分けと本文の自信（機械の判定）。人が直したら `verified_by` を足す列を将来足せるよう、`verified_by` も持つ（NULL可） |
| unreadable_reason | `body_text` が NULL か欠けるときの理由（`scanned_no_ocr` / `ocr_low_confidence` / `vertical_layout` 等）。推測で埋めない |
| extracted_at | 抽出の日時 |

- ページをまたぐ記事は `page_from < page_to`。1 ページに複数記事があれば、ページ範囲は重なってよい。ページごとに「どの記事にも入らない」ことは `kind='unsegmented'` のページ単位の記事で受ける（§8 の被覆検査）。
- 記事の並び（紙面の順）は `(doc_id, page_from, article_id)` で決まる。連番の列は持たない。

索引: `(issue_id)`・`(doc_id, page_from)`・`(source_id)`。

### 3.6 document_article_topics

`(article_id, topic_id, extractor, confidence)`、PK は `(article_id, topic_id)`。1 記事に 1 つ以上（`cover_toc` は 0 でよい）。`topic_id` は §4 の語彙。FK は `document_articles`。

### 3.7 document_article_places

`(article_id, place_raw, place_type, place_id, match_method, confidence)`。PK は `(article_id, place_raw)`。

- `place_raw`: 記事に出た地名の原文（「秋名」「大勝」「龍郷湾」等）。必ず残す。
- `place_type`: `settlement`（集落）／`river`／`coast`／`other`。照合の補助で、ここだけ語彙を持つ（`registry/` には置かず m13 の定数）。
- `place_id`: `place` 表に**既にある**ものだけ（`place_kind` が watershed・site・zone）。集落は `place` に無いので原則 NULL のまま。結ぶ規則は「名称の完全一致（NFKC・空白除去）で `place` の 1 件に決まるときだけ」。曖昧（同名が複数）なら結ばない。
- `match_method`: `exact_name`／NULL。推測の照合（部分一致・AI）はしない。結べない地名を増やすより、結ばないほうがよい。
- 集落を `place` に足すことは、この Issue では決めない（§10）。

## 4. 話題の語彙（実装: registry・r01）

`registry/article_topic.yaml`:

```yaml
topics:
  river_water:        {ja: 河川・水,           note: 河川・海岸の水、水質、水道、治水（防災と重なるときは両方付ける）}
  wildlife_alien:     {ja: 生き物・外来種,     note: 野生生物、希少種、外来種・マングース・ノネコ等の駆除}
  disaster:           {ja: 防災・災害,         note: 台風・豪雨・避難・訓練・災害の被害}
  conservation_clean: {ja: 環境保全・清掃,     note: 清掃活動・ごみ・保全活動・自然環境の普及啓発}
  agri_fishery:       {ja: 農林水産,            note: 農業・林業・水産業・特産}
  tourism:            {ja: 観光,                note: 観光・エコツーリズム・イベント誘客}
  other:              {ja: その他}
```

- 1 記事に複数付けてよい（河川と防災が重なる）。どれにも当たらなければ `other`。
- 語彙の正は yaml。m13 は yaml を直接読んで `topic_id` を検査する（`registry.sqlite` に依存しない。r01 を先に回す必要を作らない）。web からは `generated.ts`（`web/scripts/build-registry-ts.mjs` が再生成）経由で `topic` の一覧を読み、`describe_catalog` で語彙を返す。
- r01 は yaml の形（キー・`ja` の有無）を検査し、`registry.sqlite` に `article_topic` 表を足す。D1 にも持たせる場合は `schema-registry.ts` に足す（`document_article_topics.topic_id` の説明用。必須ではない）。
- 付け方は #131 で、まず語彙ごとのキーワード規則（`rule:v1`、`confidence` は一致の強さ）。AI で付ける場合も語彙は同じで、`extractor` に記録する。語彙の追加は yaml の変更で、既存の付与は付け直さない。

## 5. 置き場の比較

| 案 | 利点 | 欠点 |
|---|---|---|
| **A `cells.sqlite` に新 m スクリプト（推奨）** | `documents` と同じファイル。FK（`doc_id`）が張れる。D1 の `SOURCES` はそのまま（表は D1 の Drizzle スキーマを足すだけで owner map に載る）。worktree の symlink・CI の sample も既存の 2 原本のまま | 原本が増える（本文 約 10MB 見込み。`cells.sqlite` は 42MB なので許容）。r01 の `records` 照合が `ryuiki.sqlite` だけを見ているなら足す必要がある（§7.3） |
| B `ryuiki.sqlite` に作る | r01 の `records` 照合が既存の経路で通る。`source_id` 付きの表はここにある | 原本 828MB に本文が乗る。`documents`（cells.sqlite）への FK を原本をまたいで張れず、孤児を検査で見る必要がある |
| C 別 sqlite（`tatsugo.sqlite`） | 取り下げ・作り直しが原本から独立 | `SOURCES`・`ensure-*.sh`・指紋・worktree・CI・sample の全部に 1 ファイルぶんの経路が増える。得るものが小さい |

A にする。A の欠点（r01 の照合）は §7.3 の 1 件の追加で解決する。

## 6. 出典・get_records・describe_catalog

### 6.1 access.yaml の宣言: `records` を推奨

案の比較:

| | `documents: [180件]` | `records: [periodical_issues, document_articles]`（推奨） |
|---|---|---|
| r01 の検査 | 既存のまま使える | r01 に `cells.sqlite` の表の行数照合を足す（§7.3） |
| 意味 | 「cells の表として値が引ける」を宣言する種別。広報誌の記事は `cells` ではなく、r01 の「置き換え済みでないセルが 1 件以上」の検査に落ちる（スキーマに合わない） | 「出典の列で絞れる記録の表」。記事・号の実態に合う |
| 見え方 | `document_ids` に 180 件が並ぶ。`document_cells` を引いても空 | `record_set` が 2 つ。号の一覧・記事の本文を引く |
| 保守 | 号が増えるたびに yaml に doc_id を足す | 号が増えても yaml は変わらない |
| 定型の表（#131 の 5）が出たとき | 既存の cells に載せるだけで、同じ宣言で足りる | `documents:` を足すことは「records と排他」で書けない（別の出典 ID を切る必要がある）。定型の表が確定したら、出典を `tatsugo_koho_amami`（記事・号）と `tatsugo_koho_stats_amami`（表）の 2 つに分ける |

`records` を推奨する。`documents:` は 180 件を yaml に列挙する保守が重く、記事の本文を返す口にならない。

```yaml
record_sets:
  periodical_issues: periodical_issues     # 広報誌などの定期刊行物の号。出典は列 source_id
  document_articles: document_articles     # 定期刊行物の記事（本文つき）。出典は列 source_id
sources:
  tatsugo_koho_amami: {records: [periodical_issues, document_articles], note: "龍郷町「広報たつごう」。月刊175冊・PDF180ファイル（2012-04〜）。全文を載せる（2026-11-24 オーナーが広報担当と確認。町の著作権表記と合意は periodical_series.license）。取り下げは docs/plans/TATSUGO_KOHO.md §9"}
```

`source_registry` 側の出典の行（名前・発行者・URL・ライセンス・`redistributable`）は c99 と同じやり方で足す。`redistributable=1`（本文を載せる。ただし「自由な再利用ライセンス」ではない。§7.1 の原文で示す）。

### 6.2 record_set・列・フィルタ

| record_set | 表 | pk | q の対象 | 返す列 |
|---|---|---|---|---|
| `periodical_issues` | `periodical_issues` | `issue_id` | `label_raw`・`headlines` | issue_id, kind, year_month, year_month_to, fiscal_year, issued_on, label_raw, listing_url, headlines, n_files, n_pages, source_id、算出列 `files`（`doc_id` と PDF URL の JSON）・`n_articles` |
| `document_articles` | `document_articles` | `article_id` | `title`・`body_text`（LIKE、50 バイトまで）。`place_raw` は別の入力 `place` で引く | article_id, issue_id, doc_id, kind, issue_page_from, issue_page_to, page_from, page_to, title, section, event_dates, extractor, confidence, unreadable_reason, source_id、算出列 `topics`・`places`・`year_month`・`pdf_url`、`body_text`（§6.4）、返却時に付く `citation` |

追加する入力（`recordsInputSchema`。ほかの record_set で渡したら入力エラー）:

- `issue`: `issue_id` の完全一致（`document_articles`・`periodical_issues`）。`year_month`（`2024-12`）でも受ける。
- `year`: 号の `year_month` の暦年（整数）。`fiscal_year`: 4 月始まりの年度（整数）。別の入力に分け、両方渡したら AND。どちらも `periodical_issues` と `document_articles` で使える（記事は号の値で絞る）。
- `topic`: `topic_id`（§4。一覧は `describe_catalog` が返す）。
- `place_id`: `document_article_places.place_id` の完全一致（結べた地名だけ。結べない地名は `q` で引く）。
- 既存の `doc_id`（`document_articles` でも使う）・`id`（`article_id`/`issue_id`）・`q`・`cursor`・`limit` はそのまま。`include_body`（真偽、既定 false）を足す。

契約:

- 並びは主キー昇順。`article_id` は `<doc_id>:<ページ>:…` なので、ファイル内ページ順に近いが、号をまたいだ時系列順ではない。時系列で見たいときは `year_month` で絞って呼ぶ。
- `document_articles` と `periodical_issues` は `source_id` を必須とする（`tatsugo_koho_amami`、出典が 1 つなので `record_set` 指定だけで足りる）。`documents`（既存・sourceless）は広報誌の 180 件も含めて今のとおり返す。

### 6.3 出典（citation）と PDF URL

- 出典の文字列は 1 つの関数（`web/src/lib/records.ts` 内、または隣の小さなモジュール）でサーバ側が作る。モデルに任せない（注意書きはサーバが機械的に付ける）。
  - 形: `龍郷町「広報たつごう」2024年12月号 p.12`（範囲は `p.12–13`。合併号は `2019年4・5月合併号`、別冊は `2015年2月 別冊`）。
  - ページは号内通しページ（`issue_page_from`〜`issue_page_to`）。
- `pdf_url`: `documents.url` に `#page=<ファイル内ページ>` を付けた URL。
- `document_articles` を返す呼び出しは、常に `citation`・`pdf_url`・`source_license`（`periodical_series.license` の短縮ではなく、一文の固定文言）を各行に付ける。取り除く入力は無い。
- 「本文に書かれていること」と「当方が推定した話題・地名」は区別して返す。`topics`・`places` の各要素には `extractor` を付ける。

### 6.4 本文の返し方

- 一覧（`include_body=false`、既定）は `body_text` を返さず、`has_body`（真偽）と `body_chars`（字数）を返す。
- `include_body=true`、または `id` 指定（1 件）のときだけ `body_text` を返す。`include_body=true` は 1 回 20 件まで（超えたら入力エラー）。
- 本文を要約・切り詰めて返さない。20 件までなら全文。長い本文は 1 件で 数千字なので、MCP の応答サイズ上限（既存の `RECORDS_MAX_ROWS=500` とは別に）を実装で確認する。
- 検索（`q`）の結果は一覧の形で返し、一致した位置の前後（抜粋。前後各 40 字、`match_snippet`）を足してよい。抜粋は本文の一部をそのまま切り出すもので、要約ではない。

### 6.5 入出力の例

呼び出し 1: 2024 年度で、河川・水の話題の記事。

```json
{ "record_set": "document_articles", "fiscal_year": 2024, "topic": "river_water", "limit": 2 }
```

```json
{
  "rows": [
    {
      "article_id": "tatsugo_koho_202412_p2:003:9c41ab07",
      "issue_id": "tatsugo_koho_202412",
      "doc_id": "tatsugo_koho_202412_p2",
      "kind": "article",
      "title": "（見出し）",
      "section": "お知らせ",
      "issue_page_from": 28, "issue_page_to": 28, "page_from": 3, "page_to": 3,
      "year_month": "2024-12",
      "topics": [{"topic_id": "river_water", "confidence": 0.8, "extractor": "rule:v1"}],
      "places": [{"place_raw": "秋名", "place_type": "settlement", "place_id": null}],
      "has_body": true, "body_chars": 1240,
      "citation": "龍郷町「広報たつごう」2024年12月号 p.28",
      "pdf_url": "https://www.town.tatsugo.lg.jp/.../koho_202412_2.pdf#page=3",
      "source_license": "著作権は龍郷町に帰属。2026-11-24 オーナーが広報担当と確認のうえ、公開分を試験的に利用している。"
    }
  ],
  "n_total": 14, "next_cursor": "…"
}
```

（URL と見出しは表記の例。実データは #131 の後に決まる。）

呼び出し 2: 1 件の本文。

```json
{ "record_set": "document_articles", "id": "tatsugo_koho_202412_p2:003:9c41ab07", "include_body": true }
```

→ 上の行に `body_text`（全文）が付く。

呼び出し 3: 号の一覧。

```json
{ "record_set": "periodical_issues", "year": 2019 }
```

→ 2019-04（`year_month_to: "2019-05"`、`files` は 1 件）を含む 11 行（2019 年は 4・5 月が合併号なので 11 冊）。

`describe_catalog what='sources'` での見え方:

```json
{
  "source_id": "tatsugo_koho_amami",
  "queryable_via": ["get_records(periodical_issues)", "get_records(document_articles)"],
  "n_source_rows": {"periodical_issues": 176, "document_articles": "<件数>"},
  "license": "…（§7.1）",
  "topics": ["river_water", "wildlife_alien", "disaster", "conservation_clean", "agri_fishery", "tourism", "other"]
}
```

`topics` は `describe_catalog` の出典の説明にだけ足す（ほかの出典には付かない）。実装は、記録の集合に付く語彙の一覧を返す既存の仕組みがあればそれに寄せる。無ければ `record_set` の説明文に語彙を書く。

## 7. 実装の割り当て

### 7.1 収集担当（#131。この設計に従う契約）

- 取得・目録・記事への切り分けは `scripts/c1xx_tatsugo_koho.py`（番号は実装時）。PDF は `data/raw/tatsugo_koho/`（コミットしない）。
- 出力は `data/processed/tatsugo_koho/` の 3 つの JSONL（gitignore 済みの生成物）。m13 の入力契約で、列は §3 と同じ名前:
  - `catalog.jsonl`: 号とファイルの目録（`periodical_issues`・`periodical_issue_files` の列＋保存名・sha256・n_pages・fetched_at）
  - `articles.jsonl`: 記事（`document_articles` の列から `article_id`・`source_id`・`region_id`・`issue_page_*`・`body_sha256`・`doc_sha256` を除いたもの）。1 行に `topics`・`places` を入れ子で持たせてよい
  - `pages.jsonl`: ページごとの文字数・テキスト層の有無（被覆検査・再抽出の判断用）
- ライセンスの原文（`periodical_series.license`）:
  「掲載内容の著作権は原則として龍郷町に帰属する（町『著作権・リンク』ページ）。私的利用と著作権法上の引用を超える複製・転用には事前の相談が要る旨の記載がある。2026-11-24、オーナーが龍郷町の広報担当と話し、ネットで公開されているものを試験的に利用することを確認した（公開分のみ。取り下げの依頼があれば号・記事を外す）。」
  - これは自由な再利用ライセンスではない。`documents.license` にも同文を入れ、`documents` と同じ行の `notes` に `kind` を持つ注記（`license`）を 1 行足す。再配布を広げる根拠（CC 等）として扱わない。
- User-Agent に個人名・個人アドレスを入れない。取得は 1 ファイルずつ・間隔あり・sha256 が同じなら取り直さない。町への問い合わせや許諾の提出はしない（オーナーの行為）。

### 7.2 m スクリプト担当（`scripts/m13_tatsugo_koho.py`、DDL `scripts/schema_tatsugo_koho.sql`）

- 入力: `data/processed/tatsugo_koho/*.jsonl` と除外リスト（§9）。出力: `cells.sqlite` に `documents`（180 行）・`periodical_series`・`periodical_issues`・`periodical_issue_files`・`document_articles`・`document_article_topics`・`document_article_places`、`notes`（ライセンスの注記）。
- 何度回しても同じ結果（冪等）。広報誌のドキュメント（`doc_id LIKE 'tatsugo_koho_%'`）の行だけを消して入れ直す。**ほかの文書の行・`cells`・`notes` に触らない**。実行前に `cells.sqlite` を `.backup`（`m01 は --help でも本処理が走る` の教訓。ヘルプは `--help` に頼らずソースの docstring）。
- `article_id`・`issue_page_*`・`body_sha256`・`doc_sha256`・`source_id`・`region_id` は m13 が決める（§2・§3）。
- 検査（失敗したら止まる）は §8.1 の一覧。
- 件数と差分（旧原本との `article_id` の差）を最後に表示する。
- `body_text` が 64KB を超える記事があれば止める（D1 の 1 文の SQL サイズの上限に近い。超える記事が実在したら、その記事だけ段落で分ける設計を別に決める）。

### 7.3 registry・r01 担当

- `registry/article_topic.yaml` を足し、r01 が形を検査する（§4）。
- `registry/source/access.yaml` に §6.1 の宣言を足す。`scripts/registry/build_source_access.py` の検査（records の表に出典の行があるか）が `cells.sqlite` の表を見られるか確認し、見られなければ「records の表がどの原本にあるか」を引く方法を足す（まず `record_sets` の表の存在する原本を `PRAGMA`/`sqlite_master` で探す形が最小）。ここは実装で最初に確かめる（設計書では未確認）。
- `source_registry` の出典の行は、m13 か c1xx（c99 と同じ経路）が足す。r01 が「全出典が状態を持つ」検査を満たすこと。
- `registry.sqlite` の内容が変わるので `ensure-v2.sh` は「古い」と判定して v2 を作り直す。想定どおり（§8.2）。

### 7.4 web・records 担当

- `web/src/lib/records.ts` の `RECORD_TABLES` に `periodical_issues`・`document_articles` を足す（`sourceless` ではない。表名は `RECORD_SET_TABLES`＝access.yaml の `record_sets` の生成物）。算出列の `topics`・`places` は `document_article_topics`・`document_article_places` を 1 回だけ集計して結合する（`documents` の `n_cells` と同じ作り方。記事ごとの相関サブクエリにしない）。`year`・`issue`・`topic`・`place_id` は定数 SQL に値をバインドする。`topic`・`place_id` は `EXISTS`（バインド 1 個）で、100 個の上限に触れない。
- `recordsInputSchema` に `issue`・`year`・`fiscal_year`・`topic`・`place_id`・`include_body` を足す。`z.tuple` は使わない。説明文の「出典に紐付かない record_set」の一覧を壊さない（今回の 2 つは出典あり）。
- `citation`・`pdf_url` の関数は 1 か所（§6.3）。画面・API・MCP・AI は同じ問い合わせ層を共有する（ADR-0014）ので、MCP と AI の `get_records` は同じ関数を通る。画面は無い（広報誌の画面は別 Issue）。
- `records.test.ts` の「列定義と DDL の突き合わせ」に新しい表が乗ること。`describe_catalog` の出典の説明（`source-catalog.ts`）に §6.5 の項目が出ること。
- 検索は `q` の LIKE で足りる（約 2,600 記事×数 KB の全表走査で、D1 の読み取り行数の費用は許容。ただし記事数が 1 桁増えたら見直す）。FTS5（日本語は trigram）とベクトルの併用は #132 の評価で決める。ここでは入れない。

### 7.5 D1 担当（`web/src/db/schema.ts`・`seed-d1-local.mjs`・`web/scripts/d1/`）

- `schema.ts` に 6 表を足す（FK: `document_articles.doc_id → documents`、`periodical_issue_files.doc_id → documents`、topics・places → `document_articles`）。`pnpm run db:generate` でマイグレーションを作る。
- `seed-d1-local.mjs` の `SOURCES` は変えない（`cells.sqlite` 由来の表として owner map に自動で載る）。FK のためにテーブル名順の投入中は外すという既存の扱いで足りるかを確認する。
- 本番への入れ直しは `web/scripts/d1/reload-tables.mjs` の順序表（`rank`）を広報誌の表に合わせて拡張する: 入れる順は `documents` → `periodical_series` → `periodical_issues` → `periodical_issue_files` → `document_articles` → `document_article_topics`・`document_article_places`。ただし `documents` を丸ごと空にして入れ直すのは `notes`・`cells` の FK で重い。広報誌だけの更新は §9 の専用スクリプトを使い、`reload-tables.mjs` は新しい表（`periodical_*`・`document_article*`）だけに使う。

## 8. 受け入れ基準

### 8.1 件数の宣言と検査（m13 が止まる条件。#131 の全件取得後に確定値を m13 の定数に書く）

- `periodical_issues`: 176（`kind='monthly'` 175、`supplement` 1）。月刊は 2012-04〜2026-11 の 176 か月から合併号 1 つを引いた 175。欠けた月があれば、その月が分かる形で止める。
- `periodical_issue_files` ＝ `documents`（`doc_id LIKE 'tatsugo_koho_%'`）＝ 180。分割 4 号（201808・202307・202412・202602）は part 1・2。
- 号ごとに `n_files` ＝ `periodical_issue_files` の行数、`n_pages` ＝ ファイルの `n_pages` の合計。
- `page_offset` は part 1 が 0、part 2 が part 1 の `n_pages`。
- すべての記事で `issue_page_* = page_* + page_offset`。`page_from ≤ page_to ≤ documents.n_pages`。
- **ページの被覆**: 各ファイルの全ページ（1〜`n_pages`）が、少なくとも 1 つの記事（`unsegmented` を含む）に入っていること。
- `topic_id` が語彙に在る。`kind='article'` で話題が 0 件のものは無い（`other` を付ける）。`place_id` は `place` に在る。
- `doc_sha256` が `documents.doc_sha256` と一致。
- 令和 2 年度以降（`headlines` がある号）: `headlines` の各見出しが、その号の記事の `title` か `body_text`（NFKC・空白除去後の部分一致）に見つかること。見つからない見出しは一覧にして出す（落ちたら止めるのではなく、`reports/` ではなく標準出力に出し、閾値は #131 で決める。初期値は「号の見出しの 8 割以上が見つかること」）。

### 8.2 テスト・サンプル・スナップショット

- テスト: `scripts/tests/` に m13 の単体テスト（小さな JSONL の fixture）。`article_id` の安定性（同じ入力で同じ ID、本文だけ変えても同じ ID、見出しを変えると別 ID）、合併号・分割・別冊の doc_id、被覆検査の失敗例。`web/src/lib/records.test.ts` に 2 つの record_set とフィルタ・`citation`。r01 の `access.yaml` 検査のテスト（広報誌の宣言が通る・表が空なら落ちる）。
- サンプル（`data/sample/`、s01）: 数号だけ入れる。**2012-04（最古・目録が最も薄い）・2018-08（分割）・2019-04（合併）・2026-11（最新）の 4 号**。s01 の文書単位の選択（`document_closure`）に「広報誌は doc_id の接頭辞で号を選び、その号の `periodical_*`・`document_articles`・`topics`・`places` を一式持ってくる」を足す。FK の閉包（`documents` ← `periodical_issue_files`、`document_articles` ← topics/places）が切れないこと。実データの本文をサンプルに入れてよいかは、広報担当との合意の範囲（公開分の試験利用）で足りるが、サンプルは公開リポジトリに入るため**本文はサンプル用に最初の 1 号分だけに絞り**、残りの号は `body_text` を NULL＋`unreadable_reason='sample_omitted'` にする、を既定とする（オーナーが全文でよいと言えば外す）。
- serving snapshot（`data/sample/serving_snapshot.json`）・`reports/serving_fingerprint.json`: 広報誌の表は v2（キューブ）に流れないので、**値は変わらないはず**。ただし `registry.sqlite` の指紋が変わる（`article_topic`・`access.yaml`）ので、v2 の鮮度判定は「古い」になり作り直される。PR の前に `pnpm run serving:snapshot -- --mode snapshot`（差分ゼロ）と `scripts/b00_run_full_gate.py` を 1 回だけ回し、`reports/serving_fingerprint.json` が変わるなら一緒にコミットする（パイプラインのパスを触らなければ変わらない見込みだが、指紋の入力に registry が含まれるかを実測で確かめる）。重い検証は PR の直前に 1 回だけ。
- 原本の無い CI（clone の再現）: `data/sample/` から `cells.sqlite` 相当を作るとき、広報誌の表（ほかの cells 由来の表と同じ経路）が空でも通ること。広報誌の宣言（`records`）の「表に行がある」検査はサンプルの 4 号で通る。

### 8.3 再抽出の運用

- 再抽出（抽出器の改善）は `articles.jsonl` を作り直して m13 を回す。m13 は旧原本との差分（消えた／増えた `article_id`、同じ ID で `body_sha256` が変わった数）を表示する。ID が大量に変わる再抽出は、切り方が変わったことを意味するので、Vectorize の全入れ直しが要る（#132 が `article_id` の差分から入れ直す対象を決める）。

## 9. 取り下げ

町の依頼で号または記事を外す手順。目的は「原本・D1・Vectorize のどれにも残らない」こと。

1. **除外リストに追記**（コミットする）: `scripts/data/tatsugo_koho_withdrawn.yaml` に `{scope: issue|article, id: <issue_id|article_id>, withdrawn_on: YYYY-MM-DD, reason: 依頼の種別}`。本文・依頼者の個人情報は書かない（ID と日付だけ）。
2. **原本から外す**: `m13` が除外リストを読み、該当の号（`periodical_issues`・`periodical_issue_files`・その号の `documents`・`document_articles`・topics・places・`notes`）／記事（`document_articles` と topics・places）を入れない。号を外すと、その号の PDF（`data/raw/tatsugo_koho/` の保存名）も手元から消す手順を m13 が表示する（消すのは人）。除外リストが原本より新しいと検査で分かる（`articles.jsonl` 側に残っていても m13 が弾く）。
3. **再シード**: ローカルは `db:setup`。**本番**は `web/scripts/d1/withdraw-periodical.mjs`（新規）。`--issue`/`--article` を受け、dry-run で消す行数を出し、`--execute` で子から親の順に `DELETE`（`document_article_places`・`document_article_topics` → `document_articles` → `periodical_issue_files` → `periodical_issues` →（号の）`notes`・`documents`）を `wrangler d1 execute --remote` に流す。`CLOUDFLARE_ACCOUNT_ID` を付ける。DELETE の対象 ID は 100 個以内で区切る（`queryChunked` と同じ考え方）。実行後に件数をローカルと突き合わせる。
4. **Vectorize**: #132 の入れ直しスクリプトが、除外した `article_id` の集合から `chunk_id`（`<article_id>#<seq>`。号全体なら `article_id` の接頭辞が `<doc_id>:` のもの）を削除する。消すチャンクの一覧は、手順 3 の dry-run が出す `article_id` の一覧から作る（D1 を消す前に取る）。
5. **確認**: `get_records` で外した ID が返らないこと、Vectorize の検索で外した記事が返らないこと、`describe_catalog` の件数が減っていること。
6. **記録**: 本番反映の記録に日付と ID だけ書く（`DEPLOYMENT.md`）。

PDF の再公開（町が訂正して差し替えた）は取り下げと別の手順で、sha256 が変わるので §2.3 の検査で止まり、その号だけ抽出し直す。

## 10. 未決・逸脱

- **記事の `section` を語彙にしない**: Issue の案は語彙の欄を挙げたが、紙面の区分は時期でばらつく可能性が高く、先に語彙を決めると取りこぼす。原文のまま持つ。#131 のサンプル後に、実際の区分が少なければ語彙にする。
- **`issued_on`・`event_dates` の扱い**: Issue の案を採ったが、`issued_on` は令和 2 年度以降だけ。それ以前は NULL（月初で補わない）。ISO 化できない日付は `iso` を NULL にする。**SQLite の日時関数を使わない**（`+09:00` ではないが、規約に合わせて文字列のまま比較）。
- **集落名を `place` に足すか**: この Issue では決めない。足すなら別 Issue（行政区の境界データが要る）。現状、集落名は `place_id` NULL の原文だけ。広報誌の「話題×場所」の検索は川・流域・観測点（`place` にあるもの）に限られる。
- **記事の話題の分類を誰が付けるか**: まずキーワード規則（`rule:v1`）。精度が足りなければ #131 で AI を使うが、語彙と `extractor` の記録は変えない。AI の付け直しは新しい `extractor` の行として入れ替える（履歴は持たない）。
- **紙面のページ番号**: 号内通しページ（PDF のページを通した数）を出典の `p.○` に使う。紙面に印字されたページ番号とずれる号がありうる。#131 のサンプル調査で、ずれが大きければ `periodical_issue_files` に `printed_page_offset` を足す（今は持たない）。
- **サンプルの本文**: §8.2 のとおり最初は 1 号分だけ。サンプルが公開リポジトリに入るため、より保守的にした。許諾の範囲（ネットに公開されたもの）で足りるとオーナーが判断すれば全 4 号に広げる。
- **`document_articles` への `source_id` の複写**: 正規化としては `issue_id` から引けるが、get_records の既定の絞り（`source_id = ?`、索引が効く）と Vectorize のメタデータに使うので複写する。m13 の検査で `issues.source_id` と一致を確かめる。
- **r01 の `cells.sqlite` の表の照合**: 未確認（§7.3）。最初に確かめる。ここが重いなら、案 B（`ryuiki.sqlite`）に倒す選択肢が残る（その場合 FK は検査で代替）。
- **FTS5 を入れない**: #132 の評価に譲る。`q` の LIKE は 50 バイト（約 16 文字）までなので、長い文の検索は #132 のベクトル検索の役割。

## 11. #131 の 5（定型の表）の枠

- 「人口と世帯」等の表が毎号載るなら、既存の `cells`（`doc_id` は広報誌のファイル、`page_no` はファイル内ページ、`fiscal_year`、`row_key`・`col_key`・`value`・`unit`）に入れる。`document_articles` とは `doc_id`＋`page_no` が記事のページ範囲に入ることで対応づく（別の列は足さない）。
- 出典の宣言は §6.1 の表のとおり、`tatsugo_koho_amami`（記事・号）とは別の出典（`tatsugo_koho_stats_amami`、`documents: [doc_id…]`）に分ける。`documents:` は `records` と排他で、doc_id は 1 つの出典にしか属せないため。
- 対象と列は #131 のサンプル調査（3 冊）で決める。載っていなければ作らない。
