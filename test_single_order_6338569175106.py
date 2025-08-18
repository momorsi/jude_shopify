"""
Test script to specifically test payment creation for order 6338569175106
"""

import asyncio
import sys
import os
from typing import Dict, Any

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.sync.sales.orders_sync import OrdersSalesSync
from app.utils.logging import logger


async def test_single_order_6338569175106():
    """Test payment creation for specific order 6338569175106"""
    try:
        orders_sync = OrdersSalesSync()
        
        # Get orders from Shopify
        logger.info("Getting orders from Shopify...")
        orders_result = await orders_sync.get_orders_from_shopify("local")
        
        if orders_result["msg"] == "failure":
            logger.error(f"Failed to get orders: {orders_result.get('error')}")
            return
        
        orders = orders_result["data"]
        logger.info(f"Found {len(orders)} orders to process")
        
        # Find the specific order
        target_order = None
        for order in orders:
            order_node = order["node"]
            order_id = order_node["id"]
            order_name = order_node["name"]
            
            # Extract the numeric ID from the GraphQL ID
            if "/" in order_id:
                numeric_id = order_id.split("/")[-1]
                if numeric_id == "6338569175106":
                    target_order = order
                    break
        
        if not target_order:
            logger.error("Order 6338569175106 not found in the retrieved orders")
            return
        
        order_node = target_order["node"]
        order_name = order_node["name"]
        financial_status = order_node.get("displayFinancialStatus", "PENDING")
        
        logger.info(f"Found target order: {order_name} (ID: 6338569175106)")
        logger.info(f"Financial Status: {financial_status}")
        
        # Test payment creation for this specific order
        logger.info(f"Testing payment creation for order: {order_name}")
        
        # Process the order
        result = await orders_sync.process_order("local", target_order)
        
        if result["msg"] == "success":
            logger.info(f"✅ Successfully processed order {order_name}")
            logger.info(f"   SAP Invoice: {result.get('sap_invoice_number', 'N/A')}")
            logger.info(f"   SAP Payment: {result.get('sap_payment_number', 'N/A')}")
            logger.info(f"   Payment ID: {result.get('payment_id', 'N/A')}")
            logger.info(f"   Gateway: {result.get('payment_gateway', 'N/A')}")
            logger.info(f"   Amount: {result.get('payment_amount', 'N/A')}")
            logger.info(f"   Is Online Payment: {result.get('is_online_payment', 'N/A')}")
        else:
            logger.error(f"❌ Failed to process order {order_name}: {result.get('error')}")
        
    except Exception as e:
        logger.error(f"Error in single order test: {str(e)}")


async def main():
    logger.info("Testing payment creation for specific order 6338569175106...")
    await test_single_order_6338569175106()


if __name__ == "__main__":
    asyncio.run(main())
