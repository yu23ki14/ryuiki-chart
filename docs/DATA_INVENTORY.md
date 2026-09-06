# データ整備状況（DATA_INVENTORY）

生成日時: 2026-08-29T22:06:44

担当範囲: 収集済み公開データ -> アプリデータモデル（`data/db/ryuiki.sqlite`）へのマッピング。
`zone` は操作的定義であり公式区分ではない（詳細は `docs/ZONE_DEFINITION.md`）。

## 1. テーブルごとの行数
| table | rows | is_synthetic内訳 |
|---|---|---|
| source_registry | 101 | (is_synthetic列なし) |
| sites | 352 | is_synthetic=0: 352 |
| protocols | 6 | (is_synthetic列なし) |
| instruments | 26 | (is_synthetic列なし) |
| observers | 40 | is_synthetic=1: 40 |
| events | 29947 | is_synthetic=0: 29271, is_synthetic=1: 676 |
| event_observers | 1405 | (is_synthetic列なし) |
| measurements | 315318 | is_synthetic=0: 313053, is_synthetic=1: 2265 |
| organism_records | 823692 | is_synthetic=0: 823692 |
| interventions | 20 | is_synthetic=1: 20 |
| decisions | 14 | is_synthetic=1: 14 |
| quality_transitions | 3372 | (is_synthetic列なし) |
| sensor_timeseries | 396798 | is_synthetic=0: 377378, is_synthetic=1: 19420 |
| taxa | 8585 | (is_synthetic列なし) |
| redlist_assessments | 2884 | (is_synthetic列なし) |

## 2. sites: 流域別 地点数
| watershed_id | site数 |
|---|---|
| (未判定) | 74 |
| 83032-0024 | 12 |
| 83032-0049 | 10 |
| 83545-0017 | 9 |
| 83032-0043 | 6 |
| 83032-0042 | 6 |
| 83545-0033 | 5 |
| 83267-0017 | 5 |
| 83031-0010 | 5 |
| 83031-0003 | 5 |
| 83030-0003 | 5 |
| 83030-0001 | 5 |
| 83545-0052 | 4 |
| 83545-0012 | 4 |
| 83544-0072 | 4 |
| 83267-0005 | 4 |
| 83032-0027 | 4 |
| 83032-0010 | 4 |
| 83032-0008 | 4 |
| 83032-0007 | 4 |
| 83032-0006 | 4 |
| 83031-0001 | 4 |
| 83030-0016 | 4 |
| 83545-0056 | 3 |
| 83545-0030 | 3 |
| 83545-0023 | 3 |
| 83544-0066 | 3 |
| 83268-0074 | 3 |
| 83268-0035 | 3 |
| 83268-0002 | 3 |
| 83268-0001 | 3 |
| 83267-0003 | 3 |
| 83032-0065 | 3 |
| 83032-0052 | 3 |
| 83032-0050 | 3 |
| 83032-0026 | 3 |
| 83031-0018 | 3 |
| 83545-0055 | 2 |
| 83545-0041 | 2 |
| 83545-0034 | 2 |
| 83545-0026 | 2 |
| 83545-0020 | 2 |
| 83545-0019 | 2 |
| 83545-0015 | 2 |
| 83545-0011 | 2 |
| 83545-0006 | 2 |
| 83544-0074 | 2 |
| 83544-0073 | 2 |
| 83544-0071 | 2 |
| 83544-0070 | 2 |

## 3. sites: zone別 地点数
| zone | site数 |
|---|---|
| NULL(標高不明) | 62 |
| 1 | 4 |
| 2 | 11 |
| 3 | 56 |
| 4 | 167 |
| 5 | 52 |

## 4. sites: source_id別 地点数
| source_id | site数 |
|---|---|
| env_kousui_stations_kanagawa | 290 |
| moni1000_sites | 30 |
| sagami_livecams | 16 |
| jma_stations_kanagawa | 12 |
| dams_kanagawa | 4 |

## 5. measurements: 変数別 行数 / 期間
| variable | 行数 | min(measured_on) | max(measured_on) | quality_stage |
|---|---|---|---|---|
| 溶存酸素量 DO | 36322 | 2005 | 2026-08-21 | 公開済 |
| 化学的酸素要求量 COD | 35084 | 2005 | 2025-03-14 | 公開済 |
| pH | 33437 | 2015-04-08 | 2026-08-17 | 公開済 |
| 生物化学的酸素要求量 BOD | 26667 | 2005 | 2025-03-12 | 公開済 |
| 浮遊物質量 SS | 24179 | 2005 | 2026-07-12 | 公開済 |
| 全亜鉛 | 16808 | 2007 | 2025-03-14 | 公開済 |
| 大腸菌群数 | 12564 | 2005 | 2023-02-01 | 公開済 |
| 水温 | 9394 | 2022-04-06 | 2026-08-17 | 公開済 |
| 気温 | 7743 | 2022-04-06 | 2026-08-23 | 公開済 |
| 直鎖アルキルベンゼンスルホン酸及びその塩 LAS | 6518 | 2014 | 2025-03-12 | 公開済 |
| ノルマルヘキサン抽出物質 | 6085 | 2005 | 2025-03-12 | 公開済 |
| ノニルフェノール | 5458 | 2013 | 2025-03-12 | 公開済 |
| 大腸菌数 | 5069 | 2022 | 2025-03-14 | 公開済 |
| 流量関連（公式定義未確認のため原表記のまま） | 4668 | 2022-04-06 | 2025-03-12 | 公開済 |
| pH（最大値） | 2974 | 2005 | 2024 | 公開済 |
| pH（最小値） | 2974 | 2005 | 2024 | 公開済 |
| nno3 | 2902 | 2005 | 2024 | 公開済 |
| 全燐 T-P | 2590 | 2005 | 2024 | 公開済 |
| 全窒素 T-N | 2590 | 2005 | 2024 | 公開済 |
| ass | 2568 | 2005 | 2024 | 公開済 |
| chiobenkarubu | 2566 | 2005 | 2024 | 公開済 |
| shimajin | 2566 | 2005 | 2024 | 公開済 |
| cd | 2564 | 2005 | 2024 | 公開済 |
| chiraumu | 2564 | 2005 | 2024 | 公開済 |
| cn | 2564 | 2005 | 2024 | 公開済 |
| cr6 | 2564 | 2005 | 2024 | 公開済 |
| pb | 2564 | 2005 | 2024 | 公開済 |
| tetorakuroroechiren | 2564 | 2005 | 2024 | 公開済 |
| thg | 2564 | 2005 | 2024 | 公開済 |
| torikuroroechiren | 2564 | 2005 | 2024 | 公開済 |
| benzen | 2563 | 2005 | 2024 | 公開済 |
| jikuroroechiren11 | 2563 | 2005 | 2024 | 公開済 |
| jikuroroetan12 | 2563 | 2005 | 2024 | 公開済 |
| jikurorometan | 2563 | 2005 | 2024 | 公開済 |
| jikuroropuropen13 | 2563 | 2005 | 2024 | 公開済 |
| s12jikuroroetiren | 2563 | 2005 | 2024 | 公開済 |
| seren | 2563 | 2005 | 2024 | 公開済 |
| sienkatanso | 2563 | 2005 | 2024 | 公開済 |
| torikuroroetan111 | 2563 | 2005 | 2024 | 公開済 |
| torikuroroetan112 | 2563 | 2005 | 2024 | 公開済 |
| COD 75%値 | 2412 | 2005 | 2024 | 公開済 |
| BOD 75%値 | 2065 | 2005 | 2024 | 公開済 |
| 透明度 | 1973 | 2022-04-06 | 2025-03-14 | 公開済 |
| 底層溶存酸素量 | 1871 | 2016-04-13 | 2025-03-14 | 公開済 |
| n14jiokisan | 1795 | 2006 | 2024 | 公開済 |
| pcb | 1778 | 2005 | 2024 | 公開済 |
| b | 1599 | 2005 | 2024 | 公開済 |
| f | 1589 | 2005 | 2024 | 公開済 |
| 気温 | 515 | 2023-09-01 | 2026-08-25 | 暫定 |
| 水温 | 501 | 2023-09-01 | 2026-08-25 | 暫定 |
| pH | 500 | 2023-09-01 | 2026-08-25 | 暫定 |
| 大腸菌数 90%値 | 423 | 2022 | 2024 | 公開済 |
| 水温 | 87 | 2023-09-11 | 2026-08-23 | 検証済 |
| 気温 | 86 | 2023-09-01 | 2026-08-13 | 検証済 |
| pH | 84 | 2023-09-06 | 2026-07-30 | 検証済 |
| 溶存酸素量 DO | 63 | 2023-09-26 | 2026-08-23 | 暫定 |
| 浮遊物質量 SS | 56 | 2023-09-21 | 2026-08-23 | 暫定 |
| srhg | 24 | 2005 | 2017 | 公開済 |
| 浮遊物質量 SS | 20 | 2023-10-28 | 2026-08-01 | 検証済 |
| 溶存酸素量 DO | 9 | 2024-05-04 | 2026-07-08 | 検証済 |

## 6. sensor_timeseries: datastream別 行数 / 期間
| source_id | datastream | 行数 | min(phenomenon_time) | max(phenomenon_time) |
|---|---|---|---|---|
| sagamihara_taiki_hourly | OX | 87672 | 2015-04-01T01:00:00+09:00 | 2025-04-01T00:00:00+09:00 |
| sagamihara_taiki_hourly | RAIN | 87672 | 2015-04-01T01:00:00+09:00 | 2025-04-01T00:00:00+09:00 |
| soramame_hourly_kanagawa | SPM(mg/m3) | 37539 | 2025-08-01T01:00:00+09:00 | 2026-08-28T22:00:00+09:00 |
| soramame_hourly_kanagawa | NO2(ppm) | 37538 | 2025-08-01T01:00:00+09:00 | 2026-08-28T22:00:00+09:00 |
| soramame_hourly_kanagawa | Ox(ppm) | 37532 | 2025-08-01T01:00:00+09:00 | 2026-08-28T22:00:00+09:00 |
| soramame_hourly_kanagawa | PM2.5(μg/m3) | 37337 | 2025-08-01T01:00:00+09:00 | 2026-08-28T22:00:00+09:00 |
| soramame_hourly_kanagawa | SO2(ppm) | 18847 | 2025-08-01T01:00:00+09:00 | 2026-08-28T22:00:00+09:00 |
| synthetic_sensor | water_temperature | 11652 | 2024-01-01T00:00:00+09:00 | 2026-08-28T18:00:00+09:00 |
| synthetic_sensor | soil_moisture | 7768 | 2024-01-01T00:00:00+09:00 | 2026-08-28T18:00:00+09:00 |
| jma_daily_yokohama | 天気概況_夜 (18:00-翌日06:00) | 971 | 2024-01-01 | 2026-08-28 |
| jma_daily_yokohama | 天気概況_昼 (06:00-18:00) | 971 | 2024-01-01 | 2026-08-28 |
| jma_daily_yokohama | 日照 時間 | 971 | 2024-01-01 | 2026-08-28 |
| jma_daily_yokohama | 気圧_海面_平均 | 971 | 2024-01-01 | 2026-08-28 |
| jma_daily_yokohama | 気圧_現地_平均 | 971 | 2024-01-01 | 2026-08-28 |
| jma_daily_yokohama | 気温_平均 | 971 | 2024-01-01 | 2026-08-28 |
| jma_daily_yokohama | 気温_最低 | 971 | 2024-01-01 | 2026-08-28 |
| jma_daily_yokohama | 気温_最高 | 971 | 2024-01-01 | 2026-08-28 |
| jma_daily_yokohama | 湿度_平均 | 971 | 2024-01-01 | 2026-08-28 |
| jma_daily_yokohama | 湿度_最小 | 971 | 2024-01-01 | 2026-08-28 |
| jma_daily_yokohama | 降水量_合計 | 971 | 2024-01-01 | 2026-08-28 |
| jma_daily_yokohama | 降水量_最大_10分間 | 971 | 2024-01-01 | 2026-08-28 |
| jma_daily_yokohama | 降水量_最大_1時間 | 971 | 2024-01-01 | 2026-08-28 |
| jma_daily_yokohama | 雪_最深積雪_値 | 971 | 2024-01-01 | 2026-08-28 |
| jma_daily_yokohama | 雪_降雪_合計 | 971 | 2024-01-01 | 2026-08-28 |
| jma_daily_yokohama | 風向・風速_平均 風速 | 971 | 2024-01-01 | 2026-08-28 |
| jma_daily_yokohama | 風向・風速_最大瞬間風速_風向 | 971 | 2024-01-01 | 2026-08-28 |
| jma_daily_yokohama | 風向・風速_最大瞬間風速_風速 | 971 | 2024-01-01 | 2026-08-28 |
| jma_daily_yokohama | 風向・風速_最大風速_風向 | 971 | 2024-01-01 | 2026-08-28 |
| jma_daily_yokohama | 風向・風速_最大風速_風速 | 971 | 2024-01-01 | 2026-08-28 |
| jma_monthly_kanagawa | 日照 時間 | 668 | 2019-01 | 2026-12 |
| jma_monthly_kanagawa | 気温_平均_日平均 | 668 | 2019-01 | 2026-12 |
| jma_monthly_kanagawa | 気温_平均_日最低 | 668 | 2019-01 | 2026-12 |
| jma_monthly_kanagawa | 気温_平均_日最高 | 668 | 2019-01 | 2026-12 |
| jma_monthly_kanagawa | 気温_最低 | 668 | 2019-01 | 2026-12 |
| jma_monthly_kanagawa | 気温_最高 | 668 | 2019-01 | 2026-12 |
| jma_monthly_kanagawa | 湿度_平均 | 668 | 2019-01 | 2026-12 |
| jma_monthly_kanagawa | 湿度_最小 | 668 | 2019-01 | 2026-12 |
| jma_monthly_kanagawa | 降水量_合計 | 668 | 2019-01 | 2026-12 |
| jma_monthly_kanagawa | 降水量_最大_10分間 | 668 | 2019-01 | 2026-12 |
| jma_monthly_kanagawa | 降水量_最大_1時間 | 668 | 2019-01 | 2026-12 |
| jma_monthly_kanagawa | 降水量_最大_日 | 668 | 2019-01 | 2026-12 |
| jma_monthly_kanagawa | 風向・風速_平均 風速 | 668 | 2019-01 | 2026-12 |
| jma_monthly_kanagawa | 風向・風速_最大瞬間風速_風向 | 668 | 2019-01 | 2026-12 |
| jma_monthly_kanagawa | 風向・風速_最大瞬間風速_風速 | 668 | 2019-01 | 2026-12 |
| jma_monthly_kanagawa | 風向・風速_最大風速_風向 | 668 | 2019-01 | 2026-12 |
| jma_monthly_kanagawa | 風向・風速_最大風速_風速 | 668 | 2019-01 | 2026-12 |
| jma_monthly_kanagawa | 雪_最深 積雪 | 576 | 2019-01 | 2026-12 |
| jma_monthly_kanagawa | 雪_降雪の深さ_合計 | 576 | 2019-01 | 2026-12 |
| jma_monthly_kanagawa | 雪_降雪の深さ_日合計の最大 | 576 | 2019-01 | 2026-12 |
| jma_monthly_kanagawa | 大気現象_雪日数 | 92 | 2019-01 | 2026-08 |
| jma_monthly_kanagawa | 大気現象_雷日数 | 92 | 2019-01 | 2026-08 |
| jma_monthly_kanagawa | 大気現象_霧日数 | 92 | 2019-01 | 2026-08 |
| jma_monthly_kanagawa | 気圧_海面_平均 | 92 | 2019-01 | 2026-08 |
| jma_monthly_kanagawa | 気圧_現地_平均 | 92 | 2019-01 | 2026-08 |
| jma_monthly_kanagawa | 雪_最深積雪 | 92 | 2019-01 | 2026-08 |
| jma_monthly_kanagawa | 雪_降雪_合計 | 92 | 2019-01 | 2026-08 |
| jma_monthly_kanagawa | 雪_降雪_日合計の最大 | 92 | 2019-01 | 2026-08 |
| jma_monthly_kanagawa | 雲量_平均 | 1 | 2019-01 | 2019-01 |

## 7. organism_records: 種数・科数・年別件数
- 総レコード数: 823692
- 学名のユニーク数（≒種数、rank不問）: 33130
- 科(family)のユニーク数: 2192

| year | source_id | 件数 |
|---|---|---|
| 2026 | gbif_kanagawa_occurrences | 20975 |
| 2026 | inaturalist_kanagawa | 50215 |
| 2025 | gbif_kanagawa_occurrences | 16346 |
| 2025 | inaturalist_kanagawa | 40251 |
| 2024 | gbif_kanagawa_occurrences | 77116 |
| 2024 | inaturalist_kanagawa | 22384 |
| 2023 | gbif_kanagawa_occurrences | 57992 |
| 2023 | inaturalist_kanagawa | 17817 |
| 2022 | gbif_kanagawa_occurrences | 49599 |
| 2022 | inaturalist_kanagawa | 9438 |
| 2021 | gbif_kanagawa_occurrences | 35344 |
| 2021 | inaturalist_kanagawa | 6610 |
| 2020 | gbif_kanagawa_occurrences | 19597 |
| 2020 | inaturalist_kanagawa | 6242 |
| 2019 | gbif_kanagawa_occurrences | 20071 |
| 2019 | inaturalist_kanagawa | 5350 |
| 2018 | gbif_kanagawa_occurrences | 16385 |
| 2018 | inaturalist_kanagawa | 2473 |
| 2017 | gbif_kanagawa_occurrences | 8545 |
| 2017 | inaturalist_kanagawa | 722 |
| 2016 | gbif_kanagawa_occurrences | 13403 |
| 2016 | inaturalist_kanagawa | 958 |
| 2015 | gbif_kanagawa_occurrences | 15621 |
| 2015 | inaturalist_kanagawa | 568 |
| 2014 | gbif_kanagawa_occurrences | 15181 |
| 2014 | inaturalist_kanagawa | 479 |
| 2013 | gbif_kanagawa_occurrences | 14476 |
| 2013 | inaturalist_kanagawa | 402 |
| 2012 | gbif_kanagawa_occurrences | 7969 |
| 2012 | inaturalist_kanagawa | 229 |
| 2011 | gbif_kanagawa_occurrences | 7140 |
| 2011 | inaturalist_kanagawa | 86 |
| 2010 | gbif_kanagawa_occurrences | 7007 |
| 2010 | inaturalist_kanagawa | 114 |
| 2009 | gbif_kanagawa_occurrences | 10685 |
| 2009 | inaturalist_kanagawa | 35 |
| 2008 | gbif_kanagawa_occurrences | 9362 |
| 2008 | inaturalist_kanagawa | 83 |
| 2007 | gbif_kanagawa_occurrences | 7672 |
| 2007 | inaturalist_kanagawa | 42 |
| 2006 | gbif_kanagawa_occurrences | 5607 |
| 2006 | inaturalist_kanagawa | 20 |
| 2005 | gbif_kanagawa_occurrences | 5501 |
| 2005 | inaturalist_kanagawa | 26 |
| 2004 | gbif_kanagawa_occurrences | 4178 |
| 2004 | inaturalist_kanagawa | 5 |
| 2003 | gbif_kanagawa_occurrences | 3793 |
| 2003 | inaturalist_kanagawa | 13 |
| 2002 | gbif_kanagawa_occurrences | 2295 |
| 2002 | inaturalist_kanagawa | 11 |
| 2001 | gbif_kanagawa_occurrences | 4371 |
| 2001 | inaturalist_kanagawa | 463 |
| 2000 | gbif_kanagawa_occurrences | 4874 |
| 2000 | inaturalist_kanagawa | 5 |
| 1999 | gbif_kanagawa_occurrences | 6270 |
| 1999 | inaturalist_kanagawa | 1 |
| 1998 | gbif_kanagawa_occurrences | 6053 |
| 1998 | inaturalist_kanagawa | 8 |
| 1997 | gbif_kanagawa_occurrences | 5086 |
| 1997 | inaturalist_kanagawa | 1 |

### レッドリストカテゴリ別件数（taxa結合で一致した分のみ）
| red_list_category | 件数 |
|---|---|
| 準絶滅危惧（NT） | 1646 |
| 絶滅危惧Ⅱ類（VU） | 1472 |
| 絶滅危惧ⅠB類（EN） | 425 |
| 絶滅のおそれのある地域個体群（LP） | 418 |
| 絶滅危惧ⅠA類（CR） | 220 |
| 情報不足（DD） | 209 |
| 絶滅危惧ⅠＢ類（EN） | 152 |
| 絶滅危惧ⅠＡ類（CR） | 130 |
| 注目種 | 99 |
| 絶滅危惧II類（VU） | 90 |
| 絶滅（EX） | 80 |
| 絶滅危惧IB類（EN） | 47 |
| 絶滅危惧Ⅰ類（CR+EN） | 10 |
| 絶滅危惧I類（CR+EN） | 3 |
| 絶滅危惧IB 類（EN） | 3 |
| 絶滅危惧IA類（CR） | 3 |
| 絶滅危惧IA 類（CR） | 1 |

- is_alien=1 件数: 3721
- publication_scope別: [('全公開', 818684), ('限定共有', 5008)]

## 8. 外部キーの孤児（存在しないsite_id等を参照しているレコード）
| 参照関係 | 孤児件数 |
|---|---|
| events.site_id -> sites | 0 |
| measurements.site_id -> sites | 0 |
| measurements.event_id -> events | 0 |
| sensor_timeseries.site_id -> sites | 344137 |
| organism_records.site_id -> sites | 0 |

補足: `sensor_timeseries` の `env_kousui`以外のセンサー系（そらまめ君・相模原市大気局）は、station master に緯度経度が存在しないため sites テーブルに地点が作られていない。そのため上表の sensor_timeseries 孤児件数には、この2ソース分の全行が含まれる（データの実際の欠落であり、本スクリプトの不具合ではない。詳細は本ファイル末尾参照）。

## 9. 神奈川県バウンディングボックス外のレコード数
bbox = lon:[138.9,139.8], lat:[35.1,35.7]
| table | bbox外件数 |
|---|---|
| sites | 2 |
| organism_records | 1014 |

## 10. 既知の欠落・スコープ外（意図的に未実施）

- **GBIF (`gbif_kanagawa_occurrences.jsonl`)**: 本検証時点で organism_records に 658360 件を
  取り込み済み（iNaturalistは 165332 件）。GBIF収集は2026-08-29の第3ラウンドで完走し
  （`data/logs/gbif_repair_run3.log`）、jsonl は 658,360行・重複0で確定している。同ログの
  最終突合では GBIF側 count=659,399 に対し 1,039件（区画取得不能93件＋日付フィールド欠損による
  分割不能958件）が未取得のまま残っており、区画別の内訳は `data/logs/gbif_partition_report.csv`
  に記録済み。`scripts/m03_organisms.py` は record_id をキーに INSERT ... ON CONFLICT DO UPDATE
  するため冪等であり、再実行しても重複せず既存行のライセンス3列だけが最新化される。

- **そらまめ君（大気）・相模原市大気局**: station master に緯度経度が一切収録されておらず
  （収集エージェントのコード上のコメントで「そらまめ君の公開CSVに緯度経度は含まれない」と明記）、
  `sites` には登録していない（要求「必ずlat/lonを持つものだけ入れる」に従う）。
  一方で `sensor_timeseries` には両ソースの実測値（そらまめ君168,793行・相模原市大気175,344行）を
  そのままロードしている。そのため `sensor_timeseries.site_id` は `soramame_stations_kanagawa__*` /
  `sagamihara_taiki_stations__*` という形式のIDを持つが、対応する `sites` 行は存在しない
  （＝意図的な孤児。上記セクション8参照）。緯度経度が判明すれば `sites` に追加登録できる設計にしてある。
- **相模原市大気データの単位**: 公開元に単位の記載が無いため `unit=NULL` のまま。推測していない。
- **県民参加型 河川モニタリング調査地点**: 収集済みデータは年度別の集計値（参加人数・捕獲調査地点数
  など5行のみ）であり、地点別の緯度経度・個別測定値は収集されていない。そのため `sites` にも
  `measurements` にも地点単位のレコードは作成していない。
- **moni1000（森林・里地・沿岸の鳥類/蝶類/哺乳類/植生調査など）・biodic植生メッシュ・丹沢関連・
  河川国勢調査など**: `sites`（`moni1000_sites`のみ）を除き、今回のタスク範囲外として
  `measurements`/`organism_records` には取り込んでいない（要求定義で明示された対象ではないため）。
