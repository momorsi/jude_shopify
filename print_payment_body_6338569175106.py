"""
Print the exact SAP IncomingPayments body for order 6338569175106 without sending it.
"""

import asyncio
import sys
import os
import json

# Ensure app is importable
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.sync.sales.orders_sync import OrdersSalesSync
from app.utils.logging import logger


async def main():
    sync = OrdersSalesSync()
    store_key = "local"

    # Fetch orders
    orders_res = await sync.get_orders_from_shopify(store_key)
    if orders_res["msg"] == "failure":
        logger.error(f"Failed to get orders: {orders_res.get('error')}")
        return

    # Find the specific order by GraphQL ID suffix
    target_id_suffix = "6338569175106"
    target_order = None
    for edge in orders_res["data"]:
        node = edge["node"]
        if node.get("id", "").endswith(target_id_suffix):
            target_order = edge
            break

    if not target_order:
        logger.error("Target order not found in fetched orders")
        return

    order_node = target_order["node"]
    order_name = order_node.get("name")

    # Get or construct minimal SAP invoice DocEntry to prepare payment body
    # We will create an invoice to get a valid DocEntry, then just print the payment body.
    customer = order_node.get("customer")
    if not customer:
        logger.error("Order has no customer")
        return

    # Extract phone used by CustomerManager for lookup
    from app.sync.sales.customers import CustomerManager
    cm = CustomerManager()
    phone = cm._extract_phone_from_customer(customer)
    if not phone:
        shipping_phone = (order_node.get("shippingAddress") or {}).get("phone")
        billing_phone = (order_node.get("billingAddress") or {}).get("phone")
        phone = shipping_phone or billing_phone
    if not phone:
        logger.error("No phone number found for customer")
        return

    # Find existing customer in SAP
    sap_customer = await cm.find_customer_by_phone(phone)
    if not sap_customer:
        logger.error("SAP customer not found; cannot proceed without CardCode")
        return

    # Map order to SAP invoice format and create invoice to get DocEntry
    invoice_payload = sync.map_shopify_order_to_sap(target_order, sap_customer["CardCode"], store_key)
    created_invoice = await sync.create_invoice_in_sap(invoice_payload)
    if created_invoice["msg"] == "failure":
        logger.error(f"Failed to create invoice: {created_invoice.get('error')}")
        return

    doc_entry = created_invoice.get("sap_doc_entry")
    if not doc_entry:
        logger.error("No DocEntry returned from SAP invoice creation")
        return

    # Prepare payment body (do NOT send)
    payment_body = sync.prepare_incoming_payment_data(
        target_order,
        {"DocEntry": doc_entry},
        sap_customer["CardCode"],
        store_key,
    )

    print("\n=== IncomingPayments body ===")
    print(json.dumps(payment_body, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
