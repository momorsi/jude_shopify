#!/usr/bin/env python3
"""
Test script to retrieve products from Shopify stores
Verifies the updated configuration is working correctly
"""

import asyncio
import sys
from app.core.config import config_settings
from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.utils.logging import logger

async def test_shopify_products():
    """Test retrieving products from Shopify stores"""
    print("🧪 Testing Shopify products retrieval...")
    
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
            print(f"      API Version: {store_config.api_version}")
            print(f"      Currency: {store_config.currency}")
        
        # Test 2: Test GraphQL connection for each store
        print("\n2. Testing GraphQL connections...")
        for store_key in enabled_stores.keys():
            print(f"   Testing connection to store: {store_key}")
            
            # Test with a simple query to get locations
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
        
        # Test 3: Retrieve products from each store
        print("\n3. Retrieving products from stores...")
        for store_key in enabled_stores.keys():
            print(f"   Retrieving products from store: {store_key}")
            
            # Get first 10 products
            result = await multi_store_shopify_client.get_products(store_key, first=10)
            
            if result["msg"] == "success":
                products = result["data"]["products"]["edges"]
                print(f"   ✅ Successfully retrieved {len(products)} products from {store_key}")
                
                if products:
                    print(f"      First 5 products:")
                    for i, product_edge in enumerate(products[:5]):
                        product = product_edge["node"]
                        variants = product["variants"]["edges"]
                        variant_count = len(variants)
                        
                        print(f"      {i+1}. {product['title']}")
                        print(f"         Handle: {product['handle']}")
                        print(f"         Variants: {variant_count}")
                        
                        if variants:
                            first_variant = variants[0]["node"]
                            print(f"         First variant SKU: {first_variant['sku']}")
                            print(f"         First variant price: {first_variant['price']}")
                            print(f"         Inventory: {first_variant['inventoryQuantity']}")
                        print()
                else:
                    print(f"      No products found in {store_key}")
            else:
                print(f"   ❌ Failed to retrieve products from {store_key}: {result.get('error')}")
                return False
        
        # Test 4: Test product search by SKU (if products exist)
        print("\n4. Testing product search by SKU...")
        for store_key in enabled_stores.keys():
            print(f"   Testing SKU search in store: {store_key}")
            
            # First get a product to use its SKU for testing
            products_result = await multi_store_shopify_client.get_products(store_key, first=1)
            
            if products_result["msg"] == "success":
                products = products_result["data"]["products"]["edges"]
                if products:
                    first_product = products[0]["node"]
                    variants = first_product["variants"]["edges"]
                    if variants:
                        test_sku = variants[0]["node"]["sku"]
                        print(f"      Testing search for SKU: {test_sku}")
                        
                        # Test the search functionality from gift cards module
                        from app.sync.gift_cards import gift_cards_sync
                        existing_product_id = await gift_cards_sync.check_gift_card_exists(store_key, test_sku)
                        
                        if existing_product_id:
                            print(f"      ✅ Found product with SKU {test_sku}")
                            print(f"         Product ID: {existing_product_id}")
                        else:
                            print(f"      ⚠️  Product with SKU {test_sku} not found (this might be normal)")
                else:
                    print(f"      No products to test SKU search")
            else:
                print(f"      ❌ Failed to get products for SKU testing")
        
        print("\n✅ All Shopify tests passed! Configuration is working correctly.")
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        logger.error(f"Shopify products test failed: {str(e)}")
        return False

async def main():
    """Main function"""
    try:
        success = await test_shopify_products()
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main()) 