#!/usr/bin/env python3
"""
Dedicated script to run only inventory (stock change) sync
This script processes only stock changes from SAP to Shopify
"""

import asyncio
import sys
import os
from pathlib import Path

# Add the app directory to the Python path
current_dir = Path(__file__).parent
app_dir = current_dir / "app"
sys.path.insert(0, str(app_dir))

from app.main import ShopifySAPSync
from app.core.config import config_settings
from app.utils.logging import logger

async def run_inventory_sync_only():
    """
    Run only the inventory (stock change) sync process
    """
    print("=" * 60)
    print("Shopify-SAP Integration - Inventory Sync Only")
    print("=" * 60)
    
    # Check if inventory sync is enabled
    if not config_settings.inventory_enabled:
        print("❌ Inventory sync is disabled in configuration!")
        print("Please enable inventory sync in configurations.json")
        return
    
    print(f"✅ Inventory Sync: Enabled (every {config_settings.inventory_interval} minutes)")
    print(f"📊 Batch Size: {config_settings.inventory_batch_size}")
    print()
    
    sync_controller = ShopifySAPSync()
    
    try:
        print("🔄 Starting inventory sync...")
        result = await sync_controller.run_specific_sync("stock")
        
        if result["msg"] == "success":
            print(f"\n✅ Inventory sync completed successfully!")
            print(f"   - Processed: {result.get('processed', 0)}")
            print(f"   - Successful: {result.get('success', 0)}")
            print(f"   - Errors: {result.get('errors', 0)}")
            
            # Show detailed results if available
            if result.get('processed', 0) > 0:
                print(f"\n📊 Sync Summary:")
                print(f"   - Total items processed: {result.get('processed', 0)}")
                print(f"   - Successfully updated: {result.get('success', 0)}")
                print(f"   - Failed updates: {result.get('errors', 0)}")
                
                if result.get('errors', 0) > 0:
                    print(f"\n⚠️  {result.get('errors', 0)} items had errors during sync")
                    print("   Check the logs for detailed error information")
            else:
                print(f"\n📊 No inventory changes found to sync")
                print("   This means there are no stock changes in SAP that need to be synced to Shopify")
        else:
            print(f"\n❌ Inventory sync failed: {result.get('error')}")
            
    except Exception as e:
        print(f"\n❌ Exception occurred during inventory sync: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("Check your SAP U_API_LOG table for detailed logging information.")
    print("All API calls have been automatically logged!")

def main():
    """
    Main function for running inventory sync only
    """
    try:
        # Run the async function
        asyncio.run(run_inventory_sync_only())
    except KeyboardInterrupt:
        print("\n⚠️  Inventory sync interrupted by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # Keep console window open if running as executable
    if getattr(sys, 'frozen', False):
        print("\nPress Enter to exit...")
        input()

if __name__ == "__main__":
    main()

