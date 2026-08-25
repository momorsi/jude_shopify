"""
A return that only covers gift card lines must never produce SAP documents.

When the till issues the store-credit gift card twice, both land on the order as
gift card line items and staff void the duplicate by returning one of them. That
return is a correction, not merchandise coming back - crediting it would refund the
customer a second time. Observed on 14 orders between 2025-11 and 2026-06; #7209 is
the shape used here (Cascade Choker returned, then one of two identical 8,400 gift
card lines returned 54 seconds after the other was issued).

Run: python test_gift_card_only_returns.py
"""
from app.sync.sales.returns_sync_v4 import ReturnsSyncV4

CHOKER = "gid://shopify/LineItem/17190510002242"
GC_A = "gid://shopify/LineItem/17195916296258"
GC_B = "gid://shopify/LineItem/17195920162882"

ORDER = {
    "id": "gid://shopify/Order/6962298880066",
    "name": "#7209",
    "lineItems": {"edges": [
        {"node": {"id": CHOKER, "sku": "FG-0000844", "title": "Cascade Choker", "isGiftCard": False}},
        {"node": {"id": GC_A, "sku": None, "title": "Gift Card", "isGiftCard": True}},
        {"node": {"id": GC_B, "sku": None, "title": "Gift Card", "isGiftCard": True}},
    ]},
}


def ret(*line_item_ids):
    return {"reverseFulfillmentOrders": {"edges": [{"node": {"lineItems": {"edges": [
        {"node": {"fulfillmentLineItem": {"lineItem": {"id": lid}}}} for lid in line_item_ids
    ]}}}]}}


sync = object.__new__(ReturnsSyncV4)
check = sync._is_gift_card_only_return

# The duplicate gift card line -> skip.
assert check(ret(GC_A), ORDER) is True, "gift-card-only return must be skipped"
assert check(ret(GC_A, GC_B), ORDER) is True, "two gift card lines must be skipped"

# Real merchandise -> process.
assert check(ret(CHOKER), ORDER) is False, "merchandise return must NOT be skipped"

# Mixed: merchandise is present, so it has to be processed.
assert check(ret(CHOKER, GC_A), ORDER) is False, "mixed return must NOT be skipped"

# Unknown line item: never assume gift card, process it and let the normal path decide.
assert check(ret("gid://shopify/LineItem/999"), ORDER) is False, "unknown line must NOT be skipped"

# A return covering nothing is not a gift card return either.
assert check(ret(), ORDER) is False, "empty return must NOT be treated as gift-card-only"
assert check({}, ORDER) is False, "missing return details must NOT be treated as gift-card-only"

print("OK - gift-card-only returns skipped; merchandise, mixed, unknown and empty still processed")
