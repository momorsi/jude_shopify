"""
Items Initialization Module
Handles mapping of existing Shopify products to SAP and updates necessary fields
"""

import asyncio
from typing import Dict, Any, List, Optional, Tuple
from app.services.sap.client import sap_client
from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.core.config import config_settings
from app.utils.logging import logger, log_sync_event
from app.services.sap.api_logger import sl_add_log
from datetime import datetime
import httpx

class ItemsInitialization:
    def __init__(self):
        # Metafield definitions for sync tracking
        self.sync_metafield = {
            "namespace": "custom",
            "key": "sap_sync",
            "type": "single_line_text_field"
        }
        self.external_id_metafield = {
            "namespace": "custom", 
            "key": "external_id",
            "type": "single_line_text_field"
        }
        self.batch_size = 100  # Process products in batches
        
    async def initialize_all_stores(self):
        """
        Initialize mapping for all enabled stores
        """
        enabled_stores = config_settings.get_enabled_stores()
        logger.info(f"Starting initialization for {len(enabled_stores)} stores")
        
        for store_key, store_config in enabled_stores.items():
            try:
                logger.info(f"Processing store: {store_config.name} ({store_key})")
                await self.initialize_store(store_key, store_config)
            except Exception as e:
                logger.error(f"Failed to initialize store {store_key}: {str(e)}")
    
    async def initialize_store(self, store_key: str, store_config):
        """
        Initialize mapping for a specific store
        """
        try:
            # Step 1: Get all active products from Shopify
            products = await self.get_all_active_products(store_key)
            logger.info(f"Found {len(products)} active products in store {store_key}")
            
            # Step 2: Process products in batches
            for i in range(0, len(products), self.batch_size):
                batch = products[i:i + self.batch_size]
                await self.process_product_batch(store_key, store_config, batch)
                
            logger.info(f"Completed initialization for store {store_key}")
            
        except Exception as e:
            logger.error(f"Error initializing store {store_key}: {str(e)}")
            raise
    
    async def get_all_active_products(self, store_key: str) -> List[Dict[str, Any]]:
        """
        Get all active products from Shopify store that are NOT synced
        """
        logger.info(f"Fetching active products from store: {store_key}")
        
        # Add retry logic for GraphQL queries to handle rate limiting
        max_retries = 3
        retry_delay = 2  # Start with 2 seconds
        query = """
        query GetUnsyncedProducts($cursor: String) {
            products(first: 150, after: $cursor) {
                pageInfo {
                    hasNextPage
                    endCursor
                }
                edges {
                    node {
                        id
                        title
                        metafields(first: 5, namespace: "custom") {
                            edges {
                                node {
                                    key
                                    value
                                }
                            }
                        }
                        variants(first: 50) {
                            edges {
                                node {
                                    id
                                    title
                                    sku
                                    inventoryItem {
                                        id
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        
        all_products = []
        cursor = None
        
        while True:
            variables = {"cursor": cursor} if cursor else {}
            
            # Add retry logic for each GraphQL query
            for attempt in range(max_retries):
                try:
                    result = await multi_store_shopify_client.execute_query(store_key, query, variables)
                    
                    if result["msg"] == "success":
                        break  # Success, exit retry loop
                    else:
                        logger.warning(f"GraphQL attempt {attempt + 1}/{max_retries} failed: {result.get('error', 'Unknown error')}")
                        
                        if attempt < max_retries - 1:  # Don't sleep on last attempt
                            logger.info(f"Retrying in {retry_delay} seconds...")
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                            
                except Exception as e:
                    logger.error(f"GraphQL attempt {attempt + 1}/{max_retries} exception: {str(e)}")
                    if attempt < max_retries - 1:
                        logger.info(f"Retrying in {retry_delay} seconds...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        result = {"msg": "failure", "error": f"All {max_retries} attempts failed: {str(e)}"}
            
            if result["msg"] != "success":
                logger.error(f"Failed to get products from store {store_key}: {result.get('error')}")
                break
            
            data = result["data"]
            products_data = data.get("products", {})
            
            # Extract products from edges
            for edge in products_data.get("edges", []):
                product = edge["node"]
                all_products.append(product)
            
            # Check if there are more pages
            page_info = products_data.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
                
            cursor = page_info.get("endCursor")
        
        # Filter out products that are already synced
        unsynced_products = []
        for product in all_products:
            sync_status = self._get_sync_status(product)
            if sync_status != "synced":
                unsynced_products.append(product)
        
        logger.info(f"Found {len(all_products)} total products, {len(unsynced_products)} need syncing")
        return unsynced_products
    
    async def process_product_batch(self, store_key: str, store_config, products: List[Dict[str, Any]]):
        """
        Process a batch of products
        """
        for product in products:
            try:
                await self.process_single_product(store_key, store_config, product)
            except Exception as e:
                logger.error(f"Error processing product {product.get('id')}: {str(e)}")
    
    async def process_single_product(self, store_key: str, store_config, product: Dict[str, Any]):
        """
        Process a single product and its variants
        """
        product_id = product.get('id')
        product_title = product.get('title', '')
        
        # Check sync status from metafields
        sync_status = self._get_sync_status(product)
        
        # Skip products that are already synced or failed
        if sync_status in ["synced", "failed", "synced_prd"]:
            if sync_status == "synced":
                logger.info(f"Product {product_id} already synced, skipping")
            else:
                logger.info(f"Product {product_id} previously failed to sync, skipping")
            return
        
        variants = product.get('variants', {}).get('edges', [])
        
        try:
            # Check if this is a single variant product (no variants)
            # A product with no variants will have exactly one variant with title "Default Title"
            is_single_variant = (len(variants) == 1 and 
                               variants[0]['node'].get('title', '') == 'Default Title')
            
            logger.info(f"Product {product_id} has {len(variants)} variants, is_single_variant: {is_single_variant}")
            logger.info(f"Processing product in store: {store_key} - SAP field updates: {'enabled' if store_key == 'local' else 'disabled'}")
            
            if is_single_variant:
                # Single product (no variants)
                variant = variants[0]['node']
                logger.info(f"Processing single variant product: {product_title}")
                await self.process_single_variant_product(
                    store_key, store_config, product, variant
                )
            else:
                # Product with variants
                logger.info(f"Processing multi-variant product: {product_title} with {len(variants)} variants")
                await self.process_multi_variant_product(
                    store_key, store_config, product, variants
                )
            
            # Mark product as successfully synced
            await self.set_sync_status(store_key, product_id, "synced")
            
        except Exception as e:
            logger.error(f"Failed to process product {product_id}: {str(e)}")
            # Mark product as failed to sync
            await self.set_sync_status(store_key, product_id, "failed")
            raise
    
    async def process_single_variant_product(self, store_key: str, store_config, 
                                           product: Dict[str, Any], variant: Dict[str, Any]):
        """
        Process a single product with one variant
        """
        product_id = product.get('id')
        variant_id = variant.get('id')
        sku = variant.get('sku', '')
        
        if not sku:
            logger.warning(f"Product {product_id} has no SKU, skipping")
            return
        
        # Extract inventory variant ID
        inventory_item = variant.get('inventoryItem', {})
        inventory_variant_id = inventory_item.get('id')
        
        # For single products, use product title as main product name
        main_product_name = product.get('title', '')
        color_name = ""  # No color for single products
        
        # Create mapping records in SAP
        await self.create_sap_mapping_record(
            store_key, sku, product_id, variant_id, inventory_variant_id,
            main_product_name, color_name
        )
        
        # Also create product-level mapping record (use SKU for single products)
        await self.create_product_mapping_record(
            store_key, product_id, main_product_name, sku
        )
        
        # Update SAP item fields for single variant product (only for local store)
        # ForeignName => title of the product, U_SalesChannel => "3"
        if store_key == "local":
            await self.update_sap_item_fields(sku, main_product_name, "", "", is_single_variant=True)
        else:
            logger.info(f"Skipping SAP item field updates for international store: {store_key}")
    
    async def process_multi_variant_product(self, store_key: str, store_config,
                                           product: Dict[str, Any], variants: List[Dict[str, Any]]):
        """
        Process a product with multiple variants
        """
        product_id = product.get('id')
        main_product_name = product.get('title', '')
        
        # Filter out variants that are already synced
        unsynced_variants = await self.get_unsynced_variants(variants, store_key)
        
        if not unsynced_variants:
            logger.info(f"All variants for product {product_id} are already synced")
            return
        
        logger.info(f"Processing {len(unsynced_variants)} unsynced variants out of {len(variants)} total variants")
        
        # Create product-level mapping record once for the entire product (use product title for multi-variant)
        await self.create_product_mapping_record(
            store_key, product_id, main_product_name
        )
        
        for variant_edge in unsynced_variants:
            variant = variant_edge['node']
            variant_id = variant.get('id')
            sku = variant.get('sku', '')
            
            if not sku:
                logger.warning(f"Variant {variant_id} has no SKU, skipping")
                continue
            
            # Extract inventory variant ID
            inventory_item = variant.get('inventoryItem', {})
            inventory_variant_id = inventory_item.get('id')
            
            # Extract color from variant title
            color_name = variant.get('title', '')
            
            # Create mapping records in SAP
            await self.create_sap_mapping_record(
                store_key, sku, product_id, variant_id, inventory_variant_id,
                main_product_name, color_name
            )
            
            # Update SAP item fields for multi-variant product (only for local store)
            # ForeignName => title of the product, U_SalesChannel => "3"
            # U_ParentCommercialName => title of the product, U_ShopifyColor => title of the variant
            if store_key == "local":
                await self.update_sap_item_fields(sku, main_product_name, main_product_name, color_name, is_single_variant=False)
            else:
                logger.info(f"Skipping SAP item field updates for international store: {store_key}")
    
    async def create_sap_mapping_record(self, store_key: str, sku: str, product_id: str, 
                                       variant_id: str, inventory_variant_id: str,
                                       main_product_name: str, color_name: str):
        """
        Create variant and inventory records in SAP's Shopify_Mapping table using existing structure
        """
        # Extract product ID number from GraphQL ID
        product_id_number = product_id.split("/")[-1] if "/" in product_id else product_id
        variant_id_number = variant_id.split("/")[-1] if "/" in variant_id else variant_id
        inventory_id_number = inventory_variant_id.split("/")[-1] if "/" in inventory_variant_id else inventory_variant_id
        
        try:
            # Create variant mapping record
            variant_mapping_data = {
                "Code": variant_id_number,
                "Name": variant_id_number,
                "U_Shopify_Type": "variant",
                "U_SAP_Code": sku,
                "U_Shopify_Store": store_key,
                "U_SAP_Type": "item",
                "U_CreateDT": datetime.now().strftime('%Y-%m-%d')
            }
            
            variant_result = await sap_client.add_shopify_mapping(variant_mapping_data)
            
            if variant_result["msg"] == "success":
                logger.info(f"Created variant mapping record for SKU: {sku} in store: {store_key}")
            else:
                logger.error(f"Failed to create variant mapping record for SKU {sku}: {variant_result.get('error')}")
                raise Exception(f"Failed to create variant mapping record: {variant_result.get('error')}")
            
            # Create inventory mapping record
            inventory_mapping_data = {
                "Code": inventory_id_number,
                "Name": inventory_id_number,
                "U_Shopify_Type": "variant_inventory",
                "U_SAP_Code": sku,
                "U_Shopify_Store": store_key,
                "U_SAP_Type": "item",
                "U_CreateDT": datetime.now().strftime('%Y-%m-%d')
            }
            
            inventory_result = await sap_client.add_shopify_mapping(inventory_mapping_data)
            
            if inventory_result["msg"] == "success":
                logger.info(f"Created inventory mapping record for SKU: {sku} in store: {store_key}")
            else:
                logger.error(f"Failed to create inventory mapping record for SKU {sku}: {inventory_result.get('error')}")
                raise Exception(f"Failed to create inventory mapping record: {inventory_result.get('error')}")
                
        except Exception as e:
            logger.error(f"Error creating mapping records for SKU {sku}: {str(e)}")
            raise
    
    async def create_product_mapping_record(self, store_key: str, product_id: str, main_product_name: str, sku: str = None):
        """
        Create a product-level mapping record in SAP's Shopify_Mapping table
        For single products, use SKU. For multi-variant products, use product title
        """
        # Extract product ID number from GraphQL ID
        product_id_number = product_id.split("/")[-1] if "/" in product_id else product_id
        
        # For single products, use SKU. For multi-variant products, use product title
        sap_code = sku if sku else main_product_name
        
        # Use the existing mapping structure from the codebase
        mapping_data = {
            "Code": product_id_number,
            "Name": product_id_number,
            "U_Shopify_Type": "product",
            "U_SAP_Code": sap_code,
            "U_Shopify_Store": store_key,
            "U_SAP_Type": "item",
            "U_CreateDT": datetime.now().strftime('%Y-%m-%d')
        }
        
        try:
            result = await sap_client.add_shopify_mapping(mapping_data)
            
            if result["msg"] == "success":
                logger.info(f"Created product mapping record for product: {product_id_number} in store: {store_key}")
            else:
                logger.error(f"Failed to create product mapping record for product {product_id_number}: {result.get('error')}")
                raise Exception(f"Failed to create product mapping record: {result.get('error')}")
                
        except Exception as e:
            logger.error(f"Error creating product mapping record for product {product_id_number}: {str(e)}")
            raise
    
    def _get_metafield_value(self, product: Dict[str, Any], namespace: str, key: str) -> str:
        """
        Get metafield value from product
        """
        metafields = product.get('metafields', {}).get('edges', [])
        for edge in metafields:
            metafield = edge['node']
            if metafield.get('namespace') == namespace and metafield.get('key') == key:
                return metafield.get('value', '')
        return ''
    
    def _get_sync_status(self, product: Dict[str, Any]) -> str:
        """
        Get sync status from product using the correct metafield
        """
        return self._get_metafield_value(product, "custom", "sap_sync")
    
    async def check_variant_sync_status(self, sku: str, store_key: str) -> bool:
        """
        Check if a variant is synced by looking up its SKU in SAP mapping table
        Returns True if variant is synced, False otherwise
        """
        try:
            # Query SAP to check if this SKU exists in the mapping table
            result = await sap_client._make_request(
                method="GET",
                endpoint=f"U_SHOPIFY_MAPPING_2?$filter=U_SAP_Code eq '{sku}' and U_Shopify_Store eq '{store_key}'",
                login_required=True
            )
            
            if result["msg"] == "success":
                data = result.get("data", {})
                value = data.get("value", [])
                return len(value) > 0  # If any records found, variant is synced
            else:
                logger.warning(f"Failed to check variant sync status for SKU {sku}: {result.get('error')}")
                return False
                
        except Exception as e:
            logger.error(f"Error checking variant sync status for SKU {sku}: {str(e)}")
            return False
    
    async def get_unsynced_variants(self, variants: List[Dict[str, Any]], store_key: str) -> List[Dict[str, Any]]:
        """
        Filter variants to return only those that are not synced
        """
        unsynced_variants = []
        
        for variant_edge in variants:
            variant = variant_edge['node']
            sku = variant.get('sku', '')
            
            if not sku:
                logger.warning(f"Variant {variant.get('id')} has no SKU, including in unsynced list")
                unsynced_variants.append(variant_edge)
                continue
            
            # Check if this variant is already synced in SAP
            is_synced = await self.check_variant_sync_status(sku, store_key)
            
            if not is_synced:
                unsynced_variants.append(variant_edge)
            else:
                logger.info(f"Variant with SKU {sku} is already synced, skipping")
        
        return unsynced_variants
    
    async def set_sync_status(self, store_key: str, product_id: str, status: str):
        """
        Set sync status metafield on a product
        """
        await self._set_metafield(store_key, product_id, "custom", "sap_sync", status)
    
    async def set_external_id(self, store_key: str, product_id: str, external_id: str):
        """
        Set external ID metafield on a product
        """
        await self._set_metafield(store_key, product_id, "jude_system", "external_id", external_id)
    
    async def _set_metafield(self, store_key: str, product_id: str, namespace: str, key: str, value: str):
        """
        Set a metafield on a product using REST API with retry logic
        """
        logger.info(f"Setting metafield {namespace}.{key} = {value} for product {product_id} in store {store_key}")
        
        # Add retry logic for metafield updates
        max_retries = 3
        retry_delay = 2  # Start with 2 seconds
        
        for attempt in range(max_retries):
            try:
                # Get store configuration
                enabled_stores = config_settings.get_enabled_stores()
                store_config = enabled_stores.get(store_key)
                
                if not store_config:
                    logger.error(f"Store configuration not found for {store_key}")
                    return
                
                # Extract product ID number from GraphQL ID
                product_id_number = product_id.split("/")[-1] if "/" in product_id else product_id
                
                headers = {
                    'X-Shopify-Access-Token': store_config.access_token,
                    'Content-Type': 'application/json',
                }
                
                async with httpx.AsyncClient() as client:
                    # Get current metafields
                    metafields_url = f"https://{store_config.shop_url}/admin/api/2024-01/products/{product_id_number}/metafields.json"
                    metafields_response = await client.get(metafields_url, headers=headers)
                    metafields_response.raise_for_status()
                    metafields_data = metafields_response.json()
                    metafields = metafields_data.get('metafields', [])
                    
                    # Check if metafield already exists
                    existing_metafield = None
                    for metafield in metafields:
                        if metafield.get('namespace') == namespace and metafield.get('key') == key:
                            existing_metafield = metafield
                            break
                    
                    if existing_metafield:
                        # Update existing metafield
                        update_url = f"https://{store_config.shop_url}/admin/api/2024-01/metafields/{existing_metafield['id']}.json"
                        update_data = {
                            "metafield": {
                                "value": value
                            }
                        }
                        
                        update_response = await client.put(update_url, headers=headers, json=update_data)
                        update_response.raise_for_status()
                        
                        logger.info(f"Updated metafield {namespace}.{key} = {value} for product {product_id}")
                    else:
                        # Create new metafield
                        create_data = {
                            "metafield": {
                                "namespace": namespace,
                                "key": key,
                                "value": value,
                                "type": "single_line_text_field"
                            }
                        }
                        
                        create_response = await client.post(metafields_url, headers=headers, json=create_data)
                        create_response.raise_for_status()
                        
                        logger.info(f"Created metafield {namespace}.{key} = {value} for product {product_id}")
                
                return  # Success, exit retry loop
                    
            except httpx.HTTPStatusError as e:
                logger.warning(f"HTTP error setting metafield {namespace}.{key} for product {product_id} (attempt {attempt + 1}/{max_retries}): {e.response.status_code} - {e.response.text}")
                
                if attempt < max_retries - 1:  # Don't sleep on last attempt
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error(f"Failed to set metafield {namespace}.{key} for product {product_id} after {max_retries} attempts")
                    
            except Exception as e:
                logger.warning(f"Error setting metafield {namespace}.{key} for product {product_id} (attempt {attempt + 1}/{max_retries}): {str(e)}")
                
                if attempt < max_retries - 1:  # Don't sleep on last attempt
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error(f"Failed to set metafield {namespace}.{key} for product {product_id} after {max_retries} attempts: {str(e)}")
    
    async def update_sap_item_fields(self, sku: str, foreign_name: str, 
                                   parent_commercial_name: str, shopify_color: str, 
                                   is_single_variant: bool = True):
        """
        Update SAP item fields using PATCH request
        
        For single variant products:
        - ForeignName => title of the product
        - U_SalesChannel => "3"
        
        For multi-variant products:
        - ForeignName => title of the product
        - U_SalesChannel => "3"
        - U_ParentCommercialName => title of the product
        - U_ShopifyColor => title of the variant
        """
        update_data = {
            "ForeignName": foreign_name,
            "U_SalesChannel": "3"
        }
        
        # Add variant-specific fields for multi-variant products
        if not is_single_variant:
            if parent_commercial_name:
                update_data["U_ParentCommercialName"] = parent_commercial_name
            if shopify_color:
                update_data["U_ShopifyColor"] = shopify_color
        
        try:
            logger.info(f"Updating SAP item fields for SKU: {sku} with data: {update_data}")
            result = await sap_client._make_request(
                method="PATCH",
                endpoint=f"Items('{sku}')",
                data=update_data,
                login_required=True
            )
            
            if result["msg"] == "success":
                logger.info(f"Successfully updated SAP item fields for SKU: {sku} (single_variant: {is_single_variant})")
            else:
                logger.error(f"Failed to update SAP item fields for SKU {sku}: {result.get('error')}")
                raise Exception(f"Failed to update SAP item fields: {result.get('error')}")
                
        except Exception as e:
            logger.error(f"Error updating SAP item fields for SKU {sku}: {str(e)}")
            raise
    
    async def get_products_by_sync_status(self, store_key: str, status: str = None) -> List[Dict[str, Any]]:
        """
        Get products filtered by sync status metafield
        """
        # Build query filter based on status
        if status:
            # Filter by specific status
            query_filter = f'metafield:custom.sap_sync="{status}"'
        else:
            # Get all products without sync status (not yet processed)
            query_filter = '-metafield:custom.sap_sync'
        
        query = """
        query GetProductsBySyncStatus($cursor: String, $query: String!) {
            products(first: 150, after: $cursor, query: $query) {
                pageInfo {
                    hasNextPage
                    endCursor
                }
                edges {
                    node {
                        id
                        title
                        description
                        vendor
                        productType
                        metafields(first: 10, namespace: "custom") {
                            edges {
                                node {
                                    id
                                    namespace
                                    key
                                    value
                                    type
                                }
                            }
                        }
                        variants(first: 15) {
                            edges {
                                node {
                                    id
                                    title
                                    sku
                                    barcode
                                    inventoryItem {
                                        id
                                        tracked
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        
        all_products = []
        cursor = None
        
        while True:
            variables = {
                "cursor": cursor if cursor else None,
                "query": query_filter
            }
            
            result = await multi_store_shopify_client.execute_query(store_key, query, variables)
            
            if result["msg"] != "success":
                logger.error(f"Failed to get products by sync status from store {store_key}: {result.get('error')}")
                break
            
            data = result["data"]
            products_data = data.get("products", {})
            
            # Extract products from edges
            for edge in products_data.get("edges", []):
                product = edge["node"]
                all_products.append(product)
            
            # Check if there are more pages
            page_info = products_data.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
                
            cursor = page_info.get("endCursor")
        
        return all_products

# Global instance
items_init = ItemsInitialization()

async def main():
    """
    Main function to run the initialization process
    """
    logger.info("Starting Shopify items initialization process")
    
    try:
        await items_init.initialize_all_stores()
        logger.info("Shopify items initialization completed successfully")
    except Exception as e:
        logger.error(f"Items initialization failed: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
