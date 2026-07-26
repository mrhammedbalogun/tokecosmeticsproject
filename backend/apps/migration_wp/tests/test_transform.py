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


from apps.migration_wp.transform import (
    append_benefits,
    parse_benefits,
    parse_testimonials,
    parse_usps,
)


def test_parse_benefits_splits_on_double_space():
    raw = "Deeply moisturizes dry skin.  Soothes eczema.  Prevents flakiness."
    assert parse_benefits(raw) == [
        "Deeply moisturizes dry skin.",
        "Soothes eczema.",
        "Prevents flakiness.",
    ]


def test_parse_benefits_empty_returns_empty_list():
    assert parse_benefits("") == []
    assert parse_benefits(None) == []


def test_append_benefits_adds_ul_to_description():
    html = append_benefits("<p>Body cream.</p>", ["Soft skin.", "No irritation."])
    assert html == (
        "<p>Body cream.</p>\n"
        "<h3>Benefits</h3>\n"
        "<ul><li>Soft skin.</li><li>No irritation.</li></ul>"
    )


def test_append_benefits_with_no_benefits_returns_description_unchanged():
    assert append_benefits("<p>Body cream.</p>", []) == "<p>Body cream.</p>"


def test_parse_usps_reads_main_then_numbered_in_order():
    meta = {
        "product_main_usp": "Daily hydration, all-day softness.",
        "product_usp_1": "Relieves eczema.",
        "product_usp_3": "Absorbs fast.",
        "product_usp_4": "Smooths and protects.",
    }
    assert parse_usps(meta) == [
        "Daily hydration, all-day softness.",
        "Relieves eczema.",
        "Absorbs fast.",
        "Smooths and protects.",
    ]


def test_parse_usps_ignores_blank_and_missing():
    assert parse_usps({"product_main_usp": "", "product_usp_2": "   "}) == []


def test_parse_testimonials_groups_by_index():
    meta = {
        "Testimonial_1_Customer_Name": "Mayowa - Osogbo",
        "Testimonial_1_Review_Text": "My skin feels nourished.",
        "Testimonial_1_Skin_Concern": "",
        "Testimonial_1_Number_of_Item_Bought": "1",
        "Testimonial_2_Customer_Name": "Ada - Lagos",
        "Testimonial_2_Review_Text": "Gentle on my baby.",
        "Testimonial_2_Skin_Concern": "Eczema",
        "Testimonial_2_Number_of_Item_Bought": "3",
    }
    assert parse_testimonials(meta) == [
        {
            "name": "Mayowa - Osogbo",
            "text": "My skin feels nourished.",
            "skin_concern": "",
            "qty_bought": 1,
        },
        {
            "name": "Ada - Lagos",
            "text": "Gentle on my baby.",
            "skin_concern": "Eczema",
            "qty_bought": 3,
        },
    ]


def test_parse_testimonials_skips_entries_with_no_review_text():
    meta = {
        "Testimonial_1_Customer_Name": "Nobody",
        "Testimonial_1_Review_Text": "",
        "Testimonial_2_Customer_Name": "Ada",
        "Testimonial_2_Review_Text": "Great product.",
    }
    result = parse_testimonials(meta)
    assert len(result) == 1
    assert result[0]["name"] == "Ada"


def test_parse_testimonials_tolerates_non_numeric_quantity():
    meta = {
        "Testimonial_1_Review_Text": "Good.",
        "Testimonial_1_Number_of_Item_Bought": "a few",
    }
    assert parse_testimonials(meta)[0]["qty_bought"] is None
