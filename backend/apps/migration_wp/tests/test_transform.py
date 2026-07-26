from apps.migration_wp.transform import clean_description


def test_strips_editor_data_attributes():
    raw = '<p data-start="162" data-end="542">Nourish your skin every day.</p>'
    assert clean_description(raw) == "<p>Nourish your skin every day.</p>"


def test_strips_nbsp_entities_and_trims():
    raw = "Toke shea butter is a daily moisturizer.\n&nbsp;\n"
    assert clean_description(raw) == "Toke shea butter is a daily moisturizer."


def test_preserves_real_markup():
    raw = '<strong data-start="251" data-end="267">no chemicals</strong> inside'
    assert clean_description(raw) == "<strong>no chemicals</strong> inside"


def test_empty_input_returns_empty_string():
    assert clean_description("") == ""
    assert clean_description(None) == ""
