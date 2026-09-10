"""
Regression check for the returns follow-up query.

Two bugs, one query:

1. Follow-up used to take the first `batch_size` (10) rows of a date-filtered
   search, oldest first. Once the window held more than 10 orders, everything
   past the tenth was invisible -- order #9687's second return never reached SAP.

2. It was then changed to ask for every tracked order by id, which was complete
   but cost a request per 50 tracked orders, and it still windowed on the ORDER
   date: a return raised months after the sale could never be seen. Order #9092
   was placed 2026-07-05 and its second return came 2026-09-06.

Follow-up must now window on updated_at (creating a return bumps it), drain
every page, and process only orders it has a tracking row for.

Run: python test_returns_followup_query.py
"""
import asyncio
import math
import re
from datetime import datetime, timedelta

from app.sync.sales.returns_sync_v4 import ReturnsSyncV4, FOLLOWUP_PAGE_SIZE

ORDER_9092 = "gid://shopify/Order/7144041775170"   # placed 63 days before its 2nd return
ORDER_9687 = "gid://shopify/Order/7207304691778"   # sits past the old 10-row cutoff
UNTRACKED = "gid://shopify/Order/7207309999999"    # synced tag, no tracking row

TRACKED = [f"gid://shopify/Order/{7207305000000 + i}" for i in range(150)]
TRACKED += [ORDER_9687, ORDER_9092]

# What Shopify would return for the window: every tracked order plus one that we
# have no processing history for.
UPDATED_IN_WINDOW = TRACKED + [UNTRACKED]


class FakeTrackingDB:
    def get_orders_to_check(self):
        return list(TRACKED)


class FakeShopify:
    """Stands in for Shopify: honours `first`, and pages via `after`."""

    def __init__(self):
        self.calls = []

    async def execute_query(self, store_key, query, variables):
        self.calls.append(variables)
        if re.search(r"id:\d+", variables["query"]):
            raise AssertionError(
                f"follow-up must not enumerate tracked orders by id: {variables['query']!r}"
            )
        start = int(variables["after"] or 0)
        end = start + variables["first"]
        page = UPDATED_IN_WINDOW[start:end]
        return {
            "msg": "success",
            "data": {"orders": {
                "edges": [{"node": {"id": oid, "name": f"#{oid[-4:]}"}} for oid in page],
                "pageInfo": {
                    "hasNextPage": end < len(UPDATED_IN_WINDOW),
                    "endCursor": str(end),
                },
            }},
        }


class FakeConfig:
    returns_followup_days_old = 30
    returns_batch_size = 10


async def main():
    sync = object.__new__(ReturnsSyncV4)
    sync.shopify_client = FakeShopify()
    sync.config = FakeConfig()

    result = await sync.get_orders_from_shopify("local", "followup", FakeTrackingDB())
    returned = [e["node"]["id"] for e in result["orders"]["edges"]]

    assert ORDER_9092 in returned, "an order whose return came long after the sale was dropped"
    assert ORDER_9687 in returned, "order #9687 was dropped by the follow-up query"
    assert UNTRACKED not in returned, "an order with no tracking row would get a duplicate credit note"
    assert returned == TRACKED, f"expected all {len(TRACKED)} tracked orders, got {len(returned)}"

    # One window query, drained page by page. The window is what bounds the cost --
    # it scales with recent activity, not with the ever-growing tracking file.
    pages = math.ceil(len(UPDATED_IN_WINDOW) / FOLLOWUP_PAGE_SIZE)
    assert len(sync.shopify_client.calls) == pages, \
        f"expected {pages} pages for {len(UPDATED_IN_WINDOW)} rows, got {len(sync.shopify_client.calls)}"
    assert pages < math.ceil(len(TRACKED) / FOLLOWUP_PAGE_SIZE) + 1, \
        "follow-up must not cost a request per page of tracked orders"
    # The per-order payload costs ~12 points; 100 rows exceeds Shopify's 1000-point
    # single-query limit, which is a runtime failure, not a slow query.
    assert FOLLOWUP_PAGE_SIZE <= 50, "page size too large for the query cost limit"
    cutoff = (datetime.now() - timedelta(days=FakeConfig.returns_followup_days_old)).strftime("%Y-%m-%d")
    for variables in sync.shopify_client.calls:
        fq = variables["query"]
        assert f"updated_at:>={cutoff}" in fq, f"window must be on updated_at: {fq!r}"
        assert "-tag:sap_return_failed" in fq, f"lost the failed-tag exclusion: {fq!r}"
        assert "return_status:RETURNED" not in fq, \
            f"an order whose newest return is still open must stay in scope: {fq!r}"
        assert variables["first"] == FOLLOWUP_PAGE_SIZE

    # Empty tracking DB must not query Shopify at all.
    sync.shopify_client = FakeShopify()

    class EmptyDB:
        def get_orders_to_check(self):
            return []

    empty = await sync.get_orders_from_shopify("local", "followup", EmptyDB())
    assert empty["orders"]["edges"] == []
    assert sync.shopify_client.calls == []

    print(f"OK - {len(returned)} tracked orders returned in {pages} request(s); "
          f"#9092 and #9687 included, untracked order excluded")


if __name__ == "__main__":
    asyncio.run(main())
