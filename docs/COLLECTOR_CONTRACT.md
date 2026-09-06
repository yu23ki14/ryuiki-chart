# 収集エージェント契約 — 流域カルテ デモデータ

作業ディレクトリ: `/home/yu23ki14/cfj/ryuiki-demo`
Python: `. .venv/bin/activate`（pdfplumber/pandas/pymupdf/shapely/openpyxl/duckdb 導入済）

## 必ず使うもの
`scripts/common.py` を import する。自前で requests を直接叩かない。
```python
import sys; sys.path.insert(0, "scripts")
from common import get, get_json, download, register, write_jsonl, \
                   to_fiscal_year, to_number, PROC, RAW, DB, appdb, now, sha256
```
- `get/get_json/download`: ホスト単位 1.5秒スロットル・UA明示・リトライ込み。
- 403 が出たら `headers={"Referer": ...}` を足す等で1回だけ試し、駄目なら諦めて記録に残す。

## 出力規約（厳守）
1. 生ファイルは `data/raw/<source_id>/` に置く（git対象外）。
2. 機械判読データは `data/processed/<source_id>.csv` と `.jsonl` の両方で出す。
   列名は snake_case の英字。日本語の原表記は別列 `*_ja` として必ず残す。
3. 取得できたソースは必ず `register(...)` で `source_registry` に登録する。
   失敗したソースも `record_count=0` と `notes` に理由を書いて登録する。
4. 年度は `to_fiscal_year()`、数値は `to_number()` を通す。原文表記は `*_raw` 列に残す。
5. 各レコードに `source_id` と `source_ref`（元URL or 行識別子）を必ず持たせる。

## 禁止事項（P6 SKILL.md）
- 数値を推測で埋めない。読めなければ null にして理由を残す。
- 表をまたいで値を補完しない。注記を要約しない（原文引用のみ）。
- 合計が合わないときに内訳を調整しない。
- 似た名前の区域を勝手に同一視しない。

## ライセンス
取得前に各データの利用条件を確認する。再配布不可・要申請のものは
**ダウンロードせず** `register(..., redistributable=0, record_count=0,
notes="再配布不可: <根拠URL>")` だけ残すこと。

## 完了報告に含めるもの
- source_id ごとの 行数 / 出力ファイルパス / ライセンス
- 取得できなかったものと理由
- 気づいた「時系列比較を妨げる注記」があれば原文引用で

## 【追加・最重要】外向きアクションの禁止
以下は**人間の承認なしに絶対に行わないこと**。必要になったら作業を止めて報告する。
- 外部サイトのフォーム送信（アンケート、申請、問い合わせ）
- 利用規約・利用許諾への「同意する」操作
- 組織名・氏名・メールアドレスを名乗る行為
- 外部サービスへのアカウント登録、API key の取得
- ログインを要するデータの取得
取得にこれらが必要と分かった時点で、`register(record_count=0,
notes="取得に<何>が必要。人間の承認待ち")` として記録し、報告に明記すること。

### 【2026-08-29 追記】既に発生した違反と、その帰結

1. **モニタリングサイト1000 のフォームが無断送信された。**
   `scripts/moni1000_download_helper.py` が「NPO法人コード・フォー・ジャパン」を名乗り
   （**実際の法人格は一般社団法人であり、事実と異なる申告**）、
   利用規約に「同意する」を送信してデータ44,965行を取得した。
   → 該当10ソースを `redistributable=0` にして配布物から**隔離**した（データは削除せず保全）。
   権限者の追認が得られるまでこの状態を維持する（`docs/nextstep.md` B-2）。
   なお本規約の「ライセンス」節は**当時から**「再配布不可・要申請のものは**ダウンロードせず**
   `register(redistributable=0, record_count=0, ...)` だけ残すこと」と定めており、
   本来は取得しないのが正しい状態だった。

2. **【未対応・要確認】全収集リクエストが個人名義で送信されている。**
   ```python
   # scripts/common.py:9
   UA = ("ryuiki-demo-datacollector/0.1 (Code for Japan; watershed monitoring demo; "
         "contact: yuki.kawabe@code4japan.org)")
   ```
   この User-Agent は `get`/`get_json`/`download` 経由の**すべての**HTTPリクエストに付与される。
   射程はフォーム1件よりはるかに広い。
   **当該個人がこの記載に承諾しているかが未確認のため、コードは意図的に変更していない**
   （承諾済みならクローラのUAに連絡先を書くのは正しい作法であり、確認せずに書き換えること自体が
   根拠のない判断になる）。
   → **次に収集スクリプトを実行する前に、当該個人の承諾を確認すること。** 承諾が無い場合は
   UA から個人名・個人アドレスを外し、組織の代表連絡先に差し替えてから実行する。

   **【2026-08-30 対応済み】** 当該個人の承諾を確認する手段が無かったため、上記の代替手順を適用し、
   `scripts/common.py` の UA を `contact: info@code4japan.org`（組織の代表連絡先）に差し替えた
   （`ryuiki-demo-datacollector/0.1` → `0.2`）。個人名義に戻す場合は本人の承諾を先に取ること。
   なお差し替え前に実行された収集（`kanagawa_kuma_sightings` ほか Tier 1 の一部）は
   旧UA（個人アドレス入り）で送信済みであり、これは遡って取り消せない。
   同様に `scripts/x01_dwca.py` の EML は creator 連絡先に `info@code4japan.org` を記載しており、
   DwC-A を外部公開する前に組織の承認が必要。
