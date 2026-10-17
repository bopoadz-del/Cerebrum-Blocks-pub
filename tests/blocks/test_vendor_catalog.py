"""Payload-asserting tests for the vendor_catalog block.

Assertions target catalog payloads (Decimal prices, availability gates,
closed category set, search filters, inactive-vendor refusals) so a
control-delete gut of process() turns them red.
"""

from app.blocks.vendor_catalog import VendorCatalogBlock


def make_block():
    return VendorCatalogBlock()


async def _vendor(block, vendor_id="v1", categories=None, active=True):
    return await block.process(
        {
            "vendor_id": vendor_id,
            "name": f"Vendor {vendor_id}",
            "categories": categories or ["food"],
            "service_radius_km": 5.0,
            "active": active,
        },
        params={"operation": "register_vendor"},
    )


async def test_register_vendor_and_add_item_roundtrip():
    block = make_block()
    vendor = await _vendor(block)
    assert vendor["status"] == "success"
    assert vendor["categories"] == ["food"]

    item = await block.process(
        {"vendor_id": "v1", "item_id": "i1", "name": "Burger", "price": "9.99", "category": "food"},
        params={"operation": "add_item"},
    )
    assert item["status"] == "success"
    assert item["price"] == "9.99"

    listed = await block.process({"vendor_id": "v1"}, params={"operation": "list_items"})
    assert listed["count"] == 1
    assert listed["items"][0]["name"] == "Burger"

    status = await block.process({"vendor_id": "v1"}, params={"operation": "status"})
    assert status["item_count"] == 1
    assert status["available_count"] == 1


async def test_inactive_vendor_cannot_list_items():
    block = make_block()
    await _vendor(block, vendor_id="v2", active=False)
    item = await block.process(
        {"vendor_id": "v2", "item_id": "i2", "name": "Pizza", "price": "12.00"},
        params={"operation": "add_item"},
    )
    assert item["status"] == "error"
    assert item["error"] == "vendor_inactive"


async def test_search_filters_by_keyword_category_and_price():
    block = make_block()
    await _vendor(block, "v3", ["food", "grocery"])
    await block.process(
        {"vendor_id": "v3", "item_id": "i3", "name": "Burger", "price": "9.99", "category": "food"},
        params={"operation": "add_item"},
    )
    await block.process(
        {"vendor_id": "v3", "item_id": "i4", "name": "Milk 1L", "price": "2.50", "category": "grocery"},
        params={"operation": "add_item"},
    )

    by_keyword = await block.process({"keyword": "milk"}, params={"operation": "search_items"})
    assert by_keyword["count"] == 1
    assert by_keyword["results"][0]["item_id"] == "i4"

    by_category = await block.process({"category": "food"}, params={"operation": "search_items"})
    assert by_category["count"] == 1

    by_price = await block.process({"price_max": "3.00"}, params={"operation": "search_items"})
    assert by_price["count"] == 1
    assert str(by_price["results"][0]["price"]) == "2.50"


async def test_availability_toggle_hides_from_search():
    block = make_block()
    await _vendor(block, "v4")
    await block.process(
        {"vendor_id": "v4", "item_id": "i5", "name": "Fries", "price": "3.50"},
        params={"operation": "add_item"},
    )
    toggled = await block.process(
        {"item_id": "i5", "available": False}, params={"operation": "set_availability"}
    )
    assert toggled["available"] is False

    search = await block.process({}, params={"operation": "search_items"})
    assert search["count"] == 0

    listed = await block.process({"vendor_id": "v4"}, params={"operation": "list_items"})
    assert listed["count"] == 1  # list still shows the item


async def test_closed_category_set_and_duplicate_ids():
    block = make_block()
    bad_vendor_cat = await _vendor(block, "v5", ["skydiving"])
    assert bad_vendor_cat["status"] == "error"
    assert "closed set" in bad_vendor_cat["error"]

    await _vendor(block, "v6")
    bad_item_cat = await block.process(
        {"vendor_id": "v6", "item_id": "i6", "name": "x", "price": "1.00", "category": "skydiving"},
        params={"operation": "add_item"},
    )
    assert bad_item_cat["status"] == "error"

    await block.process(
        {"vendor_id": "v6", "item_id": "i7", "name": "x", "price": "1.00"},
        params={"operation": "add_item"},
    )
    dup = await block.process(
        {"vendor_id": "v6", "item_id": "i7", "name": "x", "price": "1.00"},
        params={"operation": "add_item"},
    )
    assert dup["status"] == "success"
    assert dup["idempotent"] is True


async def test_negative_price_and_unknown_ids_fail_loud():
    block = make_block()
    await _vendor(block, "v7")
    negative = await block.process(
        {"vendor_id": "v7", "item_id": "i8", "name": "x", "price": "-1.00"},
        params={"operation": "add_item"},
    )
    assert negative["status"] == "error"

    ghost_vendor = await block.process(
        {"vendor_id": "ghost", "item_id": "i9", "name": "x", "price": "1.00"},
        params={"operation": "add_item"},
    )
    assert ghost_vendor["status"] == "error"
    assert ghost_vendor["error"] == "vendor_not_found"

    ghost_item = await block.process(
        {"item_id": "ghost-item"}, params={"operation": "set_availability"}
    )
    assert ghost_item["status"] == "error"
    assert ghost_item["error"] == "item_not_found"

    unknown = await block.process({}, params={"operation": "restock"})
    assert unknown["status"] == "error"
    assert "register_vendor" in unknown["available_operations"]
