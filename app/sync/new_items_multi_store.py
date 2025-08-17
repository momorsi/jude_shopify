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
from app.services.sap.api_logger import sl_add_log
from datetime import datetime

class MultiStoreNewItemsSync:
    def __init__(self):
        self.batch_size = config_settings.new_items_batch_size
        self.shopify_field_mapping = {
            'ItemCode': 'sku',
            'ItemName': 'title',
            'FrgnName': 'description',
            'Barcode': 'barcode',
            'U_Text1': 'vendor',
            'U_BRND': 'brand',
        }
    

    
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
        Create a simple product without variant complexity
        Updated for Shopify API 2025-07 two-step approach
        """
        price = self._get_store_price(sap_item, store_config.price_list)
                
        product_status = "DRAFT"
        
        # Step 1: Create product with options (even for single products)
        product_data = {
            "title": sap_item.get('FrgnName', ''),
            "descriptionHtml": sap_item.get('FrgnName', ''),
            "vendor": sap_item.get('U_Text1', ''),
            "productType": "Default",
            "status": product_status,
            "tags": self._extract_tags(sap_item),
            "productOptions": [
                {
                    "name": "Title",
                    "values": [
                        {"name": "Default Title"}
                    ]
                }
            ]
        }
        
        # Add SEO fields
        if sap_item.get('FrgnName'):
            product_data["seo"] = {
                "title": sap_item.get('FrgnName'),
                "description": sap_item.get('FrgnName', '')[:255] if sap_item.get('FrgnName') else ''
            }
        
        # Step 2: Prepare variant data for bulk creation
        # Prepare inventory item data
        inventory_item = {
            "sku": sap_item.get('itemcode', ''),
            "tracked": True
        }
        
        variant = {
            "price": str(price),
            "taxable": False,  # Disable tax on this variant
            "optionValues": [
                {
                    "name": "Default Title",
                    "optionId": None  # Will be set after product creation
                }
            ],
            "inventoryItem": inventory_item
        }
        
        # Add barcode directly to the variant if available
        if sap_item.get('Barcode'):
            variant["barcode"] = sap_item.get('Barcode')
        
        return {
            "product_data": product_data,
            "variants_data": [variant],
            "sap_items": [sap_item]  # Keep reference to original item for mapping
        }
    
    def _create_product_with_variants(self, sap_items: List[Dict[str, Any]], store_config: Any) -> Dict[str, Any]:
        """
        Create a product with multiple variants based on color
        Updated for Shopify API 2025-07 two-step approach
        """
        # Use the first item as the base product
        base_item = sap_items[0]
        
        # For products with variants, use FrgnName as the product title
        product_title = base_item.get('FrgnName', '')
        
        # Determine product status based on test mode
        from app.core.config import config_settings
        product_status = "DRAFT" if config_settings.test_mode else "ACTIVE"
        
        # Step 1: Create product with options
        product_data = {
            "title": product_title,
            "descriptionHtml": base_item.get('FrgnName', ''),
            "vendor": base_item.get('U_Text1', ''),
            "productType": "Default",
            "status": product_status,
            "tags": self._extract_tags(base_item),
            "productOptions": [
                {
                    "name": "Color",
                    "values": []
                }
            ]
        }
        
        # Add SEO fields
        if base_item.get('FrgnName'):
            product_data["seo"] = {
                "title": base_item.get('FrgnName'),
                "description": base_item.get('FrgnName', '')[:255] if base_item.get('FrgnName') else ''
            }
        
        # Collect all unique colors for the product options
        colors = set()
        for item in sap_items:
            color_name = item.get('Color', '')
            if color_name:
                sap_color = self._get_color_from_sap(color_name)
                colors.add(sap_color)
        
        # Add color values to the product options
        product_data["productOptions"][0]["values"] = [
            {"name": color} for color in sorted(colors)
        ]
        
        # Step 2: Prepare variants data for bulk creation
        variants_data = []
        for item in sap_items:
            price = float(item.get('Price', 0))
            color_name = item.get('Color', '')
            sap_color = self._get_color_from_sap(color_name)
            
            # Prepare inventory item data
            inventory_item = {
                "sku": item.get('itemcode', ''),
                "tracked": True
            }
            
            variant = {
                "price": str(price),
                "taxable": False,  # Disable tax on this variant
                "optionValues": [
                    {
                        "name": sap_color,
                        "optionId": None  # Will be set after product creation
                    }
                ],
                "inventoryItem": inventory_item
            }
            
            # Add barcode directly to the variant if available
            if item.get('Barcode'):
                variant["barcode"] = item.get('Barcode')
            
            variants_data.append(variant)
        
        return {
            "product_data": product_data,
            "variants_data": variants_data,
            "sap_items": sap_items  # Keep reference to original items for mapping
        }
    
    async def create_product_with_variants_two_step(self, store_key: str, product_info: Dict[str, Any], store_config: Any) -> Dict[str, Any]:
        """
        Create product with variants using the new two-step Shopify API 2025-07 approach
        """
        try:
            product_data = product_info["product_data"]
            variants_data = product_info["variants_data"]
            sap_items = product_info["sap_items"]
            
            # Step 1: Create the product with options
            logger.info(f"Step 1: Creating product with options in store {store_key}")
            product_result = await multi_store_shopify_client.create_product_with_options(store_key, product_data)
            
            if product_result["msg"] == "failure":
                logger.error(f"Failed to create product with options in store {store_key}: {product_result.get('error')}")
                return product_result
            
            response_data = product_result["data"]["productCreate"]
            if response_data.get("userErrors"):
                errors = [error["message"] for error in response_data["userErrors"]]
                error_msg = "; ".join(errors)
                logger.error(f"User errors creating product with options in store {store_key}: {error_msg}")
                return {"msg": "failure", "error": error_msg}
            
            product = response_data["product"]
            product_id = product["id"]
            
            # Get the option ID from the response (could be Color or Title)
            option_id = None
            option_name = None
            for option in product["options"]:
                if option["name"] in ["Color", "Title"]:
                    option_id = option["id"]
                    option_name = option["name"]
                    break
            
            if not option_id:
                logger.error(f"No valid option found in created product for store {store_key}")
                return {"msg": "failure", "error": "No valid option found in created product"}
            
            # Step 2: Update variants with the correct option ID and location ID
            logger.info(f"Step 2: Creating variants in bulk for store {store_key}")
            
            # Update variants with correct option ID (no inventory quantities needed)
            for variant in variants_data:
                variant["optionValues"][0]["optionId"] = option_id
            
            # Create variants in bulk
            variants_result = await multi_store_shopify_client.create_product_variants_bulk(store_key, product_id, variants_data)
            
            if variants_result["msg"] == "failure":
                logger.error(f"Failed to create variants in bulk for store {store_key}: {variants_result.get('error')}")
                return variants_result
            
            response_data = variants_result["data"]["productVariantsBulkCreate"]
            if response_data.get("userErrors"):
                errors = [error["message"] for error in response_data["userErrors"]]
                error_msg = "; ".join(errors)
                logger.error(f"User errors creating variants in bulk for store {store_key}: {error_msg}")
                return {"msg": "failure", "error": error_msg}
            
            # Extract variant information for SAP mapping
            shopify_variants = []
            for variant in response_data["productVariants"]:
                shopify_variants.append({
                    "id": variant["id"],
                    "sku": variant["sku"],
                    "inventory_item_id": variant["inventoryItem"]["id"],
                    "selected_options": variant.get("selectedOptions", [])
                })
            
            logger.info(f"Successfully created product with {len(shopify_variants)} variants in store {store_key}")
            
            return {
                "msg": "success",
                "shopify_product_id": product_id,
                "shopify_variants": shopify_variants,
                "handle": None  # Handle will be generated by Shopify
            }
            
        except Exception as e:
            logger.error(f"Error in two-step product creation for store {store_key}: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
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
            "weight": sap_item.get('InventoryWeight', 0.0),
            "weightUnit": "KILOGRAMS",
            "taxable": False  # Disable tax on this variant
        }
        
        # Store color for potential later use (not sent to GraphQL)
        color = sap_item.get('Color', '')
        if color:
            variant_data["_color"] = color
        
        # Add barcode if available
        if sap_item.get('Barcode'):
            variant_data["barcode"] = sap_item.get('Barcode')
        return variant_data
    
    def _get_color_from_sap(self, color_name: str) -> str:
        """
        Get color directly from SAP without any mapping
        Simply return the color name as received from SAP
        """
        return color_name.strip() if color_name else ""
    
    def _extract_tags(self, sap_item: Dict[str, Any]) -> List[str]:
        """
        Extract tags from SAP item custom fields (excluding sync status which is now in metafields)
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
    

    
    async def check_existing_product(self, store_key: str, main_product_name: str) -> Dict[str, Any]:
        """
        Check if a product already exists in the store by creating a handle from the main product name
        """
        try:
            # Handle NULL/None/empty main_product_name
            if not main_product_name or main_product_name.strip() == "":
                logger.warning(f"Empty main_product_name provided for store {store_key}, skipping handle check")
                return {
                    "msg": "success",
                    "exists": False,
                    "product": None
                }
            
            # Create a handle from the main product name
            handle = main_product_name.lower().replace(' ', '-').replace('_', '-')
            
            # Ensure handle is not empty after processing
            if not handle or handle.strip() == "":
                logger.warning(f"Empty handle generated from main_product_name '{main_product_name}' for store {store_key}")
                return {
                    "msg": "success",
                    "exists": False,
                    "product": None
                }
            
            result = await multi_store_shopify_client.get_product_by_handle(store_key, handle)
            
            if result["msg"] == "success" and result["data"].get("productByHandle"):
                product = result["data"]["productByHandle"]
                

                
                return {
                    "msg": "success",
                    "exists": True,
                    "product": product
                }
            else:

                
                return {
                    "msg": "success",
                    "exists": False,
                    "product": None
                }
                
        except Exception as e:
            logger.error(f"Error checking existing product in store {store_key}: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def add_variant_to_existing_product(self, store_key: str, product_id: str, variant_data: Dict[str, Any], color: str = None) -> Dict[str, Any]:
        """
        Add a variant to an existing product using the new Shopify API 2025-07 approach
        """
        try:
            # 1. Get the product's current options using product ID
            product_info = await multi_store_shopify_client.get_product_by_id(store_key, product_id)
            if product_info["msg"] == "success" and product_info["data"].get("product"):
                product = product_info["data"]["product"]
                
                # Get the Color option ID from the product's options
                color_option_id = None
                for option in product.get("options", []):
                    if option["name"] == "Color":
                        color_option_id = option["id"]
                        break
                
                # If Color option doesn't exist in product options, try to get it from existing variants
                if not color_option_id:
                    logger.info(f"Color option not found in product options, checking existing variants for store {store_key}")
                    
                    # Look for Color option in existing variants' selectedOptions
                    for variant_edge in product.get("variants", {}).get("edges", []):
                        variant = variant_edge["node"]
                        for selected_option in variant.get("selectedOptions", []):
                            if selected_option["name"] == "Color":
                                # We found a Color option being used, but we need the option ID
                                # Since we can't create options after product creation, we'll skip this variant
                                logger.warning(f"Color option is being used in existing variants but not found in product options for store {store_key}")
                                return {"msg": "failure", "error": "Color option not properly configured in existing product"}
                
                if color_option_id:
                    logger.info(f"Found existing Color option with ID: {color_option_id}")
                else:
                    logger.warning(f"No Color option found in existing product for store {store_key}, will create new product")
                    # Return a special error that indicates we should create a new product
                    return {"msg": "failure", "error": "CREATE_NEW_PRODUCT"}
            else:
                # Product not found, create a new product instead
                logger.warning(f"Product {product_id} not found in store {store_key}, will create new product")
                return {"msg": "failure", "error": "CREATE_NEW_PRODUCT"}
            
            # 2. No location lookup needed - inventory will be handled by stock sync process
            
            # 3. Prepare variant data for bulk creation
            sap_color = self._get_color_from_sap(color) if color else "Default Title"
            
            # Prepare inventory item data
            inventory_item = {
                "sku": variant_data.get('sku', ''),
                "tracked": True
            }
            
            variant_for_bulk = {
                "price": variant_data.get('price', '0.0'),
                "taxable": variant_data.get('taxable', False),
                "optionValues": [
                    {
                        "name": sap_color,
                        "optionId": color_option_id
                    }
                ],
                "inventoryItem": inventory_item
            }
            
            # Add barcode directly to the variant if available
            if variant_data.get('barcode'):
                variant_for_bulk["barcode"] = variant_data.get('barcode')
            
            # Log the variant addition
            await sl_add_log(
                server="shopify",
                endpoint=f"/admin/api/graphql_{store_key}",
                request_data={"product_id": product_id, "variant_data": variant_for_bulk},
                action="add_variant",
                value=f"Adding variant {variant_data.get('sku')} to product {product_id} in store {store_key}"
            )
            
            # 4. Create variant using productVariantsBulkCreate
            result = await multi_store_shopify_client.create_product_variants_bulk(store_key, product_id, [variant_for_bulk])
            
            if result["msg"] == "failure":
                logger.error(f"Failed to create variant in bulk for store {store_key}: {result.get('error')}")
                await sl_add_log(
                    server="shopify",
                    endpoint=f"/admin/api/graphql_{store_key}",
                    response_data={"error": result.get("error"), "variant_data": variant_for_bulk},
                    status="failure",
                    action="add_variant",
                    value=f"Failed to add variant to product in store {store_key}: {result.get('error')}"
                )
                return result
                
            response_data = result["data"]["productVariantsBulkCreate"]
            if response_data.get("userErrors"):
                errors = [error["message"] for error in response_data["userErrors"]]
                error_msg = "; ".join(errors)
                
                await sl_add_log(
                    server="shopify",
                    endpoint=f"/admin/api/graphql_{store_key}",
                    response_data={"user_errors": errors},
                    status="failure",
                    action="add_variant",
                    value=f"User errors adding variant in store {store_key}: {error_msg}"
                )
                return {"msg": "failure", "error": error_msg}
                
            # Get the created variant from the response
            created_variants = response_data.get("productVariants", [])
            if not created_variants:
                logger.error(f"No variants created for {variant_data.get('sku')}")
                return {"msg": "failure", "error": "No variants created"}
            
            variant = created_variants[0]  # We only created one variant
            
            await sl_add_log(
                server="shopify",
                endpoint=f"/admin/api/graphql_{store_key}",
                response_data={
                    "variant_id": variant["id"],
                    "sku": variant["sku"],
                    "inventory_item_id": variant["inventoryItem"]["id"]
                },
                status="success",
                action="add_variant",
                value=f"Successfully added variant {variant['sku']} to product in store {store_key}"
            )
            
            return {
                "msg": "success",
                "shopify_variant_id": variant["id"],
                "shopify_inventory_item_id": variant["inventoryItem"]["id"],
                "sku": variant["sku"]
            }
            
        except Exception as e:
            await sl_add_log(
                server="shopify",
                endpoint=f"/admin/api/graphql_{store_key}",
                response_data={"error": str(e)},
                status="failure",
                action="add_variant_to_product",
                value=f"Exception adding variant to product in store {store_key}: {str(e)}"
            )
            logger.error(f"Error adding variant to product in store {store_key}: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def create_product_in_store(self, store_key: str, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create product in a specific Shopify store
        Returns main product ID, all variant IDs, and all inventory item IDs
        """
        try:
            # Log the Shopify API call
            await sl_add_log(
                server="shopify",
                endpoint=f"/admin/api/graphql_{store_key}",
                request_data={"product_data": product_data},
                action="create_product",
                value=f"Creating product in store {store_key}"
            )
            
            result = await multi_store_shopify_client.create_product(store_key, product_data)
            from app.utils.logging import logger
            logger.error(f"Shopify full response for store {store_key}: {result}")
            
            if result["msg"] == "failure":
                # Log the failure
                await sl_add_log(
                    server="shopify",
                    endpoint=f"/admin/api/graphql_{store_key}",
                    response_data={"error": result.get("error")},
                    status="failure",
                    action="create_product",
                    value=f"Failed to create product in store {store_key}: {result.get('error')}"
                )
                return result
                
            response_data = result["data"]["productCreate"]
            if response_data.get("userErrors"):
                errors = [error["message"] for error in response_data["userErrors"]]
                error_msg = "; ".join(errors)
                
                # Log the user errors
                await sl_add_log(
                    server="shopify",
                    endpoint=f"/admin/api/graphql_{store_key}",
                    response_data={"user_errors": errors},
                    status="failure",
                    action="create_product",
                    value=f"User errors in store {store_key}: {error_msg}"
                )
                return {"msg": "failure", "error": error_msg}
                
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
            
            # Log the success
            await sl_add_log(
                server="shopify",
                endpoint=f"/admin/api/graphql_{store_key}",
                response_data={
                    "product_id": product["id"],
                    "handle": product["handle"],
                    "variant_count": len(shopify_variants)
                },
                status="success",
                action="create_product",
                value=f"Successfully created product in store {store_key}"
            )
            
            return {
                "msg": "success",
                "shopify_product_id": product["id"],
                "shopify_variants": shopify_variants,  # All variants for proper mapping
                "handle": product["handle"]
            }
        except Exception as e:
            # Log the exception
            await sl_add_log(
                server="shopify",
                endpoint=f"/admin/api/graphql_{store_key}",
                response_data={"error": str(e)},
                status="failure",
                action="create_product",
                value=f"Exception creating product in store {store_key}: {str(e)}"
            )
            logger.error(f"Error creating product in store {store_key}: {str(e)}")
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
                        
                        # Extract main product name and existing Shopify product ID from the first item
                        main_product_name = group_items[0].get("MainProduct", "")
                        existing_shopify_product_id = group_items[0].get("Shopify_ProductCode")
                        
                        # For items with NULL MainProduct, use itemcode as the product name
                        if not main_product_name:
                            main_product_name = group_items[0].get("itemcode", "")
                        
                        # Check if we have an existing Shopify product ID
                        if existing_shopify_product_id:
                            logger.info(f"Found existing Shopify product ID: {existing_shopify_product_id} for {main_product_name}")
                            # Use the existing product ID directly
                            existing_product_result = {
                                "msg": "success",
                                "exists": True,
                                "product_id": f"gid://shopify/Product/{existing_shopify_product_id}"
                            }
                        else:
                            # Check if product already exists by handle
                            existing_product_result = await self.check_existing_product(store_key, main_product_name)
                        
                        if existing_product_result["msg"] == "failure":
                            logger.error(f"Failed to check existing product in store {store_key}: {existing_product_result.get('error')}")
                            errors += 1
                            continue
                        
                        if existing_product_result["exists"]:
                            # Product exists, add variants to it
                            logger.info(f"Product {main_product_name} already exists in store {store_key}, adding variants")
                            
                            # Get the product ID and existing variants
                            if "product_id" in existing_product_result:
                                # We have the product ID directly from Shopify_ProductCode
                                product_id = existing_product_result["product_id"]
                                shopify_product_id = existing_product_result["product_id"].split("/")[-1]
                                # Get existing variants for this product
                                product_info = await multi_store_shopify_client.get_product_by_id(store_key, product_id)
                                if product_info["msg"] == "success" and product_info["data"].get("product"):
                                    existing_variants = product_info["data"]["product"]["variants"]["edges"]
                                else:
                                    existing_variants = []
                            else:
                                # We got the product from handle lookup
                                existing_product = existing_product_result["product"]
                                product_id = existing_product["id"]
                                shopify_product_id = product_id.split("/")[-1]
                                existing_variants = existing_product["variants"]["edges"]
                            

                            
                            # Process each item as a variant
                            variant_results = []
                            for sap_item in group_items:
                                # Check if this variant already exists (only if we have existing variants info)
                                if existing_variants:
                                    variant_exists = any(variant["node"]["sku"] == sap_item.get("itemcode") for variant in existing_variants)
                                    if variant_exists:
                                        logger.info(f"Variant {sap_item.get('itemcode')} already exists, skipping")
                                        continue
                                
                                # If we don't have existing variants info, try to create the variant anyway
                                # Shopify will return an error if it already exists, which we'll handle
                                
                                # Create variant data
                                price = self._get_store_price(sap_item, store_config.price_list)
                                variant_data = self._create_variant(sap_item, store_config, price, 0)  # Inventory will be handled by inventory sync
                                
                                # Store color for later use and remove it from variant data
                                color = variant_data.pop("_color", None)
                                
                                # Add variant to existing product
                                variant_result = await self.add_variant_to_existing_product(store_key, product_id, variant_data, color)
                                
                                # Check if we need to create a new product instead
                                if variant_result["msg"] == "failure" and variant_result.get("error") == "CREATE_NEW_PRODUCT":
                                    logger.info(f"Creating new product instead of adding to existing one for store {store_key}")
                                    
                                    # Create new product with all variants using the two-step approach
                                    product_info = self.map_sap_item_to_shopify_product(group_items, store_config)
                                    store_result = await self.create_product_with_variants_two_step(store_key, product_info, store_config)
                                    
                                    if store_result["msg"] == "failure":
                                        logger.error(f"Failed to create new product in store {store_key}: {store_result.get('error')}")
                                        errors += 1
                                        break  # Break out of the variant loop since we're creating a new product
                                    else:
                                        logger.info(f"Successfully created new product in store {store_key}")
                                        shopify_product_id = store_result["shopify_product_id"].split("/")[-1]
                                        success += len(group_items)  # Count all variants as success
                                        break  # Break out of the variant loop since we're creating a new product
                                elif variant_result["msg"] == "failure" and variant_result.get("error") == "Color option not properly configured in existing product":
                                    logger.info(f"Existing product has configuration issues, creating new product for store {store_key}")
                                    
                                    # Create new product with all variants using the two-step approach
                                    product_info = self.map_sap_item_to_shopify_product(group_items, store_config)
                                    store_result = await self.create_product_with_variants_two_step(store_key, product_info, store_config)
                                    
                                    if store_result["msg"] == "failure":
                                        logger.error(f"Failed to create new product in store {store_key}: {store_result.get('error')}")
                                        errors += 1
                                        break  # Break out of the variant loop since we're creating a new product
                                    else:
                                        logger.info(f"Successfully created new product in store {store_key}")
                                        shopify_product_id = store_result["shopify_product_id"].split("/")[-1]
                                        success += len(group_items)  # Count all variants as success
                                        break  # Break out of the variant loop since we're creating a new product
                                else:
                                    variant_results.append(variant_result)
                                    
                                    if variant_result["msg"] == "success":
                                        logger.info(f"Successfully added variant {sap_item.get('itemcode')} to existing product")
                                        success += 1
                                    else:
                                        logger.error(f"Failed to add variant {sap_item.get('itemcode')}: {variant_result.get('error')}")
                                        errors += 1
                            
                        else:
                            # Product doesn't exist, create new product with all variants
                            logger.info(f"Product {main_product_name} doesn't exist in store {store_key}, creating new product")
                            
                            # Use new two-step approach for ALL products (both single and multi-variant)
                            product_info = self.map_sap_item_to_shopify_product(group_items, store_config)
                            store_result = await self.create_product_with_variants_two_step(store_key, product_info, store_config)
                            
                            if store_result["msg"] == "failure":
                                logger.error(f"Failed to create product in store {store_key}: {store_result.get('error')}")
                                errors += 1
                                continue
                            else:
                                logger.info(f"Successfully created product in store {store_key}")
                                shopify_product_id = store_result["shopify_product_id"].split("/")[-1]
                        
                        # Save Shopify IDs to SAP mapping table
                        main_product_name = group_items[0].get("MainProduct", "")
                        
                        # For single products (no variants), use itemcode as U_SAP_Code since MainProduct is NULL
                        sap_code_for_mapping = main_product_name if main_product_name else group_items[0].get("itemcode", "")                    
                        
                        mapping_result = await sap_client.add_shopify_mapping({
                            "Code": shopify_product_id,
                            "Name": shopify_product_id,
                            "U_Shopify_Type": "product",
                            "U_SAP_Code": sap_code_for_mapping,
                            "U_Shopify_Store": store_key,
                            "U_SAP_Type": "item",
                            "U_CreateDT": datetime.now().strftime('%Y-%m-%d')
                        })                        
                        
                        # Handle variant mappings based on whether we created a new product or added to existing
                        if existing_product_result["exists"]:
                            # For existing products, use the variant results from add_variant_to_existing_product
                            for sap_item in group_items:
                                itemcode = sap_item.get("itemcode", "")
                                
                                # Find the matching variant result
                                variant_result = None
                                for vr in variant_results:
                                    if vr.get("sku") == itemcode:
                                        variant_result = vr
                                        break
                                
                                if variant_result and variant_result["msg"] == "success":
                                    variant_id = variant_result["shopify_variant_id"].split("/")[-1]
                                    inventory_id = variant_result["shopify_inventory_item_id"].split("/")[-1]
                                    
                                    variant_mapping_result = await sap_client.add_shopify_mapping({
                                        "Code": variant_id,
                                        "Name": variant_id,
                                        "U_Shopify_Type": "variant",
                                        "U_SAP_Code": itemcode,
                                        "U_Shopify_Store": store_key,
                                        "U_SAP_Type": "item",
                                        "U_CreateDT": datetime.now().strftime('%Y-%m-%d')
                                    })
                                    
                                    inventory_mapping_result = await sap_client.add_shopify_mapping({
                                        "Code": inventory_id,
                                        "Name": inventory_id,
                                        "U_Shopify_Type": "variant_inventory",
                                        "U_SAP_Code": itemcode,
                                        "U_Shopify_Store": store_key,
                                        "U_SAP_Type": "item",
                                        "U_CreateDT": datetime.now().strftime('%Y-%m-%d')
                                    })
                        else:
                            # For new products, use the store_result from create_product_in_store
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
                                    variant_mapping_result = await sap_client.add_shopify_mapping({
                                        "Code": variant_id,
                                        "Name": variant_id,
                                        "U_Shopify_Type": "variant",
                                        "U_SAP_Code": itemcode,
                                        "U_Shopify_Store": store_key,
                                        "U_SAP_Type": "item",
                                        "U_CreateDT": datetime.now().strftime('%Y-%m-%d')
                                    })
                                    
                                if inventory_id:
                                    inventory_mapping_result = await sap_client.add_shopify_mapping({
                                        "Code": inventory_id,
                                        "Name": inventory_id,
                                        "U_Shopify_Type": "variant_inventory",
                                        "U_SAP_Code": itemcode,
                                        "U_Shopify_Store": store_key,
                                        "U_SAP_Type": "item",
                                        "U_CreateDT": datetime.now().strftime('%Y-%m-%d')
                                    })

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
            # Log the error in the sync process
            await sl_add_log(
                server="system",
                endpoint="/sync/new_items_multi_store",
                response_data={"error": str(e)},
                status="failure",
                action="sync_error",
                value=f"Error in multi-store new items sync: {str(e)}"
            )
            
            logger.error(f"Error in multi-store new items sync: {str(e)}")
            return {"msg": "failure", "error": str(e)}

# Create singleton instance
multi_store_new_items_sync = MultiStoreNewItemsSync() 
