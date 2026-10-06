"""元号の基準年（西暦 = 基準 + 元号年）。requests 等に依存しない（v2 パイプラインの
`scripts/migrate/period.py` が import する。`scripts/common.py` は requests を import するため
パイプラインからは直接使えない。`scripts/common.py` の `ERA` はここから読む）。
"""

ERA = {"令和": 2018, "平成": 1988, "昭和": 1925, "R": 2018, "H": 1988, "S": 1925}
