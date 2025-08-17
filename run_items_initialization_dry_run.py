"""
Production script to run items initialization for first 50 unsynced products
This will sync the first 50 active products from Shopify to SAP WITHOUT updating metafields
"""

import asyncio
import sys
import os
from datetime import datetime

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

async def run_items_initialization_dry_run():
    try:
        from app.sync.items_init import items_init
        from app.core.config import config_settings
        
        print("=" * 80)
        print("🚀 SHOPIFY TO SAP ITEMS INITIALIZATION (WITH METAFIELD UPDATES)")
        print("=" * 80)
        print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("✅ NOTE: This will update metafields to mark products as synced/failed")
        print()
        
        # Get enabled stores
        enabled_stores = config_settings.get_enabled_stores()
        if not enabled_stores:
            print("❌ No enabled stores found in configuration")
            return
        
        print(f"📋 Found {len(enabled_stores)} enabled store(s)")
        for store_key in enabled_stores.keys():
            print(f"   - {store_key}")
        print()
        
        # Initialize the items initialization processor
        processor = items_init
        
        # Process each store
        total_products_processed = 0
        total_products_synced = 0
        total_products_failed = 0
        
        for store_key, store_config in enabled_stores.items():
            print(f"🔄 Processing store: {store_key}")
            print("-" * 50)
            
            try:
                # Get first 50 unsynced products
                print("1. Getting first 50 unsynced products...")
                unsynced_products = await processor.get_all_active_products(store_key)
                
                if len(unsynced_products) == 0:
                    print("✅ No unsynced products found")
                    continue
                
                # Limit to first 50 products
                products_to_process = unsynced_products[:50]
                print(f"2. Processing first {len(products_to_process)} products (out of {len(unsynced_products)} total)")
                
                # Process each product individually (without metafield updates)
                for i, product in enumerate(products_to_process, 1):
                    try:
                        print(f"   Processing product {i}/{len(products_to_process)}: {product.get('title', 'No Title')}")
                        
                        # Process the product with metafield updates
                        await process_single_product_with_metafields(processor, store_key, store_config, product)
                        total_products_synced += 1
                        
                    except Exception as e:
                        print(f"   ❌ Failed to process product: {str(e)}")
                        total_products_failed += 1
                        continue
                
                total_products_processed += len(products_to_process)
                
                print(f"✅ Store {store_key} completed:")
                print(f"   - Products processed: {len(products_to_process)}")
                print(f"   - Products synced: {total_products_synced}")
                print(f"   - Products failed: {total_products_failed}")
                    
            except Exception as e:
                print(f"❌ Error processing store {store_key}: {str(e)}")
                continue
            
            print()
        
        # Final summary
        print("=" * 80)
        print("📊 INITIALIZATION SUMMARY")
        print("=" * 80)
        print(f"Total products processed: {total_products_processed}")
        print(f"Total products synced: {total_products_synced}")
        print(f"Total products failed: {total_products_failed}")
        print(f"Success rate: {(total_products_synced/total_products_processed*100):.1f}%" if total_products_processed > 0 else "N/A")
        print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        print()
        print("✅ Products were marked as synced in Shopify")
        print("   Products with custom.sap_sync = 'synced' will be excluded from future runs")
        
        print()
        print("✅ Items initialization process completed!")
        
    except Exception as e:
        print(f"❌ Fatal error during initialization: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

async def process_single_product_with_metafields(processor, store_key: str, store_config, product: dict):
    """
    Process a single product with metafield updates
    """
    product_id = product.get('id')
    product_title = product.get('title', '')
    variants = product.get('variants', {}).get('edges', [])
    
    try:
        if len(variants) == 1:
            # Single product (no variants)
            variant = variants[0]['node']
            await process_single_variant_with_metafields(processor, store_key, store_config, product, variant)
        else:
            # Product with variants
            await process_multi_variant_with_metafields(processor, store_key, store_config, product, variants)
        
        # Mark product as successfully synced
        await processor.set_sync_status(store_key, product_id, "synced")
        print(f"      ✅ Marked product as synced in Shopify")
        
    except Exception as e:
        print(f"      ❌ Failed to process product: {str(e)}")
        # Mark product as failed to sync
        await processor.set_sync_status(store_key, product_id, "failed")
        raise

async def process_single_variant_with_metafields(processor, store_key: str, store_config, product: dict, variant: dict):
    """
    Process a single product with one variant with metafield updates
    """
    product_id = product.get('id')
    variant_id = variant.get('id')
    sku = variant.get('sku', '')
    
    if not sku:
        print(f"      ⚠️  Product {product_id} has no SKU, skipping")
        return
    
    # Extract inventory variant ID
    inventory_item = variant.get('inventoryItem', {})
    inventory_variant_id = inventory_item.get('id')
    
    # For single products, use product title as main product name
    main_product_name = product.get('title', '')
    color_name = ""  # No color for single products
    
    # Create mapping records in SAP (creates both variant and inventory records)
    await processor.create_sap_mapping_record(
        store_key, sku, product_id, variant_id, inventory_variant_id,
        main_product_name, color_name
    )
    
    # Also create product-level mapping record (use SKU for single products)
    await processor.create_product_mapping_record(
        store_key, product_id, main_product_name, sku
    )
    
    # Update SAP item fields
    await processor.update_sap_item_fields(sku, main_product_name, "", "")
    
    print(f"      ✅ Created SAP mapping and updated item fields for SKU: {sku}")

async def process_multi_variant_with_metafields(processor, store_key: str, store_config, product: dict, variants: list):
    """
    Process a product with multiple variants with metafield updates
    """
    product_id = product.get('id')
    main_product_name = product.get('title', '')
    
    # Filter out variants that are already synced
    unsynced_variants = await processor.get_unsynced_variants(variants)
    
    if not unsynced_variants:
        print(f"      ✅ All variants for product {product_id} are already synced")
        return
    
    print(f"      Processing {len(unsynced_variants)} unsynced variants out of {len(variants)} total variants")
    
    # Create product-level mapping record once for the entire product (use product title for multi-variant)
    await processor.create_product_mapping_record(
        store_key, product_id, main_product_name
    )
    
    for variant_edge in unsynced_variants:
        variant = variant_edge['node']
        variant_id = variant.get('id')
        sku = variant.get('sku', '')
        
        if not sku:
            print(f"      ⚠️  Variant {variant_id} has no SKU, skipping")
            continue
        
        # Extract inventory variant ID
        inventory_item = variant.get('inventoryItem', {})
        inventory_variant_id = inventory_item.get('id')
        
        # Extract color from variant title
        color_name = variant.get('title', '')
        
        # Create mapping records in SAP (creates both variant and inventory records)
        await processor.create_sap_mapping_record(
            store_key, sku, product_id, variant_id, inventory_variant_id,
            main_product_name, color_name
        )
        
        # Update SAP item fields
        await processor.update_sap_item_fields(sku, main_product_name, main_product_name, color_name)
        
        print(f"      ✅ Created SAP mapping and updated item fields for variant SKU: {sku}")

if __name__ == "__main__":
    print("Starting Shopify to SAP Items Initialization (WITH METAFIELD UPDATES)...")
    print("This will sync the first 50 unsynced active products from Shopify to SAP")
    print("✅ Products will be marked as synced in Shopify")
    print()
    
    # Ask for confirmation
    response = input("Do you want to proceed? (yes/no): ").lower().strip()
    
    if response in ['yes', 'y']:
        success = asyncio.run(run_items_initialization_dry_run())
        if success:
            print("\n🎉 Initialization completed successfully!")
        else:
            print("\n❌ Initialization failed. Check the logs for details.")
    else:
        print("Initialization cancelled by user.")
