from apps.migration_wp.management.commands.extract_wp_catalog import Command


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
    assert Command._collect_attachment_ids([101, 102], meta) == [9001, 9002, 9003, 9004, 9005]


def test_ignores_blank_and_non_numeric_attachment_refs():
    meta = {101: {"_thumbnail_id": "", "_product_image_gallery": " , ,abc", "Small_Image_1": "n/a"}}
    assert Command._collect_attachment_ids([101], meta) == []


def test_product_with_no_meta_is_safe():
    assert Command._collect_attachment_ids([999], {}) == []
