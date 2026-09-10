"""
Free shipping and free gift items must not be invoiced to the customer.

Both left invoices permanently open by the un-collected amount (24 invoices,
2026-07 to 2026-08, EGP 26,020 total):

  #9497  "LOYALTY FREE SHIPPING"  - shipping 160 discounted to 0, but SAP was
         billed 100 revenue + 60 cost because totalShippingPriceSet reports the
         price BEFORE shipping discounts. Invoice open by 160.
  #9778  "Free gift with your order above 7k" - the gift line has
         discountedUnitPriceSet 0, and the old guard `sale_price > 0` skipped
         the discount calculation, so it went to SAP at 1800 @ 0%.
         Invoice open by 1800.

Run: python test_free_shipping_and_free_gift.py
"""
from app.sync.sales.orders_sync import OrdersSalesSync

CC = {"CostingCode": "ONL", "CostingCode2": "SAL", "CostingCode3": "OnlineS", "Warehouse": "SW",
      "COGSCostingCode": "ONL", "COGSCostingCode2": "SAL", "COGSCostingCode3": "OnlineS"}


def money(amount):
    return {"shopMoney": {"amount": str(amount), "currencyCode": "EGP"}}


def shipping_order(original, charged):
    return {
        "totalShippingPriceSet": money(original),
        "shippingLines": {"edges": [{"node": {"discountedPriceSet": money(charged)}}]},
    }


def line(sku, original, discounted):
    return {"node": {
        "id": f"gid://shopify/LineItem/{sku}", "name": sku, "sku": sku,
        "quantity": 1, "currentQuantity": 1,
        "originalUnitPriceSet": money(original),
        "discountedUnitPriceSet": money(discounted),
        "discountAllocations": [],
        "variant": {"sku": sku, "price": str(original), "compareAtPrice": str(original)},
    }}


sync = OrdersSalesSync()
freight = lambda o: sync._calculate_freight_expenses(o, "local", {}, CC, "Tuyingo")

# --- #9497: shipping 160 fully discounted -> nothing billed for freight -------
assert freight(shipping_order(160, 0)) == [], "free shipping must add no freight expense"

# --- unchanged behaviour when shipping is actually charged --------------------
paid = freight(shipping_order(160, 160))
assert [e["LineTotal"] for e in paid] == [100, 60], paid
assert [e["ExpenseCode"] for e in paid] == [6, 4], paid
assert all(e["DistributionRule"] == "ONL" for e in paid), paid

# config_data is a singleton - a previous order must not leak into the next one
from app.core.config import config_data
assert config_data["shopify"]["freight_config"]["local"]["160"]["revenue"] == {"ExpenseCode": 6, "LineTotal": 100}

# --- partial shipping discount scales both lines instead of dropping freight ---
half = freight(shipping_order(160, 80))
assert [e["LineTotal"] for e in half] == [50, 30], half

# --- pickup order: no shipping at all ----------------------------------------
assert freight({"totalShippingPriceSet": money(0), "shippingLines": {"edges": []}}) == []

# --- #9778: free gift line must reach SAP at 100% discount -------------------
order = dict(shipping_order(120, 120), **{
    "id": "gid://shopify/Order/1", "name": "#9778", "createdAt": "2026-08-02T10:00:00Z",
    "sourceName": "web", "sourceIdentifier": "", "displayFinancialStatus": "PAID", "displayFulfillmentStatus": "FULFILLED",
    "lineItems": {"edges": [line("FG-0000559", 1800, 0), line("FG-0000766", 9800, 9800)]},
    "subtotalPriceSet": money(9800), "totalPriceSet": money(9920),
    "discountApplications": {"edges": []}, "transactions": [], "refunds": [],
    "shippingAddress": {"address1": "1 Road", "city": "Cairo"}, "billingAddress": {},
    "fulfillmentOrders": {"edges": []}, "metafields": {"edges": []},
    "retailLocation": None, "customer": None, "tags": [],
})

invoice = sync.map_shopify_order_to_sap({"node": order}, "C0028898", "local")
lines = {l["ItemCode"]: l for l in invoice["DocumentLines"]}

gift = lines["FG-0000559"]
assert gift["UnitPrice"] == 1800.0, gift
assert gift["DiscountPercent"] == 100.0, gift          # was missing entirely -> billed 1800
assert gift["U_ItemDiscountAmount"] == 1800.0, gift

paid_line = lines["FG-0000766"]
assert "DiscountPercent" not in paid_line, paid_line    # full-price line untouched

# Invoice total must equal what the customer paid: 9800 items + 120 freight
billed = sum(l["UnitPrice"] * l["Quantity"] * (1 - l.get("DiscountPercent", 0) / 100)
             for l in invoice["DocumentLines"])
billed += sum(e["LineTotal"] for e in invoice.get("DocumentAdditionalExpenses", []))
assert billed == 9920.0, billed

print("OK - free shipping and free gift no longer inflate the SAP invoice")
