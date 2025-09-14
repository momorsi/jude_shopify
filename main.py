#!/usr/bin/env python3
"""
Main entry point for Shopify-SAP Integration
This script runs all enabled sync processes
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

async def run_all_enabled_syncs():
    """
    Run all enabled sync processes
    """
    print("=" * 60)
    print("Shopify-SAP Integration - Automated Sync")
    print("=" * 60)
    
    sync_controller = ShopifySAPSync()
    
    # Check which syncs are enabled from configuration
    enabled_syncs = []
    
    if config_settings.new_items_enabled:
        enabled_syncs.append("new_items")
        print(f"✅ New Items Sync: Enabled (every {config_settings.new_items_interval} minutes)")
    
    if config_settings.inventory_enabled:
        enabled_syncs.append("inventory")
        print(f"✅ Inventory Sync: Enabled (every {config_settings.inventory_interval} minutes)")
    
    if config_settings.item_changes_enabled:
        enabled_syncs.append("item_changes")
        print(f"✅ Item Changes Sync: Enabled (every {config_settings.item_changes_interval} minutes)")
    
    if config_settings.price_changes_enabled:
        enabled_syncs.append("price_changes")
        print(f"✅ Price Changes Sync: Enabled (every {config_settings.price_changes_interval} minutes)")
    
    if config_settings.sales_orders_enabled:
        enabled_syncs.append("sales_orders")
        print(f"✅ Sales Orders Sync: Enabled (every {config_settings.sales_orders_interval} minutes)")
    
    if config_settings.payment_recovery_enabled:
        enabled_syncs.append("payment_recovery")
        print(f"✅ Payment Recovery Sync: Enabled (every {config_settings.payment_recovery_interval} minutes)")
    
    if config_settings.returns_enabled:
        enabled_syncs.append("returns")
        print(f"✅ Returns Sync: Enabled (every {config_settings.returns_interval} minutes)")
    
    if not enabled_syncs:
        print("❌ No sync processes are enabled in configuration!")
        print("Please enable at least one sync in configurations.json")
        return
    
    print(f"\n🔄 Running {len(enabled_syncs)} enabled sync(s): {', '.join(enabled_syncs)}")
    print()
    
    # Run all enabled syncs
    try:
        result = await sync_controller.run_all_syncs()
        
        if result["msg"] == "success":
            print(f"\n✅ All syncs completed successfully!")
            print(f"   - Total syncs run: {result.get('total_syncs', 0)}")
            
            for sync_name, sync_result in result.get("results", {}).items():
                if sync_result.get("msg") == "success":
                    processed = sync_result.get("processed", 0)
                    success = sync_result.get("success", 0)
                    errors = sync_result.get("errors", 0)
                    print(f"   - {sync_name}: ✅ Success ({processed} processed, {success} successful, {errors} errors)")
                else:
                    print(f"   - {sync_name}: ❌ Failed - {sync_result.get('error')}")
        else:
            print(f"\n❌ Sync failed: {result.get('error')}")
            
    except Exception as e:
        print(f"\n❌ Exception occurred: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("Check your SAP U_API_LOG table for detailed logging information.")
    print("All API calls have been automatically logged!")

def main():
    """
    Main function for PyInstaller executable
    """
    try:
        # Run the async function
        asyncio.run(run_all_enabled_syncs())
    except KeyboardInterrupt:
        print("\n⚠️  Sync interrupted by user")
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