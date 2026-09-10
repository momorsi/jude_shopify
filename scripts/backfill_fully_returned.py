"""
One-off: flag every tracked order that already has nothing left to return.

New syncs set the flag as they process each order, but orders finished before the
flag existed never get touched again, so they would sit in the tracking file for
ever. Read-only against Shopify; the only write is the tracking file.

    python scripts/backfill_fully_returned.py                       # report only
    python scripts/backfill_fully_returned.py --write               # set the flags
    python scripts/backfill_fully_returned.py ~/Desktop/rt.json --write

With no path it uses data/returns_tracking.json, so run it from the same working
directory as the sync. Pass a path to work on a copy taken off the server.
"""
import asyncio
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.sync.sales.returns_sync_v4 import ReturnsSyncV4
from app.sync.sales.returns_tracking import ReturnsTrackingDB

CHUNK = 50
Q = """
query($first: Int!, $query: String) {
  orders(first: $first, query: $query) {
    edges { node {
      id name
      returns(first: 25) { edges { node { id } } }
      lineItems(first: 50) { edges { node { currentQuantity isGiftCard } } }
    } }
  }
}
"""


async def main(write, path):
    sync = ReturnsSyncV4()
    db = ReturnsTrackingDB(path) if path else ReturnsTrackingDB()
    if write:
        backup = db.db_path.with_suffix(db.db_path.suffix + ".bak")
        shutil.copy2(db.db_path, backup)
        print(f"backup written to {backup}")

    ids = [k.split("/")[-1] for k in db.data]
    orders = []
    for i in range(0, len(ids), CHUNK):
        fq = "(" + " OR ".join(f"id:{n}" for n in ids[i:i + CHUNK]) + ")"
        result = await sync.shopify_client.execute_query("local", Q, {"first": CHUNK, "query": fq})
        if result.get("msg") != "success":
            print(f"  chunk {i // CHUNK + 1} FAILED: {result.get('error')} -- aborting, nothing written")
            return 1
        orders += [e["node"] for e in result["data"]["orders"]["edges"]]

    if len(orders) != len(ids):
        print(f"Shopify returned {len(orders)} of {len(ids)} orders; the rest keep being checked")

    before = len(db.get_orders_to_check())
    if write:
        retired = sum(1 for o in orders if db.mark_fully_returned_if_exhausted(o))
    else:
        retired = sum(1 for o in orders if db.is_fully_returned(o))

    print(f"tracked orders   : {len(db.data)}")
    print(f"checked          : {len(orders)}")
    print(f"{'retired         ' if write else 'would retire    '}: {retired}")
    print(f"still followed   : {before - retired}")
    if not write:
        print("\ndry run -- pass --write to set the flags")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.exit(asyncio.run(main("--write" in sys.argv, args[0] if args else None)))
