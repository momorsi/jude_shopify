"""
Script to cancel incorrect SAP payments and invoices, and remove Shopify order tags
This script handles orders that were synced with incorrect prices due to expired sales.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import httpx
from typing import Dict, Any, List, Optional
from app.services.sap.client import sap_client
from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.core.config import config_settings
from app.utils.logging import logger

# SAP Endpoints
INVOICES_ENDPOINT = "Invoices?$select=DocEntry,DocCurrency,U_Shopify_Order_ID&$filter=CreationDate eq '2025-11-09' and NumAtCard ne null"

# Headers for SAP requests
SAP_HEADERS = {
    'Prefer': 'odata.maxpagesize=100',
    'Content-Type': 'application/json',
    'Accept': '*/*'
}


async def remove_all_order_tags(store_key: str, order_id: str) -> Dict[str, Any]:
    """
    Remove all tags from a Shopify order by setting tags to empty array
    """
    try:
        # Get current order to verify it exists
        get_order_query = """
        query getOrder($id: ID!) {
            order(id: $id) {
                id
                name
                tags
            }
        }
        """
        
        get_result = await multi_store_shopify_client.execute_query(
            store_key, 
            get_order_query, 
            {"id": order_id}
        )
        
        if get_result.get("msg") != "success":
            return {"msg": "failure", "error": f"Failed to get order: {get_result.get('error')}"}
        
        order_data = get_result.get("data", {}).get("order", {})
        if not order_data:
            return {"msg": "failure", "error": "Order not found"}
        
        # Update order with empty tags array
        update_mutation = """
        mutation orderUpdate($input: OrderInput!) {
            orderUpdate(input: $input) {
                order {
                    id
                    name
                    tags
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """
        
        variables = {
            "input": {
                "id": order_id,
                "tags": []  # Empty array to remove all tags
            }
        }
        
        result = await multi_store_shopify_client.execute_query(store_key, update_mutation, variables)
        
        if result.get("msg") == "success":
            logger.info(f"✅ Removed all tags from order {order_id} in store {store_key}")
        else:
            logger.error(f"❌ Failed to remove tags from order {order_id}: {result.get('error')}")
        
        return result
        
    except Exception as e:
        logger.error(f"Error removing tags from order {order_id}: {str(e)}")
        return {"msg": "failure", "error": str(e)}


async def process_invoices() -> Dict[str, Any]:
    """
    Process invoices: patch, cancel, and remove Shopify tags
    """
    logger.info("=" * 80)
    logger.info("Processing Invoices")
    logger.info("=" * 80)
    
    # Fetch invoices from SAP
    logger.info(f"Fetching invoices from SAP...")
    result = await sap_client._make_request(
        method='GET',
        endpoint=INVOICES_ENDPOINT,
        headers=SAP_HEADERS
    )
    
    if result["msg"] == "failure":
        logger.error(f"Failed to fetch invoices: {result.get('error')}")
        return result
    
    invoices = result["data"].get("value", [])
    logger.info(f"Found {len(invoices)} invoices to process")
    
    processed_orders = set()  # Track orders we've already processed to avoid duplicate tag removal
    
    for invoice in invoices:
        doc_entry = invoice.get("DocEntry")
        doc_currency = invoice.get("DocCurrency", "")
        shopify_order_id = invoice.get("U_Shopify_Order_ID", "")
        
        if not shopify_order_id:
            logger.warning(f"Invoice {doc_entry} has no Shopify Order ID, skipping")
            continue
        
        logger.info(f"\n--- Processing Invoice {doc_entry} ---")
        logger.info(f"Shopify Order ID: {shopify_order_id}")
        logger.info(f"Currency: {doc_currency}")
        
        # Determine store based on currency
        store_key = "local" if doc_currency == "EGP" else "international"
        logger.info(f"Store: {store_key}")
        
        # Extract order ID before patching
        order_id_gid = f"gid://shopify/Order/{shopify_order_id}"
        
        # Step 1: Patch Invoice to clear NumAtCard and U_Shopify_Order_ID
        logger.info(f"Step 1: Patching Invoice {doc_entry} to clear NumAtCard and U_Shopify_Order_ID...")
        patch_result = await sap_client._make_request(
            method='PATCH',
            endpoint=f"Invoices({doc_entry})",
            data={
                "NumAtCard": "",
                "U_Shopify_Order_ID": ""
            },
            headers=SAP_HEADERS
        )
        
        if patch_result["msg"] == "failure":
            logger.error(f"Failed to patch invoice {doc_entry}: {patch_result.get('error')}")
            continue
        
        logger.info(f"✅ Successfully patched invoice {doc_entry}")
        
        # Step 2: Cancel the invoice
        logger.info(f"Step 2: Cancelling invoice {doc_entry}...")
        cancel_result = await sap_client._make_request(
            method='POST',
            endpoint=f"Invoices({doc_entry})/Cancel",
            data={},
            headers=SAP_HEADERS
        )
        
        if cancel_result["msg"] == "failure":
            logger.error(f"Failed to cancel invoice {doc_entry}: {cancel_result.get('error')}")
            continue
        
        logger.info(f"✅ Successfully cancelled invoice {doc_entry}")
        
        # Step 3: Remove tags from Shopify order
        if shopify_order_id not in processed_orders:
            logger.info(f"Step 3: Removing tags from Shopify order {shopify_order_id}...")
            tag_result = await remove_all_order_tags(store_key, order_id_gid)
            
            if tag_result["msg"] == "success":
                logger.info(f"✅ Successfully removed tags from order {shopify_order_id}")
            else:
                logger.error(f"❌ Failed to remove tags: {tag_result.get('error')}")
            
            processed_orders.add(shopify_order_id)
        else:
            logger.info(f"Skipping tag removal for order {shopify_order_id} (already processed)")
        
        # Small delay to avoid rate limiting
        await asyncio.sleep(0.5)
    
    logger.info(f"\n✅ Completed processing {len(invoices)} invoices")
    return {"msg": "success", "processed": len(invoices)}


async def main():
    """
    Main function to run the cancellation script
    """
    logger.info("=" * 80)
    logger.info("SAP Invoice Cancellation Script")
    logger.info("This script will:")
    logger.info("1. Fetch invoices from SAP")
    logger.info("2. Patch them to clear Shopify Order ID fields")
    logger.info("3. Cancel the invoices")
    logger.info("4. Remove tags from Shopify orders")
    logger.info("=" * 80)
    
    try:
        # Process invoices (includes tag removal)
        invoices_result = await process_invoices()
        
        # Summary
        logger.info("\n" + "=" * 80)
        logger.info("SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Invoices processed: {invoices_result.get('processed', 0)}")
        logger.info("=" * 80)
        
        if invoices_result["msg"] == "success":
            logger.info("✅ All operations completed successfully!")
            return {"msg": "success", "invoices": invoices_result}
        else:
            logger.error("❌ Some operations failed. Check logs above for details.")
            return {"msg": "failure", "invoices": invoices_result}
            
    except Exception as e:
        logger.error(f"Fatal error in main script: {str(e)}")
        return {"msg": "failure", "error": str(e)}


if __name__ == "__main__":
    # Run the script
    result = asyncio.run(main())
    exit(0 if result.get("msg") == "success" else 1)

