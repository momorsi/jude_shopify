#!/usr/bin/env python3
"""
Continuous Runner for Shopify-SAP Integration
This script runs all enabled sync processes continuously with their own intervals
"""

import asyncio
import sys
import os
from pathlib import Path
import signal
import time

# Add the app directory to the Python path
current_dir = Path(__file__).parent
app_dir = current_dir / "app"
sys.path.insert(0, str(app_dir))

from app.main import ShopifySAPSync
from app.core.config import config_settings
from app.utils.logging import logger

class ContinuousSyncRunner:
    """
    Continuous sync runner that manages multiple sync processes with intervals
    """
    
    def __init__(self):
        self.sync_controller = ShopifySAPSync()
        self.running = False
        self.start_time = None
        
    def signal_handler(self, signum, frame):
        """
        Handle interrupt signals gracefully
        """
        print(f"\n🛑 Received signal {signum}, stopping continuous sync...")
        self.running = False
        self.sync_controller.running = False
    
    async def run_continuous_syncs(self):
        """
        Run all enabled syncs continuously with their own intervals
        """
        self.running = True
        self.start_time = time.time()
        
        print("=" * 80)
        print("🔄 Shopify-SAP Integration - Continuous Mode")
        print("=" * 80)
        print(f"⏰ Started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # Show enabled syncs and their intervals
        enabled_syncs = []
        
        if config_settings.new_items_enabled:
            enabled_syncs.append(f"📦 New Items: Every {config_settings.new_items_interval} minutes")
        
        if config_settings.inventory_enabled:
            enabled_syncs.append(f"📊 Inventory: Every {config_settings.inventory_interval} minutes")
        
        if config_settings.item_changes_enabled:
            enabled_syncs.append(f"🔄 Item Changes: Every {config_settings.item_changes_interval} minutes")
        
        if config_settings.price_changes_enabled:
            enabled_syncs.append(f"💰 Price Changes: Every {config_settings.price_changes_interval} minutes")
        
        if config_settings.sales_orders_enabled:
            enabled_syncs.append(f"🛒 Sales Orders: Every {config_settings.sales_orders_interval} minutes")
        
        if config_settings.payment_recovery_enabled:
            enabled_syncs.append(f"💳 Payment Recovery: Every {config_settings.payment_recovery_interval} minutes")
        
        if config_settings.returns_enabled:
            enabled_syncs.append(f"🔄 Returns: Every {config_settings.returns_interval} minutes")
        
        if config_settings.freight_prices_enabled:
            enabled_syncs.append(f"🚚 Freight Prices: Daily at {config_settings.freight_prices_run_time} ({config_settings.freight_prices_timezone})")
        
        if not enabled_syncs:
            print("❌ No sync processes are enabled in configuration!")
            print("Please enable at least one sync in configurations.json")
            return
        
        print("✅ Enabled Sync Processes:")
        for sync_info in enabled_syncs:
            print(f"   {sync_info}")
        
        print()
        print("🔄 Starting continuous sync processes...")
        print("Press Ctrl+C to stop all syncs gracefully")
        print("-" * 80)
        
        try:
            # Start the continuous sync processes
            await self.sync_controller.run_continuous_syncs()
            
        except KeyboardInterrupt:
            print("\n🛑 Continuous sync interrupted by user")
        except Exception as e:
            print(f"\n❌ Fatal error in continuous sync: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            self.running = False
            self.sync_controller.running = False
            
            # Show runtime statistics
            if self.start_time:
                runtime = time.time() - self.start_time
                hours = int(runtime // 3600)
                minutes = int((runtime % 3600) // 60)
                seconds = int(runtime % 60)
                print(f"\n⏱️  Total runtime: {hours:02d}:{minutes:02d}:{seconds:02d}")
            
            print("\n" + "=" * 80)
            print("🛑 Continuous sync stopped")
            print("Check your SAP U_API_LOG table for detailed logging information.")
            print("All API calls have been automatically logged!")

async def main():
    """
    Main function for continuous sync runner
    """
    runner = ContinuousSyncRunner()
    
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, runner.signal_handler)
    signal.signal(signal.SIGTERM, runner.signal_handler)
    
    try:
        await runner.run_continuous_syncs()
    except Exception as e:
        print(f"\n❌ Fatal error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # Keep console window open if running as executable
    if getattr(sys, 'frozen', False):
        print("\nPress Enter to exit...")
        input()

if __name__ == "__main__":
    asyncio.run(main())
