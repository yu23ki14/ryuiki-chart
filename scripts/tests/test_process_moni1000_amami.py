"""奄美の抽出（process_moni1000_amami）が空振りしないことのテスト。小さな CSV を tmp_path に作る。"""
import pytest

pd = pytest.importorskip("pandas")  # CI の reconcile 環境には pandas が無い

import process_moni1000_amami as pa  # noqa: E402  (pandas を使うので importorskip の後)


def write(path, df):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8")


def sin04(tmp_path, rows):
    write(tmp_path / "SIN04/BirdData2010B.csv", pd.DataFrame(rows, columns=["サイトID", "都道府県", "市町村", "種名", "個体数"]))


def test_sin04_picks_amami_rows_only(tmp_path):
    sin04(tmp_path, [[200029, "鹿児島県", "奄美市", "ルリカケス", 1], [100474, "鹿児島県", "大島郡宇検村", "メジロ", 2],
                     [100243, "鹿児島県", "霧島市", "メジロ", 1], [1, "神奈川県", "奄美市", "メジロ", 1]])
    out = pa.extract_sin04(tmp_path)
    assert sorted(out["site_id"]) == [100474, 200029] and set(out["source_id"]) == {"moni1000_forest_bird_amami"}


def test_sin04_stops_when_no_files_or_no_rows(tmp_path):
    with pytest.raises(pa.ExtractError, match="BirdData"):
        pa.extract_sin04(tmp_path)
    sin04(tmp_path, [[100243, "鹿児島県", "霧島市", "メジロ", 1]])
    with pytest.raises(pa.ExtractError, match="0 行"):
        pa.extract_sin04(tmp_path)


@pytest.mark.parametrize("code", [460800, "460800", 460800.0, "460800.0"])
def test_sig02_matches_site_code_in_any_type(tmp_path, code):
    df = pd.DataFrame({"Site Code": [code, 130700], "Count": [1, 2]})
    write(tmp_path / "SIG02/一斉調査日個体数リスト表(2004-05以降).csv", df)
    out = pa.extract_sig02(tmp_path)
    assert len(out) == 1 and out["source_id"].iloc[0] == "moni1000_coast_shorebird_amami"


def test_sig02_stops_when_missing_or_empty(tmp_path):
    with pytest.raises(pa.ExtractError, match="無い"):
        pa.extract_sig02(tmp_path)
    write(tmp_path / "SIG02/一斉調査日個体数リスト表(2004-05以降).csv", pd.DataFrame({"Site Code": [130700], "Count": [1]}))
    with pytest.raises(pa.ExtractError, match="0 行"):
        pa.extract_sig02(tmp_path)
