"""
Delete orders already retired from follow-up (fully_returned) from the tracking file.

Optional housekeeping. The flag alone already keeps these orders out of every
follow-up window -- pruning only reclaims file size, and it throws away the record
of which returns reached SAP. Keep a copy before running it in anger.

    python scripts/prune_returns_tracking.py                       # report only
    python scripts/prune_returns_tracking.py --write               # delete, after a .bak
    python scripts/prune_returns_tracking.py ~/Desktop/rt.json --write

With no path it uses data/returns_tracking.json, so run it from the same working
directory as the sync. Pass a path to work on a copy taken off the server.
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.sync.sales.returns_tracking import ReturnsTrackingDB


def main(write, path):
    db = ReturnsTrackingDB(path) if path else ReturnsTrackingDB()
    retired = [oid for oid, t in db.data.items() if t.get("fully_returned")]
    print(f"tracking file : {db.db_path}")
    print(f"orders        : {len(db.data)}")
    print(f"retired       : {len(retired)}")
    print(f"still checked : {len(db.get_orders_to_check())}")

    if not retired:
        return 0
    if not write:
        print("\ndry run -- pass --write to delete them")
        return 0

    backup = db.db_path.with_suffix(db.db_path.suffix + ".bak")
    shutil.copy2(db.db_path, backup)
    removed = db.prune_fully_returned()
    print(f"\nbackup written to {backup}")
    print(f"deleted {removed} order(s); {len(db.data)} remain")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.exit(main("--write" in sys.argv, args[0] if args else None))
