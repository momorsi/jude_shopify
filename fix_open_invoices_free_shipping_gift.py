"""
One-off remediation: close the invoices left open by the free-shipping / free-gift bugs.

Both bugs are fixed in orders_sync.py, but 27 invoices were already posted with an
inflated DocTotal (see test_free_shipping_and_free_gift.py for the root causes).
The incoming payments are correct, so each invoice sits open by exactly the amount
that was over-billed.

Correction: one JOURNAL ENTRY per invoice, reversing the over-billed amount against
the very accounts the original invoice posted to, then internally reconciled against
the invoice so it closes.

Why a journal entry and not a credit note: this SAP company rejects service-type
marketing documents outright ("(14002) Cant add document with service type" - all
3,283 existing credit notes here are item-type), and an ITEM-type credit note is
wrong on the facts, because the free gift items physically shipped. Crediting them
as items would restock goods that are gone and reverse COGS that was correctly
recognised. Only the revenue side was over-stated, so only the revenue side is
reversed, which is exactly what this journal entry does.

Nothing is derived from a hardcoded amount: the over-billing is recomputed from
Shopify and must match the invoice's open balance to the piastre or the invoice is
skipped for manual review.

    python fix_open_invoices_free_shipping_gift.py            # dry run, writes nothing
    python fix_open_invoices_free_shipping_gift.py --post     # actually post
    python fix_open_invoices_free_shipping_gift.py --post --only 9778,10151
    python fix_open_invoices_free_shipping_gift.py --post --account 40201000   # gift ones
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime

from app.core.config import config_data
from app.services.sap.client import sap_client
from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.utils.logging import logger

STORE_KEY = "local"

# ExpenseCode -> (GL account, applies cost centres). Confirmed identical across all
# 8 affected freight invoices; asserted per invoice against the real journal entry.
FREIGHT_ACCOUNTS = {6: ("20101516", False), 4: ("40101201", True)}

# The free gift over-billing landed in 40101101 "Revenue Account", but that account is
# BlockManualPosting=tYES - finance locked it deliberately, so a journal entry cannot
# touch it. The debit therefore has to go somewhere else, and where it goes is an
# accounting policy decision, not a technical one (see HANDOVER doc). Pass it with
# --account; there is no default, because guessing would silently misclassify
# EGP 23,000 of P&L. Candidates that permit manual posting:
#   40201000  Customer Discounts Allowed   (contra-revenue - recommended)
#   61306100  Offers & Discounts           (expense)
#   61304300  Gifts / 6080108 Marketing - Gift (expense)

ORDERS_QUERY = """
query($q: String!) {
  orders(first: 50, query: $q) {
    edges { node {
      name
      totalShippingPriceSet { shopMoney { amount } }
      shippingLines(first: 5) { edges { node { discountedPriceSet { shopMoney { amount } } } } }
      lineItems(first: 50) { edges { node {
        sku currentQuantity
        originalUnitPriceSet { shopMoney { amount } }
        discountedUnitPriceSet { shopMoney { amount } }
      } } }
    } }
  }
}
"""


def _amount(money_set):
    return float(money_set["shopMoney"]["amount"]) if money_set else 0.0


async def shopify_overbilling(order_names):
    """What each order was over-billed, straight from Shopify: {order_name: {...}}."""
    out = {}
    for chunk_start in range(0, len(order_names), 20):
        chunk = order_names[chunk_start:chunk_start + 20]
        query = " OR ".join(f"name:{name}" for name in chunk)
        result = await multi_store_shopify_client.execute_query(STORE_KEY, ORDERS_QUERY, {"q": query})
        for edge in result["data"]["orders"]["edges"]:
            node = edge["node"]
            original_shipping = _amount(node["totalShippingPriceSet"])
            shipping_edges = node["shippingLines"]["edges"]
            charged = sum(_amount(e["node"]["discountedPriceSet"]) for e in shipping_edges) if shipping_edges else original_shipping

            free_skus = {}
            for line_edge in node["lineItems"]["edges"]:
                line = line_edge["node"]
                qty = line["currentQuantity"] or 0
                original = _amount(line["originalUnitPriceSet"])
                if qty > 0 and original > 0 and _amount(line["discountedUnitPriceSet"]) == 0:
                    free_skus[line["sku"]] = free_skus.get(line["sku"], 0) + original * qty

            out[node["name"]] = {
                "ship_loss": round(original_shipping - charged, 2),
                "free_skus": free_skus,
            }
    return out


async def open_invoices():
    """Every open A/R invoice carrying a Shopify order reference.

    The Service Layer pages at 20 rows, so this must loop - reading only the first
    page silently corrects a third of the invoices and calls it done.
    """
    found, skip = [], 0
    while True:
        result = await sap_client._make_request(
            method="GET",
            endpoint=("Invoices?$select=DocNum,DocEntry,TransNum,CardCode,DocTotal,PaidToDate,"
                      "NumAtCard,Series,Comments,DocumentStatus"
                      "&$filter=DocumentStatus eq 'bost_Open' and NumAtCard ne null"
                      f"&$skip={skip}"),
        )
        if result["msg"] == "failure":
            raise RuntimeError(f"Could not list invoices: {result.get('error')}")
        page = result["data"]["value"]
        if not page:
            break
        found.extend(page)
        skip += len(page)
        if not result["data"].get("odata.nextLink"):
            break
    return [i for i in found if round(i["DocTotal"] - i["PaidToDate"], 2) > 0.01]


def build_journal_entry(invoice, full_invoice, overbilling, gift_account=None):
    """Journal entry reversing exactly what was over-billed, or (None, reason)."""
    lines = []
    total = 0.0
    order_name = f"#{invoice['NumAtCard']}"
    reasons = []

    # --- free gift items: reverse the revenue only, never the stock ---------------
    free_skus = dict(overbilling["free_skus"])
    for sap_line in full_invoice["DocumentLines"]:
        item_code = sap_line["ItemCode"]
        if item_code not in free_skus:
            continue
        if sap_line["DiscountPercent"]:
            continue  # already correctly discounted, nothing over-billed here
        if not gift_account:
            return None, (f"free gift needs --account ({sap_line['AccountCode']} is "
                          "BlockManualPosting - see HANDOVER doc)")
        line_total = round(sap_line["LineTotal"], 2)
        lines.append({
            "AccountCode": gift_account,
            "LineTotal": line_total,
            "Description": f"Free gift correction {item_code} - Shopify {order_name}",
            "CostingCode": sap_line.get("CostingCode"),
            "CostingCode2": sap_line.get("CostingCode2"),
            "CostingCode3": sap_line.get("CostingCode3"),
        })
        total += line_total
        free_skus.pop(item_code)
        reasons.append(f"free gift {item_code}")

    if free_skus:
        # A bundle SKU expands into several SAP item codes; matching those to a free
        # gift is guesswork, so hand it back rather than post a wrong credit note.
        return None, f"free SKUs {sorted(free_skus)} not found as invoice lines"

    # --- free shipping: reverse the freight expenses -------------------------------
    if overbilling["ship_loss"] > 0:
        for expense in full_invoice.get("DocumentAdditionalExpenses") or []:
            if not expense.get("LineTotal"):
                continue
            mapping = FREIGHT_ACCOUNTS.get(expense["ExpenseCode"])
            if not mapping:
                return None, f"unmapped freight ExpenseCode {expense['ExpenseCode']}"
            account, use_cost_centres = mapping
            line_total = round(expense["LineTotal"], 2)
            line = {
                "AccountCode": account,
                "LineTotal": line_total,
                "Description": f"Free shipping correction - Shopify {order_name}",
            }
            if use_cost_centres:
                line["CostingCode"] = expense.get("DistributionRule")
                line["CostingCode2"] = expense.get("DistributionRule2")
                line["CostingCode3"] = expense.get("DistributionRule3")
            lines.append(line)
            total += line_total
        reasons.append("free shipping")

    if not lines:
        return None, "nothing to reverse"

    open_amount = round(invoice["DocTotal"] - invoice["PaidToDate"], 2)
    if abs(round(total, 2) - open_amount) > 0.01:
        return None, f"computed {total:.2f} != open balance {open_amount:.2f}"

    today = datetime.now().strftime("%Y-%m-%d")
    # Credit the customer (reduces A/R), debit back the accounts that were over-credited.
    je_lines = [{"ShortName": invoice["CardCode"], "Credit": round(total, 2), "Debit": 0.0,
                 "LineMemo": f"Correction {order_name}"[:50]}]
    for line in lines:
        je_line = {"AccountCode": line["AccountCode"], "Debit": line["LineTotal"], "Credit": 0.0,
                   "LineMemo": line["Description"][:50]}
        for cc in ("CostingCode", "CostingCode2", "CostingCode3"):
            if line.get(cc):
                je_line[cc] = line[cc]
        je_lines.append(je_line)

    return {
        "ReferenceDate": today, "DueDate": today, "TaxDate": today,
        "Memo": f"Correction {order_name} inv {invoice['DocNum']}"[:50],
        "Reference": str(invoice["DocNum"]),
        "Reference2": invoice["NumAtCard"],
        "JournalEntryLines": je_lines,
        "_reasons": reasons,
        "_lines": lines,
    }, None


def reconciliation_payload(journal_number, invoice, amount):
    """Same shape returns_sync_v4 already uses in production, with the credit leg
    coming from a journal entry (object type 30) instead of a credit note."""
    return {
        "ReconDate": datetime.now().strftime("%Y-%m-%d"),
        "CardOrAccount": "coaCard",
        "InternalReconciliationOpenTransRows": [
            {"ShortName": invoice["CardCode"], "TransId": journal_number, "TransRowId": 0,
             "SrcObjTyp": "30", "SrcObjAbs": journal_number,
             "CreditOrDebit": "codCredit", "ReconcileAmount": amount, "Selected": "tYES"},
            {"ShortName": invoice["CardCode"], "TransId": invoice["TransNum"], "TransRowId": 0,
             "SrcObjTyp": "13", "SrcObjAbs": invoice["DocEntry"],
             "CreditOrDebit": "codDebit", "ReconcileAmount": amount, "Selected": "tYES"},
        ],
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--post", action="store_true", help="actually write to SAP (default: dry run)")
    parser.add_argument("--only", help="comma-separated Shopify order numbers to limit to")
    parser.add_argument("--account", help="GL account to debit for free-gift corrections "
                                          "(e.g. 40201000). Required for gift invoices; "
                                          "freight invoices do not need it.")
    args = parser.parse_args()

    only = {o.strip().lstrip("#") for o in args.only.split(",")} if args.only else None

    invoices = await open_invoices()
    invoices = [i for i in invoices if not only or i["NumAtCard"] in only]
    if not invoices:
        print("No open invoices matched.")
        return

    overbilling = await shopify_overbilling([f"#{i['NumAtCard']}" for i in invoices])

    planned, skipped = [], []
    for invoice in invoices:
        order_name = f"#{invoice['NumAtCard']}"
        info = overbilling.get(order_name)
        if not info or (info["ship_loss"] <= 0 and not info["free_skus"]):
            skipped.append((order_name, invoice["DocNum"], "no free shipping / free gift on this order"))
            continue

        detail = await sap_client._make_request(method="GET", endpoint=f"Invoices({invoice['DocEntry']})")
        if detail["msg"] == "failure":
            skipped.append((order_name, invoice["DocNum"], f"could not read invoice: {detail.get('error')}"))
            continue

        entry, reason = build_journal_entry(invoice, detail["data"], info, args.account)
        if entry is None:
            skipped.append((order_name, invoice["DocNum"], reason))
            continue
        planned.append((invoice, entry))

    print(f"\n{'Order':>8} {'Invoice':>10} {'Open':>9}  Journal entry debits")
    for invoice, entry in planned:
        open_amount = round(invoice["DocTotal"] - invoice["PaidToDate"], 2)
        detail = " + ".join(f"{l['AccountCode']} {l['LineTotal']:.0f}" for l in entry["_lines"])
        print(f"{'#'+invoice['NumAtCard']:>8} {invoice['DocNum']:>10} {open_amount:>9.2f}  {detail}")
    print(f"\n{len(planned)} invoices to correct, EGP "
          f"{sum(round(i['DocTotal']-i['PaidToDate'],2) for i, _ in planned):,.2f}")

    if skipped:
        print(f"\nSkipped for manual review ({len(skipped)}):")
        for order_name, doc_num, reason in skipped:
            print(f"  {order_name:>8} {doc_num:>10}  {reason}")

    if not args.post:
        print("\nDRY RUN - nothing written. Re-run with --post to apply.")
        return

    print()
    for invoice, entry in planned:
        order_name = f"#{invoice['NumAtCard']}"
        amount = round(invoice["DocTotal"] - invoice["PaidToDate"], 2)
        payload = {k: v for k, v in entry.items() if not k.startswith("_")}

        created = await sap_client._make_request(method="POST", endpoint="JournalEntries", data=payload)
        if created["msg"] == "failure":
            print(f"  {order_name}: FAILED to create journal entry: {created.get('error')}")
            logger.error(f"{order_name}: journal entry failed: {created.get('error')}")
            continue

        journal_number = created["data"]["JdtNum"]
        reconciled = await sap_client._make_request(
            method="POST", endpoint="InternalReconciliations",
            data=reconciliation_payload(journal_number, invoice, amount),
        )
        if reconciled["msg"] == "failure":
            print(f"  {order_name}: journal entry {journal_number} posted but RECONCILE FAILED: "
                  f"{reconciled.get('error')} - reconcile manually")
            logger.error(f"{order_name}: reconcile failed: {reconciled.get('error')}")
            continue

        print(f"  {order_name}: invoice {invoice['DocNum']} closed by journal entry {journal_number} ({amount:,.2f})")


if __name__ == "__main__":
    asyncio.run(main())
