"""
Run the returns follow-up sync for ONE order, for verifying a fix before letting
the scheduled follow-up loose on everything.

    python run_followup_for_order.py 7207304691778           # dry run: report only
    python run_followup_for_order.py 7207304691778 --write   # actually write to SAP

Must run with the same working directory as the real sync, so that
data/returns_tracking.json is the live tracking file -- otherwise the SAP
documents get created but recorded nowhere, and the next scheduled run will
process the same return a second time.
"""
import asyncio
import sys

from app.sync.sales.returns_sync_v4 import ReturnsSyncV4
from app.sync.sales.returns_tracking import ReturnsTrackingDB


class SingleOrderDB(ReturnsTrackingDB):
    def __init__(self, order_gid):
        super().__init__()
        self._only = order_gid

    def get_orders_to_check(self):
        return [self._only] if self._only in self.data else []


async def main(numeric_id, write):
    order_gid = f"gid://shopify/Order/{numeric_id}"
    sync = ReturnsSyncV4()
    db = SingleOrderDB(order_gid)

    if not db.get_orders_to_check():
        print(f"{order_gid} is not in {db.db_path} -- wrong working directory?")
        return 1

    stores = sync.config.get_enabled_stores()
    res = await sync.get_orders_from_shopify("local", "followup", db)
    edges = res.get("orders", {}).get("edges", [])
    if not edges:
        print(f"Shopify returned nothing for {order_gid}")
        return 1

    order = edges[0]["node"]
    shopify_returns = [
        r["node"]["id"] for r in order.get("returns", {}).get("edges", []) if r.get("node", {}).get("id")
    ]
    done = db.get_processed_return_ids(order_gid)
    new = [r for r in shopify_returns if r not in done]

    print(f"order          {order.get('name')} ({order_gid})")
    print(f"sap entries    {sync._extract_sap_doc_entries(order)}")
    print(f"returns        {len(shopify_returns)} total, {len(done)} already processed")
    for r in new:
        print(f"  UNPROCESSED  {r}")
    if not new:
        print("nothing to do")
        return 0

    if not write:
        print("\ndry run -- pass --write to create the SAP documents")
        return 0

    store = stores["local"]
    result = await sync._process_refunded_order(
        order,
        "local",
        {
            "name": store.name, "shop_url": store.shop_url, "api_version": store.api_version,
            "timeout": store.timeout, "currency": store.currency,
            "price_list": store.price_list, "enabled": store.enabled,
        },
        db,
        check_mode="followup",
    )
    print(f"\nresult: {result}")
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1], "--write" in sys.argv)))
