#!/usr/bin/env python3
"""
Test script for sales module - test order processing with new features
"""

import asyncio
import sys
import os

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from app.sync.sales.orders_sync import OrdersSalesSync
from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.services.sap.client import sap_client
from app.core.config import config_settings
from app.utils.logging import logger

async def test_location_warehouse_mapping():
    """
    Test the location-warehouse mapping functionality
    """
    print("🔍 Testing location-warehouse mapping...")
    
    try:
        # Test getting mapping for local store
        mapping = config_settings.get_location_warehouse_mapping("local")
        print(f"✅ Local store mapping: {mapping}")
        
        # Test getting warehouse code for specific location
        warehouse_code = config_settings.get_warehouse_code_for_location("local", "gid://shopify/Location/123456789")
        print(f"✅ Warehouse code for location 123456789: {warehouse_code}")
        
        # Test getting default warehouse
        default_warehouse = config_settings.get_warehouse_code_for_location("local", "unknown_location")
        print(f"✅ Default warehouse for unknown location: {default_warehouse}")
        
    except Exception as e:
        print(f"❌ Error testing location-warehouse mapping: {str(e)}")

async def test_sales_module():
    """
    Test the sales module with new features
    """
    print("🚀 Starting sales module test...")
    
    try:
        print("📋 Getting enabled stores...")
        # Get enabled stores
        enabled_stores = multi_store_shopify_client.get_enabled_stores()
        if not enabled_stores:
            print("❌ No enabled Shopify stores found")
            return
        
        print(f"✅ Found {len(enabled_stores)} enabled stores")
        
        # Use the first enabled store
        store_key = list(enabled_stores.keys())[0]
        print(f"🏪 Testing with store: {store_key}")
        
        # Create orders sync instance
        print("🔧 Creating OrdersSalesSync instance...")
        orders_sync = OrdersSalesSync()
        
        # Get unsynced orders
        print("📦 Getting unsynced orders...")
        result = await orders_sync.get_orders_from_shopify(store_key)
        
        if result["msg"] == "success":
            orders = result["data"]
            print(f"✅ Found {len(orders)} unsynced orders")
            
            if orders:
                # Test with the first order
                first_order = orders[0]
                order_name = first_order["node"]["name"]
                financial_status = first_order["node"].get("financialStatus", "PENDING")
                fulfillment_status = first_order["node"].get("fulfillmentStatus", "UNFULFILLED")
                
                print(f"🧪 Testing with order: {order_name}")
                print(f"   - Payment Status: {financial_status}")
                print(f"   - Fulfillment Status: {fulfillment_status}")
                
                # Process the order
                process_result = await orders_sync.process_order(store_key, first_order)
                
                if process_result["msg"] == "success":
                    print(f"✅ Successfully processed order {order_name}")
                    print(f"   - SAP Invoice Number: {process_result.get('sap_invoice_number')}")
                    print(f"   - Customer Card Code: {process_result.get('customer_card_code')}")
                    print(f"   - Ship To Code: {process_result.get('ship_to_code')}")
                    print(f"   - Financial Status: {process_result.get('financial_status')}")
                    print(f"   - Fulfillment Status: {process_result.get('fulfillment_status')}")
                else:
                    print(f"❌ Failed to process order {order_name}: {process_result.get('error')}")
            else:
                print("ℹ️  No unsynced orders found to test")
        else:
            print(f"❌ Failed to get orders: {result.get('error')}")
            
    except Exception as e:
        print(f"❌ Error in test: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("🎯 Starting tests...")
    
    # Test location-warehouse mapping
    print("\n=== Testing Location-Warehouse Mapping ===")
    asyncio.run(test_location_warehouse_mapping())
    
    # Test sales module
    print("\n=== Testing Sales Module ===")
    asyncio.run(test_sales_module())
    
    print("🏁 All tests completed.") 