#!/usr/bin/env python3
"""
Test script to verify multi-store setup with local store only
"""

import asyncio
import sys
from app.core.config import config_settings
from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.utils.logging import logger
from app.services.sap.client import sap_client

async def test_multi_store_setup():
    """Test the multi-store setup"""
    print("🧪 Testing multi-store setup...")
    
    try:
        # Test 1: Check enabled stores
        print("\n1. Checking enabled stores...")
        enabled_stores = config_settings.get_enabled_stores()
        print(f"   Enabled stores: {list(enabled_stores.keys())}")
        
        if not enabled_stores:
            print("   ❌ No enabled stores found!")
            return False
        
        for store_key, store_config in enabled_stores.items():
            print(f"   ✅ Store '{store_key}': {store_config.name}")
            print(f"      URL: {store_config.shop_url}")
            print(f"      Location ID: {store_config.location_id}")
            print(f"      Currency: {store_config.currency}")
            print(f"      Price List: {store_config.price_list}")
            print(f"      Warehouse: {store_config.warehouse_code}")
        
        # Test 2: Check multi-store client initialization
        print("\n2. Checking multi-store client initialization...")
        client_stores = multi_store_shopify_client.get_enabled_stores()
        print(f"   Client stores: {list(client_stores.keys())}")
        
        if not client_stores:
            print("   ❌ No stores found in multi-store client!")
            return False
        
        # Test 3: Test GraphQL connection for each store
        print("\n3. Testing GraphQL connections...")
        for store_key in enabled_stores.keys():
            print(f"   Testing connection to store: {store_key}")
            
            # Test with a simple query
            result = await multi_store_shopify_client.get_locations(store_key)
            
            if result["msg"] == "success":
                print(f"   ✅ Successfully connected to {store_key}")
                locations = result["data"]["locations"]["edges"]
                print(f"      Found {len(locations)} locations")
                for location in locations:
                    loc_data = location["node"]
                    print(f"      - {loc_data['name']} (ID: {loc_data['id']})")
            else:
                print(f"   ❌ Failed to connect to {store_key}: {result.get('error')}")
                return False
        
        # Test 4: Test SAP connection
        print("\n4. Testing SAP connection...")
        
        # Test SAP login
        login_success = await sap_client._login()
        if login_success:
            print("   ✅ SAP login successful")
        else:
            print("   ❌ SAP login failed")
            return False
        
        # Test getting new items
        new_items_result = await sap_client.get_new_items()
        if new_items_result["msg"] == "success":
            items = new_items_result["data"].get("value", [])
            print(f"   ✅ SAP connection successful - Found {len(items)} new items")
        else:
            print(f"   ❌ Failed to get new items from SAP: {new_items_result.get('error')}")
            return False
        
        print("\n✅ All tests passed! Multi-store setup is working correctly.")
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        logger.error(f"Multi-store setup test failed: {str(e)}")
        return False

async def main():
    """Main function"""
    try:
        success = await test_multi_store_setup()
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        sys.exit(1)

def test_get_new_items_from_sap():
    async def run():
        print('Testing SAP view retrieval (all stores)...')
        result_all = await sap_client.get_new_items()
        print('All stores result:', result_all)

        print('Testing SAP view retrieval (local store)...')
        result_local = await sap_client.get_new_items(store_key='local')
        print('Local store result:', result_local)

    asyncio.run(run())

if __name__ == "__main__":
    test_get_new_items_from_sap() 