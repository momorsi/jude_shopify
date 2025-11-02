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
            headers = {'Content-Type': 'application/json', 'Accept': '*/*', 'Prefer': f'odata.maxpagesize={self.batch_size}'}
            result = await sap_client._make_request("GET", query, headers=headers)
            
            if result["msg"] == "failure":
                logger.error(f"Failed to get price changes from SAP for store {store_key}: {result.get('error')}")
                return {"msg": "failure", "error": result.get('error')}
            
            items = result["data"].get("value", [])
            logger.info(f"Found {len(items)} price changes for store {store_key}")
            
            return {"msg": "success", "data": {"items": items}}
            
        except Exception as e:
            logger.error(f"Error getting price changes for store {store_key}: {str(e)}")
            return {"msg": "failure", "error": str(e)}

    async def update_product_price(self, store_key: str, product_id: str, price: float, sale_price: Optional[float] = None) -> Dict[str, Any]:
        """
        Update product price in Shopify by updating the default variant
        Use the SAP variant ID directly - no need to query Shopify first
        """
        try:
            # Extract the product number from the product ID
            # Format: gid://shopify/Product/1234567890 -> 1234567890
            product_number = product_id.split('/')[-1]
            
            # For products, we need to find the variant ID from SAP data
            # Since we don't have it here, we'll need to get it from the calling method
            logger.info(f"Product price update requested for {product_id} - need variant ID from SAP data")
            
            return {"msg": "failure", "error": "Product price updates require variant ID from SAP data"}
            
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

    async def update_variant_price(self, store_key: str, variant_id: str, price: float, sale_price: Optional[float] = None, product_id: str = None) -> Dict[str, Any]:
        """
        Update variant price and compare price in Shopify using the correct mutation directly
        """
        max_retries = 3
        retry_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                # Prepare variant data
                variant_data = {"price": str(price)}
                
                # Add compare price if provided
                if sale_price is not None and sale_price > 0:
                    variant_data["compareAtPrice"] = str(sale_price)
                
                # Log the update attempt
                await sl_add_log(
                    server="shopify",
                    endpoint=f"/admin/api/graphql_{store_key}",
                    request_data={"variant_id": variant_id, "price": price, "sale_price": sale_price, "attempt": attempt + 1},
                    action="update_variant_price",
                    value=f"Updating variant {variant_id} price to {price}, sale price to {sale_price} in store {store_key} (attempt {attempt + 1})"
                )
                
                # Use the correct mutation directly - no fallback needed
                # Pass product_id to avoid unnecessary API call
                result = await multi_store_shopify_client.update_variant_direct(
                    store_key, 
                    variant_id, 
                    variant_data,
                    product_id
                )
                
                if result["msg"] == "success":
                    await sl_add_log(
                        server="shopify",
                        endpoint=f"/admin/api/graphql_{store_key}",
                        response_data={"variant_id": variant_id, "price": price, "sale_price": sale_price, "attempt": attempt + 1},
                        status="success",
                        action="update_variant_price",
                        value=f"Successfully updated variant {variant_id} price to {price}, sale price to {sale_price} in store {store_key}"
                    )
                    logger.info(f"✅ Successfully updated variant {variant_id} price to {price}, sale price to {sale_price} in store {store_key}")
                    return result
                else:
                    error_msg = result.get("error", "Unknown error")
                    logger.warning(f"Attempt {attempt + 1} failed for variant {variant_id}: {error_msg}")
                    
                    if attempt < max_retries - 1:
                        logger.info(f"Retrying in {retry_delay} seconds...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                    else:
                        # Final attempt failed
                        await sl_add_log(
                            server="shopify",
                            endpoint=f"/admin/api/graphql_{store_key}",
                            response_data={"error": error_msg, "attempts": max_retries},
                            status="failure",
                            action="update_variant_price",
                            value=f"Failed to update variant {variant_id} price in store {store_key} after {max_retries} attempts: {error_msg}"
                        )
                        logger.error(f"❌ Failed to update variant {variant_id} price in store {store_key} after {max_retries} attempts: {error_msg}")
                        return result
                        
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"Exception on attempt {attempt + 1} for variant {variant_id}: {error_msg}")
                
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    # Final attempt failed
                    await sl_add_log(
                        server="shopify",
                        endpoint=f"/admin/api/graphql_{store_key}",
                        response_data={"error": error_msg, "attempts": max_retries},
                        status="failure",
                        action="update_variant_price",
                        value=f"Exception updating variant {variant_id} price in store {store_key} after {max_retries} attempts: {error_msg}"
                    )
                    logger.error(f"❌ Exception updating variant {variant_id} price in store {store_key} after {max_retries} attempts: {error_msg}")
                    return {"msg": "failure", "error": error_msg}
        
        return {"msg": "failure", "error": "Max retries exceeded"}

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
                response_data={"reference": reference, "value": str(price), "status": "shopify_update_successful"},
                status="success",
                action="price",
                reference=reference,
                value=str(price)
            )
            
            logger.info(f"✅ Successfully logged price change to SAP for {reference}: {price} (Shopify update was successful)")
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
            normal_price = sap_item.get('Price', 0.0)
            sale_price = sap_item.get('SalePrice', 0.0)
            
            # Convert sale price to None if it's negative (0 is a valid sale price)
            if sale_price < 0:
                sale_price = None
            
            # Check if this is a product with no variants
            if sap_item.get('Shopify_ProductCode'):
                # Product with no variants - we need the variant ID from SAP
                if sap_item.get('Shopify_VariantId'):
                    # We have the variant ID directly from SAP - use it!
                    variant_id = f"gid://shopify/ProductVariant/{sap_item['Shopify_VariantId']}"
                    product_id = f"gid://shopify/Product/{sap_item['Shopify_ProductCode']}"
                    logger.info(f"Processing product price change for {item_code} using SAP variant ID: {variant_id}")
                    
                    # Update variant price directly: SalePrice goes to price, normal price goes to compareAtPrice
                    # Pass product_id to avoid unnecessary API call
                    price_result = await self.update_variant_price(store_key, variant_id, sale_price, normal_price, product_id)
                    
                    # Only log to SAP API_LOG if the Shopify update was successful
                    if price_result["msg"] == "success":
                        log_result = await self.log_price_change_to_api_log(item_code, store_key, sale_price)
                        price_logged = log_result["msg"] == "success"
                    else:
                        price_logged = False
                    
                    return {
                        "msg": "success",
                        "item_code": item_code,
                        "type": "product",
                        "product_id": product_id,
                        "variant_id": variant_id,
                        "price_updated": price_result["msg"] == "success",
                        "price_logged": price_logged,
                        "price": sale_price,
                        "compare_at_price": normal_price
                    }
                else:
                    # No variant ID in SAP - this shouldn't happen for products
                    logger.error(f"No Shopify variant ID found in SAP for product {item_code}")
                    return {
                        "msg": "failure",
                        "error": f"No Shopify variant ID found in SAP for product {item_code}"
                    }
                
            elif sap_item.get('Shopify_VariantId'):
                # Variant of a product
                variant_id = f"gid://shopify/ProductVariant/{sap_item['Shopify_VariantId']}"
                logger.info(f"Processing variant price change for {item_code} (variant ID: {variant_id})")
                
                # Update variant price: SalePrice goes to price, normal price goes to compareAtPrice
                price_result = await self.update_variant_price(store_key, variant_id, sale_price, normal_price)
                
                # Only log to SAP API_LOG if the Shopify update was successful
                if price_result["msg"] == "success":
                    log_result = await self.log_price_change_to_api_log(item_code, store_key, sale_price)
                    price_logged = log_result["msg"] == "success"
                else:
                    price_logged = False
                
                return {
                    "msg": "success",
                    "item_code": item_code,
                    "type": "variant",
                    "variant_id": variant_id,
                    "price_updated": price_result["msg"] == "success",
                    "price_logged": price_logged,
                    "price": sale_price,
                    "compare_at_price": normal_price
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
                            if result["price_updated"]:
                                success += 1
                                logger.info(f"✅ Successfully processed price change for {result['item_code']} (price: {result['price']})")
                            else:
                                errors += 1
                                logger.error(f"❌ Shopify update failed for {result['item_code']} (price: {result['price']}) - SAP retrieval succeeded but Shopify update failed")
                        else:
                            errors += 1
                            logger.error(f"❌ Failed to process price change for {sap_item.get('ItemCode', 'unknown')}: {result.get('error')}")
                        
                        processed += 1
                        await asyncio.sleep(0.5)  # Rate limiting
                        
                    except Exception as e:
                        errors += 1
                        logger.error(f"❌ Exception processing price change for {sap_item.get('ItemCode', 'unknown')}: {str(e)}")
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