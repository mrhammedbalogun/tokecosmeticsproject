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


from apps.migration_wp.transform import generate_sku, parse_option_values


def test_generate_sku_prefers_real_sku():
    assert generate_sku(existing_sku="TOKE-SHEA-50", wp_id=1234) == "TOKE-SHEA-50"


def test_generate_sku_falls_back_to_wp_id():
    assert generate_sku(existing_sku="", wp_id=1234) == "TC-WP-1234"
    assert generate_sku(existing_sku=None, wp_id=99) == "TC-WP-99"


def test_generate_sku_uses_variation_id_not_parent():
    """The whole point: two variations of one parent must not collide."""
    a = generate_sku(existing_sku="", wp_id=5001)
    b = generate_sku(existing_sku="", wp_id=5002)
    assert a != b


def test_parse_option_values_maps_taxonomy_axis_to_term_name():
    attrs = {"attribute_pa_product-size": "50ml"}
    term_names = {("pa_product-size", "50ml"): "50 ml"}
    assert parse_option_values(attrs, term_names) == {"Product Size": "50 ml"}


def test_parse_option_values_handles_non_taxonomy_axis():
    """shea-variant is a raw meta axis, not a pa_* taxonomy (4 variations use it)."""
    assert parse_option_values({"attribute_shea-variant": "Unscented"}, {}) == {
        "Shea Variant": "Unscented"
    }


def test_parse_option_values_falls_back_to_slug_when_term_missing():
    attrs = {"attribute_pa_size": "large"}
    assert parse_option_values(attrs, {}) == {"Size": "large"}


def test_parse_option_values_ignores_blank_values():
    assert parse_option_values({"attribute_pa_size": ""}, {}) == {}


def test_axis_label_preserves_acronyms_and_apostrophes():
    """`.title()` would give 'Uv Protection' and "It'S Scented" — both wrong."""
    assert parse_option_values({"attribute_pa_UV-protection": "high"}, {}) == {
        "UV Protection": "high"
    }
    assert parse_option_values({"attribute_pa_it's-scented": "yes"}, {}) == {
        "It's Scented": "yes"
    }


def test_parse_option_values_merges_multiple_axes():
    """Real variations carry several axes at once — taxonomy-backed and raw together."""
    attrs = {
        "attribute_pa_product-size": "100ml",
        "attribute_pa_price-options": "single",
        "attribute_shea-variant": "Unscented",
    }
    term_names = {
        ("pa_product-size", "100ml"): "100 ml",
        ("pa_price-options", "single"): "Single",
    }
    assert parse_option_values(attrs, term_names) == {
        "Product Size": "100 ml",
        "Price Options": "Single",
        "Shea Variant": "Unscented",
    }


from apps.migration_wp.transform import collect_attachment_ids, ordered_attachment_ids


def test_collects_thumbnail_gallery_and_acf_ids_deduped_and_sorted():
    meta = {
        101: {
            "_thumbnail_id": "9001",
            "_product_image_gallery": "9002,9003",
            "Small_Image_1": "9004",
            "Medium_Image_2": "9001",  # duplicate of the thumbnail
        },
        102: {"_thumbnail_id": "9005"},
    }
    assert collect_attachment_ids([101, 102], meta) == [9001, 9002, 9003, 9004, 9005]


def test_ignores_blank_and_non_numeric_attachment_refs():
    meta = {101: {"_thumbnail_id": "", "_product_image_gallery": " , ,abc", "Small_Image_1": "n/a"}}
    assert collect_attachment_ids([101], meta) == []


def test_product_with_no_meta_is_safe():
    assert collect_attachment_ids([999], {}) == []


def test_ordered_attachment_ids_puts_thumbnail_first_even_with_a_higher_id():
    """4 live products have an ACF image whose attachment id is LOWER than
    their thumbnail's -- sorting by id (like collect_attachment_ids does)
    would put that ACF image at position 0 instead of the thumbnail."""
    meta = {
        "_thumbnail_id": "9001",
        "_product_image_gallery": "9002",
        "Small_Image_1": "8999",  # uploaded before the thumbnail was set
    }
    assert ordered_attachment_ids(meta) == [9001, 9002, 8999]


def test_ordered_attachment_ids_dedupes_by_first_occurrence():
    meta = {
        "_thumbnail_id": "9001",
        "_product_image_gallery": "9002,9003",
        "Small_Image_1": "9004",
        "Medium_Image_2": "9001",  # duplicate of the thumbnail -- must not move it
    }
    assert ordered_attachment_ids(meta) == [9001, 9002, 9003, 9004]


def test_ordered_attachment_ids_ignores_blank_and_non_numeric_refs():
    meta = {"_thumbnail_id": "", "_product_image_gallery": " , ,abc", "Small_Image_1": "n/a"}
    assert ordered_attachment_ids(meta) == []


def test_ordered_attachment_ids_with_no_meta_is_safe():
    assert ordered_attachment_ids({}) == []
