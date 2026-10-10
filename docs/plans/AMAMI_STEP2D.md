# 奄美 Step 2d: 行政文書を documents に載せる（Issue #89 §5）

奄美の行政文書を、原本 `cells.sqlite` の `documents`（と `notes`）に載せる。表は作らない（cells は 0 件）。載せた文書は `get_records(record_set=documents / document_notes)`・`/documents`・`/sources` に出る。2026-10-11 に設計担当が各文書を取得して確かめた。

## 0. 決定（設計担当の推奨を採った。2026-10-11）

1. **範囲**
   - Issue §5 の9文書を載せる。
   - 追加でノネコの目標の2023年度改訂版を載せる（今の対策が分かるため）。
   - そのほかの補足資料は載せない。対象外にしたのは、モニタリングの説明資料（a-0・a-m）と、流域治水の関連2本。
2. **モニタリングの評価シート5本（a-1〜a-5、各20MB未満）**
   - `data/raw/amami_doc/` に保存し、n_pages と sha256 を入れる。
   - 再配布はしない（gitignore 済み）。
3. **出典は、発行者とライセンスでまとめた5つにする**（§2）。
4. **ライセンスの表記が無い3件は、メタデータだけ載せる**
   - 対象は、地域戦略・エコツーリズム推進全体構想・持続的観光マスタープラン。
   - 載せるのは題名・URL・ページ数・sha256 だけで、本文は転載しない。`redistributable=0` にする。
5. **fiscal_year** には版の年度を入れる。計画期間は notes に書く。
6. **PDF の保存先** は `data/raw/amami_doc/`。
7. **マングースの後継計画**: 今回は探さない。notes に「2024年9月に根絶を達成し、後継の計画があるが未確認」と書く。
8. **notes は事実だけを書く**（期間の終了、改定案であることなど）。本文の要約や数値の転記はしない。`blocks_timeseries` は全部 0。

## 1. 文書（設計担当が確認）

| doc_id | 発行者 | 版・期間 | ライセンス |
|---|---|---|---|
| `amami_wh_comprehensive_plan_2025draft` | 環境省ほか（`…/plan/pdf/d-2-j.pdf`） | 改定案。日付は空欄 | PDL1.0 |
| `mlit_amami_action_plan_2016` | 国交省（`001294716.pdf`） | 2016年 | PDL1.0（mlit.go.jp/link.html） |
| `moe_amami_mongoose_plan_r3_r7` | 環境省（`z-1-j.pdf`） | 2021-04〜2026-03 | PDL1.0 |
| `amami_biodiversity_strategy_2015_2024` | 奄美大島自然保護協議会（大和村のサイト） | 2020年3月改訂。期間は2015〜2024年度 | 表記なし |
| `bodik_460001_amami_ryuiki_chisui_2022` | 鹿児島県（BODIK、4p） | 2023年登録 | CC BY 4.0 |
| `moe_amami_noneko_plan_2018_2027` | 環境省ほか（`naha/0328amami.pdf`） | 2018〜2027年度 | PDL1.0 |
| `moe_amami_noneko_goal_2023rev` | 環境省（`content/000165719.pdf`） | 2023年度改訂 | PDL1.0 |
| `amami_ecotourism_zentai_2017` | 奄美群島エコツーリズム推進協議会（`z-4-j.pdf`） | 2017年2月 | 表記なし |
| `amami_sustainable_tourism_mp_2016` | 鹿児島県（`z-2-j.pdf`。`z-5-j` は沖縄島北部版なので間違えない） | 2016年3月 | 表記なし |
| `moe_wh_monitoring_eval_r1`〜`r5` | 環境省（`a-1-j.pdf`〜`a-5-j.pdf`） | R1〜R5年度 | PDL1.0 |

URL の全文と、確かめた事実は設計担当の調査結果にある（PR の本文に転記する）。

## 2. 出典と登録

| source_id | 文書 | ライセンス |
|---|---|---|
| `moe_amami_wh_plans_amami` | 包括的管理計画・マングース・ノネコ2本・評価シート5本 | PDL1.0（c96 と同じ原文） |
| `mlit_amami_action_plan_amami` | 国交省の行動計画 | PDL1.0 |
| `amami_biodiversity_strategy_amami` | 地域戦略 | 表記なし |
| `bodik_kagoshima_ryuiki_chisui_amami` | 流域治水 | CC BY 4.0 |
| `amami_tourism_plans_amami` | エコツーリズム構想・持続的観光マスタープラン | 表記なし |

- `access.yaml` は `reason: pdf_document`（神奈川の文書の出典と同じ扱い）。
- `license.yaml` の mappings と `LICENSE_MATRIX.md` を直す。
- 件数を直書きしたテスト（source・edition・caveat）を直す。
- `coverage.yaml` は触らない。cells の無い文書は、documents と notes を丸ごとサンプルに入れるため。

## 3. 実装（1人）

- `scripts/c99_amami_gov_docs.py` を作る。`doccells` の `fetch_pdf`・`commit_doc` を使い、cells は空で渡す（その doc_id の cells を消すだけで、ほかの doc_id には触れない）。
- ページ数は pdfplumber で取る。
- テストは DB とフィクスチャだけで書く。CI では PDF を取りに行かない。
- 統合の順:
  1. `.backup` を取る。
  2. c99 を原本に書く。
  3. ほかの doc_id の documents・cells・notes を全表 EXCEPT で突き合わせ、差が0であることを確かめる。
  4. r01 → `build:registry:ts` → `build:v2` → サンプル → 一時 clone での CI 再現 → b00。
- p1_maker・p1_maker_v2・p3_fixer・c25・c26 は回さない。
