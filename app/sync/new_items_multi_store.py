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
        SKU is set at the variant level (Shopify standard approach)
        Inventory will be handled separately by the inventory sync process
        """
        price = self._get_store_price(sap_item, store_config.price_list)
        
        product_data = {
            "title": sap_item.get('ItemName', ''),
            "descriptionHtml": sap_item.get('FrgnName', ''),
            "vendor": sap_item.get('U_Text1', ''),
            "productType": "Default",
            "status": "DRAFT",  # Always create as draft for testing
            "tags": self._extract_tags(sap_item),
            "variants": [{
                "sku": sap_item.get('itemcode', ''),  # SKU at variant level (Shopify standard)
                "price": str(price),
                "inventoryPolicy": "DENY",
                "inventoryManagement": "SHOPIFY",
                "weight": sap_item.get('InventoryWeight', 0.0),
                "weightUnit": "KILOGRAMS",
                "taxable": False  # Disable tax on this variant
                # Inventory quantities will be set separately by inventory sync
            }]
        }
        
        # Add barcode at variant level if available
        if sap_item.get('Barcode'):
            product_data["variants"][0]["barcode"] = sap_item.get('Barcode')
        
        # Add SEO fields
        if sap_item.get('ItemName'):
            product_data["seo"] = {
                "title": sap_item.get('ItemName'),
                "description": sap_item.get('FrgnName', '')[:255] if sap_item.get('FrgnName') else ''
            }
        
        return product_data
    
    def _create_product_with_variants(self, sap_items: List[Dict[str, Any]], store_config: Any) -> Dict[str, Any]:
        """
        Create a product with multiple variants based on color
        Inventory will be handled separately by the inventory sync process
        """
        # Use the first item as the base product
        base_item = sap_items[0]
        

        
        product_data = {
            "title": base_item.get('MainProduct', ''),
            "status": "DRAFT",
            "options": ["Color"],
            "variants": []
        }
        # Add all variants with correct options, sku, and price fields
        for item in sap_items:
            price = float(item.get('Price', 0))
            color_name = item.get('Color', '')
            mapped_color = self._map_color_to_shopify_color(color_name)
            
            variant = {
                "options": [mapped_color],
                "sku": item.get('itemcode', ''),
                "price": str(price),
                "inventoryManagement": "SHOPIFY",
                "inventoryPolicy": "DENY",
                "taxable": False  # Disable tax on this variant
                # Inventory quantities will be set separately by inventory sync
            }
            
            # Add barcode if available
            if item.get('Barcode'):
                variant["barcode"] = item.get('Barcode')
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
    
    def _map_color_to_shopify_color(self, color_name: str) -> str:
        """
        Map SAP color names to Shopify-recognized color values
        This ensures color swatches appear in the Shopify admin
        Note: Shopify requires exact color option values for swatches to appear
        """
        color_mapping = {
            # Standard colors - using Shopify's exact color option values
            'red': 'Red',
            'blue': 'Blue', 
            'green': 'Green',
            'yellow': 'Yellow',
            'black': 'Black',
            'white': 'White',
            'gray': 'Gray',
            'grey': 'Gray',
            'purple': 'Purple',
            'orange': 'Orange',
            'pink': 'Pink',
            'brown': 'Brown',
            'navy': 'Navy',
            'beige': 'Beige',
            'cream': 'Cream',
            'silver': 'Silver',
            'gold': 'Gold',
            'bronze': 'Bronze',
            'copper': 'Copper',
            'rose gold': 'Rose Gold',
            'rose-gold': 'Rose Gold',
            'rosegold': 'Rose Gold',
            
            # Specific color variations
            'lime green': 'Lime Green',
            'lime-green': 'Lime Green',
            'limegreen': 'Lime Green',
            'light blue': 'Light Blue',
            'light-blue': 'Light Blue',
            'lightblue': 'Light Blue',
            'dark blue': 'Dark Blue',
            'dark-blue': 'Dark Blue',
            'darkblue': 'Dark Blue',
            'light green': 'Light Green',
            'light-green': 'Light Green',
            'lightgreen': 'Light Green',
            'dark green': 'Dark Green',
            'dark-green': 'Dark Green',
            'darkgreen': 'Dark Green',
            'light pink': 'Light Pink',
            'light-pink': 'Light Pink',
            'lightpink': 'Light Pink',
            'hot pink': 'Hot Pink',
            'hot-pink': 'Hot Pink',
            'hotpink': 'Hot Pink',
            'baby pink': 'Baby Pink',
            'baby-pink': 'Baby Pink',
            'babypink': 'Baby Pink',
            'coral': 'Coral',
            'teal': 'Teal',
            'turquoise': 'Turquoise',
            'lavender': 'Lavender',
            'lilac': 'Lilac',
            'mint': 'Mint',
            'olive': 'Olive',
            'maroon': 'Maroon',
            'burgundy': 'Burgundy',
            'wine': 'Wine',
            'champagne': 'Champagne',
            'ivory': 'Ivory',
            'off-white': 'Off White',
            'offwhite': 'Off White',
            'charcoal': 'Charcoal',
            'slate': 'Slate',
            'taupe': 'Taupe',
            'tan': 'Tan',
            'khaki': 'Khaki',
            'camel': 'Camel',
            'nude': 'Nude',
            'transparent': 'Transparent',
            'clear': 'Clear',
            'multicolor': 'Multicolor',
            'multi-color': 'Multicolor',
            'multicoloured': 'Multicolor',
            'multi-colour': 'Multicolor',
            'rainbow': 'Rainbow',
            'metallic': 'Metallic',
            'glitter': 'Glitter',
            'matte': 'Matte',
            'glossy': 'Glossy',
            'shimmer': 'Shimmer',
            'iridescent': 'Iridescent',
            'holographic': 'Holographic',
            'neon': 'Neon',
            'pastel': 'Pastel',
            'vintage': 'Vintage',
            'distressed': 'Distressed',
            'faded': 'Faded',
            'bleached': 'Bleached',
            'tie-dye': 'Tie Dye',
            'tiedye': 'Tie Dye',
            'tie dye': 'Tie Dye',
            'ombre': 'Ombre',
            'gradient': 'Gradient',
            'floral': 'Floral',
            'geometric': 'Geometric',
            'striped': 'Striped',
            'polka dot': 'Polka Dot',
            'polkadot': 'Polka Dot',
            'polka-dot': 'Polka Dot',
            'checkered': 'Checkered',
            'plaid': 'Plaid',
            'argyle': 'Argyle',
            'herringbone': 'Herringbone',
            'houndstooth': 'Houndstooth',
            'paisley': 'Paisley',
            'tartan': 'Tartan',
            'gingham': 'Gingham',
            'denim': 'Denim',
            'leather': 'Leather',
            'suede': 'Suede',
            'velvet': 'Velvet',
            'satin': 'Satin',
            'silk': 'Silk',
            'cotton': 'Cotton',
            'linen': 'Linen',
            'wool': 'Wool',
            'cashmere': 'Cashmere',
            'acrylic': 'Acrylic',
            'polyester': 'Polyester',
            'nylon': 'Nylon',
            'spandex': 'Spandex',
            'lycra': 'Lycra',
            'elastane': 'Elastane',
            'mesh': 'Mesh',
            'lace': 'Lace',
            'crochet': 'Crochet',
            'knit': 'Knit',
            'woven': 'Woven',
            'jersey': 'Jersey',
            'fleece': 'Fleece',
            'faux fur': 'Faux Fur',
            'faux-fur': 'Faux Fur',
            'fauxfur': 'Faux Fur',
            'faux leather': 'Faux Leather',
            'faux-leather': 'Faux Leather',
            'fauxleather': 'Faux Leather',
            'faux suede': 'Faux Suede',
            'faux-suede': 'Faux Suede',
            'fauxsuede': 'Faux Suede',
            'faux silk': 'Faux Silk',
            'faux-silk': 'Faux Silk',
            'fauxsilk': 'Faux Silk',
            'faux velvet': 'Faux Velvet',
            'faux-velvet': 'Faux Velvet',
            'fauxvelvet': 'Faux Velvet',
            'faux satin': 'Faux Satin',
            'faux-satin': 'Faux Satin',
            'fauxsatin': 'Faux Satin',
            'faux lace': 'Faux Lace',
            'faux-lace': 'Faux Lace',
            'fauxlace': 'Faux Lace',
            'faux crochet': 'Faux Crochet',
            'faux-crochet': 'Faux Crochet',
            'fauxcrochet': 'Faux Crochet',
            'faux knit': 'Faux Knit',
            'faux-knit': 'Faux Knit',
            'fauxknit': 'Faux Knit',
            'faux woven': 'Faux Woven',
            'faux-woven': 'Faux Woven',
            'fauxwoven': 'Faux Woven',
            'faux jersey': 'Faux Jersey',
            'faux-jersey': 'Faux Jersey',
            'fauxjersey': 'Faux Jersey',
            'faux fleece': 'Faux Fleece',
            'faux-fleece': 'Faux Fleece',
            'fauxfleece': 'Faux Fleece',
            'faux mesh': 'Faux Mesh',
            'faux-mesh': 'Faux Mesh',
            'fauxmesh': 'Faux Mesh',
            'faux lace': 'Faux Lace',
            'faux-lace': 'Faux Lace',
            'fauxlace': 'Faux Lace',
            'faux crochet': 'Faux Crochet',
            'faux-crochet': 'Faux Crochet',
            'fauxcrochet': 'Faux Crochet',
            'faux knit': 'Faux Knit',
            'faux-knit': 'Faux Knit',
            'fauxknit': 'Faux Knit',
            'faux woven': 'Faux Woven',
            'faux-woven': 'Faux Woven',
            'fauxwoven': 'Faux Woven',
            'faux jersey': 'Faux Jersey',
            'faux-jersey': 'Faux Jersey',
            'fauxjersey': 'Faux Jersey',
            'faux fleece': 'Faux Fleece',
            'faux-fleece': 'Faux Fleece',
            'fauxfleece': 'Faux Fleece',
            'faux mesh': 'Faux Mesh',
            'faux-mesh': 'Faux Mesh',
            'fauxmesh': 'Faux Mesh',
        }
        
        # Normalize the color name (lowercase, remove extra spaces)
        normalized_color = color_name.lower().strip()
        
        # Return mapped color if found, otherwise return original (capitalized)
        return color_mapping.get(normalized_color, color_name.title())
    
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
    

    
    async def check_existing_product(self, store_key: str, main_product_name: str) -> Dict[str, Any]:
        """
        Check if a product already exists in the store by creating a handle from the main product name
        """
        try:
            # Handle NULL/None main_product_name
            if not main_product_name:
                main_product_name = "default"
            
            # Create a handle from the main product name
            handle = main_product_name.lower().replace(' ', '-').replace('_', '-')
            

            
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
        Add a variant to an existing product
        """
        try:
            # 1. Get the product's current options using product ID
            product_info = await multi_store_shopify_client.get_product_by_id(store_key, product_id)
            if product_info["msg"] == "success" and product_info["data"].get("product"):
                product = product_info["data"]["product"]
                options = [opt["name"] for opt in product.get("options", [])]
                # 2. If the only option is 'Title', update to ['Color']
                if options == ["Title"]:
                    await multi_store_shopify_client.update_product_options(store_key, product_id, ["Color"])
                # 3. Ensure Color option has proper values for swatches to appear
                elif "Color" in options and color:
                    # Get current color values and add the new color if needed
                    color_option = next((opt for opt in product.get("options", []) if opt["name"] == "Color"), None)
                    if color_option:
                        mapped_color = self._map_color_to_shopify_color(color)
                        current_values = color_option.get("values", [])
                        if mapped_color not in current_values:
                            # Note: We can't update option values via GraphQL in this version
                            # The color swatches will appear when variants are created with proper color values
                            logger.info(f"Color {mapped_color} will be added to product options when variant is created")

            
            # 3. Add the variant with options if color is available
            if color:
                mapped_color = self._map_color_to_shopify_color(color)
                variant_data["options"] = [mapped_color]  # Use mapped color for proper swatch display
            
            # Remove any option-related fields that might cause issues
            variant_data.pop("selectedOptions", None)
            variant_data.pop("option1", None)
            
            # Log the variant addition
            await sl_add_log(
                server="shopify",
                endpoint=f"/admin/api/graphql_{store_key}",
                request_data={"product_id": product_id, "variant_data": variant_data},
                action="add_variant",
                value=f"Adding variant {variant_data.get('sku')} to product {product_id} in store {store_key}"
            )
            
            result = await multi_store_shopify_client.add_variant_to_product(store_key, product_id, variant_data)
            
            if result["msg"] == "failure":
                # Check if the error is about variant already existing
                error_msg = result.get("error", "")
                if "already exists" in error_msg:
                    logger.info(f"Variant {variant_data.get('sku')} already exists, attempting to update it")
                    
                    # Try to find the existing variant and update it
                    # For now, we'll return a success message since the variant exists
                    # In a more complete implementation, we would find and update the existing variant
                    return {
                        "msg": "success",
                        "shopify_variant_id": "existing",  # Placeholder
                        "shopify_inventory_item_id": "existing",  # Placeholder
                        "sku": variant_data.get('sku'),
                        "note": "Variant already exists"
                    }
                else:
                    logger.error(f"Detailed variant creation error for {variant_data.get('sku')}: {result.get('error')}")
                    await sl_add_log(
                        server="shopify",
                        endpoint=f"/admin/api/graphql_{store_key}",
                        response_data={"error": result.get("error"), "variant_data": variant_data},
                        status="failure",
                        action="add_variant",
                        value=f"Failed to add variant to product in store {store_key}: {result.get('error')}"
                    )
                    return result
                
            response_data = result["data"]["productVariantCreate"]
            if response_data.get("userErrors"):
                errors = [error["message"] for error in response_data["userErrors"]]
                error_msg = "; ".join(errors)
                
                # Check if the error is about variant already existing
                if "already exists" in error_msg:
                    logger.info(f"Variant {variant_data.get('sku')} already exists, treating as success")
                    return {
                        "msg": "success",
                        "shopify_variant_id": "existing",  # Placeholder
                        "shopify_inventory_item_id": "existing",  # Placeholder
                        "sku": variant_data.get('sku'),
                        "note": "Variant already exists"
                    }
                else:
                    await sl_add_log(
                        server="shopify",
                        endpoint=f"/admin/api/graphql_{store_key}",
                        response_data={"user_errors": errors},
                        status="failure",
                        action="add_variant",
                        value=f"User errors adding variant in store {store_key}: {error_msg}"
                    )
                    return {"msg": "failure", "error": error_msg}
                
            variant = response_data["productVariant"]
            
            # 4. Update the variant to set the color option if needed
            if color:
                mapped_color = self._map_color_to_shopify_color(color)
                update_result = await multi_store_shopify_client.update_variant(
                    store_key, 
                    variant["id"], 
                    {
                        "title": mapped_color  # Set the title to the mapped color value
                    }
                )
                
                if update_result["msg"] == "success":
                    logger.info(f"Updated variant {variant['sku']} title to '{color}'")
                else:
                    logger.warning(f"Failed to update variant {variant['sku']} title: {update_result.get('error')}")
            
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
            
            # Set inventory for the new variant
            inventory_result = await multi_store_shopify_client.update_inventory(
                store_key, 
                variant["inventoryItem"]["id"], 
                inventory_quantity
            )
            
            if inventory_result["msg"] == "failure":
                logger.warning(f"Failed to set inventory for variant {variant['sku']}: {inventory_result.get('error')}")
            
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
                            product_data = self.map_sap_item_to_shopify_product(group_items, store_config)
                            store_result = await self.create_product_in_store(store_key, product_data)
                            
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
                            "U_CreateDate": datetime.now().strftime('%Y-%m-%d')
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
                                        "U_CreateDate": datetime.now().strftime('%Y-%m-%d')
                                    })
                                    
                                    inventory_mapping_result = await sap_client.add_shopify_mapping({
                                        "Code": inventory_id,
                                        "Name": inventory_id,
                                        "U_Shopify_Type": "variant_inventory",
                                        "U_SAP_Code": itemcode,
                                        "U_Shopify_Store": store_key,
                                        "U_SAP_Type": "item",
                                        "U_CreateDate": datetime.now().strftime('%Y-%m-%d')
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
                                        "U_CreateDate": datetime.now().strftime('%Y-%m-%d')
                                    })
                                    
                                if inventory_id:
                                    inventory_mapping_result = await sap_client.add_shopify_mapping({
                                        "Code": inventory_id,
                                        "Name": inventory_id,
                                        "U_Shopify_Type": "variant_inventory",
                                        "U_SAP_Code": itemcode,
                                        "U_Shopify_Store": store_key,
                                        "U_SAP_Type": "item",
                                        "U_CreateDate": datetime.now().strftime('%Y-%m-%d')
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