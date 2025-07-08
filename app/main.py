import asyncio
from datetime import datetime
import pytz
from app.core.config import config_settings
from app.utils.logging import logger, log_sync_event
from app.sync.master_data import sync_master_data
from app.sync.new_items import new_items_sync
from app.services.shopify.client import shopify_client
from app.services.sap.client import sap_client
#from app.sync.inventory import sync_inventory
#from app.sync.orders import sync_orders

async def master_data_sync():
    """Handle master data synchronization"""
    if not config_settings.master_data_enabled:
        return
    
    try:
        logger.info("Starting master data sync")
        await sync_master_data()
    except Exception as e:
        logger.error(f"Error in master data sync: {str(e)}")

async def new_items_sync_task():
    """Handle new items synchronization from SAP to Shopify"""
    try:
        logger.info("Starting new items sync")
        result = await new_items_sync.sync_new_items()
        
        if result["msg"] == "success":
            logger.info(f"New items sync completed: {result.get('processed', 0)} processed, {result.get('success', 0)} successful, {result.get('errors', 0)} errors")
        else:
            logger.error(f"New items sync failed: {result.get('error', 'Unknown error')}")
            
    except Exception as e:
        logger.error(f"Error in new items sync: {str(e)}")

async def inventory_sync():
    """Handle inventory synchronization"""
    if not config_settings.inventory_enabled:
        return
    
    try:
        logger.info("Starting inventory sync")
        #await sync_inventory()
    except Exception as e:
        logger.error(f"Error in inventory sync: {str(e)}")

async def orders_sync():
    """Handle orders synchronization"""
    if not config_settings.orders_enabled:
        return
    
    try:
        logger.info("Starting orders sync")
        #await sync_orders()
    except Exception as e:
        logger.error(f"Error in orders sync: {str(e)}")

async def sync_scheduler():
    """Main scheduler function"""
    while True:
        now = datetime.utcnow()
        logger.info(f"Sync cycle started at {now}")
        
        # Run all sync tasks
        await asyncio.gather(
            master_data_sync(),
            new_items_sync_task(),
            inventory_sync(),
            orders_sync()
        )
        
        # Calculate next run time
        next_run = now.timestamp() + (config_settings.master_data_interval * 60)
        logger.info(f"Next sync cycle scheduled for {datetime.fromtimestamp(next_run)}")
        
        # Wait until next cycle
        await asyncio.sleep(config_settings.master_data_interval * 60)

async def test_shopify_connection():
    """Test Shopify connection by fetching products"""
    try:
        print("\nTesting Shopify Connection...")
        print("============================")
        print(f"Store URL: {config_settings.shopify_shop_url}")
        print(f"API Version: {config_settings.shopify_api_version}")
        print(f"Access Token: {config_settings.shopify_access_token[:5]}...{config_settings.shopify_access_token[-5:]}")
        print("============================\n")
        
        logger.info("Testing Shopify connection...")
        
        # Get first 5 products
        result = await shopify_client.get_products(first=5)
        
        if result["msg"] == "failure":
            error_msg = f"Failed to connect to Shopify: {result.get('error')}"
            print(f"\n❌ {error_msg}")
            print("\nDetailed Error Information:")
            print("-------------------------")
            print(result.get('error', 'No detailed error information available'))
            logger.error(error_msg)
            return False
        
        # Log success
        success_msg = "Successfully connected to Shopify!"
        print(f"\n✅ {success_msg}")
        logger.info(success_msg)
        
        # Print product details
        products = result["data"]["products"]
        print("\nFound Products:")
        print("==============")
        
        if not products["edges"]:
            print("No products found in the store.")
            return True
            
        for edge in products["edges"]:
            product = edge["node"]
            print(f"\n📦 Product: {product['title']}")
            print(f"🔗 Handle: {product['handle']}")
            if product.get('description'):
                print(f"📝 Description: {product['description'][:100]}...")
            
            # Print variant details
            variants = product.get("variants", {}).get("edges", [])
            for variant_edge in variants:
                variant = variant_edge["node"]
                print(f"  └─ Variant:")
                print(f"     ├─ SKU: {variant.get('sku', 'No SKU')}")
                print(f"     ├─ Price: {variant.get('price', 'No price')}")
                print(f"     └─ Inventory: {variant.get('inventoryQuantity', 'No inventory')}")
        
        print("\n✨ Shopify connection test completed successfully!")
        return True
        
    except Exception as e:
        error_msg = f"Error testing Shopify connection: {str(e)}"
        print(f"\n❌ {error_msg}")
        print("\nDetailed Error Information:")
        print("-------------------------")
        print(str(e))
        logger.error(error_msg)
        return False

async def test_sap_connection():
    """Test SAP connection by fetching items"""
    try:
        print("\nTesting SAP Connection...")
        print("========================")
        print(f"Server: {config_settings.sap_server}")
        print(f"Company: {config_settings.sap_company}")
        print(f"User: {config_settings.sap_user}")
        print("========================\n")
        
        logger.info("Testing SAP connection...")
        
        # Test login first
        login_success = await sap_client._login()
        if not login_success:
            error_msg = "Failed to login to SAP"
            print(f"\n❌ {error_msg}")
            logger.error(error_msg)
            return False
        
        # Get first 5 items
        result = await sap_client.get_items(top=5)
        
        if result["msg"] == "failure":
            error_msg = f"Failed to connect to SAP: {result.get('error')}"
            print(f"\n❌ {error_msg}")
            print("\nDetailed Error Information:")
            print("-------------------------")
            print(result.get('error', 'No detailed error information available'))
            logger.error(error_msg)
            return False
        
        # Log success
        success_msg = "Successfully connected to SAP!"
        print(f"\n✅ {success_msg}")
        logger.info(success_msg)
        
        # Print item details
        items = result["data"].get("value", [])
        print("\nFound Items:")
        print("============")
        
        if not items:
            print("No items found in SAP.")
            return True
            
        for item in items[:5]:  # Show first 5 items
            print(f"\n📦 Item: {item.get('ItemName', 'No name')}")
            print(f"🔢 Code: {item.get('ItemCode', 'No code')}")
            print(f"📝 Description: {item.get('ItemsGroupCode', 'No group')}")
            print(f"💰 Price: {item.get('Price', 'No price')}")
        
        print("\n✨ SAP connection test completed successfully!")
        return True
        
    except Exception as e:
        error_msg = f"Error testing SAP connection: {str(e)}"
        print(f"\n❌ {error_msg}")
        print("\nDetailed Error Information:")
        print("-------------------------")
        print(str(e))
        logger.error(error_msg)
        return False

async def test_connections():
    """Test both Shopify and SAP connections"""
    print("\n🚀 Starting Connection Tests")
    print("===========================")
    
    # Test Shopify
    shopify_success = await test_shopify_connection()
    
    print("\n" + "="*50 + "\n")
    
    # Test SAP
    sap_success = await test_sap_connection()
    
    # Summary
    print("\n" + "="*50)
    print("TEST SUMMARY")
    print("="*50)
    print(f"Shopify: {'✅ PASSED' if shopify_success else '❌ FAILED'}")
    print(f"SAP:     {'✅ PASSED' if sap_success else '❌ FAILED'}")
    
    if shopify_success and sap_success:
        print("\n🎉 All connections successful! Ready to start sync.")
    else:
        print("\n⚠️  Some connections failed. Please check your configuration.")

if __name__ == "__main__":
    try:
        logger.info("Starting sync service")
        asyncio.run(sync_scheduler())
    except KeyboardInterrupt:
        logger.info("Sync service stopped by user")
    except Exception as e:
        logger.error(f"Sync service stopped due to error: {str(e)}")

    try:
        asyncio.run(test_connections())
    except KeyboardInterrupt:
        print("\n⚠️  Test stopped by user")
        logger.info("Test stopped by user")
    except Exception as e:
        error_msg = f"Test stopped due to error: {str(e)}"
        print(f"\n❌ {error_msg}")
        print("\nDetailed Error Information:")
        print("-------------------------")
        print(str(e))
        logger.error(error_msg) 