"""c29（鹿児島県レッドリスト PDF）の行の切り分けのテスト。PDF は使わず、extract_text() が返す行を直接渡す。"""
import c29_kagoshima_redlist_2014 as c29
import c29b_kagoshima_ordinance_species as c29b


def sci(latin, rank_required=False):
    return c29.parse_scientific(latin, rank_required=rank_required)


def test_vernacular_and_latin_glued_or_spaced():
    assert c29.split_vernacular("アマミノクロウサギPentalagus furnessi") == ("アマミノクロウサギ", "Pentalagus furnessi")
    assert c29.split_vernacular("ヒモラン Lycopodium sieboldii Miquel.") == ("ヒモラン", "Lycopodium sieboldii Miquel.")
    assert c29.split_vernacular("ヒラミレモン（シーカシャー） _ a_s_t_a_tCitrus depressa Hayata")[0] == "ヒラミレモン（シーカシャー）"


def test_authors_are_dropped_from_scientific_name():
    assert sci("Lycopodium sieboldii Miquel.", True) == "Lycopodium sieboldii"
    assert sci("Arachniodes chinensis（ Rosenst.） Ching", True) == "Arachniodes chinensis"
    assert sci("Pyropia tenera（Kjellman） Kikuchi， Miyata 2011", True) == "Pyropia tenera"
    # 著者の前置詞（小文字）を種内小名と取り違えない（植物は階級語の直後だけ）
    assert sci("Genus species de Vriese", True) == "Genus species"


def test_infraspecific_ranks_kept_as_trinomial():
    assert sci("Lycopodium sieboldii var. christensenianum Tagawa", True) == "Lycopodium sieboldii var. christensenianum"
    assert sci("Euhadra herklotsi var.hyugana") == "Euhadra herklotsi var. hyugana"
    assert sci("Symplocos chinensis var. leucocarpa f. pilosa（Nakai） Ohwi", True) == \
        "Symplocos chinensis var. leucocarpa f. pilosa"
    # 動物は階級語なしの三名法
    assert sci("Pteropus dasymallus dasymallus") == "Pteropus dasymallus dasymallus"
    assert sci("Pteropus dasymallus dasymallus Temminck, 1825") == "Pteropus dasymallus dasymallus"
    assert sci("Rana narina Stejneger, 1901") == "Rana narina"


def test_author_particles_and_qualifiers_are_not_infraspecific():
    # 階級語なし（動物）でも、著者の小辞・修飾語を亜種小名に取らない
    for latin, want in (("Uca lactea de Haan", "Uca lactea"), ("Genus species von Siebold", "Genus species"),
                        ("Genus species van der Hoeven", "Genus species"), ("Genus species du Bois", "Genus species"),
                        ("Genus species la Cruz", "Genus species"), ("Genus species complex", "Genus species"),
                        ("Genus species group", "Genus species"), ("Genus species (de Haan, 1835)", "Genus species")):
        assert sci(latin) == want, latin
    # 後に著者（大文字）か行末が続く小文字語は亜種小名
    assert sci("Genus species subspecies Author") == "Genus species subspecies"


def test_subgenus_parenthesis_and_spacing_in_parens():
    assert sci("Satsuma（ Luchuhadra） adelinae") == "Satsuma adelinae"
    assert sci("Aegista（Aegista） squarrosa tokunoshimana") == "Aegista squarrosa tokunoshimana"
    assert c29.clean_latin("Satsuma（ Luchuhadra） adelinae") == "Satsuma(Luchuhadra) adelinae"
    assert sci("Melampu(s Melampus) taeniolus") == "Melampus taeniolus"


def test_sp_and_unresolved_names_have_empty_scientific_name():
    for latin in ("Ophieleotris sp. 1", "Taenioides sp.B", "Gekko sp.", "Rhinogobius sp. YB",
                  "Angustassiminea aff. parasitologica", "Aegista（Aegista） sp."):
        assert sci(latin) == "", latin


def test_garbled_glyphs_and_overflowing_letter():
    assert sci("Rhinogobius ㉁uviatilis") == "Rhinogobius fluviatilis"
    assert sci("Moellendorf㉀a（ Trichelix） tokunoensis") == "Moellendorffia tokunoensis"
    assert sci("Dryopteris hendersoni（i Bedd.） C. Chr.", True) == "Dryopteris hendersonii"
    assert sci("a_s_t_a_tCitrus depressa Hayata", True) == "Citrus depressa"


def test_category_roman_numeral_glyphs():
    assert c29.norm_category("絶滅危惧I 類") == "絶滅危惧Ⅰ類"
    assert c29.norm_category("絶滅危惧II 類") == "絶滅危惧Ⅱ類"
    assert c29.norm_category("絶滅危惧Ⅱ類") == "絶滅危惧Ⅱ類"
    assert c29.norm_category("準絶滅危惧") == "準絶滅危惧"
    assert c29.HEAD_RE.match("絶滅危惧I 類（603）").group(2) == "603"
    assert c29.HEAD_RE.match("情報不足（4）")


def parse(kind, texts, groups):
    return c29.parse_pdf_lines(c29.SRC[kind]["rank_required"], [(1, t) for t in texts], set(groups))


def test_rows_grouped_by_heading_and_counted():
    rows, counts, declared = parse("animals", [
        "哺乳類", "絶滅危惧Ⅰ類（2）",
        "オリイジネズミCrocidura orii",
        "アマミノクロウサギPentalagus furnessi",
        "準絶滅危惧（1）", "ヒメネズミApodemus argenteus",
        "鳥類", "情報不足（1）", "ミゾゴイGorsachius goisagi"], ["哺乳類", "鳥類"])
    assert [(r["taxon_group_ja"], r["category_code"], r["vernacular_name_ja"]) for r in rows] == [
        ("哺乳類", "CR+EN", "オリイジネズミ"), ("哺乳類", "CR+EN", "アマミノクロウサギ"),
        ("哺乳類", "NT", "ヒメネズミ"), ("鳥類", "DD", "ミゾゴイ")]
    assert counts[("哺乳類", "絶滅危惧Ⅰ類")] == declared[("哺乳類", "絶滅危惧Ⅰ類")] == 2


def test_wrapped_lines_are_joined():
    # 括弧書きの折り返し（閉じ括弧だけ余る行）
    rows, counts, _ = parse("animals", [
        "陸産貝類", "絶滅危惧Ⅰ類（1）",
        "ヒメユリヤマタカマイマイ Satsuma（ Luchuhadra） largillierti var. sooi （シラユキヤマタカマイマイ沖永良部島",
        "個体群）"], ["陸産貝類"])
    assert len(rows) == 1 and rows[0]["scientific_name"] == "Satsuma largillierti var. sooi"
    # 和名が 2 行・学名が 3 行目にはみ出す（アマミマルバネクワガタ請島亜種）
    rows, _, _ = parse("animals", [
        "昆虫類", "絶滅危惧Ⅰ類（1）",
        "アマミマルバネクワガタ請島亜種", "（ウケジママルバネクワガタ）", "Neolucanus protogenetitives hamaii"], ["昆虫類"])
    assert len(rows) == 1
    assert rows[0]["vernacular_name_ja"] == "アマミマルバネクワガタ請島亜種 （ウケジママルバネクワガタ）"
    # 植物で見出しより 2 行多かった原因: ラテン文字で始まる折り返し行（Type＝…, nov.）
    rows, _, _ = parse("plants", [
        "維管束植物", "絶滅危惧II 類（2）",
        "ケラマツツジ Rhododendron scabrum G. Don",
        "ホソバケラマツツジ Rhododendron scabrum var. angustifolium M. Ho_a, nom. nud（. Narrow leaved",
        "Type＝Rheophyte）"], ["維管束植物"])
    assert [r["scientific_name"] for r in rows] == ["Rhododendron scabrum", "Rhododendron scabrum var. angustifolium"]
    rows, _, _ = parse("plants", [
        "維管束植物", "準絶滅危惧（1）",
        "ナガバハグマ（オキナワハグマ） Ainsliaea maccroclinidioides var. oblonga（ Koidzumi） Hatusima, c",
        "nov."], ["維管束植物"])
    assert len(rows) == 1


def test_last_species_before_heading_is_not_a_group_name():
    lines = [(1, t) for t in ["哺乳類", "準絶滅危惧（1）", "ヒメネズミApodemus argenteus", "情報不足（1）", "ヤマネGlirulus japonica"]]
    assert c29._group_names(lines) == {"哺乳類"}


def test_ordinance_row_and_link():
    r = c29b.row_from_cells(["魚 類", "タメトモハゼ", "Ophieleotris sp.", "カワアナゴ科", "絶滅危惧Ⅰ類"], False)
    assert (r["group"], r["sci"], r["cat"]) == ("魚類", "", "絶滅危惧Ⅰ類")
    r = c29b.row_from_cells(["貝 類", "ムラクモカノコガイ", "Neritina （Vittoida） variegata", "アマオブネガイ科", "絶滅危惧Ⅰ類"], False)
    assert r["sci"] == "Neritina variegata"
    assert c29b.row_from_cells(["甲殻類", "ドウクツベンケイガニ", "Karstarma boholano", "ベンケイガニ科", "－"], False)["cat"] == ""
    assert c29b.row_from_cells(["分類", "種名（和名）", "種名（学名）", "科名", "県カテゴリー"], False) is None
    html = '<a href="documents/x_1.pdf">パンフレット</a><a href="/ad04/a/documents/y-1.pdf">鹿児島県指定希少野生動植物一覧表（PDF：86KB）</a>'
    assert c29b.find_pdf_url(html).endswith("/ad04/a/documents/y-1.pdf")


def test_ordinance_plants_use_rank_required_like_c29():
    row = ["植物", "テスト", "Genus species de Vriese", "科", "絶滅危惧Ⅱ類"]
    assert c29b.row_from_cells(row, c29.SRC["plants"]["rank_required"])["sci"] == "Genus species"
    assert c29.SRC["plants"]["rank_required"] is True and c29.SRC["animals"]["rank_required"] is False


def test_make_row_columns_and_category_code():
    r = c29.make_row(group="g", verna="v", sci="A b", raw="A b X", cat="準絶滅危惧", ref="u", year=2014,
                     sid="s", moe={"A b": "絶滅危惧IA類"})
    assert list(r) == c29.COLS
    assert (r["category_code"], r["national_category_ja"]) == ("NT", "絶滅危惧IA類")
    assert c29.make_row(group="g", verna="v", sci="", raw="", cat="", ref="u", year=2026, sid="s", moe={})["category_code"] == ""
