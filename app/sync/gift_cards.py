"""
Gift Cards Sync Module
Syncs gift cards from SAP to Shopify stores
Handles creating new gift cards and updating existing ones
"""

import asyncio
from typing import Dict, Any, List, Optional
from app.services.sap.client import sap_client
from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.core.config import config_settings
from app.utils.logging import logger, log_sync_event
from datetime import datetime

class GiftCardsSync:
    def __init__(self):
        self.batch_size = config_settings.master_data_batch_size
    
    async def get_gift_cards_from_sap(self) -> Dict[str, Any]:
        """
        Get gift cards from SAP
        """
        try:
            # You'll need to create this endpoint in SAP or use existing one
            # For now, using a placeholder endpoint
            result = await sap_client._make_request('GET', 'sml.svc/GIFT_CARDS?$orderby=CardCode')
            
            if result["msg"] == "failure":
                logger.error(f"Failed to get gift cards from SAP: {result.get('error')}")
                return {"msg": "failure", "error": result.get("error")}
            
            gift_cards = result["data"].get("value", [])
            logger.info(f"Retrieved {len(gift_cards)} gift cards from SAP")
            
            return {"msg": "success", "data": gift_cards}
            
        except Exception as e:
            logger.error(f"Error getting gift cards from SAP: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    def map_sap_gift_card_to_shopify(self, sap_gift_card: Dict[str, Any], store_config: Any) -> Dict[str, Any]:
        """
        Map SAP gift card data to Shopify gift card format for a specific store
        """
        try:
            # Get store-specific price
            price = self._get_store_price(sap_gift_card, store_config.price_list)
            
            gift_card_data = {
                "title": sap_gift_card.get('CardName', ''),
                "descriptionHtml": sap_gift_card.get('CardDescription', ''),
                "productType": "Gift Card",
                "status": "ACTIVE" if sap_gift_card.get('Active') == 'Y' else "DRAFT",
                "tags": self._extract_tags(sap_gift_card),
                "variants": [{
                    "sku": sap_gift_card.get('CardCode', ''),
                    "price": str(price),
                    "inventoryPolicy": "CONTINUE",
                    "inventoryManagement": "SHOPIFY",
                    "inventoryQuantities": [{
                        "availableQuantity": 999,  # High inventory for gift cards
                        "locationId": store_config.location_id
                    }],
                    "weight": 0.0,
                    "weightUnit": "KILOGRAMS"
                }]
            }
            
            # Add SEO fields
            if sap_gift_card.get('CardName'):
                gift_card_data["seo"] = {
                    "title": sap_gift_card.get('CardName'),
                    "description": sap_gift_card.get('CardDescription', '')[:255] if sap_gift_card.get('CardDescription') else ''
                }
            
            return gift_card_data
            
        except Exception as e:
            logger.error(f"Error mapping SAP gift card to Shopify: {str(e)}")
            raise
    
    def _get_store_price(self, sap_gift_card: Dict[str, Any], price_list: int) -> float:
        """
        Get price for a specific store based on price list
        """
        price = sap_gift_card.get('Price', 0.0)
        
        # Apply store-specific price adjustments if needed
        if price_list == 1:  # Local store (SAR)
            return price
        elif price_list == 2:  # International store (USD)
            # Convert SAR to USD
            exchange_rate = 0.27
            return price * exchange_rate
        
        return price
    
    def _extract_tags(self, sap_gift_card: Dict[str, Any]) -> List[str]:
        """
        Extract tags from SAP gift card custom fields
        """
        tags = []
        
        # Add gift card specific tags
        tags.append("Gift Card")
        
        # Add category as tag
        if sap_gift_card.get('U_Category'):
            tags.append(f"Category:{sap_gift_card['U_Category']}")
        
        # Add other custom fields as tags
        custom_fields = ['U_Occasion', 'U_Theme', 'U_Value']
        for field in custom_fields:
            if sap_gift_card.get(field):
                tags.append(f"{field}:{sap_gift_card[field]}")
        
        return tags
    
    async def create_gift_card_in_store(self, store_key: str, gift_card_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create gift card in a specific Shopify store
        """
        try:
            result = await multi_store_shopify_client.create_product(store_key, gift_card_data)
            
            if result["msg"] == "failure":
                return result
            
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
            logger.error(f"Error creating gift card in store {store_key}: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def update_gift_card_in_store(self, store_key: str, shopify_product_id: str, gift_card_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update existing gift card in a specific Shopify store
        """
        try:
            # Update product mutation
            mutation = """
            mutation productUpdate($input: ProductInput!) {
                productUpdate(input: $input) {
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
            
            # Add the product ID to the input
            gift_card_data["id"] = shopify_product_id
            
            result = await multi_store_shopify_client.execute_query(store_key, mutation, {"input": gift_card_data})
            
            if result["msg"] == "failure":
                return result
            
            response_data = result["data"]["productUpdate"]
            
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
            logger.error(f"Error updating gift card in store {store_key}: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def check_gift_card_exists(self, store_key: str, sap_card_code: str) -> Optional[str]:
        """
        Check if a gift card already exists in Shopify by SKU
        Returns the Shopify product ID if found, None otherwise
        """
        try:
            query = """
            query GetProductBySku($sku: String!) {
                products(first: 1, query: $sku) {
                    edges {
                        node {
                            id
                            title
                            variants(first: 1) {
                                edges {
                                    node {
                                        sku
                                    }
                                }
                            }
                        }
                    }
                }
            }
            """
            
            result = await multi_store_shopify_client.execute_query(store_key, query, {"sku": f"sku:{sap_card_code}"})
            
            if result["msg"] == "failure":
                return None
            
            products = result["data"]["products"]["edges"]
            if products:
                product = products[0]["node"]
                # Verify the SKU matches
                variant_sku = product["variants"]["edges"][0]["node"]["sku"]
                if variant_sku == sap_card_code:
                    return product["id"]
            
            return None
            
        except Exception as e:
            logger.error(f"Error checking if gift card exists in store {store_key}: {str(e)}")
            return None
    
    async def update_sap_with_shopify_ids(self, sap_gift_card: Dict[str, Any], store_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update SAP gift card with Shopify product IDs from all stores
        """
        try:
            card_code = sap_gift_card.get('CardCode')
            if not card_code:
                return {"msg": "failure", "error": "No card code found"}
            
            # Prepare update data for SAP
            update_data = {
                "U_SyncDT": datetime.now().strftime("%Y-%m-%d"),
                "U_SyncTime": "SYNCED"
            }
            
            # Add store-specific IDs
            for store_key, result in store_results.items():
                if result["msg"] == "success":
                    shopify_data = result
                    update_data[f"U_{store_key.upper()}_SID"] = shopify_data["shopify_product_id"].split('/')[-1]
                    update_data[f"U_{store_key.upper()}_VARIANT_SID"] = shopify_data["shopify_variant_id"].split('/')[-1]
                    update_data[f"U_{store_key.upper()}_INVENTORY_SID"] = shopify_data["shopify_inventory_item_id"].split('/')[-1]
            
            # Update the SAP gift card
            result = await sap_client.update_entity('GiftCards', card_code, update_data)
            
            if result["msg"] == "failure":
                logger.error(f"Failed to update SAP gift card {card_code}: {result.get('error')}")
                return {"msg": "failure", "error": result.get("error")}
            
            logger.info(f"Successfully updated SAP gift card {card_code} with Shopify IDs")
            return {"msg": "success"}
            
        except Exception as e:
            logger.error(f"Error updating SAP with Shopify IDs: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def sync_gift_cards(self) -> Dict[str, Any]:
        """
        Main sync function for gift cards
        Handles both creating new gift cards and updating existing ones
        """
        logger.info("Starting gift cards sync from SAP to Shopify")
        
        try:
            # Get gift cards from SAP
            sap_result = await self.get_gift_cards_from_sap()
            if sap_result["msg"] == "failure":
                return sap_result
            
            gift_cards = sap_result["data"]
            if not gift_cards:
                logger.info("No gift cards found in SAP")
                return {"msg": "success", "processed": 0, "success": 0, "errors": 0}
            
            # Get enabled stores
            enabled_stores = multi_store_shopify_client.get_enabled_stores()
            if not enabled_stores:
                logger.error("No enabled Shopify stores found")
                return {"msg": "failure", "error": "No enabled Shopify stores found"}
            
            # Process each gift card
            processed = 0
            success = 0
            errors = 0
            
            for gift_card in gift_cards:
                try:
                    card_code = gift_card.get('CardCode')
                    logger.info(f"Processing gift card: {card_code}")
                    
                    # Process gift card in each store
                    store_results = {}
                    all_stores_success = True
                    
                    for store_key, store_config in enabled_stores.items():
                        logger.info(f"Processing gift card in store: {store_config.name}")
                        
                        # Check if gift card already exists
                        existing_product_id = await self.check_gift_card_exists(store_key, card_code)
                        
                        # Map SAP gift card to Shopify format
                        gift_card_data = self.map_sap_gift_card_to_shopify(gift_card, store_config)
                        
                        if existing_product_id:
                            # Update existing gift card
                            logger.info(f"Updating existing gift card in store {store_key}")
                            store_result = await self.update_gift_card_in_store(store_key, existing_product_id, gift_card_data)
                        else:
                            # Create new gift card
                            logger.info(f"Creating new gift card in store {store_key}")
                            store_result = await self.create_gift_card_in_store(store_key, gift_card_data)
                        
                        store_results[store_key] = store_result
                        
                        if store_result["msg"] == "failure":
                            logger.error(f"Failed to process gift card in store {store_key}: {store_result.get('error')}")
                            all_stores_success = False
                        else:
                            logger.info(f"Successfully processed gift card in store {store_key}")
                    
                    # Update SAP with Shopify IDs if all stores succeeded
                    if all_stores_success:
                        sap_update_result = await self.update_sap_with_shopify_ids(gift_card, store_results)
                        
                        if sap_update_result["msg"] == "failure":
                            logger.error(f"Failed to update SAP with Shopify IDs: {sap_update_result.get('error')}")
                            # Don't count this as a complete failure since gift cards were processed
                        
                        success += 1
                        logger.info(f"Successfully synced gift card {card_code} to all stores")
                    else:
                        errors += 1
                        logger.error(f"Failed to sync gift card {card_code} to all stores")
                    
                except Exception as e:
                    logger.error(f"Error processing gift card {card_code}: {str(e)}")
                    errors += 1
                
                processed += 1
                
                # Add small delay to avoid overwhelming the APIs
                await asyncio.sleep(0.5)
            
            # Log sync event
            log_sync_event(
                sync_type="gift_cards_sap_to_shopify",
                items_processed=processed,
                success_count=success,
                error_count=errors
            )
            
            logger.info(f"Gift cards sync completed: {processed} processed, {success} successful, {errors} errors")
            
            return {
                "msg": "success",
                "processed": processed,
                "success": success,
                "errors": errors
            }
            
        except Exception as e:
            logger.error(f"Error in gift cards sync: {str(e)}")
            return {"msg": "failure", "error": str(e)}

# Create singleton instance
gift_cards_sync = GiftCardsSync() 