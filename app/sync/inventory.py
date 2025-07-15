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
        
    async def get_inventory_changes_from_sap(self, last_sync_time: str = None) -> Dict[str, Any]:
        """
        Get inventory changes from SAP since last sync
        Uses the change tracking table to get only modified items
        """
        try:
            # Build filter query for changes since last sync
            filter_query = None
            if last_sync_time:
                # Filter for changes after the last sync time
                filter_query = f"UpdateDate gt {last_sync_time}"
            
            # Get inventory changes from SAP custom endpoint
            result = await sap_client.get_inventory_changes(filter_query=filter_query)
            
            if result["msg"] == "failure":
                logger.error(f"Failed to get inventory changes from SAP: {result.get('error')}")
                return {"msg": "failure", "error": result.get("error")}
            
            changes = result["data"].get("value", [])
            logger.info(f"Retrieved {len(changes)} inventory changes from SAP")
            
            return {"msg": "success", "data": changes}
            
        except Exception as e:
            logger.error(f"Error getting inventory changes from SAP: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def get_current_inventory_from_sap(self, item_codes: List[str]) -> Dict[str, Any]:
        """
        Get current inventory quantities for specific items from SAP
        Used as fallback when change tracking is not available
        """
        try:
            # Build filter for specific item codes
            item_filter = " or ".join([f"ItemCode eq '{code}'" for code in item_codes])
            filter_query = f"({item_filter})"
            
            result = await sap_client.get_items(filter_query=filter_query)
            
            if result["msg"] == "failure":
                logger.error(f"Failed to get current inventory from SAP: {result.get('error')}")
                return {"msg": "failure", "error": result.get("error")}
            
            items = result["data"].get("value", [])
            logger.info(f"Retrieved current inventory for {len(items)} items from SAP")
            
            return {"msg": "success", "data": items}
            
        except Exception as e:
            logger.error(f"Error getting current inventory from SAP: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def get_shopify_inventory_mappings(self, item_codes: List[str]) -> Dict[str, Any]:
        """
        Get Shopify inventory mappings for SAP items
        Returns mapping of SAP item codes to Shopify inventory item IDs
        """
        try:
            # Get mappings from SAP U_SHOPIFY_MAPPING table
            item_codes_str = ",".join([f"'{code}'" for code in item_codes])
            filter_query = f"U_SAP_Type eq 'item' and U_Shopify_Type eq 'variant_inventory' and U_SAP_Code in ({item_codes_str})"
            
            result = await sap_client.get_entity('U_SHOPIFY_MAPPING', filter_query=filter_query)
            
            if result["msg"] == "failure":
                logger.error(f"Failed to get Shopify mappings: {result.get('error')}")
                return {"msg": "failure", "error": result.get("error")}
            
            mappings = result["data"].get("value", [])
            
            # Create lookup dictionary
            mapping_dict = {}
            for mapping in mappings:
                sap_code = mapping.get('U_SAP_Code')
                shopify_id = mapping.get('Code')
                store = mapping.get('U_Shopify_Store')
                
                if sap_code and shopify_id and store:
                    if sap_code not in mapping_dict:
                        mapping_dict[sap_code] = {}
                    mapping_dict[sap_code][store] = shopify_id
            
            logger.info(f"Retrieved {len(mapping_dict)} Shopify inventory mappings")
            return {"msg": "success", "data": mapping_dict}
            
        except Exception as e:
            logger.error(f"Error getting Shopify inventory mappings: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def update_shopify_inventory(self, item_code: str, store_mappings: Dict[str, str], 
                                     sap_quantities: Dict[str, int]) -> Dict[str, Any]:
        """
        Update inventory quantities in Shopify for a specific item across all stores
        """
        try:
            results = {}
            
            for store_key, inventory_id in store_mappings.items():
                try:
                    # Get store configuration
                    store_config = config_settings.get_store_by_name(store_key)
                    if not store_config:
                        logger.warning(f"Store configuration not found for {store_key}")
                        continue
                    
                    # Get quantity for this store's warehouse
                    warehouse_code = store_config.warehouse_code
                    quantity = sap_quantities.get(warehouse_code, 0)
                    
                    # Update inventory using Shopify REST API
                    update_data = {
                        "location_id": store_config.location_id,
                        "inventory_item_id": inventory_id,
                        "available": quantity
                    }
                    
                    result = await multi_store_shopify_client.update_inventory_level(
                        store_key, update_data
                    )
                    
                    if result["msg"] == "success":
                        # Log successful inventory update
                        await sl_add_log(
                            server="shopify",
                            endpoint=f"inventory_levels/{store_key}",
                            request_data=update_data,
                            response_data=result.get("data"),
                            status="success",
                            reference=item_code,
                            action="update_inventory",
                            value=f"Updated {item_code} to {quantity} in {store_key}"
                        )
                        
                        results[store_key] = {
                            "msg": "success",
                            "quantity": quantity,
                            "warehouse": warehouse_code
                        }
                    else:
                        # Log failed inventory update
                        await sl_add_log(
                            server="shopify",
                            endpoint=f"inventory_levels/{store_key}",
                            request_data=update_data,
                            response_data=result.get("error"),
                            status="failure",
                            reference=item_code,
                            action="update_inventory",
                            value=f"Failed to update {item_code} in {store_key}"
                        )
                        
                        results[store_key] = {
                            "msg": "failure",
                            "error": result.get("error")
                        }
                        
                except Exception as e:
                    logger.error(f"Error updating inventory for {item_code} in {store_key}: {str(e)}")
                    results[store_key] = {
                        "msg": "failure",
                        "error": str(e)
                    }
            
            return {"msg": "success", "results": results}
            
        except Exception as e:
            logger.error(f"Error updating Shopify inventory for {item_code}: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
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

    async def sync_inventory_changes(self, last_sync_time: str = None) -> Dict[str, Any]:
        """
        Main inventory sync function using change-based tracking
        """
        logger.info("Starting inventory sync using change-based tracking")
        
        try:
            # Get inventory changes from SAP
            changes_result = await self.get_inventory_changes_from_sap(last_sync_time)
            if changes_result["msg"] == "failure":
                return changes_result
            
            changes = changes_result["data"]
            if not changes:
                logger.info("No inventory changes found in SAP")
                return {"msg": "success", "processed": 0, "success": 0, "errors": 0}
            
            # Extract unique item codes from changes
            item_codes = list(set([change.get('ItemCode') for change in changes if change.get('ItemCode')]))
            
            # Get Shopify inventory mappings
            mappings_result = await self.get_shopify_inventory_mappings(item_codes)
            if mappings_result["msg"] == "failure":
                return mappings_result
            
            mappings = mappings_result["data"]
            
            # Process each item with changes
            processed = 0
            success = 0
            errors = 0
            
            for item_code in item_codes:
                try:
                    logger.info(f"Processing inventory changes for item: {item_code}")
                    
                    # Get store mappings for this item
                    store_mappings = mappings.get(item_code, {})
                    if not store_mappings:
                        logger.warning(f"No Shopify mappings found for item {item_code}")
                        continue
                    
                    # Get current quantities from SAP for this item
                    current_result = await self.get_current_inventory_from_sap([item_code])
                    if current_result["msg"] == "failure":
                        logger.error(f"Failed to get current inventory for {item_code}")
                        errors += 1
                        continue
                    
                    current_items = current_result["data"]
                    if not current_items:
                        logger.warning(f"No current inventory data found for {item_code}")
                        continue
                    
                    # Extract quantities by warehouse
                    sap_quantities = {}
                    for item in current_items:
                        warehouse_code = item.get('WarehouseCode', '01')  # Default warehouse
                        quantity = int(item.get('QuantityOnStock', 0))
                        sap_quantities[warehouse_code] = quantity
                    
                    # Update Shopify inventory
                    update_result = await self.update_shopify_inventory(
                        item_code, store_mappings, sap_quantities
                    )
                    
                    if update_result["msg"] == "success":
                        success += 1
                        logger.info(f"Successfully synced inventory for {item_code}")
                    else:
                        errors += 1
                        logger.error(f"Failed to sync inventory for {item_code}: {update_result.get('error')}")
                    
                    processed += 1
                    
                    # Add small delay to avoid overwhelming the APIs
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    logger.error(f"Error processing inventory changes for {item_code}: {str(e)}")
                    errors += 1
                    processed += 1
            
            # Log sync event
            log_sync_event(
                sync_type="inventory_changes",
                items_processed=processed,
                success_count=success,
                error_count=errors
            )
            
            logger.info(f"Inventory sync completed: {processed} processed, {success} successful, {errors} errors")
            
            return {
                "msg": "success",
                "processed": processed,
                "success": success,
                "errors": errors
            }
            
        except Exception as e:
            logger.error(f"Error in inventory sync: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def sync_all_inventory(self) -> Dict[str, Any]:
        """
        Sync all inventory quantities (fallback method)
        Used when change tracking is not available or for initial sync
        """
        logger.info("Starting full inventory sync")
        
        try:
            # Get all items that have Shopify mappings
            filter_query = "U_SAP_Type eq 'item' and U_Shopify_Type eq 'variant_inventory'"
            result = await sap_client.get_entity('U_SHOPIFY_MAPPING', filter_query=filter_query)
            
            if result["msg"] == "failure":
                return result
            
            mappings = result["data"].get("value", [])
            if not mappings:
                logger.info("No Shopify inventory mappings found")
                return {"msg": "success", "processed": 0, "success": 0, "errors": 0}
            
            # Group by SAP item code
            item_mappings = {}
            for mapping in mappings:
                sap_code = mapping.get('U_SAP_Code')
                shopify_id = mapping.get('Code')
                store = mapping.get('U_Shopify_Store')
                
                if sap_code and shopify_id and store:
                    if sap_code not in item_mappings:
                        item_mappings[sap_code] = {}
                    item_mappings[sap_code][store] = shopify_id
            
            # Process each item
            processed = 0
            success = 0
            errors = 0
            
            for item_code, store_mappings in item_mappings.items():
                try:
                    logger.info(f"Processing full inventory sync for item: {item_code}")
                    
                    # Get current quantities from SAP
                    current_result = await self.get_current_inventory_from_sap([item_code])
                    if current_result["msg"] == "failure":
                        errors += 1
                        continue
                    
                    current_items = current_result["data"]
                    if not current_items:
                        continue
                    
                    # Extract quantities by warehouse
                    sap_quantities = {}
                    for item in current_items:
                        warehouse_code = item.get('WarehouseCode', '01')
                        quantity = int(item.get('QuantityOnStock', 0))
                        sap_quantities[warehouse_code] = quantity
                    
                    # Update Shopify inventory
                    update_result = await self.update_shopify_inventory(
                        item_code, store_mappings, sap_quantities
                    )
                    
                    if update_result["msg"] == "success":
                        success += 1
                    else:
                        errors += 1
                    
                    processed += 1
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    logger.error(f"Error in full inventory sync for {item_code}: {str(e)}")
                    errors += 1
                    processed += 1
            
            # Log sync event
            log_sync_event(
                sync_type="inventory_full",
                items_processed=processed,
                success_count=success,
                error_count=errors
            )
            
            logger.info(f"Full inventory sync completed: {processed} processed, {success} successful, {errors} errors")
            
            return {
                "msg": "success",
                "processed": processed,
                "success": success,
                "errors": errors
            }
            
        except Exception as e:
            logger.error(f"Error in full inventory sync: {str(e)}")
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

# Convenience functions
async def sync_inventory():
    """Main inventory sync function - uses change-based tracking"""
    return await inventory_sync.sync_inventory_changes()

async def sync_all_inventory():
    """Full inventory sync function - syncs all items"""
    return await inventory_sync.sync_all_inventory() 

async def sync_stock_change_view():
    """Sync inventory using the MASHURA_StockChangeB1SLQuery view."""
    return await inventory_sync.sync_stock_change_view() 