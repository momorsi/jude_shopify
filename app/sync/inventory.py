"""
Inventory Sync Module
Syncs inventory changes from SAP to Shopify using change-based tracking
Supports multi-store inventory management
"""

import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from app.services.sap.client import sap_client
from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.core.config import config_settings
from app.utils.logging import logger, log_sync_event
from app.services.sap.api_logger import sl_add_log

class InventorySync:
    def __init__(self):
        self.batch_size = config_settings.inventory_batch_size
        

    

    

    

    
    async def update_onhand_metafield(self, store_key: str, variant_id: str, onhand: float) -> Dict[str, Any]:
        """
        Update the OnHand value as a metafield for the given variant in Shopify.
        """
        try:
            metafield_data = {
                "metafield": {
                    "namespace": "inventory",
                    "key": "onhand",
                    "value": str(onhand),
                    "type": "number_decimal"
                }
            }
            # Shopify REST API for variant metafields
            from app.core.config import config_settings
            store_config = config_settings.get_store_by_name(store_key)
            import httpx
            url = f"https://{store_config.shop_url}/admin/api/{store_config.api_version}/variants/{variant_id}/metafields.json"
            headers = {
                'X-Shopify-Access-Token': store_config.access_token,
                'Content-Type': 'application/json',
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=metafield_data, headers=headers)
                if response.status_code == 201:
                    return {"msg": "success", "data": response.json()}
                else:
                    return {"msg": "failure", "error": f"HTTP {response.status_code}: {response.text}"}
        except Exception as e:
            return {"msg": "failure", "error": str(e)}


    


    async def sync_stock_change_view(self) -> Dict[str, Any]:
        """
        Sync inventory using the MASHURA_StockChangeB1SLQuery SAP view.
        For each row, update Shopify inventory using the REST API (not GraphQL):
        - Sets the available quantity for the given inventory item and location.
        - Logs the result in SAP API_LOG with all required fields.
        This is the production-ready approach for reliable, direct inventory updates.
        """
        logger.info("Starting stock change sync using MASHURA_StockChangeB1SLQuery view")
        try:
            # Fetch all rows from the view (use view.svc explicitly)
            result = await sap_client.get_entities('view.svc/MASHURA_StockChangeB1SLQuery', top=self.batch_size)
            if result["msg"] != "success":
                logger.error(f"Failed to fetch stock changes: {result.get('error')}")
                return {"msg": "failure", "error": result.get("error")}
            rows = result["data"].get("value", [])
            if not rows:
                logger.info("No stock changes found in the view.")
                return {"msg": "success", "processed": 0, "success": 0, "errors": 0}

            processed = 0
            success = 0
            errors = 0
            for row in rows:
                item_code = row.get("ItemCode")
                variant_id = row.get("Variant_ID")
                available = row.get("Available")
                onhand = row.get("OnHand")
                location_id = row.get("Location_ID")
                reference = f"{item_code}-{location_id}"
                log_status = "success"
                log_error = None
                try:
                    # Update Shopify inventory (available)
                    update_data = {
                        "location_id": location_id,
                        "inventory_item_id": variant_id,
                        "available": int(available)
                    }
                    store_key = None
                    for key, store in config_settings.get_enabled_stores().items():
                        if str(store.location_id).endswith(str(location_id)) or str(store.location_id) == str(location_id):
                            store_key = key
                            break
                    if not store_key:
                        raise Exception(f"No store found for location_id {location_id}")
                    result = await multi_store_shopify_client.update_inventory_level(store_key, update_data)
                    if result["msg"] != "success":
                        log_status = "failure"
                        log_error = result.get("error")
                        errors += 1
                    else:
                        await self.update_onhand_metafield(store_key, variant_id, onhand)
                        success += 1
                except Exception as e:
                    log_status = "failure"
                    log_error = str(e)
                    errors += 1
                finally:
                    await sl_add_log(
                        server="shopify",
                        endpoint="inventory_levels",
                        request_data=update_data,
                        response_data=log_error if log_status == "failure" else None,
                        status=log_status,
                        reference=reference,
                        action="quantity",
                        value=str(available)
                    )
                    processed += 1
                    await asyncio.sleep(0.1)
            logger.info(f"Stock change sync completed: {processed} processed, {success} successful, {errors} errors")
            return {"msg": "success", "processed": processed, "success": success, "errors": errors}
        except Exception as e:
            logger.error(f"Error in stock change sync: {str(e)}")
            return {"msg": "failure", "error": str(e)}

# Global instance
inventory_sync = InventorySync()

# Convenience function
async def sync_stock_change_view():
    """Sync inventory using the MASHURA_StockChangeB1SLQuery view."""
    return await inventory_sync.sync_stock_change_view() 