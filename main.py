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
    
    # Check which syncs are enabled
    enabled_syncs = []
    
    # For now, we'll enable new_items and stock by default since they're not in config
    # You can add these to configurations.json later
    enabled_syncs.append("new_items")
    enabled_syncs.append("stock")
    
    if config_settings.master_data_enabled:
        enabled_syncs.append("master_data")
    
    if config_settings.orders_enabled:
        enabled_syncs.append("orders")
    
    # Gift cards not in config yet, so we'll skip for now
    # if config_settings.gift_cards_enabled:
    #     enabled_syncs.append("gift_cards")
    
    if not enabled_syncs:
        print("❌ No sync processes are enabled in configuration!")
        print("Please enable at least one sync in configurations.json")
        return
    
    print(f"🔄 Running {len(enabled_syncs)} enabled sync(s): {', '.join(enabled_syncs)}")
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