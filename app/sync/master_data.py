from app.services.shopify.client import shopify_client
from app.core.config import config_settings
from app.utils.logging import logger, log_sync_event
import asyncio
from typing import List, Dict, Any

async def sync_products(batch_size: int = None) -> Dict[str, Any]:
    """
    Sync products from Shopify to SAP
    """
    if batch_size is None:
        batch_size = config_settings.master_data_batch_size

    try:
        # Get products from Shopify
        result = await shopify_client.get_products(first=batch_size)
        
        if result["msg"] == "failure":
            logger.error(f"Failed to get products from Shopify: {result.get('error')}")
            return {"msg": "failure", "error": result.get("error")}

        products = result["data"]["products"]
        
        # Process each product
        processed = 0
        success = 0
        errors = 0

        for edge in products["edges"]:
            product = edge["node"]
            try:
                # TODO: Implement SAP product sync
                # This is where you'll add your SAP integration code
                processed += 1
                success += 1
            except Exception as e:
                logger.error(f"Error processing product {product.get('id')}: {str(e)}")
                errors += 1

        # Log sync event
        log_sync_event(
            sync_type="master_data_products",
            items_processed=processed,
            success_count=success,
            error_count=errors
        )

        return {
            "msg": "success",
            "processed": processed,
            "success": success,
            "errors": errors,
            "has_next_page": products["pageInfo"]["hasNextPage"],
            "end_cursor": products["pageInfo"]["endCursor"]
        }

    except Exception as e:
        logger.error(f"Error in product sync: {str(e)}")
        return {"msg": "failure", "error": str(e)}

async def sync_variants(batch_size: int = None) -> Dict[str, Any]:
    """
    Sync product variants from Shopify to SAP
    """
    if batch_size is None:
        batch_size = config_settings.master_data_batch_size

    try:
        # Get products with variants from Shopify
        result = await shopify_client.get_products(first=batch_size)
        
        if result["msg"] == "failure":
            logger.error(f"Failed to get products from Shopify: {result.get('error')}")
            return {"msg": "failure", "error": result.get("error")}

        products = result["data"]["products"]
        
        # Process variants
        processed = 0
        success = 0
        errors = 0

        for edge in products["edges"]:
            product = edge["node"]
            variants = product.get("variants", {}).get("edges", [])
            
            for variant_edge in variants:
                variant = variant_edge["node"]
                try:
                    # TODO: Implement SAP variant sync
                    # This is where you'll add your SAP integration code
                    processed += 1
                    success += 1
                except Exception as e:
                    logger.error(f"Error processing variant {variant.get('id')}: {str(e)}")
                    errors += 1

        # Log sync event
        log_sync_event(
            sync_type="master_data_variants",
            items_processed=processed,
            success_count=success,
            error_count=errors
        )

        return {
            "msg": "success",
            "processed": processed,
            "success": success,
            "errors": errors,
            "has_next_page": products["pageInfo"]["hasNextPage"],
            "end_cursor": products["pageInfo"]["endCursor"]
        }

    except Exception as e:
        logger.error(f"Error in variant sync: {str(e)}")
        return {"msg": "failure", "error": str(e)}

async def sync_master_data():
    """
    Main master data sync function
    """
    if not config_settings.master_data_enabled:
        logger.info("Master data sync is disabled")
        return

    logger.info("Starting master data sync")
    
    # Sync products
    products_result = await sync_products()
    if products_result["msg"] == "failure":
        logger.error(f"Product sync failed: {products_result.get('error')}")
        return

    # Sync variants
    variants_result = await sync_variants()
    if variants_result["msg"] == "failure":
        logger.error(f"Variant sync failed: {variants_result.get('error')}")
        return

    logger.info("Master data sync completed") 