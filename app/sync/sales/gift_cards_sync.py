"""
Gift Cards Sync for Sales Module
Syncs gift cards from SAP to Shopify stores
"""

import asyncio
from typing import Dict, Any, List, Optional
from app.services.sap.client import sap_client
from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.core.config import config_settings
from app.utils.logging import logger, log_sync_event
from datetime import datetime


class GiftCardsSalesSync:
    """
    Handles gift cards synchronization from SAP to Shopify stores
    """
    
    def __init__(self):
        self.batch_size = config_settings.sales_gift_cards_batch_size
    
    async def get_gift_cards_from_sap(self) -> Dict[str, Any]:
        """
        Get gift cards from SAP
        """
        try:
            # Get gift cards from SAP
            result = await sap_client.get_entities(
                entity_type='Items',
                filter_query="U_IsGiftCard eq 'Y'",  # Assuming custom field for gift cards
                orderby='ItemCode',
                top=self.batch_size
            )
            
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
                "title": sap_gift_card.get('ItemName', ''),
                "descriptionHtml": sap_gift_card.get('U_GiftCardDescription', ''),
                "productType": "Gift Card",
                "status": "ACTIVE" if sap_gift_card.get('Active') == 'Y' else "DRAFT",
                "tags": self._extract_tags(sap_gift_card),
                "variants": [{
                    "sku": sap_gift_card.get('ItemCode', ''),
                    "price": str(price),
                    "inventoryPolicy": "CONTINUE",
                    "inventoryManagement": "SHOPIFY",
                    "weight": 0.0,
                    "weightUnit": "KILOGRAMS"
                }]
            }
            
            # Add SEO fields
            if sap_gift_card.get('ItemName'):
                gift_card_data["seo"] = {
                    "title": sap_gift_card.get('ItemName'),
                    "description": sap_gift_card.get('U_GiftCardDescription', '')[:255] if sap_gift_card.get('U_GiftCardDescription') else ''
                }
            
            return gift_card_data
            
        except Exception as e:
            logger.error(f"Error mapping SAP gift card to Shopify: {str(e)}")
            raise
    
    def _get_store_price(self, sap_gift_card: Dict[str, Any], price_list: int) -> float:
        """
        Get price for a specific store based on price list
        """
        # Get base price from SAP
        base_price = sap_gift_card.get('Price', 0.0)
        
        # Apply store-specific price adjustments if needed
        if price_list == 1:  # Local store (EGP)
            return base_price
        elif price_list == 7:  # International store (USD)
            # Convert EGP to USD (you might want to use a dynamic exchange rate)
            exchange_rate = 0.032  # Approximate EGP to USD rate
            return base_price * exchange_rate
        
        return base_price
    
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
        custom_fields = ['U_Occasion', 'U_Theme', 'U_Value', 'U_Design']
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
                "shopify_inventory_item_id": product["variants"]["edges"][0]["node"]["inventoryItem"]["id"]
            }
            
        except Exception as e:
            logger.error(f"Error updating gift card in store {store_key}: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def check_gift_card_exists(self, store_key: str, sap_item_code: str) -> Optional[str]:
        """
        Check if gift card already exists in Shopify store
        """
        try:
            # Query to find product by SKU
            query = """
            query getProductBySku($sku: String!) {
                products(first: 1, query: $sku) {
                    edges {
                        node {
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
                    }
                }
            }
            """
            
            result = await multi_store_shopify_client.execute_query(
                store_key, 
                query, 
                {"sku": f"sku:{sap_item_code}"}
            )
            
            if result["msg"] == "failure":
                return None
            
            products = result["data"]["products"]["edges"]
            if products:
                return products[0]["node"]["id"]
            
            return None
            
        except Exception as e:
            logger.error(f"Error checking gift card existence: {str(e)}")
            return None
    
    async def update_sap_with_shopify_ids(self, sap_gift_card: Dict[str, Any], store_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update SAP gift card with Shopify mapping information
        """
        try:
            # Prepare update data
            update_data = {
                "U_ShopifyProductID": store_results.get("shopify_product_id", ""),
                "U_ShopifyVariantID": store_results.get("shopify_variant_id", ""),
                "U_ShopifyHandle": store_results.get("handle", ""),
                "U_LastSyncDate": datetime.now().isoformat()
            }
            
            # Update SAP item
            result = await sap_client.update_entity(
                entity_type='Items',
                entity_id=sap_gift_card['ItemCode'],
                entity_data=update_data
            )
            
            if result["msg"] == "success":
                logger.info(f"Updated SAP gift card mapping: {sap_gift_card['ItemCode']}")
                return {"msg": "success"}
            else:
                logger.error(f"Failed to update SAP gift card mapping: {result.get('error')}")
                return result
                
        except Exception as e:
            logger.error(f"Error updating SAP gift card mapping: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def sync_gift_cards(self) -> Dict[str, Any]:
        """
        Main gift cards sync process
        """
        logger.info("Starting gift cards sync...")
        
        try:
            # Get gift cards from SAP
            sap_result = await self.get_gift_cards_from_sap()
            if sap_result["msg"] == "failure":
                return sap_result
            
            gift_cards = sap_result["data"]
            if not gift_cards:
                logger.info("No gift cards found in SAP")
                return {"msg": "success", "processed": 0, "created": 0, "updated": 0}
            
            # Get enabled stores
            enabled_stores = config_settings.get_enabled_stores()
            if not enabled_stores:
                logger.warning("No enabled stores found")
                return {"msg": "failure", "error": "No enabled stores found"}
            
            total_processed = 0
            total_created = 0
            total_updated = 0
            
            # Process each gift card
            for gift_card in gift_cards:
                try:
                    # Process for each enabled store
                    for store_key, store_config in enabled_stores.items():
                        try:
                            # Check if gift card already exists
                            existing_product_id = await self.check_gift_card_exists(store_key, gift_card['ItemCode'])
                            
                            # Map SAP data to Shopify format
                            shopify_data = self.map_sap_gift_card_to_shopify(gift_card, store_config)
                            
                            if existing_product_id:
                                # Update existing gift card
                                result = await self.update_gift_card_in_store(
                                    store_key, 
                                    existing_product_id, 
                                    shopify_data
                                )
                                if result["msg"] == "success":
                                    total_updated += 1
                                    logger.info(f"Updated gift card in {store_key}: {gift_card['ItemCode']}")
                            else:
                                # Create new gift card
                                result = await self.create_gift_card_in_store(store_key, shopify_data)
                                if result["msg"] == "success":
                                    total_created += 1
                                    logger.info(f"Created gift card in {store_key}: {gift_card['ItemCode']}")
                                    
                                    # Update SAP with Shopify IDs
                                    await self.update_sap_with_shopify_ids(gift_card, result)
                            
                            total_processed += 1
                            
                        except Exception as e:
                            logger.error(f"Error processing gift card {gift_card['ItemCode']} for store {store_key}: {str(e)}")
                            continue
                    
                except Exception as e:
                    logger.error(f"Error processing gift card {gift_card.get('ItemCode', 'Unknown')}: {str(e)}")
                    continue
            
            # Log sync event
            log_sync_event(
                sync_type="sales_gift_cards",
                items_processed=total_processed,
                success_count=total_created + total_updated,
                error_count=len(gift_cards) - (total_created + total_updated)
            )
            
            logger.info(f"Gift cards sync completed. Processed: {total_processed}, Created: {total_created}, Updated: {total_updated}")
            
            return {
                "msg": "success",
                "processed": total_processed,
                "created": total_created,
                "updated": total_updated
            }
            
        except Exception as e:
            logger.error(f"Error in gift cards sync: {str(e)}")
            return {"msg": "failure", "error": str(e)} 