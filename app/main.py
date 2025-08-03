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
from app.sync.sales.gift_cards_sync import GiftCardsSalesSync
from app.sync.sales.orders_sync import OrdersSalesSync
from app.sync.item_changes import item_changes_sync
from app.sync.price_changes import price_changes_sync
from app.utils.logging import logger
from app.core.config import config_settings

class ShopifySAPSync:
    """
    Main sync controller for Shopify-SAP integration
    """
    
    def __init__(self):
        self.new_items_sync = MultiStoreNewItemsSync()
        self.gift_cards_sync = GiftCardsSync()
        self.sales_gift_cards_sync = GiftCardsSalesSync()
        self.sales_orders_sync = OrdersSalesSync()
        self.running = False
    
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
    
    async def run_sales_gift_cards_sync(self) -> Dict[str, Any]:
        """
        Run sales gift cards sync (SAP → Shopify)
        """
        logger.info("Starting sales gift cards sync...")
        return await self.sales_gift_cards_sync.sync_gift_cards()
    
    async def run_sales_orders_sync(self) -> Dict[str, Any]:
        """
        Run sales orders sync (Shopify → SAP)
        """
        logger.info("Starting sales orders sync...")
        return await self.sales_orders_sync.sync_orders()
    
    async def run_item_changes_sync(self) -> Dict[str, Any]:
        """
        Run item changes sync (SAP → Shopify)
        """
        logger.info("Starting item changes sync...")
        return await item_changes_sync.sync_item_changes()
    
    async def run_price_changes_sync(self) -> Dict[str, Any]:
        """
        Run price changes sync (SAP → Shopify)
        """
        logger.info("Starting price changes sync...")
        return await price_changes_sync.sync_price_changes()
    
    async def run_all_syncs(self) -> Dict[str, Any]:
        """
        Run all enabled syncs in sequence
        """
        logger.info("Starting all syncs...")
        
        results = {}
        
        # SAP → Shopify syncs (check config)
        if config_settings.new_items_enabled:
            results["new_items"] = await self.run_new_items_sync()
        
        if config_settings.inventory_enabled:
            results["stock_change"] = await self.run_stock_change_sync()
        
        # Item changes sync (check config)
        if config_settings.item_changes_enabled:
            results["item_changes"] = await self.run_item_changes_sync()
        
        # Price changes sync (check config)
        if config_settings.price_changes_enabled:
            results["price_changes"] = await self.run_price_changes_sync()
        
        # Shopify → SAP syncs (check config)
        if config_settings.master_data_enabled:
            results["master_data"] = await self.run_master_data_sync()
        
        if config_settings.orders_enabled:
            results["orders"] = await self.run_orders_sync()
        
        # Sales Module syncs
        if config_settings.sales_gift_cards_enabled:
            results["sales_gift_cards"] = await self.run_sales_gift_cards_sync()
        
        if config_settings.sales_orders_enabled:
            results["sales_orders"] = await self.run_sales_orders_sync()
        
        return {
            "msg": "success",
            "results": results,
            "total_syncs": len(results)
        }
    
    async def run_specific_sync(self, sync_type: str) -> Dict[str, Any]:
        """
        Run a specific sync type
        """
        # Check if sync is enabled before running
        if sync_type == "new_items" and not config_settings.new_items_enabled:
            return {
                "msg": "failure",
                "error": "New items sync is disabled in configuration"
            }
        elif sync_type == "stock" and not config_settings.inventory_enabled:
            return {
                "msg": "failure",
                "error": "Stock change sync is disabled in configuration"
            }
        elif sync_type == "master_data" and not config_settings.master_data_enabled:
            return {
                "msg": "failure",
                "error": "Master data sync is disabled in configuration"
            }
        elif sync_type == "orders" and not config_settings.orders_enabled:
            return {
                "msg": "failure",
                "error": "Orders sync is disabled in configuration"
            }
        elif sync_type == "sales_gift_cards" and not config_settings.sales_gift_cards_enabled:
            return {
                "msg": "failure",
                "error": "Sales gift cards sync is disabled in configuration"
            }
        elif sync_type == "sales_orders" and not config_settings.sales_orders_enabled:
            return {
                "msg": "failure",
                "error": "Sales orders sync is disabled in configuration"
            }
        
        sync_functions = {
            "new_items": self.run_new_items_sync,
            "stock": self.run_stock_change_sync,
            "item_changes": self.run_item_changes_sync,
            "price_changes": self.run_price_changes_sync,
            "master_data": self.run_master_data_sync,
            "orders": self.run_orders_sync,
            "gift_cards": self.run_gift_cards_sync,
            "sales_gift_cards": self.run_sales_gift_cards_sync,
            "sales_orders": self.run_sales_orders_sync,
            "all": self.run_all_syncs
        }
        
        if sync_type not in sync_functions:
            return {
                "msg": "failure",
                "error": f"Unknown sync type: {sync_type}. Available: {list(sync_functions.keys())}"
            }
        
        return await sync_functions[sync_type]()
    
    async def run_continuous_syncs(self):
        """
        Run syncs continuously with separate intervals for each sync type
        """
        self.running = True
        logger.info("Starting continuous sync mode...")
        
        # Create tasks for each enabled sync with their own intervals
        tasks = []
        
        if config_settings.new_items_enabled:
            new_items_task = asyncio.create_task(
                self._run_sync_with_interval("new_items", config_settings.new_items_interval)
            )
            tasks.append(new_items_task)
            logger.info(f"New items sync scheduled to run every {config_settings.new_items_interval} minutes")
        
        if config_settings.inventory_enabled:
            inventory_task = asyncio.create_task(
                self._run_sync_with_interval("stock", config_settings.inventory_interval)
            )
            tasks.append(inventory_task)
            logger.info(f"Inventory sync scheduled to run every {config_settings.inventory_interval} minutes")
        
        if config_settings.item_changes_enabled:
            item_changes_task = asyncio.create_task(
                self._run_sync_with_interval("item_changes", config_settings.item_changes_interval)
            )
            tasks.append(item_changes_task)
            logger.info(f"Item changes sync scheduled to run every {config_settings.item_changes_interval} minutes")
        
        if config_settings.price_changes_enabled:
            price_changes_task = asyncio.create_task(
                self._run_sync_with_interval("price_changes", config_settings.price_changes_interval)
            )
            tasks.append(price_changes_task)
            logger.info(f"Price changes sync scheduled to run every {config_settings.price_changes_interval} minutes")
        
        if config_settings.master_data_enabled:
            master_data_task = asyncio.create_task(
                self._run_sync_with_interval("master_data", config_settings.master_data_interval)
            )
            tasks.append(master_data_task)
            logger.info(f"Master data sync scheduled to run every {config_settings.master_data_interval} minutes")
        
        if config_settings.orders_enabled:
            orders_task = asyncio.create_task(
                self._run_sync_with_interval("orders", config_settings.orders_interval)
            )
            tasks.append(orders_task)
            logger.info(f"Orders sync scheduled to run every {config_settings.orders_interval} minutes")
        
        # Sales Module continuous syncs
        if config_settings.sales_gift_cards_enabled:
            sales_gift_cards_task = asyncio.create_task(
                self._run_sync_with_interval("sales_gift_cards", config_settings.sales_gift_cards_interval)
            )
            tasks.append(sales_gift_cards_task)
            logger.info(f"Sales gift cards sync scheduled to run every {config_settings.sales_gift_cards_interval} minutes")
        
        if config_settings.sales_orders_enabled:
            sales_orders_task = asyncio.create_task(
                self._run_sync_with_interval("sales_orders", config_settings.sales_orders_interval)
            )
            tasks.append(sales_orders_task)
            logger.info(f"Sales orders sync scheduled to run every {config_settings.sales_orders_interval} minutes")
        
        if not tasks:
            logger.warning("No syncs are enabled in configuration")
            return
        
        try:
            # Wait for all tasks to complete (they run indefinitely)
            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            logger.info("Received interrupt signal, stopping continuous sync...")
            self.running = False
            # Cancel all tasks
            for task in tasks:
                task.cancel()
            # Wait for tasks to be cancelled
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _run_sync_with_interval(self, sync_type: str, interval_minutes: int):
        """
        Run a specific sync type continuously with the given interval
        """
        while self.running:
            try:
                logger.info(f"Running {sync_type} sync...")
                result = await self.run_specific_sync(sync_type)
                
                if result["msg"] == "success":
                    logger.info(f"✅ {sync_type} sync completed successfully")
                    if "processed" in result:
                        logger.info(f"   - Processed: {result.get('processed', 0)}")
                        logger.info(f"   - Successful: {result.get('success', 0)}")
                        logger.info(f"   - Errors: {result.get('errors', 0)}")
                else:
                    logger.error(f"❌ {sync_type} sync failed: {result.get('error')}")
                
            except Exception as e:
                logger.error(f"❌ Exception in {sync_type} sync: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
            
            # Wait for the specified interval before next run
            if self.running:
                logger.info(f"Waiting {interval_minutes} minutes before next {sync_type} sync...")
                await asyncio.sleep(interval_minutes * 60)  # Convert minutes to seconds

async def main():
    """
    Main entry point
    """
    parser = argparse.ArgumentParser(description="Shopify-SAP Integration Sync")
    parser.add_argument(
        "--sync", 
        type=str, 
        default="all",
        choices=["new_items", "stock", "item_changes", "price_changes", "master_data", "orders", "gift_cards", "all"],
        help="Type of sync to run (default: all)"
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Run syncs continuously with intervals from configuration"
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
        if args.continuous:
            print("🔄 Starting continuous sync mode...")
            print("Press Ctrl+C to stop")
            print()
            
            # Show enabled syncs and their intervals
            if config_settings.new_items_enabled:
                print(f"📦 New Items: Every {config_settings.new_items_interval} minutes")
            if config_settings.inventory_enabled:
                print(f"📊 Inventory: Every {config_settings.inventory_interval} minutes")
            if config_settings.item_changes_enabled:
                print(f"🔄 Item Changes: Every {config_settings.item_changes_interval} minutes")
            if config_settings.price_changes_enabled:
                print(f"💰 Price Changes: Every {config_settings.price_changes_interval} minutes")
            if config_settings.master_data_enabled:
                print(f"📋 Master Data: Every {config_settings.master_data_interval} minutes")
            if config_settings.orders_enabled:
                print(f"📦 Orders: Every {config_settings.orders_interval} minutes")
            
            print()
            await sync_controller.run_continuous_syncs()
            
        else:
            # Single run mode
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
                
    except KeyboardInterrupt:
        print("\n🛑 Sync stopped by user")
    except Exception as e:
        print(f"\n❌ Exception occurred: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("Check your SAP U_API_LOG table for detailed logging information.")
    print("All API calls have been automatically logged!")

if __name__ == "__main__":
    asyncio.run(main()) 