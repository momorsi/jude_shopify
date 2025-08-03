"""
Price Changes Sync Module
Syncs price changes from SAP to Shopify including product and variant price updates
"""

import asyncio
from typing import Dict, Any, List, Optional
from app.services.sap.client import sap_client
from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.core.config import config_settings
from app.utils.logging import logger, log_sync_event
from app.services.sap.api_logger import sl_add_log
from datetime import datetime

class PriceChangesSync:
    def __init__(self):
        self.batch_size = config_settings.price_changes_batch_size

    async def get_price_changes(self, store_key: str) -> Dict[str, Any]:
        """
        Get price changes from SAP for a specific store
        """
        try:
            # Query the MASHURA_PriceChangeB1SLQuery view
            query = f"view.svc/MASHURA_PriceChangeB1SLQuery?$filter=Shopify_Store eq '{store_key}'"
            
            result = await sap_client._make_request("GET", query)
            
            if result["msg"] == "failure":
                logger.error(f"Failed to get price changes from SAP for store {store_key}: {result.get('error')}")
                return {"msg": "failure", "error": result.get('error')}
            
            items = result["data"].get("value", [])
            logger.info(f"Found {len(items)} price changes for store {store_key}")
            
            return {"msg": "success", "data": {"items": items}}
            
        except Exception as e:
            logger.error(f"Error getting price changes for store {store_key}: {str(e)}")
            return {"msg": "failure", "error": str(e)}

    async def update_product_price(self, store_key: str, product_id: str, price: float) -> Dict[str, Any]:
        """
        Update product price in Shopify by updating the default variant
        """
        try:
            # First, get the product to find its default variant
            product_result = await multi_store_shopify_client.get_product_by_id(store_key, product_id)
            
            if product_result["msg"] == "failure":
                logger.error(f"Failed to get product {product_id} for price update: {product_result.get('error')}")
                return product_result
            
            product_data = product_result["data"]["product"]
            variants = product_data.get("variants", {}).get("edges", [])
            
            if not variants:
                logger.error(f"No variants found for product {product_id}")
                return {"msg": "failure", "error": f"No variants found for product {product_id}"}
            
            # Get the first variant (default variant)
            default_variant = variants[0]["node"]
            variant_id = default_variant["id"]
            
            logger.info(f"Updating default variant {variant_id} price for product {product_id}")
            
            # Log the update
            await sl_add_log(
                server="shopify",
                endpoint=f"/admin/api/graphql_{store_key}",
                request_data={"product_id": product_id, "variant_id": variant_id, "price": price},
                action="update_product_price",
                value=f"Updating product {product_id} default variant price to {price} in store {store_key}"
            )
            
            # Update the default variant's price
            result = await multi_store_shopify_client.update_variant(
                store_key, 
                variant_id, 
                {"price": str(price)}
            )
            
            if result["msg"] == "success":
                await sl_add_log(
                    server="shopify",
                    endpoint=f"/admin/api/graphql_{store_key}",
                    response_data={"product_id": product_id, "variant_id": variant_id, "price": price},
                    status="success",
                    action="update_product_price",
                    value=f"Successfully updated product {product_id} default variant price to {price} in store {store_key}"
                )
                logger.info(f"Successfully updated product {product_id} default variant price to {price} in store {store_key}")
            else:
                await sl_add_log(
                    server="shopify",
                    endpoint=f"/admin/api/graphql_{store_key}",
                    response_data={"error": result.get("error")},
                    status="failure",
                    action="update_product_price",
                    value=f"Failed to update product {product_id} default variant price in store {store_key}: {result.get('error')}"
                )
                logger.error(f"Failed to update product {product_id} default variant price in store {store_key}: {result.get('error')}")
            
            return result
            
        except Exception as e:
            await sl_add_log(
                server="shopify",
                endpoint=f"/admin/api/graphql_{store_key}",
                response_data={"error": str(e)},
                status="failure",
                action="update_product_price",
                value=f"Exception updating product {product_id} price in store {store_key}: {str(e)}"
            )
            logger.error(f"Error updating product {product_id} price in store {store_key}: {str(e)}")
            return {"msg": "failure", "error": str(e)}

    async def update_variant_price(self, store_key: str, variant_id: str, price: float) -> Dict[str, Any]:
        """
        Update variant price in Shopify
        """
        try:
            # Log the update
            await sl_add_log(
                server="shopify",
                endpoint=f"/admin/api/graphql_{store_key}",
                request_data={"variant_id": variant_id, "price": price},
                action="update_variant_price",
                value=f"Updating variant {variant_id} price to {price} in store {store_key}"
            )
            
            result = await multi_store_shopify_client.update_variant(
                store_key, 
                variant_id, 
                {"price": str(price)}
            )
            
            if result["msg"] == "success":
                await sl_add_log(
                    server="shopify",
                    endpoint=f"/admin/api/graphql_{store_key}",
                    response_data={"variant_id": variant_id, "price": price},
                    status="success",
                    action="update_variant_price",
                    value=f"Successfully updated variant {variant_id} price to {price} in store {store_key}"
                )
                logger.info(f"Successfully updated variant {variant_id} price to {price} in store {store_key}")
            else:
                await sl_add_log(
                    server="shopify",
                    endpoint=f"/admin/api/graphql_{store_key}",
                    response_data={"error": result.get("error")},
                    status="failure",
                    action="update_variant_price",
                    value=f"Failed to update variant {variant_id} price in store {store_key}: {result.get('error')}"
                )
                logger.error(f"Failed to update variant {variant_id} price in store {store_key}: {result.get('error')}")
            
            return result
            
        except Exception as e:
            await sl_add_log(
                server="shopify",
                endpoint=f"/admin/api/graphql_{store_key}",
                response_data={"error": str(e)},
                status="failure",
                action="update_variant_price",
                value=f"Exception updating variant {variant_id} price in store {store_key}: {str(e)}"
            )
            logger.error(f"Error updating variant {variant_id} price in store {store_key}: {str(e)}")
            return {"msg": "failure", "error": str(e)}

    async def log_price_change_to_api_log(self, item_code: str, store_key: str, price: float) -> Dict[str, Any]:
        """
        Log price change to SAP API_LOG table
        """
        try:
            reference = f"{item_code}-{store_key}"
            
            await sl_add_log(
                server="sap",
                endpoint="price_change",
                request_data={"item_code": item_code, "store_key": store_key, "price": price},
                response_data={"reference": reference, "value": str(price)},
                status="success",
                action="price",
                reference=reference,
                value=str(price)
            )
            
            logger.info(f"Successfully logged price change for {reference}: {price}")
            return {"msg": "success"}
            
        except Exception as e:
            logger.error(f"Error logging price change for {item_code}-{store_key}: {str(e)}")
            return {"msg": "failure", "error": str(e)}

    async def process_price_changes(self, store_key: str, sap_item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single price change
        """
        try:
            item_code = sap_item.get('ItemCode', '')
            price = sap_item.get('Price', 0.0)
            
            # Check if this is a product with no variants
            if sap_item.get('Shopify_ProductCode'):
                # Product with no variants
                product_id = f"gid://shopify/Product/{sap_item['Shopify_ProductCode']}"
                logger.info(f"Processing product price change for {item_code} (product ID: {product_id})")
                
                # Update product price
                price_result = await self.update_product_price(store_key, product_id, price)
                
                # Log to API_LOG
                log_result = await self.log_price_change_to_api_log(item_code, store_key, price)
                
                return {
                    "msg": "success",
                    "item_code": item_code,
                    "type": "product",
                    "product_id": product_id,
                    "price_updated": price_result["msg"] == "success",
                    "price_logged": log_result["msg"] == "success",
                    "price": price
                }
                
            elif sap_item.get('Shopify_VariantId'):
                # Variant of a product
                variant_id = f"gid://shopify/ProductVariant/{sap_item['Shopify_VariantId']}"
                logger.info(f"Processing variant price change for {item_code} (variant ID: {variant_id})")
                
                # Update variant price
                price_result = await self.update_variant_price(store_key, variant_id, price)
                
                # Log to API_LOG
                log_result = await self.log_price_change_to_api_log(item_code, store_key, price)
                
                return {
                    "msg": "success",
                    "item_code": item_code,
                    "type": "variant",
                    "variant_id": variant_id,
                    "price_updated": price_result["msg"] == "success",
                    "price_logged": log_result["msg"] == "success",
                    "price": price
                }
            else:
                logger.warning(f"No Shopify ID found for item {item_code}")
                return {
                    "msg": "failure",
                    "error": f"No Shopify ID found for item {item_code}"
                }
                
        except Exception as e:
            logger.error(f"Error processing price change for {sap_item.get('ItemCode', 'unknown')}: {str(e)}")
            return {"msg": "failure", "error": str(e)}

    async def sync_price_changes(self) -> Dict[str, Any]:
        """
        Main sync function for price changes
        """
        logger.info("Starting price changes sync from SAP to Shopify")
        
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
                logger.info(f"Processing price changes for store: {store_key}")
                
                # Get price changes for this store
                changes_result = await self.get_price_changes(store_key)
                if changes_result["msg"] == "failure":
                    logger.error(f"Failed to get price changes for store {store_key}: {changes_result.get('error')}")
                    continue
                
                items = changes_result["data"]["items"]
                if not items:
                    logger.info(f"No price changes found for store {store_key}")
                    continue
                
                logger.info(f"Processing {len(items)} price changes for store {store_key}")
                
                for sap_item in items:
                    try:
                        result = await self.process_price_changes(store_key, sap_item)
                        
                        if result["msg"] == "success":
                            success += 1
                            logger.info(f"Successfully processed price change for {result['item_code']} (price: {result['price']})")
                        else:
                            errors += 1
                            logger.error(f"Failed to process price change for {sap_item.get('ItemCode', 'unknown')}: {result.get('error')}")
                        
                        processed += 1
                        await asyncio.sleep(0.5)  # Rate limiting
                        
                    except Exception as e:
                        errors += 1
                        logger.error(f"Error processing price change for {sap_item.get('ItemCode', 'unknown')}: {str(e)}")
                        await asyncio.sleep(0.5)

            # Log sync event
            log_sync_event(
                sync_type="price_changes_sap_to_shopify",
                items_processed=processed,
                success_count=success,
                error_count=errors
            )
            
            logger.info(f"Price changes sync completed: {processed} processed, {success} successful, {errors} errors")
            return {
                "msg": "success",
                "processed": processed,
                "success": success,
                "errors": errors
            }
            
        except Exception as e:
            logger.error(f"Error in price changes sync: {str(e)}")
            return {"msg": "failure", "error": str(e)}

# Create singleton instance
price_changes_sync = PriceChangesSync() 