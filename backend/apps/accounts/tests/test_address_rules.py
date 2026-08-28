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


def test_ng_requires_a_landmark():
    """A Nigerian street address frequently will not take a rider to the door;
    "opposite Shoprite, off Ikeja bus stop" is what does."""
    assert "landmark" in required_fields_for("NG")


def test_no_other_market_requires_a_landmark():
    """The mirror image of the postcode rule, and the reason this is not global: a
    GB/US/CA parcel routes on its postcode, so demanding a nearest-bus-stop there
    would read as a broken form and block a market we actively sell to."""
    for code in ("GB", "US", "CA", "FR", "ZZ", ""):
        assert "landmark" not in required_fields_for(code), code


def test_landmark_and_postcode_never_both_apply():
    """Each market gets ONE way of being found, not two. If a future market is added
    to both sets this fails, which is the moment to decide which one actually routes
    a parcel there rather than asking the shopper for both."""
    for code in ("NG", "GB", "US", "CA", "FR"):
        req = required_fields_for(code)
        assert not ("landmark" in req and "postcode" in req), code
