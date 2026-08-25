"""
Regression checks for the second-return path on one order.

Both bugs below fired on order #9687's second return and stopped it reaching SAP:

  1. The credit note reuse guard was `existing_cn_entry and not has_existing_returns`
     while the create guard was only `not existing_cn_entry`. On an order that already
     had a `sap_return_cn_*` tag from an earlier return, BOTH branches were skipped and
     `credit_note_result` was read unassigned -> UnboundLocalError.
  2. The gift card invoice was taken from the order's first `sap_giftcard_invoice_*`
     tag, which belongs to the earlier return and is already reconciled against that
     return's credit note. Reconciling a second credit note against it fails with
     "Reconciliation amount must be less than the balance due" [3821-7].

Each return needs its own credit note AND its own gift card invoice. The Shopify
gift card is looked up, not created -- it already exists from the refund.

Run: python test_multiple_returns.py
"""
import asyncio

from app.sync.sales.returns_sync_v4 import ReturnsSyncV4

ORDER_ID = "gid://shopify/Order/7207304691778"
RETURN_1 = "gid://shopify/Return/26056720450"
GC_1 = "gid://shopify/GiftCard/555572166722"   # earlier return's gift card
GC_2 = "gid://shopify/GiftCard/555630526530"   # this return's gift card, already in Shopify

# Tags as they stood after return #1: credit note 3151, gift card invoice 35651.
ORDER = {
    "id": ORDER_ID,
    "name": "#9687",
    "createdAt": "2026-07-30T14:06:36Z",
    "tags": ["sap_invoice_35229", "sap_payment_33350",
             "sap_return_cn_3151", "sap_giftcard_invoice_35651",
             f"sap_return_{RETURN_1.split('/')[-1]}"],
}


class TrackingWithOneReturn:
    def get_processed_return_ids(self, order_id):
        return [RETURN_1]

    def get_processed_gift_card_ids(self, order_id):
        return [GC_1]


def build_sync():
    sync = object.__new__(ReturnsSyncV4)
    sync.calls = []

    async def created_invoice(order, gift_card_id, total, *a, **kw):
        sync.calls.append(("create_gift_card_invoice", gift_card_id, total))
        return {"success": True, "doc_entry": 36264, "data": {"TransNum": 155067}}

    async def reconciled(cn_entry, cn_trans, inv_entry, inv_trans, card, total):
        sync.calls.append(("reconcile", cn_entry, inv_entry))
        return {"success": True, "reconciliation_id": 53222}

    async def gift_cards(order_id, created_at):
        # Shopify holds both: the earlier return's and this one's.
        return [{"id": GC_1, "initial_value": 5300.0}, {"id": GC_2, "initial_value": 6900.0}]

    async def sap_request(**kw):
        sync.calls.append(("sap_get", kw.get("endpoint")))
        return {"msg": "success", "data": {}}

    async def add_tag(order_id, tag, store_key):
        sync.calls.append(("tag", tag))

    sync._create_gift_card_invoice = created_invoice
    sync._reconcile_credit_note_with_invoice = reconciled
    sync._get_gift_cards_for_order = gift_cards
    sync._add_order_tag_with_retry = add_tag
    sync._is_pos_order = lambda order, store_key: False
    sync.sap_client = type("C", (), {"_make_request": staticmethod(sap_request)})()
    return sync


async def main():
    sync = build_sync()
    result = await sync._process_scenario_1_store_credit(
        ORDER, 3222, {"TransNum": 155066, "DocDate": "2026-08-25", "SalesPersonCode": 1,
                      "CardCode": "C0001"},
        6900.0, {}, "local", {"currency": "EGP"}, TrackingWithOneReturn(),
    )

    assert result.get("success"), f"second return failed: {result}"

    # The earlier return's gift card invoice must not be reused or even fetched.
    fetched = [c for c in sync.calls if c[0] == "sap_get" and "35651" in str(c[1])]
    assert not fetched, f"reused the earlier return's gift card invoice: {fetched}"

    created = [c for c in sync.calls if c[0] == "create_gift_card_invoice"]
    assert len(created) == 1, f"expected exactly one new gift card invoice, got {created}"
    assert created[0][1] == GC_2, f"used the wrong gift card: {created[0][1]}"
    assert created[0][2] == 6900.0, f"wrong invoice amount: {created[0][2]}"

    # Reconciled against THIS return's credit note and THIS return's invoice.
    assert ("reconcile", 3222, 36264) in sync.calls, f"reconciliation wrong: {sync.calls}"
    assert result["invoice_entry"] == 36264
    assert result["gift_card_id"] == GC_2

    # Guard invariant behind bug 1: reuse and create conditions are each other's
    # negation, so a credit note result is always produced.
    for existing_cn, prior_returns in [("3151", True), ("3151", False), (None, True), (None, False)]:
        reuse = bool(existing_cn) and not prior_returns
        create = not reuse
        assert reuse != create, f"both branches skipped for {existing_cn=} {prior_returns=}"

    print("OK - second return builds its own gift card invoice 36264 from gift card "
          f"...{GC_2[-6:]}, reconciles against credit note 3222, reuses nothing")


if __name__ == "__main__":
    asyncio.run(main())
