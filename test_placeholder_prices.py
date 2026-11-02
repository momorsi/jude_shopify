"""Checks placeholder repricing in app/sync/price_changes.py without touching Shopify."""
import asyncio
from decimal import Decimal as D
from unittest.mock import patch

from app.sync import price_changes as pc

REAL = [
    {"id": "r1", "title": "Pendant Only / None / None", "sku": "FG-1", "price": "5100.00"},
    {"id": "r2", "title": "Pendant & Chain / Short / None", "sku": "M,FG-1", "price": "8500.00"},
    {"id": "r3", "title": "Pendant & Chain / Long / None", "sku": "L,FG-1", "price": "9600.00"},
    {"id": "r4", "title": "Pendant & Cord / None / Black", "sku": "B,FG-1", "price": "6600.00"},
    {"id": "r5", "title": "Pendant & Cord / None / Brown", "sku": "N,FG-1", "price": "6600.00"},
]


def test_target_price():
    t = pc.placeholder_target_price
    assert t("Pendant Only / Long / Black", REAL) == D("5100")
    assert t("Pendant & Chain / Short / Black", REAL) == D("8500")
    assert t("Pendant & Chain / Long / Brown", REAL) == D("9600")
    assert t("Pendant & Chain / None / None", REAL) == D("8500")  # no length: cheapest
    assert t("Pendant & Cord / Long / None", REAL) == D("6600")


def product(handle, placeholders):
    variants = REAL + placeholders
    node = {"id": "p", "handle": handle, "variants": {"edges": [{"node": v} for v in variants]}}
    return {"msg": "success", "data": {"products": {"edges": [{"node": node}]}}}


def test_sweep_writes_only_stale_and_survives_a_bad_product():
    stale = {"id": "s1", "title": "Pendant Only / Short / None", "sku": None, "price": "4800.00"}
    current = [{"id": f"c{i}", "title": "Pendant & Cord / Long / None", "sku": None, "price": "6600.00"} for i in range(21)]
    good = product("good", [stale] + current)
    wrong_shape = product("bad", [])  # 5 variants only: must be refused
    calls = []

    async def query(store, q, variables):
        return wrong_shape if variables["q"] == "handle:bad" else good

    async def update(self, store, variant_id, price, sale, product_id):
        calls.append((variant_id, price, sale))
        return {"msg": "success"}

    async def no_sleep(_):
        pass

    with patch.object(pc, "PLACEHOLDER_PRODUCT_HANDLES", ["bad", "good"]), \
            patch.object(pc.multi_store_shopify_client, "execute_query", query), \
            patch.object(pc.PriceChangesSync, "update_variant_price", update), \
            patch.object(pc.asyncio, "sleep", no_sleep):
        result = asyncio.run(pc.price_changes_sync.sync_placeholder_prices("local"))

    assert calls == [("s1", "5100.00", None)]  # real variants and current placeholders untouched
    assert result == (1, 1)                    # bad product counted, good one still processed


if __name__ == "__main__":
    test_target_price()
    test_sweep_writes_only_stale_and_survives_a_bad_product()
    print("ok")
