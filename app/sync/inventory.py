"""
Inventory Sync Module
Syncs inventory changes from SAP to Shopify using change-based tracking
Supports multi-store inventory management
"""

import asyncio
import httpx
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
        

    

    

    

    

    def _get_store_for_location(self, location_id: str) -> str:
        """
        Determine which store to use based on location_id
        This is a simple implementation - you may need to enhance this based on your specific logic
        """
        # For now, return the first enabled store
        # You can enhance this to map specific location_ids to specific stores
        enabled_stores = config_settings.get_enabled_stores()
        if enabled_stores:
            return list(enabled_stores.keys())[0]
        return None

    async def create_inventory_item(self, store_key: str, item_code: str, location_id: str, available: int) -> Dict[str, Any]:
        """
        Create inventory item for a variant at a specific location
        """
        try:
            # First, get the variant ID for this item_code
            variant_id = await self._get_variant_id_by_sku(store_key, item_code)
            if not variant_id:
                return {"msg": "failure", "error": f"Variant not found for SKU {item_code}"}
            
            # Create inventory item at the location
            store_config = config_settings.get_enabled_stores()[store_key]
            url = f"https://{store_config.shop_url}/admin/api/{store_config.api_version}/inventory_levels/set.json"
            
            inventory_data = {
                "location_id": location_id,
                "inventory_item_id": variant_id,
                "available": available
            }
            
            headers = {
                'X-Shopify-Access-Token': store_config.access_token,
                'Content-Type': 'application/json',
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=inventory_data, headers=headers)
                if response.status_code == 200:
                    response_data = response.json()
                    return {
                        "msg": "success", 
                        "inventory_item_id": variant_id,
                        "data": response_data
                    }
                else:
                    return {"msg": "failure", "error": f"HTTP {response.status_code}: {response.text}"}
        except Exception as e:
            return {"msg": "failure", "error": str(e)}

    async def _get_variant_id_by_sku(self, store_key: str, sku: str) -> str:
        """
        Get variant ID by SKU using GraphQL
        """
        try:
            query = """
            query getVariantBySku($sku: String!) {
                productVariants(first: 1, query: $sku) {
                    edges {
                        node {
                            id
                            sku
                            inventoryItem {
                                id
                            }
                        }
                    }
                }
            }
            """
            
            variables = {"sku": sku}
            result = await multi_store_shopify_client.execute_graphql_query(store_key, query, variables)
            
            if result["msg"] == "success" and result["data"].get("productVariants", {}).get("edges"):
                variant = result["data"]["productVariants"]["edges"][0]["node"]
                return variant["inventoryItem"]["id"]
            return None
        except Exception as e:
            logger.error(f"Error getting variant ID by SKU: {str(e)}")
            return None

    async def save_inventory_mapping(self, item_code: str, inventory_item_id: str, mapping_type: str) -> Dict[str, Any]:
        """
        Save inventory mapping back to SAP
        """
        try:
            mapping_data = {
                "Code": inventory_item_id,
                "Name": inventory_item_id,
                "U_Shopify_Type": mapping_type,
                "U_SAP_Code": item_code,
                "U_SAP_Type": "item",
                "U_CreateDT": datetime.now().strftime('%Y%m%d')
            }
            
            result = await sap_client.add_shopify_mapping(mapping_data)
            
            if result["msg"] == "success":
                logger.info(f"Successfully saved inventory mapping for {item_code}: {inventory_item_id}")
                return {"msg": "success", "mapping_id": inventory_item_id}
            else:
                logger.error(f"Failed to save inventory mapping: {result.get('error')}")
                return {"msg": "failure", "error": result.get("error")}
        except Exception as e:
            logger.error(f"Error saving inventory mapping: {str(e)}")
            return {"msg": "failure", "error": str(e)}

    async def sync_stock_change_view(self) -> Dict[str, Any]:
        """
        Sync inventory using the MASHURA_StockChangeB1SLQuery SAP view.
        New logic:
        - If Variant_ID is null: Create inventory item and save mapping to SAP
        - If Variant_ID is not null: Update existing inventory
        - Handles multiple locations per product dynamically
        """
        logger.info("Starting stock change sync using MASHURA_StockChangeB1SLQuery view")
        try:
            # Get enabled stores
            enabled_stores = config_settings.get_enabled_stores()
            if not enabled_stores:
                logger.error("No enabled Shopify stores found")
                return {"msg": "failure", "error": "No enabled Shopify stores found"}

            processed = 0
            success = 0
            errors = 0

            for store_key, store_config in enabled_stores.items():
                logger.info(f"Processing inventory changes for store: {store_key}")
                
                # Fetch rows from the view filtered by store
                query = f"view.svc/MASHURA_StockChangeB1SLQuery?$filter=Shopify_Store eq '{store_key}'"
                result = await sap_client._make_request("GET", query)
                
                if result["msg"] != "success":
                    logger.error(f"Failed to fetch stock changes for store {store_key}: {result.get('error')}")
                    continue
                
                rows = result["data"].get("value", [])
                if not rows:
                    logger.info(f"No stock changes found for store {store_key}.")
                    continue
                
                logger.info(f"Processing {len(rows)} inventory changes for store {store_key}")
                
                for row in rows:
                    item_code = row.get("ItemCode")
                    variant_id = row.get("Variant_ID")  # This could be null
                    available = row.get("Available")
                    onhand = row.get("OnHand")
                    location_id = row.get("Location_ID")  # Actual Shopify location ID
                    reference = f"{item_code}-{location_id}"
                    log_status = "success"
                    log_error = None
                    
                    try:
                        # Use the current store_key from the loop instead of determining it
                        if variant_id is None or variant_id == "":
                            # Create inventory item for this variant at this location
                            logger.info(f"Creating inventory for item {item_code} at location {location_id}")
                            result = await self.create_inventory_item(store_key, item_code, location_id, available)
                            if result["msg"] == "success":
                                # Save the created inventory item ID back to SAP
                                await self.save_inventory_mapping(item_code, result["inventory_item_id"], "variant_inventory")
                                success += 1
                            else:
                                log_status = "failure"
                                log_error = result.get("error")
                                errors += 1
                        else:
                            # Update existing inventory
                            logger.info(f"Updating inventory for item {item_code} (variant {variant_id}) at location {location_id}")
                            update_data = {
                                "location_id": location_id,
                                "inventory_item_id": variant_id,
                                "available": int(available)
                            }
                            result = await multi_store_shopify_client.update_inventory_level(store_key, update_data)
                            if result["msg"] != "success":
                                log_status = "failure"
                                log_error = result.get("error")
                                errors += 1
                            else:
                                success += 1
                                
                    except Exception as e:
                        log_status = "failure"
                        log_error = str(e)
                        errors += 1
                    finally:
                        await sl_add_log(
                            server="shopify",
                            endpoint="inventory_levels",
                            request_data={"item_code": item_code, "variant_id": variant_id, "location_id": location_id, "available": available},
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