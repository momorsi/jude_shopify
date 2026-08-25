"""
Regression check for the returns follow-up query.

The follow-up sync used to ask Shopify for `tag:sap_invoice_synced ... created_at:>=<30d>`
and take the first `batch_size` (10) rows, oldest first, then filter client-side against
the tracking DB. Once the 30-day window held more than 10 tagged orders, every tracked
order past the tenth was invisible -- which is why order #9687's second return never
reached SAP. Follow-up must now ask for the tracked order ids explicitly.

Run: python test_returns_followup_query.py
"""
import asyncio
import re

from app.sync.sales.returns_sync_v4 import ReturnsSyncV4

ORDER_9687 = "gid://shopify/Order/7207304691778"
# 68 tracked orders in the window, mirroring production volume. #9687 sits 15th --
# past the old 10-row cutoff.
TRACKED = [f"gid://shopify/Order/{7207304000000 + i}" for i in range(14)]
TRACKED.append(ORDER_9687)
TRACKED += [f"gid://shopify/Order/{7207305000000 + i}" for i in range(53)]


class FakeTrackingDB:
    def get_orders_to_check(self, days_old=30):
        return list(TRACKED)


class FakeShopify:
    """Stands in for Shopify: honours the id: filter and the `first` page cap."""

    def __init__(self):
        self.filter_queries = []

    async def execute_query(self, store_key, query, variables):
        fq = variables["query"]
        self.filter_queries.append(fq)
        wanted = set(re.findall(r"id:(\d+)", fq))
        if not wanted:
            raise AssertionError(f"follow-up must filter by order id, got: {fq!r}")
        edges = [
            {"node": {"id": oid, "name": f"#{oid[-4:]}"}}
            for oid in TRACKED
            if oid.split("/")[-1] in wanted
        ][: variables["first"]]
        return {
            "msg": "success",
            "data": {"orders": {"edges": edges, "pageInfo": {"hasNextPage": False, "endCursor": None}}},
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

    assert ORDER_9687 in returned, "order #9687 was dropped by the follow-up query"
    assert returned == TRACKED, f"expected all {len(TRACKED)} tracked orders, got {len(returned)}"

    asked = []
    for fq in sync.shopify_client.filter_queries:
        ids = re.findall(r"id:(\d+)", fq)
        assert len(ids) <= 250, f"a single page cannot exceed Shopify's 250-row cap: {len(ids)}"
        assert len(fq) < 4000, f"filter query too long for Shopify search: {len(fq)} chars"
        assert "-tag:sap_return_failed" in fq, f"lost the failed-tag exclusion: {fq!r}"
        asked += ids
    assert set(asked) == {o.split("/")[-1] for o in TRACKED}, "not every tracked order was asked for"

    request_count = len(sync.shopify_client.filter_queries)

    # Empty tracking DB must not query Shopify at all.
    sync.shopify_client = FakeShopify()

    class EmptyDB:
        def get_orders_to_check(self, days_old=30):
            return []

    empty = await sync.get_orders_from_shopify("local", "followup", EmptyDB())
    assert empty["orders"]["edges"] == []
    assert sync.shopify_client.filter_queries == []

    print(f"OK - {len(returned)}/{len(TRACKED)} tracked orders returned in "
          f"{request_count} request(s), #9687 included")


if __name__ == "__main__":
    asyncio.run(main())
