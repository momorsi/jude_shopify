"""
Main entry point for Shopify-SAP integration
Unified sync controller for all sync operations
"""

import asyncio
import sys
import argparse
from typing import Dict, Any, List
from app.sync.new_items_multi_store import MultiStoreNewItemsSync
from app.sync.inventory import sync_stock_change_view
from app.sync.master_data import sync_master_data
from app.sync.orders import sync_orders
from app.sync.gift_cards import GiftCardsSync
from app.utils.logging import logger
from app.core.config import config_settings

class ShopifySAPSync:
    """
    Main sync controller for Shopify-SAP integration
    """
    
    def __init__(self):
        self.new_items_sync = MultiStoreNewItemsSync()
        self.gift_cards_sync = GiftCardsSync()
    
    async def run_new_items_sync(self) -> Dict[str, Any]:
        """
        Run new items sync (SAP → Shopify)
        """
        logger.info("Starting new items sync...")
        return await self.new_items_sync.sync_new_items()
    
    async def run_stock_change_sync(self) -> Dict[str, Any]:
        """
        Run stock change sync (SAP → Shopify)
        """
        logger.info("Starting stock change sync...")
        return await sync_stock_change_view()
    
    async def run_master_data_sync(self) -> Dict[str, Any]:
        """
        Run master data sync (Shopify → SAP)
        """
        logger.info("Starting master data sync...")
        return await sync_master_data()
    
    async def run_orders_sync(self) -> Dict[str, Any]:
        """
        Run orders sync (Shopify → SAP)
        """
        logger.info("Starting orders sync...")
        return await sync_orders()
    
    async def run_gift_cards_sync(self) -> Dict[str, Any]:
        """
        Run gift cards sync (SAP → Shopify)
        """
        logger.info("Starting gift cards sync...")
        return await self.gift_cards_sync.sync_gift_cards()
    
    async def run_all_syncs(self) -> Dict[str, Any]:
        """
        Run all enabled syncs in sequence
        """
        logger.info("Starting all syncs...")
        
        results = {}
        
        # SAP → Shopify syncs
        if config_settings.new_items_enabled:
            results["new_items"] = await self.run_new_items_sync()
        
        if config_settings.stock_sync_enabled:
            results["stock_change"] = await self.run_stock_change_sync()
        
        if config_settings.gift_cards_enabled:
            results["gift_cards"] = await self.run_gift_cards_sync()
        
        # Shopify → SAP syncs
        if config_settings.master_data_enabled:
            results["master_data"] = await self.run_master_data_sync()
        
        if config_settings.orders_enabled:
            results["orders"] = await self.run_orders_sync()
        
        return {
            "msg": "success",
            "results": results,
            "total_syncs": len(results)
        }
    
    async def run_specific_sync(self, sync_type: str) -> Dict[str, Any]:
        """
        Run a specific sync type
        """
        sync_functions = {
            "new_items": self.run_new_items_sync,
            "stock": self.run_stock_change_sync,
            "master_data": self.run_master_data_sync,
            "orders": self.run_orders_sync,
            "gift_cards": self.run_gift_cards_sync,
            "all": self.run_all_syncs
        }
        
        if sync_type not in sync_functions:
            return {
                "msg": "failure",
                "error": f"Unknown sync type: {sync_type}. Available: {list(sync_functions.keys())}"
            }
        
        return await sync_functions[sync_type]()

async def main():
    """
    Main entry point
    """
    parser = argparse.ArgumentParser(description="Shopify-SAP Integration Sync")
    parser.add_argument(
        "--sync", 
        type=str, 
        default="all",
        choices=["new_items", "stock", "master_data", "orders", "gift_cards", "all"],
        help="Type of sync to run (default: all)"
    )
    parser.add_argument(
        "--verbose", 
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logger.setLevel("DEBUG")
    
    print("=" * 60)
    print("Shopify-SAP Integration Sync")
    print("=" * 60)
    
    sync_controller = ShopifySAPSync()
    
    try:
        result = await sync_controller.run_specific_sync(args.sync)
        
        if result["msg"] == "success":
            if args.sync == "all":
                print(f"\n✅ All syncs completed successfully!")
                print(f"   - Total syncs run: {result.get('total_syncs', 0)}")
                for sync_name, sync_result in result.get("results", {}).items():
                    if sync_result.get("msg") == "success":
                        print(f"   - {sync_name}: ✅ Success")
                    else:
                        print(f"   - {sync_name}: ❌ Failed - {sync_result.get('error')}")
            else:
                print(f"\n✅ {args.sync} sync completed successfully!")
                if "processed" in result:
                    print(f"   - Processed: {result.get('processed', 0)}")
                    print(f"   - Successful: {result.get('success', 0)}")
                    print(f"   - Errors: {result.get('errors', 0)}")
        else:
            print(f"\n❌ {args.sync} sync failed: {result.get('error')}")
            
    except Exception as e:
        print(f"\n❌ Exception occurred: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("Check your SAP U_API_LOG table for detailed logging information.")
    print("All API calls have been automatically logged!")

if __name__ == "__main__":
    asyncio.run(main()) 