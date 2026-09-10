"""
An order with nothing left to return must drop out of follow-up.

Every tracked order is carried through every future follow-up window, for ever.
Once each line on an order has been returned, no new return can ever arrive on it,
so checking it again is pure cost. Shopify zeroes a line's currentQuantity when it
is returned or refunded, which is the signal used here.

Run: python test_fully_returned_retirement.py
"""
import json
import tempfile
from pathlib import Path

from app.sync.sales.returns_tracking import ReturnsTrackingDB

RETURN_1 = "gid://shopify/Return/1"
RETURN_2 = "gid://shopify/Return/2"


def order(order_id, returns, lines):
    return {
        "id": order_id,
        "returns": {"edges": [{"node": {"id": r}} for r in returns]},
        "lineItems": {"edges": [{"node": dict(n)} for n in lines]},
    }


def item(current, is_gift_card=False):
    return {"quantity": 1, "currentQuantity": current, "isGiftCard": is_gift_card}


def db_with(rows):
    path = Path(tempfile.mkdtemp()) / "returns_tracking.json"
    path.write_text(json.dumps(rows))
    return ReturnsTrackingDB(str(path))


def tracked(order_id, return_ids, fully_returned=False):
    row = {
        "order_id": order_id,
        "order_name": "#" + order_id[-4:],
        "created_at": "2026-07-05T18:42:17Z",
        "processed_returns": [{"return_id": r, "credit_note_entry": 1, "items": []} for r in return_ids],
    }
    if fully_returned:
        row["fully_returned"] = True
    return row


def main():
    # A single-item order, that one item returned -> retire it.
    db = db_with({"o1": tracked("o1", [RETURN_1])})
    assert db.mark_fully_returned_if_exhausted(order("o1", [RETURN_1], [item(0)])) is True
    assert db.get_orders_to_check() == [], "a spent single-item order must leave follow-up"
    assert json.loads(Path(db.db_path).read_text())["o1"]["fully_returned"] is True, "flag must persist"

    # Two items, both returned across two returns -> retire it.
    db = db_with({"o2": tracked("o2", [RETURN_1, RETURN_2])})
    assert db.mark_fully_returned_if_exhausted(
        order("o2", [RETURN_1, RETURN_2], [item(0), item(0)])) is True
    assert db.get_orders_to_check() == []

    # Two items, only one returned -> the other can still come back. Keep it.
    db = db_with({"o3": tracked("o3", [RETURN_1])})
    assert db.mark_fully_returned_if_exhausted(order("o3", [RETURN_1], [item(0), item(1)])) is False
    assert db.get_orders_to_check() == ["o3"]

    # Gift card lines keep their quantity for ever and must not hold an order open.
    db = db_with({"o4": tracked("o4", [RETURN_1])})
    assert db.mark_fully_returned_if_exhausted(
        order("o4", [RETURN_1], [item(0), item(1, is_gift_card=True)])) is True

    # An unprocessed return means the order still owes SAP a credit note. Keep it.
    db = db_with({"o5": tracked("o5", [RETURN_1])})
    assert db.mark_fully_returned_if_exhausted(order("o5", [RETURN_1, RETURN_2], [item(0)])) is False
    assert db.get_orders_to_check() == ["o5"]

    # currentQuantity we cannot read is not proof of anything. Keep it.
    db = db_with({"o6": tracked("o6", [RETURN_1])})
    assert db.mark_fully_returned_if_exhausted(order("o6", [RETURN_1], [item(None)])) is False

    # The order query caps line items at 50; at the cap the order is not fully visible.
    db = db_with({"o7": tracked("o7", [RETURN_1])})
    assert db.mark_fully_returned_if_exhausted(order("o7", [RETURN_1], [item(0)] * 50)) is False
    assert db.mark_fully_returned_if_exhausted(order("o7", [RETURN_1], [item(0)] * 49)) is True

    # Already retired -> no repeated writes.
    db = db_with({"o8": tracked("o8", [RETURN_1], fully_returned=True)})
    assert db.mark_fully_returned_if_exhausted(order("o8", [RETURN_1], [item(0)])) is False
    assert db.get_orders_to_check() == []

    print("OK - spent orders retire from follow-up; partly-returned, unprocessed, "
          "unreadable and truncated orders stay")


if __name__ == "__main__":
    main()
