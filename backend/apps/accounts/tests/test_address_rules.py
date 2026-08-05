from apps.core.address_rules import required_fields_for


def test_ng_requires_state_region():
    req = required_fields_for("NG")
    assert "state_region" in req
    assert "line1" in req


def test_gb_requires_postcode():
    req = required_fields_for("GB")
    assert "postcode" in req
    assert "city_text" in req


def test_region_countries_keep_their_postcode_and_city():
    """The trap the old if/else invited: joining REGION_COUNTRIES must never cost
    GB/US/CA the postcode — it is the field that actually routes the parcel."""
    for code in ("GB", "US", "CA"):
        req = required_fields_for(code)
        assert "state_region" in req, code
        assert "city_text" in req, code
        assert "postcode" in req, code


def test_unknown_country_uses_text_no_postcode():
    req = required_fields_for("FR")
    assert "city_text" in req
    assert "postcode" not in req
    assert "state_region" not in req
