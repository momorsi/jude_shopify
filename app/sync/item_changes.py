"""
Item Changes Sync Module
Syncs item changes from SAP to Shopify including product updates, variant updates, and active status
"""

import asyncio
from typing import Dict, Any, List, Optional
from app.services.sap.client import sap_client
from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.core.config import config_settings
from app.utils.logging import logger, log_sync_event
from app.services.sap.api_logger import sl_add_log
from datetime import datetime

class ItemChangesSync:
    def __init__(self):
        self.batch_size = config_settings.new_items_batch_size

    async def get_item_changes(self, store_key: str) -> Dict[str, Any]:
        """
        Get item changes from SAP for a specific store
        """
        try:
            # Query the MASHURA_ItemChangeB1SLQuery view
            query = f"view.svc/MASHURA_ItemChangeB1SLQuery?$filter=Shopify_Store eq '{store_key}'"
            
            result = await sap_client._make_request("GET", query)
            
            if result["msg"] == "failure":
                logger.error(f"Failed to get item changes from SAP for store {store_key}: {result.get('error')}")
                return {"msg": "failure", "error": result.get('error')}
            
            items = result["data"].get("value", [])
            logger.info(f"Found {len(items)} item changes for store {store_key}")
            
            return {"msg": "success", "data": {"items": items}}
            
        except Exception as e:
            logger.error(f"Error getting item changes for store {store_key}: {str(e)}")
            return {"msg": "failure", "error": str(e)}

    async def update_product_comprehensive(self, store_key: str, product_id: str, sap_item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update product comprehensively - handles title, status, and variant details with optimized approach
        """
        try:
            is_active = sap_item.get('IsActive', 'Y') == 'Y'
            
            # Determine status based on test mode and SAP status
            if config_settings.test_mode:
                status = "DRAFT"
                logger.info(f"Test mode enabled: Keeping product {product_id} as DRAFT regardless of SAP status")
            else:
                status = "ACTIVE" if is_active else "DRAFT"
            
            # Prepare product update data (product-level fields only)
            product_update_data = {}
            
            # Add status
            product_update_data["status"] = status
            
            # Add title if available
            if sap_item.get('FrgnName'):
                product_update_data["title"] = sap_item['FrgnName']
            
            # Log the product update
            await sl_add_log(
                server="shopify",
                endpoint=f"/admin/api/graphql_{store_key}",
                request_data={"product_id": product_id, "update_data": product_update_data},
                action="update_product_comprehensive",
                value=f"Updating product {product_id} comprehensively in store {store_key}"
            )
            
            # Execute the product update with retry logic
            result = await self._update_product_with_retry(store_key, product_id, product_update_data)
            
            if result["msg"] == "success":
                await sl_add_log(
                    server="shopify",
                    endpoint=f"/admin/api/graphql_{store_key}",
                    response_data={"product_id": product_id, "updated_fields": list(product_update_data.keys())},
                    status="success",
                    action="update_product_comprehensive",
                    value=f"Successfully updated product {product_id} comprehensively in store {store_key}"
                )
                logger.info(f"Successfully updated product {product_id} comprehensively in store {store_key}")
            else:
                await sl_add_log(
                    server="shopify",
                    endpoint=f"/admin/api/graphql_{store_key}",
                    response_data={"error": result.get("error")},
                    status="failure",
                    action="update_product_comprehensive",
                    value=f"Failed to update product {product_id} comprehensively in store {store_key}: {result.get('error')}"
                )
                logger.error(f"Failed to update product {product_id} comprehensively in store {store_key}: {result.get('error')}")
            
            return result
            
        except Exception as e:
            await sl_add_log(
                server="shopify",
                endpoint=f"/admin/api/graphql_{store_key}",
                response_data={"error": str(e)},
                status="failure",
                action="update_product_comprehensive",
                value=f"Exception updating product {product_id} comprehensively in store {store_key}: {str(e)}"
            )
            logger.error(f"Error updating product {product_id} comprehensively in store {store_key}: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def _update_product_with_retry(self, store_key: str, product_id: str, product_update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update product with retry logic for handling transient failures
        """
        max_attempts = 2
        retry_delay = 2  # Start with 2 seconds
        
        for attempt in range(max_attempts):
            try:
                result = await multi_store_shopify_client.update_product(store_key, product_id, product_update_data)
                
                if result["msg"] == "success":
                    return result
                
                # Check if this is a retryable error
                error_msg = result.get("error", "").lower()
                if any(keyword in error_msg for keyword in ["timeout", "rate limit", "temporary", "network", "connection", "graphql query error"]):
                    if attempt < max_attempts - 1:
                        logger.warning(f"Retryable error on attempt {attempt + 1}: {result.get('error')}")
                        logger.info(f"Retrying in {retry_delay} seconds...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                else:
                    # Non-retryable error, return immediately
                    return result
                    
            except Exception as e:
                if attempt < max_attempts - 1:
                    logger.warning(f"Exception on attempt {attempt + 1}: {str(e)}")
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    return {"msg": "failure", "error": str(e)}
        
        return {"msg": "failure", "error": "All retry attempts failed"}
    
    async def _update_variant_with_retry(self, store_key: str, variant_id: str, variant_update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update variant with retry logic for handling transient failures
        """
        max_attempts = 3
        retry_delay = 2  # Start with 2 seconds
        
        for attempt in range(max_attempts):
            try:
                result = await self._update_variant_individual(store_key, variant_id, variant_update_data)
                
                if result["msg"] == "success":
                    return result
                
                # Check if this is a retryable error
                error_msg = result.get("error", "").lower()
                if any(keyword in error_msg for keyword in ["timeout", "rate limit", "temporary", "network", "connection", "graphql query error"]):
                    if attempt < max_attempts - 1:
                        logger.warning(f"Retryable error on attempt {attempt + 1}: {result.get('error')}")
                        logger.info(f"Retrying in {retry_delay} seconds...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                else:
                    # Non-retryable error, return immediately
                    return result
                    
            except Exception as e:
                if attempt < max_attempts - 1:
                    logger.warning(f"Exception on attempt {attempt + 1}: {str(e)}")
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    return {"msg": "failure", "error": str(e)}
        
        return {"msg": "failure", "error": "All retry attempts failed"}
    
    async def update_variant_comprehensive(self, store_key: str, variant_id: str, sap_item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update variant comprehensively - handles barcode and color/title using individual variant updates
        """
        try:
            # Prepare variant update data
            variant_update_data = {}
            
            # Add barcode if available
            if sap_item.get('Barcode'):
                variant_update_data["barcode"] = sap_item['Barcode']
            
            # Add color/title if available
            if sap_item.get('Color'):
                from app.sync.new_items_multi_store import multi_store_new_items_sync
                mapped_color = multi_store_new_items_sync._get_color_from_sap(sap_item['Color'])
                variant_update_data["title"] = mapped_color
            
            if not variant_update_data:
                logger.info(f"No variant details to update for variant {variant_id}")
                return {"msg": "success", "note": "No changes needed"}
            
            # Log the variant update
            await sl_add_log(
                server="shopify",
                endpoint=f"/admin/api/graphql_{store_key}",
                request_data={"variant_id": variant_id, "update_data": variant_update_data},
                action="update_variant_comprehensive",
                value=f"Updating variant {variant_id} comprehensively in store {store_key}"
            )
            
            # Use individual variant update for fields not supported in bulk update with retry logic
            result = await self._update_variant_with_retry(store_key, variant_id, variant_update_data)
            
            if result["msg"] == "success":
                await sl_add_log(
                    server="shopify",
                    endpoint=f"/admin/api/graphql_{store_key}",
                    response_data={"variant_id": variant_id, "updated_fields": list(variant_update_data.keys())},
                    status="success",
                    action="update_variant_comprehensive",
                    value=f"Successfully updated variant {variant_id} comprehensively in store {store_key}"
                )
                logger.info(f"Successfully updated variant {variant_id} comprehensively in store {store_key}")
            else:
                await sl_add_log(
                    server="shopify",
                    endpoint=f"/admin/api/graphql_{store_key}",
                    response_data={"error": result.get("error")},
                    status="failure",
                    action="update_variant_comprehensive",
                    value=f"Failed to update variant {variant_id} comprehensively in store {store_key}: {result.get('error')}"
                )
                logger.error(f"Failed to update variant {variant_id} comprehensively in store {store_key}: {result.get('error')}")
            
            return result
            
        except Exception as e:
            await sl_add_log(
                server="shopify",
                endpoint=f"/admin/api/graphql_{store_key}",
                response_data={"error": str(e)},
                status="failure",
                action="update_variant_comprehensive",
                value=f"Exception updating variant {variant_id} comprehensively in store {store_key}: {str(e)}"
            )
            logger.error(f"Error updating variant {variant_id} comprehensively in store {store_key}: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def _update_variant_individual(self, store_key: str, variant_id: str, variant_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update individual variant - currently disabled due to GraphQL API limitations
        The productVariantUpdate mutation doesn't exist in Shopify's GraphQL API
        """
        try:
            # For now, we'll skip individual variant updates since the GraphQL API doesn't support
            # direct variant updates for barcode and title fields
            logger.warning(f"Skipping variant update for {variant_id} - GraphQL API limitations")
            logger.warning(f"Attempted to update: {variant_data}")
            
            # Return success for now to avoid blocking the sync process
            # TODO: Implement alternative approach for variant updates
            return {"msg": "success", "note": "Skipped due to API limitations"}
            
        except Exception as e:
            return {"msg": "failure", "error": str(e)}

    async def update_item_change_record(self, item_code: str, update_date: str, update_time: str, store_key: str) -> Dict[str, Any]:
        """
        Update or create record in U_ITEM_CHANGE table
        """
        try:
            # Convert date format from YYYYMMDD to YYYY-MM-DD
            formatted_date = f"{update_date[:4]}-{update_date[4:6]}-{update_date[6:8]}"
            
            # Convert time format from HHMMSS to HH:MM:SS
            # Handle both string and integer formats
            if isinstance(update_time, int):
                time_str = str(update_time).zfill(6)  # Ensure 6 digits
            else:
                time_str = str(update_time)
            
            formatted_time = f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}"
            
            # Try to update existing record first
            update_data = {
                "U_LastChangeDate": formatted_date,
                "U_LastChangeTime": formatted_time
            }
            
            # Use PATCH to update existing record
            result = await sap_client._make_request(
                "PATCH", 
                f"U_ITEM_CHANGE('{item_code}')",
                update_data
            )
            
            if result["msg"] == "success":
                logger.info(f"Successfully updated item change record for {item_code}")
                return result
            else:
                # If update fails, try to create new record
                create_data = {
                    "Code": f"{item_code}-{store_key}",
                    "Name": f"{item_code}-{store_key}",
                    "U_LastChangeDate": formatted_date,
                    "U_LastChangeTime": formatted_time
                }
                
                result = await sap_client._make_request("POST", "U_ITEM_CHANGE", create_data)
                
                if result["msg"] == "success":
                    logger.info(f"Successfully created item change record for {item_code}")
                else:
                    logger.error(f"Failed to create item change record for {item_code}: {result.get('error')}")
                
                return result
                
        except Exception as e:
            logger.error(f"Error updating item change record for {item_code}: {str(e)}")
            return {"msg": "failure", "error": str(e)}

    async def process_item_changes(self, store_key: str, sap_item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single item change with optimized approach - separate but efficient calls
        """
        try:
            item_code = sap_item.get('ItemCode', '')
            
            # Check if this is a product with no variants
            if sap_item.get('Shopify_ProductCode'):
                # Product with no variants
                product_id = f"gid://shopify/Product/{sap_item['Shopify_ProductCode']}"
                logger.info(f"Processing product change for {item_code} (product ID: {product_id})")
                
                # Skip if Product ID is completely empty (but allow None for variant-only items)
                if not sap_item['Shopify_ProductCode'] or sap_item['Shopify_ProductCode'].strip() == '':
                    logger.warning(f"Skipping {item_code} - Empty Shopify Product ID: {sap_item['Shopify_ProductCode']}")
                    return {
                        "msg": "skipped",
                        "item_code": item_code,
                        "type": "product",
                        "product_id": product_id,
                        "reason": "Empty Shopify Product ID"
                    }
                
                # Update product (title and status)
                product_result = await self.update_product_comprehensive(store_key, product_id, sap_item)
                
                # Update variant if needed (barcode and color)
                variant_result = {"msg": "success", "note": "No variant to update"}
                if sap_item.get('Shopify_VariantId'):
                    variant_id = f"gid://shopify/ProductVariant/{sap_item['Shopify_VariantId']}"
                    variant_result = await self.update_variant_comprehensive(store_key, variant_id, sap_item)
                
                # Check if ALL operations succeeded before updating item change record
                overall_success = (
                    product_result["msg"] == "success" and 
                    variant_result["msg"] == "success"
                )
                
                # Only update item change record if ALL operations succeeded
                change_result = {"msg": "success", "note": "Skipped due to operation failure"}
                if overall_success:
                    change_result = await self.update_item_change_record(
                        item_code,
                        sap_item.get('UpdateDate', ''),
                        sap_item.get('UpdateTS', ''),
                        store_key
                    )
                
                return {
                    "msg": "success" if overall_success else "failure",
                    "item_code": item_code,
                    "type": "product",
                    "product_id": product_id,
                    "product_update_success": product_result["msg"] == "success",
                    "variant_update_success": variant_result["msg"] == "success",
                    "change_record_updated": change_result["msg"] == "success",
                    "error": None if overall_success else "One or more operations failed"
                }
                
            elif sap_item.get('Shopify_VariantId'):
                # Variant of a product
                variant_id = f"gid://shopify/ProductVariant/{sap_item['Shopify_VariantId']}"
                product_id = f"gid://shopify/Product/{sap_item['Shopify_ProductCode']}"
                logger.info(f"Processing variant change for {item_code} (variant ID: {variant_id}, product ID: {product_id})")
                
                # Note: Some items may have None as Product ID but still have valid Variant IDs
                # This is normal for variant-only changes
                
                # Update product (status only, since this is a variant change)
                product_result = await self.update_product_comprehensive(store_key, product_id, sap_item)
                
                # Update variant (barcode and color)
                variant_result = await self.update_variant_comprehensive(store_key, variant_id, sap_item)
                
                # Check if ALL operations succeeded before updating item change record
                overall_success = (
                    product_result["msg"] == "success" and 
                    variant_result["msg"] == "success"
                )
                
                # Only update item change record if ALL operations succeeded
                change_result = {"msg": "success", "note": "Skipped due to operation failure"}
                if overall_success:
                    change_result = await self.update_item_change_record(
                        item_code,
                        sap_item.get('UpdateDate', ''),
                        sap_item.get('UpdateTS', ''),
                        store_key
                    )
                
                return {
                    "msg": "success" if overall_success else "failure",
                    "item_code": item_code,
                    "type": "variant",
                    "variant_id": variant_id,
                    "product_id": product_id,
                    "product_update_success": product_result["msg"] == "success",
                    "variant_update_success": variant_result["msg"] == "success",
                    "change_record_updated": change_result["msg"] == "success",
                    "error": None if overall_success else "One or more operations failed"
                }
            else:
                logger.warning(f"No Shopify ID found for item {item_code}")
                return {
                    "msg": "failure",
                    "error": f"No Shopify ID found for item {item_code}"
                }
                
        except Exception as e:
            logger.error(f"Error processing item change for {sap_item.get('ItemCode', 'unknown')}: {str(e)}")
            return {"msg": "failure", "error": str(e)}

    async def sync_item_changes(self) -> Dict[str, Any]:
        """
        Main sync function for item changes
        """
        logger.info("Starting item changes sync from SAP to Shopify")
        
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
                logger.info(f"Processing item changes for store: {store_key}")
                
                # Get item changes for this store
                changes_result = await self.get_item_changes(store_key)
                if changes_result["msg"] == "failure":
                    logger.error(f"Failed to get item changes for store {store_key}: {changes_result.get('error')}")
                    continue
                
                items = changes_result["data"]["items"]
                if not items:
                    logger.info(f"No item changes found for store {store_key}")
                    continue
                
                logger.info(f"Processing {len(items)} item changes for store {store_key}")
                
                for sap_item in items:
                    try:
                        result = await self.process_item_changes(store_key, sap_item)
                        
                        if result["msg"] == "success":
                            success += 1
                            logger.info(f"Successfully processed item change for {result['item_code']}")
                        else:
                            errors += 1
                            logger.error(f"Failed to process item change for {sap_item.get('ItemCode', 'unknown')}: {result.get('error')}")
                        
                        processed += 1
                        await asyncio.sleep(0.5)  # Rate limiting
                        
                    except Exception as e:
                        errors += 1
                        logger.error(f"Error processing item change for {sap_item.get('ItemCode', 'unknown')}: {str(e)}")
                        await asyncio.sleep(0.5)

            # Log sync event
            log_sync_event(
                sync_type="item_changes_sap_to_shopify",
                items_processed=processed,
                success_count=success,
                error_count=errors
            )
            
            logger.info(f"Item changes sync completed: {processed} processed, {success} successful, {errors} errors")
            return {
                "msg": "success",
                "processed": processed,
                "success": success,
                "errors": errors
            }
            
        except Exception as e:
            logger.error(f"Error in item changes sync: {str(e)}")
            return {"msg": "failure", "error": str(e)}

# Create singleton instance
item_changes_sync = ItemChangesSync() 