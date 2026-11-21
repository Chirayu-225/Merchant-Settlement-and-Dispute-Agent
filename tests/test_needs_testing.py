from product import needs_testing


def test_required_items_are_present_and_complete():
    ids = {item["id"] for item in needs_testing.NEEDS_TESTING}
    assert needs_testing.REQUIRED_IDS <= ids
    for item in needs_testing.NEEDS_TESTING:
        assert item["status"] in ("flagged", "partly measured")
        for field in ("title", "what", "measured_so_far", "still_flagged", "how_to_test"):
            assert item[field].strip(), (item["id"], field)


def test_ids_are_unique():
    ids = [i["id"] for i in needs_testing.NEEDS_TESTING]
    assert len(ids) == len(set(ids))
