"""
Main entry point for Shopify-SAP integration
Unified sync controller for all sync operations
"""

import asyncio
import sys
import argparse
from typing import Dict, Any, List
from app.sync.new_items_multi_store import MultiStoreNewItemsSync, color_mapper
from app.sync.inventory import sync_stock_change_view


from app.sync.sales.orders_sync import OrdersSalesSync
from app.sync.sales.payment_recovery import PaymentRecoverySync
from app.sync.sales.returns_sync_v2 import ReturnsSyncV2
from app.sync.sales.returns_sync_v3 import ReturnsSyncV3
from app.sync.sales.returns_sync_v4 import ReturnsSyncV4
from app.sync.sales.gift_card_expiry_sync import GiftCardExpirySync
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

        self.sales_orders_sync = OrdersSalesSync()
        self.payment_recovery_sync = PaymentRecoverySync()
        self.returns_sync_v3 = ReturnsSyncV3()
        self.returns_sync_v4 = ReturnsSyncV4()
        self.gift_card_expiry_sync = GiftCardExpirySync()
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
    

    

    
    async def run_sales_orders_sync(self) -> Dict[str, Any]:
        """
        Run sales orders sync (Shopify → SAP)
        """
        logger.info("Starting sales orders sync...")
        return await self.sales_orders_sync.sync_orders()
    
    async def run_payment_recovery_sync(self) -> Dict[str, Any]:
        """
        Run payment recovery sync (SAP → Shopify → SAP)
        """
        logger.info("Starting payment recovery sync...")
        return await self.payment_recovery_sync.sync_payment_recovery()
    
    async def run_returns_sync(self) -> Dict[str, Any]:
        """
        Run returns sync (Shopify → SAP) - V4 with multiple returns support
        """
        logger.info("Starting returns sync V4...")
        return await self.returns_sync_v4.sync_returns()
    
    async def run_returns_followup_sync(self) -> Dict[str, Any]:
        """
        Run returns follow-up sync (checking old orders for new returns)
        """
        logger.info("Starting returns follow-up sync...")
        return await self.returns_sync_v4.sync_returns_followup()
    
    async def run_gift_card_expiry_sync(self) -> Dict[str, Any]:
        """
        Run gift card expiry sync (Shopify → Shopify)
        """
        logger.info("Starting gift card expiry sync...")
        return await self.gift_card_expiry_sync.sync_gift_card_expiry_all_stores()
    
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
    
    async def run_freight_prices_sync(self) -> Dict[str, Any]:
        """
        Run freight prices sync (SAP → Configuration)
        """
        logger.info("Starting freight prices sync...")
        from app.sync.freight_sync import freight_sync
        result = await freight_sync.sync_freight_prices()
        
        # Convert result format to match other syncs
        if result.get("success"):
            return {
                "msg": "success",
                "processed": 1,
                "successful": 1,
                "errors": 0,
                "local_entries": result.get("local_entries", 0),
                "international_entries": result.get("international_entries", 0)
            }
        else:
            return {
                "msg": "failure",
                "error": result.get("error", "Unknown error"),
                "processed": 0,
                "successful": 0,
                "errors": 1
            }
    
    async def run_color_metaobjects_sync(self) -> Dict[str, Any]:
        """
        Run color metaobjects sync (Shopify → JSON mapping file)
        """
        logger.info("Starting color metaobjects sync...")
        result = await color_mapper.sync_all_stores()
        
        if result["msg"] == "success":
            total_colors = sum(r.get("color_count", 0) for r in result.get("results", {}).values())
            return {
                "msg": "success",
                "processed": len(result.get("results", {})),
                "successful": sum(1 for r in result.get("results", {}).values() if r.get("success")),
                "errors": sum(1 for r in result.get("results", {}).values() if not r.get("success")),
                "total_colors": total_colors
            }
        else:
            return {
                "msg": "failure",
                "error": "Failed to sync color metaobjects",
                "processed": 0,
                "successful": 0,
                "errors": 1
            }
    
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
        
        # Freight prices sync (check config)
        if config_settings.freight_prices_enabled:
            results["freight_prices"] = await self.run_freight_prices_sync()
        
        # Color metaobjects sync (check config)
        if config_settings.color_metaobjects_enabled:
            results["color_metaobjects"] = await self.run_color_metaobjects_sync()
        
        # Sales Module syncs
        
        if config_settings.sales_orders_enabled:
            results["sales_orders"] = await self.run_sales_orders_sync()
        
        if config_settings.payment_recovery_enabled:
            results["payment_recovery"] = await self.run_payment_recovery_sync()
        
        if config_settings.returns_enabled:
            results["returns"] = await self.run_returns_sync()
        
        if config_settings.gift_card_expiry_enabled:
            results["gift_card_expiry"] = await self.run_gift_card_expiry_sync()
        
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
        elif sync_type == "item_changes" and not config_settings.item_changes_enabled:
            return {
                "msg": "failure",
                "error": "Item changes sync is disabled in configuration"
            }
        elif sync_type == "price_changes" and not config_settings.price_changes_enabled:
            return {
                "msg": "failure",
                "error": "Price changes sync is disabled in configuration"
            }
        elif sync_type == "sales_orders" and not config_settings.sales_orders_enabled:
            return {
                "msg": "failure",
                "error": "Sales orders sync is disabled in configuration"
            }
        elif sync_type == "payment_recovery" and not config_settings.payment_recovery_enabled:
            return {
                "msg": "failure",
                "error": "Payment recovery sync is disabled in configuration"
            }
        elif sync_type == "returns" and not config_settings.returns_enabled:
            return {
                "msg": "failure",
                "error": "Returns sync is disabled in configuration"
            }
        elif sync_type == "returns_followup" and not config_settings.returns_followup_enabled:
            return {
                "msg": "failure",
                "error": "Returns follow-up sync is disabled in configuration"
            }
        elif sync_type == "gift_card_expiry" and not config_settings.gift_card_expiry_enabled:
            return {
                "msg": "failure",
                "error": "Gift card expiry sync is disabled in configuration"
            }
        
        sync_functions = {
            "new_items": self.run_new_items_sync,
            "stock": self.run_stock_change_sync,
            "item_changes": self.run_item_changes_sync,
            "price_changes": self.run_price_changes_sync,
            "freight_prices": self.run_freight_prices_sync,
            "color_metaobjects": self.run_color_metaobjects_sync,
    
            "sales_orders": self.run_sales_orders_sync,
            "payment_recovery": self.run_payment_recovery_sync,
            "returns": self.run_returns_sync,
            "returns_followup": self.run_returns_followup_sync,
            "gift_card_expiry": self.run_gift_card_expiry_sync,
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
        
        if config_settings.freight_prices_enabled:
            freight_prices_task = asyncio.create_task(
                self._run_freight_sync_daily()
            )
            tasks.append(freight_prices_task)
            logger.info(f"Freight prices sync scheduled to run daily at {config_settings.freight_prices_run_time}")
        
        if config_settings.color_metaobjects_enabled:
            color_metaobjects_task = asyncio.create_task(
                self._run_color_metaobjects_sync_daily()
            )
            tasks.append(color_metaobjects_task)
            logger.info(f"Color metaobjects sync scheduled to run daily at {config_settings.color_metaobjects_run_time}")

        
        # Sales Module continuous syncs
        
        if config_settings.sales_orders_enabled:
            sales_orders_task = asyncio.create_task(
                self._run_sync_with_interval("sales_orders", config_settings.sales_orders_interval)
            )
            tasks.append(sales_orders_task)
            logger.info(f"Sales orders sync scheduled to run every {config_settings.sales_orders_interval} minutes")
        
        if config_settings.payment_recovery_enabled:
            payment_recovery_task = asyncio.create_task(
                self._run_sync_with_interval("payment_recovery", config_settings.payment_recovery_interval)
            )
            tasks.append(payment_recovery_task)
            logger.info(f"Payment recovery sync scheduled to run every {config_settings.payment_recovery_interval} minutes")
        
        if config_settings.returns_enabled:
            returns_task = asyncio.create_task(
                self._run_sync_with_interval("returns", config_settings.returns_interval)
            )
            tasks.append(returns_task)
            logger.info(f"Returns sync scheduled to run every {config_settings.returns_interval} minutes")
        
        if config_settings.returns_followup_enabled:
            returns_followup_task = asyncio.create_task(
                self._run_sync_with_interval("returns_followup", config_settings.returns_followup_interval)
            )
            tasks.append(returns_followup_task)
            logger.info(f"Returns follow-up sync scheduled to run every {config_settings.returns_followup_interval} minutes")
        
        if config_settings.gift_card_expiry_enabled:
            gift_card_expiry_task = asyncio.create_task(
                self._run_sync_with_interval("gift_card_expiry", config_settings.gift_card_expiry_interval)
            )
            tasks.append(gift_card_expiry_task)
            logger.info(f"Gift card expiry sync scheduled to run every {config_settings.gift_card_expiry_interval} minutes")
        
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
    
    async def _run_freight_sync_daily(self):
        """
        Run freight sync daily at the specified time
        """
        import datetime
        import pytz
        
        while self.running:
            try:
                # Get current time in the configured timezone
                timezone = pytz.timezone(config_settings.freight_prices_timezone)
                now = datetime.datetime.now(timezone)
                
                # Parse the run time (format: "HH:MM")
                run_time_parts = config_settings.freight_prices_run_time.split(":")
                run_hour = int(run_time_parts[0])
                run_minute = int(run_time_parts[1])
                
                # Create target time for today
                target_time = now.replace(hour=run_hour, minute=run_minute, second=0, microsecond=0)
                
                # If target time has passed today, schedule for tomorrow
                if now >= target_time:
                    target_time += datetime.timedelta(days=1)
                
                # Calculate seconds until target time
                seconds_until_run = (target_time - now).total_seconds()
                
                logger.info(f"Freight sync scheduled for {target_time.strftime('%Y-%m-%d %H:%M:%S')} ({config_settings.freight_prices_timezone})")
                logger.info(f"Waiting {seconds_until_run/3600:.1f} hours until next freight sync...")
                
                # Wait until target time
                await asyncio.sleep(seconds_until_run)
                
                if self.running:
                    logger.info("Running daily freight sync...")
                    result = await self.run_specific_sync("freight_prices")
                    
                    if result["msg"] == "success":
                        logger.info(f"✅ Freight sync completed successfully")
                        if "local_entries" in result:
                            logger.info(f"   - Local entries: {result.get('local_entries', 0)}")
                            logger.info(f"   - International entries: {result.get('international_entries', 0)}")
                        
                        # Reload configurations.json from disk
                        try:
                            from app.core.config import configs
                            configs.reload_config()
                            logger.info("✅ Configuration file reloaded after freight sync")
                        except Exception as e:
                            logger.error(f"❌ Failed to reload configuration: {str(e)}")
                    else:
                        logger.error(f"❌ Freight sync failed: {result.get('error')}")
                
            except Exception as e:
                logger.error(f"❌ Exception in freight sync: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                # Wait 1 hour before retrying on error
                if self.running:
                    await asyncio.sleep(3600)
    
    async def _run_color_metaobjects_sync_daily(self):
        """
        Run color metaobjects sync daily at the specified time
        """
        import datetime
        import pytz
        
        while self.running:
            try:
                # Get current time in the configured timezone
                timezone = pytz.timezone(config_settings.color_metaobjects_timezone)
                now = datetime.datetime.now(timezone)
                
                # Parse the run time (format: "HH:MM")
                run_time_parts = config_settings.color_metaobjects_run_time.split(":")
                run_hour = int(run_time_parts[0])
                run_minute = int(run_time_parts[1])
                
                # Create target time for today
                target_time = now.replace(hour=run_hour, minute=run_minute, second=0, microsecond=0)
                
                # If target time has passed today, schedule for tomorrow
                if now >= target_time:
                    target_time += datetime.timedelta(days=1)
                
                # Calculate seconds until target time
                seconds_until_run = (target_time - now).total_seconds()
                
                logger.info(f"Color metaobjects sync scheduled for {target_time.strftime('%Y-%m-%d %H:%M:%S')} ({config_settings.color_metaobjects_timezone})")
                logger.info(f"Waiting {seconds_until_run/3600:.1f} hours until next color metaobjects sync...")
                
                # Wait until target time
                await asyncio.sleep(seconds_until_run)
                
                if self.running:
                    logger.info("Running daily color metaobjects sync...")
                    result = await self.run_color_metaobjects_sync()
                    
                    if result["msg"] == "success":
                        logger.info(f"✅ Color metaobjects sync completed successfully")
                        logger.info(f"   - Stores processed: {result.get('processed', 0)}")
                        logger.info(f"   - Total colors mapped: {result.get('total_colors', 0)}")
                        
                        # Reload color mappings from disk
                        try:
                            from app.sync.new_items_multi_store import color_mapper
                            color_mapper.reload_mappings()
                            logger.info("✅ Color mappings reloaded after sync")
                        except Exception as e:
                            logger.error(f"❌ Failed to reload color mappings: {str(e)}")
                    else:
                        logger.error(f"❌ Color metaobjects sync failed: {result.get('error')}")
                
            except Exception as e:
                logger.error(f"❌ Exception in color metaobjects sync: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                # Wait 1 hour before retrying on error
                if self.running:
                    await asyncio.sleep(3600)

async def main():
    """
    Main entry point
    """
    parser = argparse.ArgumentParser(description="Shopify-SAP Integration Sync")
    parser.add_argument(
        "--sync", 
        type=str, 
        default="all",
        choices=["new_items", "stock", "item_changes", "price_changes", "freight_prices", "color_metaobjects", "sales_orders", "payment_recovery", "returns", "all"],
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
            if config_settings.sales_orders_enabled:
                print(f"🛒 Sales Orders: Every {config_settings.sales_orders_interval} minutes")
            if config_settings.payment_recovery_enabled:
                print(f"💳 Payment Recovery: Every {config_settings.payment_recovery_interval} minutes")
            if config_settings.returns_enabled:
                print(f"🔄 Returns: Every {config_settings.returns_interval} minutes")

            
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