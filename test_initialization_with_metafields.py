"""
Test script to verify initialization process with metafield updates
"""

import asyncio
import sys
import os

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

async def test_initialization_with_metafields():
    try:
        from app.sync.items_init import items_init
        from app.core.config import config_settings
        
        print("=== TESTING INITIALIZATION WITH METAFIELD UPDATES ===")
        print("This will test the initialization process with metafield updates")
        print()
        
        # Get enabled stores
        enabled_stores = config_settings.get_enabled_stores()
        if not enabled_stores:
            print("❌ No enabled stores found")
            return
        
        store_key = list(enabled_stores.keys())[0]  # Use first store
        print(f"Using store: {store_key}")
        print()
        
        # Get first 5 unsynced products for testing
        print("1. Getting first 5 unsynced products...")
        unsynced_products = await items_init.get_all_active_products(store_key)
        
        if len(unsynced_products) == 0:
            print("✅ No unsynced products found")
            return
        
        # Limit to first 5 products for testing
        products_to_process = unsynced_products[:5]
        print(f"2. Found {len(products_to_process)} products to test")
        
        # Process each product
        for i, product in enumerate(products_to_process, 1):
            try:
                print(f"\n--- Processing Product {i}/{len(products_to_process)} ---")
                print(f"Product: {product.get('title', 'No Title')}")
                print(f"Product ID: {product.get('id')}")
                
                # Check current sync status
                sync_status = items_init._get_sync_status(product)
                print(f"Current sync status: {sync_status or 'Not set'}")
                
                # Process the product (this will update metafields)
                await items_init.process_single_product(store_key, None, product)
                
                print(f"✅ Product processed successfully")
                
            except Exception as e:
                print(f"❌ Failed to process product: {str(e)}")
                continue
        
        print("\n=== TEST COMPLETED ===")
        print("Check the products in Shopify to verify metafields were updated")
        
    except Exception as e:
        print(f"❌ Error during test: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("Testing initialization with metafield updates...")
    print("This will process 5 products and update their metafields")
    print()
    
    # Ask for confirmation
    response = input("Do you want to proceed? (yes/no): ").lower().strip()
    
    if response in ['yes', 'y']:
        asyncio.run(test_initialization_with_metafields())
        print("\n🎉 Test completed!")
    else:
        print("Test cancelled by user.")
