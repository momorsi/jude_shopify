"""
Test script to specifically test incoming payment creation for PAID orders
"""

import asyncio
import sys
import os
from typing import Dict, Any

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.sync.sales.orders_sync import OrdersSalesSync
from app.utils.logging import logger


async def test_payment_creation():
    """Test payment creation for PAID orders"""
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
        
        # Find PAID orders
        paid_orders = []
        for order in orders:
            order_node = order["node"]
            financial_status = order_node.get("displayFinancialStatus", "PENDING")
            if financial_status == "PAID":
                paid_orders.append(order)
        
        logger.info(f"Found {len(paid_orders)} PAID orders")
        
        if not paid_orders:
            logger.info("No PAID orders found to test payment creation")
            return
        
        # Test payment creation for the first PAID order
        test_order = paid_orders[0]
        order_node = test_order["node"]
        order_name = order_node["name"]
        financial_status = order_node.get("displayFinancialStatus", "PENDING")
        
        logger.info(f"Testing payment creation for order: {order_name} (Status: {financial_status})")
        
        # Process the order
        result = await orders_sync.process_order("local", test_order)
        
        if result["msg"] == "success":
            logger.info(f"✅ Successfully processed order {order_name}")
            logger.info(f"   SAP Invoice: {result.get('sap_invoice_number', 'N/A')}")
            logger.info(f"   SAP Payment: {result.get('sap_payment_number', 'N/A')}")
            logger.info(f"   Payment ID: {result.get('payment_id', 'N/A')}")
            logger.info(f"   Gateway: {result.get('payment_gateway', 'N/A')}")
            logger.info(f"   Amount: {result.get('payment_amount', 'N/A')}")
        else:
            logger.error(f"❌ Failed to process order {order_name}: {result.get('error')}")
        
    except Exception as e:
        logger.error(f"Error in payment creation test: {str(e)}")


async def test_payment_data_preparation():
    """Test payment data preparation logic"""
    try:
        orders_sync = OrdersSalesSync()
        
        # Get a sample order
        orders_result = await orders_sync.get_orders_from_shopify("local")
        if orders_result["msg"] == "failure":
            logger.error(f"Failed to get orders: {orders_result.get('error')}")
            return
        
        orders = orders_result["data"]
        if not orders:
            logger.info("No orders found")
            return
        
        test_order = orders[0]
        order_node = test_order["node"]
        order_name = order_node["name"]
        
        logger.info(f"Testing payment data preparation for order: {order_name}")
        
        # Extract payment info
        payment_info = orders_sync._extract_payment_info(order_node)
        logger.info(f"Payment Info: {payment_info}")
        
        # Determine payment type
        source_name = order_node.get("sourceName", "").lower()
        source_identifier = order_node.get("sourceIdentifier", "").lower()
        payment_type = orders_sync._determine_payment_type(source_name, source_identifier, payment_info)
        logger.info(f"Payment Type: {payment_type}")
        
        # Test bank transfer account mapping
        from app.core.config import config_settings
        transfer_account = config_settings.get_bank_transfer_account("local", "Paymob")
        logger.info(f"Paymob transfer account: {transfer_account}")
        
        cod_account = config_settings.get_bank_transfer_account("local", "Cash on Delivery (COD)")
        logger.info(f"COD transfer account: {cod_account}")
        
    except Exception as e:
        logger.error(f"Error in payment data preparation test: {str(e)}")


async def main():
    logger.info("Testing payment creation logic...")
    
    # Test 1: Payment data preparation
    logger.info("\n=== Test 1: Payment Data Preparation ===")
    await test_payment_data_preparation()
    
    # Test 2: Payment creation for PAID orders
    logger.info("\n=== Test 2: Payment Creation for PAID Orders ===")
    await test_payment_creation()


if __name__ == "__main__":
    asyncio.run(main())
