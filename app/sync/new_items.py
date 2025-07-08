"""
New Items Sync Module
Syncs new items from SAP to Shopify and updates SAP with Shopify product IDs
"""

import asyncio
from typing import Dict, Any, List, Optional
from app.services.sap.client import sap_client
from app.services.shopify.client import shopify_client
from app.core.config import config_settings
from app.utils.logging import logger, log_sync_event

class NewItemsSync:
    def __init__(self):
        self.batch_size = config_settings.master_data_batch_size
        self.shopify_field_mapping = {
            'ItemCode': 'sku',
            'ItemName': 'title',
            'ForeignName': 'description',
            'BarCode': 'barcode',
            'U_Text1': 'vendor',  # Assuming U_Text1 contains vendor info
            'U_BRND': 'brand',    # Assuming U_BRND contains brand info
        }
    
    async def get_new_items_from_sap(self) -> Dict[str, Any]:
        """
        Get new items from SAP that haven't been synced to Shopify yet
        """
        try:
            # Get new items from SAP custom endpoint
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
    
    def map_sap_item_to_shopify_product(self, sap_item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Map SAP item data to Shopify product format
        """
        try:
            # Basic product mapping
            product_data = {
                "title": sap_item.get('ItemName', ''),
                "descriptionHtml": sap_item.get('ForeignName', ''),
                "vendor": sap_item.get('U_Text1', ''),
                "productType": "Default",  # You can customize this
                "status": "ACTIVE" if sap_item.get('Valid') == 'tYES' else "DRAFT",
                "tags": self._extract_tags(sap_item),
                "variants": [self._create_variant(sap_item)]
            }
            
            # Add SEO fields if available
            if sap_item.get('ItemName'):
                product_data["seo"] = {
                    "title": sap_item.get('ItemName'),
                    "description": sap_item.get('ForeignName', '')[:255]  # Limit to 255 chars
                }
            
            return product_data
            
        except Exception as e:
            logger.error(f"Error mapping SAP item to Shopify product: {str(e)}")
            raise
    
    def _create_variant(self, sap_item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create Shopify variant from SAP item
        """
        # Get price from ItemPrices collection
        price = 0.0
        if sap_item.get('ItemPrices'):
            for price_info in sap_item['ItemPrices']:
                if price_info.get('PriceList') == 1:  # Default price list
                    price = price_info.get('Price', 0.0)
                    break
        
        variant_data = {
            "sku": sap_item.get('ItemCode', ''),
            "price": str(price),
            "inventoryPolicy": "DENY",
            "inventoryManagement": "SHOPIFY",
            "inventoryQuantities": [{
                "availableQuantity": int(sap_item.get('QuantityOnStock', 0)),
                "locationId": config_settings.shopify_location_id
            }],
            "weight": sap_item.get('InventoryWeight', 0.0),
            "weightUnit": "KILOGRAMS"
        }
        
        # Add barcode if available
        if sap_item.get('BarCode'):
            variant_data["barcode"] = sap_item.get('BarCode')
        
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
    
    async def create_product_in_shopify(self, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create product in Shopify
        """
        try:
            mutation = """
            mutation productCreate($input: ProductInput!) {
                productCreate(input: $input) {
                    product {
                        id
                        title
                        handle
                        variants(first: 1) {
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
                    userErrors {
                        field
                        message
                    }
                }
            }
            """
            
            result = await shopify_client.execute_query(mutation, {"input": product_data})
            
            if result["msg"] == "failure":
                return {"msg": "failure", "error": result.get("error")}
            
            response_data = result["data"]["productCreate"]
            
            if response_data.get("userErrors"):
                errors = [error["message"] for error in response_data["userErrors"]]
                return {"msg": "failure", "error": "; ".join(errors)}
            
            product = response_data["product"]
            return {
                "msg": "success",
                "shopify_product_id": product["id"],
                "shopify_variant_id": product["variants"]["edges"][0]["node"]["id"],
                "shopify_inventory_item_id": product["variants"]["edges"][0]["node"]["inventoryItem"]["id"],
                "handle": product["handle"]
            }
            
        except Exception as e:
            logger.error(f"Error creating product in Shopify: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def update_sap_with_shopify_id(self, sap_item_code: str, shopify_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update SAP item with Shopify product ID and other sync information
        """
        try:
            # Prepare update data for SAP
            update_data = {
                "U_Main_SID": shopify_data["shopify_product_id"].split('/')[-1],  # Extract ID from gid
                "U_Price_SID": shopify_data["shopify_variant_id"].split('/')[-1],  # Extract ID from gid
                "U_Extend_SID": shopify_data["shopify_inventory_item_id"].split('/')[-1],  # Extract ID from gid
                "U_SyncDT": asyncio.get_event_loop().time(),  # Current timestamp
                "U_SyncTime": "SYNCED"  # Mark as synced
            }
            
            # Update the SAP item
            result = await sap_client.update_item(sap_item_code, update_data)
            
            if result["msg"] == "failure":
                logger.error(f"Failed to update SAP item {sap_item_code}: {result.get('error')}")
                return {"msg": "failure", "error": result.get("error")}
            
            logger.info(f"Successfully updated SAP item {sap_item_code} with Shopify IDs")
            return {"msg": "success"}
            
        except Exception as e:
            logger.error(f"Error updating SAP with Shopify ID: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def sync_new_items(self) -> Dict[str, Any]:
        """
        Main sync function for new items
        """
        logger.info("Starting new items sync from SAP to Shopify")
        
        try:
            # Get new items from SAP
            sap_result = await self.get_new_items_from_sap()
            if sap_result["msg"] == "failure":
                return sap_result
            
            items = sap_result["data"]
            if not items:
                logger.info("No new items found in SAP")
                return {"msg": "success", "processed": 0, "success": 0, "errors": 0}
            
            # Process each item
            processed = 0
            success = 0
            errors = 0
            
            for item in items:
                try:
                    logger.info(f"Processing SAP item: {item.get('ItemCode')}")
                    
                    # Map SAP item to Shopify format
                    product_data = self.map_sap_item_to_shopify_product(item)
                    
                    # Create product in Shopify
                    shopify_result = await self.create_product_in_shopify(product_data)
                    
                    if shopify_result["msg"] == "failure":
                        logger.error(f"Failed to create product in Shopify: {shopify_result.get('error')}")
                        errors += 1
                        continue
                    
                    # Update SAP with Shopify IDs
                    sap_update_result = await self.update_sap_with_shopify_id(
                        item['ItemCode'], 
                        shopify_result
                    )
                    
                    if sap_update_result["msg"] == "failure":
                        logger.error(f"Failed to update SAP with Shopify ID: {sap_update_result.get('error')}")
                        # Note: We don't count this as an error since the product was created successfully
                        # But we should log it for investigation
                    
                    success += 1
                    logger.info(f"Successfully synced item {item.get('ItemCode')} to Shopify")
                    
                except Exception as e:
                    logger.error(f"Error processing item {item.get('ItemCode')}: {str(e)}")
                    errors += 1
                
                processed += 1
                
                # Add small delay to avoid overwhelming the APIs
                await asyncio.sleep(0.5)
            
            # Log sync event
            log_sync_event(
                sync_type="new_items_sap_to_shopify",
                items_processed=processed,
                success_count=success,
                error_count=errors
            )
            
            logger.info(f"New items sync completed: {processed} processed, {success} successful, {errors} errors")
            
            return {
                "msg": "success",
                "processed": processed,
                "success": success,
                "errors": errors
            }
            
        except Exception as e:
            logger.error(f"Error in new items sync: {str(e)}")
            return {"msg": "failure", "error": str(e)}

# Create singleton instance
new_items_sync = NewItemsSync() 