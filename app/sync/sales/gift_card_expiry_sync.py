"""
Gift Card Expiry Sync Module
Queries Shopify for gift cards without expiry dates and updates them to expire 1 year after creation
"""

import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.core.config import config_settings
from app.utils.logging import logger, log_sync_event


class GiftCardExpirySync:
    """
    Handles updating gift card expiry dates for gift cards without expiry dates
    """
    
    def __init__(self):
        self.shopify_client = multi_store_shopify_client
        self.batch_size = config_settings.gift_card_expiry_batch_size
    
    async def get_gift_cards_from_shopify(self, store_key: str, after: Optional[str] = None) -> Dict[str, Any]:
        """
        Get gift cards from Shopify store that need expiry date updates
        Query: NOT expires_on:* status:enabled
        """
        try:
            query = """
            query getGiftCards($first: Int!, $after: String, $query: String!) {
                giftCards(first: $first, after: $after, query: $query) {
                    edges {
                        node {
                            id
                            createdAt
                            expiresOn
                            initialValue {
                                amount
                                currencyCode
                            }
                            enabled
                            lastCharacters
                        }
                    }
                    pageInfo {
                        hasNextPage
                        endCursor
                    }
                }
            }
            """
            
            query_string = "NOT expires_on:* status:enabled"
            
            variables = {
                "first": self.batch_size,
                "after": after,
                "query": query_string
            }
            
            # Add retry logic for GraphQL queries to handle timeouts and rate limiting
            max_retries = 3
            retry_delay = 2  # Start with 2 seconds
            
            for attempt in range(max_retries):
                try:
                    result = await self.shopify_client.execute_query(store_key, query, variables)
                    
                    if result.get("msg") == "success":
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
            
            if result.get("msg") == "failure":
                logger.error(f"Failed to query gift cards from Shopify after {max_retries} attempts: {result.get('error')}")
                return {
                    "msg": "failure",
                    "error": result.get("error"),
                    "gift_cards": [],
                    "has_next_page": False,
                    "end_cursor": None
                }
            
            data = result.get("data", {})
            gift_cards_data = data.get("giftCards", {})
            edges = gift_cards_data.get("edges", [])
            page_info = gift_cards_data.get("pageInfo", {})
            
            gift_cards = []
            for edge in edges:
                gift_cards.append(edge.get("node", {}))
            
            return {
                "msg": "success",
                "gift_cards": gift_cards,
                "has_next_page": page_info.get("hasNextPage", False),
                "end_cursor": page_info.get("endCursor")
            }
            
        except Exception as e:
            logger.error(f"Error querying gift cards from Shopify: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "msg": "failure",
                "error": str(e),
                "gift_cards": [],
                "has_next_page": False,
                "end_cursor": None
            }
    
    async def update_gift_card_expiry(self, store_key: str, gift_card_id: str, expires_on: str) -> Dict[str, Any]:
        """
        Update gift card expiry date using Shopify GraphQL mutation
        """
        try:
            mutation = """
            mutation giftCardUpdate($id: ID!, $input: GiftCardUpdateInput!) {
                giftCardUpdate(id: $id, input: $input) {
                    giftCard {
                        id
                        expiresOn
                        createdAt
                    }
                    userErrors {
                        field
                        message
                    }
                }
            }
            """
            
            variables = {
                "id": gift_card_id,
                "input": {
                    "expiresOn": expires_on
                }
            }
            
            # Add retry logic for GraphQL mutations to handle timeouts and rate limiting
            max_retries = 3
            retry_delay = 2  # Start with 2 seconds
            
            for attempt in range(max_retries):
                try:
                    result = await self.shopify_client.execute_query(store_key, mutation, variables)
                    
                    if result.get("msg") == "success":
                        # Check for user errors (these are not retryable)
                        data = result.get("data", {})
                        gift_card_update = data.get("giftCardUpdate", {})
                        user_errors = gift_card_update.get("userErrors", [])
                        
                        if user_errors:
                            error_messages = [error.get("message", "Unknown error") for error in user_errors]
                            return {
                                "msg": "failure",
                                "error": "; ".join(error_messages)
                            }
                        
                        if gift_card_update.get("giftCard"):
                            return {
                                "msg": "success",
                                "gift_card": gift_card_update["giftCard"]
                            }
                        
                        return {
                            "msg": "failure",
                            "error": "No gift card returned from mutation"
                        }
                    else:
                        logger.warning(f"GraphQL mutation attempt {attempt + 1}/{max_retries} failed: {result.get('error', 'Unknown error')}")
                        
                        if attempt < max_retries - 1:  # Don't sleep on last attempt
                            logger.info(f"Retrying mutation in {retry_delay} seconds...")
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                        
                except Exception as e:
                    logger.error(f"GraphQL mutation attempt {attempt + 1}/{max_retries} exception: {str(e)}")
                    if attempt < max_retries - 1:
                        logger.info(f"Retrying mutation in {retry_delay} seconds...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        result = {"msg": "failure", "error": f"All {max_retries} attempts failed: {str(e)}"}
            
            # If we get here, all retries failed
            if result.get("msg") == "failure":
                return {
                    "msg": "failure",
                    "error": result.get("error", "Unknown error")
                }
            
            return {
                "msg": "failure",
                "error": "No gift card returned from mutation"
            }
            
        except Exception as e:
            logger.error(f"Error updating gift card expiry: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "msg": "failure",
                "error": str(e)
            }
    
    def calculate_expiry_date(self, created_at: str) -> str:
        """
        Calculate expiry date as 1 year after creation date
        Returns date in YYYY-MM-DD format
        """
        try:
            # Parse the created_at date (format: "2024-01-15T10:30:00Z")
            created_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            
            # Add 1 year
            expiry_date = created_date + timedelta(days=365)
            
            # Return in YYYY-MM-DD format
            return expiry_date.strftime("%Y-%m-%d")
            
        except Exception as e:
            logger.error(f"Error calculating expiry date from {created_at}: {str(e)}")
            # Fallback: use current date + 1 year
            return (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
    
    async def sync_gift_card_expiry(self, store_key: str) -> Dict[str, Any]:
        """
        Main sync method to update gift card expiry dates
        """
        logger.info(f"Starting gift card expiry sync for store: {store_key}")
        
        processed = 0
        success = 0
        errors = 0
        error_details = []
        
        after = None
        has_next_page = True
        
        while has_next_page:
            # Get batch of gift cards
            result = await self.get_gift_cards_from_shopify(store_key, after)
            
            if result.get("msg") == "failure":
                logger.error(f"Failed to get gift cards: {result.get('error')}")
                errors += 1
                error_details.append(f"Query error: {result.get('error')}")
                break
            
            gift_cards = result.get("gift_cards", [])
            
            if not gift_cards:
                logger.info("No gift cards found that need expiry date updates")
                break
            
            logger.info(f"Processing {len(gift_cards)} gift cards...")
            
            # Process each gift card
            for gift_card in gift_cards:
                processed += 1
                gift_card_id = gift_card.get("id")
                created_at = gift_card.get("createdAt")
                enabled = gift_card.get("enabled", False)
                last_characters = gift_card.get("lastCharacters", "Unknown")
                
                if not gift_card_id:
                    logger.warning("Gift card missing ID, skipping")
                    errors += 1
                    continue
                
                if not created_at:
                    logger.warning(f"Gift card {gift_card_id} missing createdAt, skipping")
                    errors += 1
                    continue
                
                # Verify gift card is enabled (should always be true based on query, but check for safety)
                if not enabled:
                    logger.warning(f"Gift card {last_characters} is not enabled, skipping")
                    errors += 1
                    continue
                
                # Calculate expiry date (1 year after creation)
                expires_on = self.calculate_expiry_date(created_at)
                
                logger.info(f"Updating gift card {last_characters} (ID: {gift_card_id}) - Setting expiry to {expires_on}")
                
                # Update gift card expiry
                update_result = await self.update_gift_card_expiry(store_key, gift_card_id, expires_on)
                
                if update_result.get("msg") == "success":
                    success += 1
                    logger.info(f"✅ Successfully updated gift card {last_characters} expiry to {expires_on}")
                else:
                    errors += 1
                    error_msg = update_result.get("error", "Unknown error")
                    error_details.append(f"Gift card {last_characters}: {error_msg}")
                    logger.error(f"❌ Failed to update gift card {last_characters}: {error_msg}")
                
                # Small delay between updates to avoid rate limiting
                await asyncio.sleep(0.5)
            
            # Check if there are more pages
            has_next_page = result.get("has_next_page", False)
            after = result.get("end_cursor")
            
            if has_next_page:
                logger.info(f"More gift cards available, fetching next page...")
        
        result_summary = {
            "msg": "success" if errors == 0 else "partial_success" if success > 0 else "failure",
            "processed": processed,
            "success": success,
            "errors": errors
        }
        
        if error_details:
            result_summary["error_details"] = error_details[:10]  # Limit to first 10 errors
        
        logger.info(f"Gift card expiry sync completed - Processed: {processed}, Success: {success}, Errors: {errors}")
        
        return result_summary
    
    async def sync_gift_card_expiry_all_stores(self) -> Dict[str, Any]:
        """
        Sync gift card expiry dates for all enabled stores
        """
        enabled_stores = config_settings.get_enabled_stores()
        
        if not enabled_stores:
            return {
                "msg": "failure",
                "error": "No enabled stores found"
            }
        
        all_results = {}
        total_processed = 0
        total_success = 0
        total_errors = 0
        
        for store_key, store_config in enabled_stores.items():
            logger.info(f"Processing gift card expiry sync for store: {store_key}")
            
            result = await self.sync_gift_card_expiry(store_key)
            all_results[store_key] = result
            
            total_processed += result.get("processed", 0)
            total_success += result.get("success", 0)
            total_errors += result.get("errors", 0)
        
        return {
            "msg": "success" if total_errors == 0 else "partial_success" if total_success > 0 else "failure",
            "results": all_results,
            "processed": total_processed,
            "success": total_success,
            "errors": total_errors
        }

