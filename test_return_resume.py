"""
A retried return must resume the documents it already created, never duplicate them.

Order #9092's second return created credit note 3284, then failed because the gift
card lookup could not see the card. The retry has to pick 3284 back up and carry on
with the missing gift card invoice. Before this, two rules got in the way:

  * the credit note lookup returned the FIRST sap_return_cn_* tag, which belongs to
    an earlier return, and reuse was refused outright whenever the order had any
    processed return -- so the retry created a second credit note;
  * the gift card invoice lookup had the same shape, so a crash after the invoice
    but before reconciliation billed the customer a second invoice.

Both now resume the document that no processed return has claimed.

Run: python test_return_resume.py
"""
import asyncio

from app.sync.sales.returns_sync_v4 import ReturnsSyncV4

CARD_R1 = "gid://shopify/GiftCard/555505680450"   # first return's card, recorded
CARD_R2 = "gid://shopify/GiftCard/555944116290"   # second return's card

ORDER = {
    "id": "gid://shopify/Order/7144041775170",
    "name": "#9092",
    "tags": [
        "sap_invoice_34584", "sap_payment_32754",
        "sap_return_cn_3138",             # first return, recorded in tracking
        "sap_return_cn_3284",             # this return, created then abandoned
        "sap_giftcard_invoice_35448",     # first return's invoice, already reconciled
    ],
}

RETURNED_ITEMS = [{"ItemCode": "FG-0000830", "Quantity": 1, "UnitPrice": 6400.0}]

INVOICES = {
    "35448": {"DocEntry": 35448, "TransNum": 1, "DocumentLines": [{"U_GiftCard": "555505680450"}]},
    "36883": {"DocEntry": 36883, "TransNum": 2, "DocumentLines": [{"U_GiftCard": "555944116290"}]},
}


class FakeSAP:
    def __init__(self):
        self.reads = []

    async def _make_request(self, method, endpoint, params=None, data=None):
        self.reads.append(endpoint)
        entry = endpoint.split("(")[1].rstrip(")")
        if endpoint.startswith("Invoices("):
            return {"msg": "success", "data": INVOICES[entry]}
        raise AssertionError(f"unexpected SAP call: {endpoint}")


def sync():
    s = object.__new__(ReturnsSyncV4)
    s.sap_client = FakeSAP()
    return s


async def main():
    s = sync()

    # --- credit note: pick the one tracking has not claimed, not the first tag ---
    recorded = {"3138"}
    assert s._get_existing_credit_note_entry(ORDER, recorded) == "3284", \
        "must resume this return's credit note, not the earlier return's"
    assert s._get_existing_credit_note_entry(ORDER, {"3138", "3284"}) is None, \
        "with every credit note claimed there is nothing to resume"
    assert s._get_existing_credit_note_entry(ORDER, set()) == "3138"

    # --- and only when it is still open and covers exactly these items ---
    open_cn = {"DocumentStatus": "bost_Open", "DocumentLines": [{"ItemCode": "FG-0000830", "Quantity": 1.0}]}
    assert s._credit_note_matches_return(open_cn, RETURNED_ITEMS) is True
    closed = dict(open_cn, DocumentStatus="bost_Close")
    assert s._credit_note_matches_return(closed, RETURNED_ITEMS) is False, \
        "a closed credit note is already reconciled"
    wrong_item = {"DocumentStatus": "bost_Open", "DocumentLines": [{"ItemCode": "FG-0000575", "Quantity": 1.0}]}
    assert s._credit_note_matches_return(wrong_item, RETURNED_ITEMS) is False, \
        "a credit note for other items belongs to another return"
    wrong_qty = {"DocumentStatus": "bost_Open", "DocumentLines": [{"ItemCode": "FG-0000830", "Quantity": 2.0}]}
    assert s._credit_note_matches_return(wrong_qty, RETURNED_ITEMS) is False

    # --- gift card invoice: the earlier return's invoice must not be reused ---
    found = await s._find_resumable_gift_card_invoice(ORDER, [CARD_R1])
    assert found is None, "invoice 35448 is the first return's and is already reconciled"

    # --- but this return's own abandoned invoice must be picked back up ---
    s2 = sync()
    order_with_own = dict(ORDER, tags=ORDER["tags"] + ["sap_giftcard_invoice_36883"])
    found = await s2._find_resumable_gift_card_invoice(order_with_own, [CARD_R1])
    assert found is not None and found["entry"] == 36883, "must resume its own invoice"
    assert found["gift_card_id"] == CARD_R2, "and recover the gift card from its line"

    # --- once recorded, it is off limits again ---
    s3 = sync()
    assert await s3._find_resumable_gift_card_invoice(order_with_own, [CARD_R1, CARD_R2]) is None

    print("OK - retries resume credit note 3284 and their own gift card invoice; "
          "earlier returns' documents stay untouched")


if __name__ == "__main__":
    asyncio.run(main())
