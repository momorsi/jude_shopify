"""
Multi-Store New Items Sync Module
Syncs new items from SAP to multiple Shopify stores with different prices and inventory
Handles parent items and variants based on SAP master data structure
"""

import asyncio
from typing import Dict, Any, List, Optional
from app.services.sap.client import sap_client
from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.core.config import config_settings
from app.utils.logging import logger, log_sync_event
from datetime import datetime

class MultiStoreNewItemsSync:
    def __init__(self):
        self.batch_size = config_settings.master_data_batch_size
        self.shopify_field_mapping = {
            'ItemCode': 'sku',
            'ItemName': 'title',
            'FrgnName': 'description',
            'Barcode': 'barcode',
            'U_Text1': 'vendor',
            'U_BRND': 'brand',
        }
    
    async def get_new_items_from_sap(self) -> Dict[str, Any]:
        """
        Get new items from SAP that haven't been synced to Shopify yet
        """
        try:
            result = await sap_client.get_new_items()
            
            if result["msg"] == "failure":
                logger.error(f"Failed to get new items from SAP: {result.get('error')}")
                return {"msg": "failure", "error": result.get("error")}
            
            items = result["data"].get("value", [])
            logger.info(f"Retrieved {len(items)} new items from SAP")
            
            return {"msg": "success", "data": items}
            
        except Exception as e:
            logger.error(f"Error getting new items from SAP: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    def group_items_by_parent(self, items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group items by MainProduct and Shopify_Store to create product variants
        """
        main_item_groups = {}
        for item in items:
            main_product = item.get('MainProduct', '')
            shopify_store = item.get('Shopify_Store', '')
            if main_product and shopify_store:
                key = (main_product, shopify_store)
                if key not in main_item_groups:
                    main_item_groups[key] = []
                main_item_groups[key].append(item)
            else:
                # Fallback: group by itemcode and store if MainProduct is missing
                item_code = item.get('itemcode', '')
                key = (item_code, shopify_store)
                if key not in main_item_groups:
                    main_item_groups[key] = []
                main_item_groups[key].append(item)
        # Debug logging for group keys
        from app.utils.logging import logger
        for group_key, group_items in main_item_groups.items():
            logger.info(f"Product group: {group_key} has {len(group_items)} items")
        return main_item_groups
    
    def map_sap_item_to_shopify_product(self, sap_items: List[Dict[str, Any]], store_config: Any) -> Dict[str, Any]:
        """
        Map SAP items to Shopify product format for a specific store
        Handles both single items and product variants
        """
        try:
            if len(sap_items) == 1:
                # Single item (no variants)
                item = sap_items[0]
                return self._create_single_product(item, store_config)
            else:
                # Multiple items (variants)
                return self._create_product_with_variants(sap_items, store_config)
                
        except Exception as e:
            logger.error(f"Error mapping SAP items to Shopify product: {str(e)}")
            raise
    
    def _create_single_product(self, sap_item: Dict[str, Any], store_config: Any) -> Dict[str, Any]:
        """
        Create a single product without variants
        """
        price = self._get_store_price(sap_item, store_config.price_list)
        inventory_quantity = self._get_store_inventory(sap_item, store_config.warehouse_code)
        
        product_data = {
            "title": sap_item.get('ItemName', ''),
            "descriptionHtml": sap_item.get('FrgnName', ''),
            "vendor": sap_item.get('U_Text1', ''),
            "productType": "Default",
            "status": "DRAFT",  # Always create as draft for testing
            "tags": self._extract_tags(sap_item),
            "variants": [self._create_variant(sap_item, store_config, price, inventory_quantity)]
        }
        
        # Add SEO fields
        if sap_item.get('ItemName'):
            product_data["seo"] = {
                "title": sap_item.get('ItemName'),
                "description": sap_item.get('FrgnName', '')[:255] if sap_item.get('FrgnName') else ''
            }
        
        return product_data
    
    def _create_product_with_variants(self, sap_items: List[Dict[str, Any]], store_config: Any) -> Dict[str, Any]:
        """
        Create a product with multiple variants based on color, including inventory and price
        """
        # Use the first item as the base product
        base_item = sap_items[0]
        product_data = {
            "title": base_item.get('MainProduct', ''),
            "status": "DRAFT",
            "options": ["Color"],
            "variants": []
        }
        # Add all variants with correct options, sku, inventory, and price fields
        for item in sap_items:
            inventory_quantity = int(item.get('Available', 0))
            price = float(item.get('Price', 0))
            variant = {
                "options": [item.get('Color', '')],
                "sku": item.get('itemcode', ''),
                "price": str(price),
                "inventoryManagement": "SHOPIFY",
                "inventoryQuantities": [{
                    "availableQuantity": inventory_quantity,
                    "locationId": store_config.location_id
                }]
            }
            product_data["variants"].append(variant)
        return product_data
    
    def _get_store_price(self, sap_item: Dict[str, Any], price_list: int) -> float:
        """
        Get price for a specific store based on price list
        Currently uses the single Price field from SAP, but can be extended for multiple price lists
        """
        # For now, use the single Price field from SAP
        # In the future, this can be extended to handle multiple price lists
        price = sap_item.get('Price', 0.0)
        
        # Apply store-specific price adjustments if needed
        if price_list == 1:  # Local store (SAR)
            return price
        elif price_list == 2:  # International store (USD)
            # Convert SAR to USD (you can adjust the exchange rate)
            exchange_rate = 0.27  # 1 SAR = 0.27 USD (approximate)
            return price * exchange_rate
        
        return price
    
    def _get_store_inventory(self, sap_item: Dict[str, Any], warehouse_code: str) -> int:
        """
        Get inventory quantity for a specific store based on warehouse
        Currently uses a default value, but can be extended for warehouse-specific inventory
        """
        # For now, use a default inventory value
        # In the future, this can be extended to get warehouse-specific inventory
        default_inventory = 10  # Default inventory for new items
        
        # You can implement warehouse-specific logic here
        if warehouse_code == "01":  # Local warehouse
            return default_inventory
        elif warehouse_code == "02":  # International warehouse
            return default_inventory // 2  # Half inventory for international store
        
        return default_inventory
    
    def _create_variant(self, sap_item: Dict[str, Any], store_config: Any, price: float, inventory_quantity: int) -> Dict[str, Any]:
        """
        Create Shopify variant from SAP item for a specific store
        Enhanced to properly handle color options
        """
        variant_data = {
            "sku": sap_item.get('itemcode', ''),
            "price": str(price),
            "inventoryPolicy": "DENY",
            "inventoryManagement": "SHOPIFY",
            "inventoryQuantities": [{
                "availableQuantity": inventory_quantity,
                "locationId": store_config.location_id
            }],
            "weight": sap_item.get('InventoryWeight', 0.0),
            "weightUnit": "KILOGRAMS",
            "option1": sap_item.get('Color', '')  # Set the color as the first option value
        }
        # Add barcode if available
        if sap_item.get('Barcode'):
            variant_data["barcode"] = sap_item.get('Barcode')
        return variant_data
    
    def _extract_tags(self, sap_item: Dict[str, Any]) -> List[str]:
        """
        Extract tags from SAP item custom fields
        """
        tags = []
        
        # Add brand as tag
        if sap_item.get('U_BRND'):
            tags.append(f"Brand:{sap_item['U_BRND']}")
        
        # Add other custom fields as tags
        custom_fields = ['U_Color', 'U_Flavor', 'U_Size', 'U_Attribute']
        for field in custom_fields:
            if sap_item.get(field):
                tags.append(f"{field}:{sap_item[field]}")
        
        return tags
    
    async def create_product_in_store(self, store_key: str, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create product in a specific Shopify store
        Returns main product ID, all variant IDs, and all inventory item IDs
        """
        try:
            result = await multi_store_shopify_client.create_product(store_key, product_data)
            from app.utils.logging import logger
            logger.error(f"Shopify full response for store {store_key}: {result}")
            if result["msg"] == "failure":
                return result
            response_data = result["data"]["productCreate"]
            if response_data.get("userErrors"):
                errors = [error["message"] for error in response_data["userErrors"]]
                return {"msg": "failure", "error": "; ".join(errors)}
            product = response_data["product"]
            # Extract all variants and inventory item IDs for SAP mapping
            shopify_variants = []
            for variant_edge in product["variants"]["edges"]:
                variant = variant_edge["node"]
                shopify_variants.append({
                    "id": variant["id"],
                    "sku": variant["sku"],
                    "inventory_item_id": variant["inventoryItem"]["id"],
                    "selected_options": variant.get("selectedOptions", [])
                })
            return {
                "msg": "success",
                "shopify_product_id": product["id"],
                "shopify_variants": shopify_variants,  # All variants for proper mapping
                "handle": product["handle"]
            }
        except Exception as e:
            logger.error(f"Error creating product in store {store_key}: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def update_sap_with_shopify_ids(self, sap_items: List[Dict[str, Any]], store_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update SAP items with Shopify product and variant IDs from all stores
        Enhanced to properly map variants to their specific SAP items
        """
        try:
            # Get the Shopify response data
            shopify_data = None
            for store_key, result in store_results.items():
                if result["msg"] == "success":
                    shopify_data = result
                    break
            
            if not shopify_data:
                logger.error("No successful Shopify results found")
                return {"msg": "failure", "error": "No successful Shopify results"}
            
            # Extract product and variants from Shopify response
            shopify_product_id = shopify_data["shopify_product_id"]
            shopify_variants = shopify_data.get("shopify_variants", [])
            
            # Update each SAP item with its corresponding Shopify variant ID
            for sap_item in sap_items:
                item_code = sap_item.get('ItemCode')
                if not item_code:
                    continue
                
                # Prepare update data for SAP
                update_data = {
                    "U_SyncDT": datetime.now().strftime("%Y-%m-%d"),
                    "U_SyncTime": "SYNCED"
                }
                
                # Add store-specific product ID
                for store_key, result in store_results.items():
                    if result["msg"] == "success":
                        shopify_data = result
                        update_data[f"U_{store_key.upper()}_SID"] = shopify_data["shopify_product_id"].split('/')[-1]
                        
                        # Find the specific variant ID for this SAP item
                        sap_sku = sap_item.get('ItemCode')
                        sap_color = sap_item.get('U_Color', '')
                        
                        # Try to find matching variant by SKU or color
                        variant_id = None
                        if shopify_data.get("shopify_variants"):
                            for variant in shopify_data["shopify_variants"]:
                                if variant.get("sku") == sap_sku:
                                    variant_id = variant.get("id")
                                    break
                        
                        if variant_id:
                            update_data[f"U_{store_key.upper()}_VARIANT_SID"] = variant_id.split('/')[-1]
                        else:
                            # Fallback to first variant if specific match not found
                            update_data[f"U_{store_key.upper()}_VARIANT_SID"] = shopify_data["shopify_variant_id"].split('/')[-1]
                        
                        update_data[f"U_{store_key.upper()}_INVENTORY_SID"] = shopify_data["shopify_inventory_item_id"].split('/')[-1]
                
                # Update the SAP item
                result = await sap_client.update_item(item_code, update_data)
                
                if result["msg"] == "failure":
                    logger.error(f"Failed to update SAP item {item_code}: {result.get('error')}")
                    return {"msg": "failure", "error": result.get("error")}
                
                logger.info(f"Successfully updated SAP item {item_code} with Shopify IDs")
            
            return {"msg": "success"}
            
        except Exception as e:
            logger.error(f"Error updating SAP with Shopify IDs: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def sync_new_items(self) -> Dict[str, Any]:
        """
        Main sync function for new items to multiple stores
        Handles parent items and variants
        """
        logger.info("Starting multi-store new items sync from SAP to Shopify")
        try:
            # Get enabled stores
            enabled_stores = multi_store_shopify_client.get_enabled_stores()
            if not enabled_stores:
                logger.error("No enabled Shopify stores found")
                return {"msg": "failure", "error": "No enabled Shopify stores found"}

            processed = 0
            success = 0
            errors = 0

            for store_key, store_config in enabled_stores.items():
                logger.info(f"Fetching new items for store: {store_key}")
                sap_result = await sap_client.get_new_items(store_key=store_key)
                if sap_result["msg"] == "failure":
                    logger.error(f"Failed to get new items from SAP for store {store_key}: {sap_result.get('error')}")
                    continue
                items = sap_result["data"].get("value", [])
                if not items:
                    logger.info(f"No new items found in SAP for store {store_key}")
                    continue
                # Group items by parent to handle variants (all items are for this store only)
                parent_groups = self.group_items_by_parent(items)
                logger.info(f"Grouped {len(items)} items into {len(parent_groups)} product groups for store {store_key}")
                for parent_key, group_items in parent_groups.items():
                    try:
                        logger.info(f"Processing product group: {parent_key} with {len(group_items)} items for store {store_key}")
                        # Map SAP items to Shopify format for this store
                        product_data = self.map_sap_item_to_shopify_product(group_items, store_config)
                        # Create product in this store
                        store_result = await self.create_product_in_store(store_key, product_data)
                        store_results = {store_key: store_result}
                        if store_result["msg"] == "failure":
                            logger.error(f"Failed to create product in store {store_key}: {store_result.get('error')}")
                            errors += 1
                        else:
                            logger.info(f"Successfully created product in store {store_key}")
                            # Save Shopify IDs to SAP mapping table
                            shopify_product_id = store_result["shopify_product_id"].split("/")[-1]
                            main_product_name = group_items[0].get("MainProduct", "")
                            await sap_client.add_shopify_mapping({
                                "Code": shopify_product_id,
                                "Name": shopify_product_id,
                                "U_Shopify_Type": "product",
                                "U_SAP_Code": main_product_name,
                                "U_Shopify_Store": store_key,
                                "U_SAP_Type": "item"
                            })
                            for sap_item in group_items:
                                itemcode = sap_item.get("itemcode", "")
                                # Find the matching variant in the Shopify response
                                variant_id = None
                                inventory_id = None
                                for variant in store_result["shopify_variants"]:
                                    if variant["sku"] == itemcode:
                                        variant_id = variant["id"].split("/")[-1]
                                        inventory_id = variant["inventory_item_id"].split("/")[-1]
                                        break
                                if variant_id:
                                    await sap_client.add_shopify_mapping({
                                        "Code": variant_id,
                                        "Name": variant_id,
                                        "U_Shopify_Type": "variant",
                                        "U_SAP_Code": itemcode,
                                        "U_Shopify_Store": store_key,
                                        "U_SAP_Type": "item"
                                    })
                                if inventory_id:
                                    await sap_client.add_shopify_mapping({
                                        "Code": inventory_id,
                                        "Name": inventory_id,
                                        "U_Shopify_Type": "variant_inventory",
                                        "U_SAP_Code": itemcode,
                                        "U_Shopify_Store": store_key,
                                        "U_SAP_Type": "item"
                                    })
                            # Update SAP with Shopify IDs (legacy/compat)
                            sap_update_result = await self.update_sap_with_shopify_ids(group_items, store_results)
                            if sap_update_result["msg"] == "failure":
                                logger.error(f"Failed to update SAP with Shopify IDs: {sap_update_result.get('error')}")
                            success += 1
                    except Exception as e:
                        logger.error(f"Error processing product group {parent_key} for store {store_key}: {str(e)}")
                        errors += 1
                    processed += 1
                    await asyncio.sleep(0.5)
            # Log sync event
            log_sync_event(
                sync_type="multi_store_new_items_sap_to_shopify",
                items_processed=processed,
                success_count=success,
                error_count=errors
            )
            logger.info(f"Multi-store new items sync completed: {processed} processed, {success} successful, {errors} errors")
            return {
                "msg": "success",
                "processed": processed,
                "success": success,
                "errors": errors
            }
        except Exception as e:
            logger.error(f"Error in multi-store new items sync: {str(e)}")
            return {"msg": "failure", "error": str(e)}

# Create singleton instance
multi_store_new_items_sync = MultiStoreNewItemsSync() 