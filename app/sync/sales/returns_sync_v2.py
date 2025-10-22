"""
Returns Sync V2 - Handle refunds by creating gift cards and new invoices
"""

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Any, Optional

from app.services.shopify.multi_store_client import MultiStoreShopifyClient
from app.services.sap.client import SAPClient
from app.core.config import config_settings
from app.sync.sales.sap_operations import SAPOperations

logger = logging.getLogger(__name__)

class ReturnsSyncV2:
    def __init__(self):
        self.shopify_client = MultiStoreShopifyClient()
        self.sap_client = SAPClient()
        self.sap_operations = SAPOperations(self.sap_client)
        self.config = config_settings
        
    async def sync_returns(self):
        """
        Main method to sync returns by creating gift cards and new invoices
        """
        try:
            logger.info("Starting returns sync V2 - Gift card approach")
            
            # Get all stores from configuration
            stores = self.config.get_enabled_stores()
            if not stores:
                logger.warning("No stores found in configuration")
                return {"msg": "failure", "error": "No stores found"}
            
            total_processed = 0
            total_successful = 0
            total_errors = 0
            
            for store_key, store_config in stores.items():
                try:
                    logger.info(f"Processing returns for store: {store_key}")
                    # Convert store_config to dict format for compatibility
                    store_config_dict = {
                        "name": store_config.name,
                        "shop_url": store_config.shop_url,
                        "access_token": store_config.access_token,
                        "api_version": store_config.api_version,
                        "timeout": store_config.timeout,
                        "currency": store_config.currency,
                        "price_list": store_config.price_list,
                        "enabled": store_config.enabled
                    }
                    
                    result = await self._process_store_returns(store_key, store_config_dict)
                except Exception as e:
                    logger.error(f"ERROR in store processing loop for {store_key}: {str(e)}")
                    continue
                if result:
                    total_processed += result.get("processed", 0)
                    total_successful += result.get("successful", 0)
                    total_errors += result.get("errors", 0)
            
            logger.info(f"Returns sync V2 completed. Processed: {total_processed}, Success: {total_successful}, Errors: {total_errors}")
            
            return {
                "msg": "success",
                "processed": total_processed,
                "successful": total_successful,
                "errors": total_errors
            }
                
        except Exception as e:
            logger.error(f"Error in returns sync V2: {str(e)}")
            return {
                "msg": "failure",
                "error": str(e)
            }

    async def get_orders_from_shopify(self, store_key: str) -> Dict[str, Any]:
        """
        Get refunded orders from Shopify store that need to be processed
        """
        import asyncio
        
        max_retries = 3
        base_delay = 2  # seconds
        
        for attempt in range(max_retries):
            try:
                # Query for refunded orders that need processing
                filter_query = (
                    f"""tag:returntest 
                    financial_status:refunded OR financial_status:partially_refunded OR return_status:RETURNED
                    tag:sap_invoice_synced 
                    tag:sap_payment_synced 
                    -tag:sap_return_synced 
                    created_at:>={self._get_date_filter()}"""
                )
                
                logger.info(f"Fetching refunded orders with filter: {filter_query} (attempt {attempt + 1}/{max_retries})")
                
                # Use the same GraphQL query structure as orders sync
                query = """
                query getOrders($first: Int!, $after: String, $query: String) {
                    orders(first: $first, after: $after, sortKey: CREATED_AT, reverse: true, query: $query) {
                        edges {
                            node {
                                id
                                name
                                createdAt
                                displayFinancialStatus
                                displayFulfillmentStatus
                                returnStatus
                                sourceName
                                sourceIdentifier
                                totalPriceSet {
                                    shopMoney {
                                        amount
                                        currencyCode
                                    }
                                }
                                subtotalPriceSet {
                                    shopMoney {
                                        amount
                                        currencyCode
                                    }
                                }
                                totalShippingPriceSet {
                                    shopMoney {
                                        amount
                                        currencyCode
                                    }
                                }
                                customer {
                                    id
                                    firstName
                                    lastName
                                    email
                                    phone
                                    addresses {
                                        address1
                                        address2
                                        city
                                        province
                                        zip
                                        country
                                        phone
                                    }
                                }
                                retailLocation {
                                    id
                                }
                                metafields(first: 10) {
                                    edges {
                                        node {
                                            namespace
                                            key
                                            value
                                        }
                                    }
                                }
                                tags
                                shippingAddress {
                                    address1
                                    address2
                                    city
                                    province
                                    zip
                                    country
                                    phone
                                    firstName
                                    lastName
                                    company
                                }
                                billingAddress {
                                    address1
                                    address2
                                    city
                                    province
                                    zip
                                    country
                                    phone
                                    firstName
                                    lastName
                                    company
                                }
                                lineItems(first: 50) {
                                    edges {
                                        node {
                                            id
                                            name
                                            quantity
                                            sku
                                            isGiftCard
                                            currentQuantity
                                            originalUnitPriceSet {
                                                shopMoney {
                                                    amount
                                                    currencyCode
                                                }
                                            }
                                            discountedUnitPriceSet {
                                                shopMoney {
                                                    amount
                                                    currencyCode
                                                }
                                            }
                                            variant {
                                                id
                                                sku
                                                price
                                                compareAtPrice
                                                product {
                                                    id
                                                    title
                                                }
                                            }
                                        }
                                    }
                                }
                                transactions(first: 10) {
                                    id
                                    kind
                                    status
                                    gateway
                                    amountSet {
                                        shopMoney {
                                            amount
                                            currencyCode
                                        }
                                    }
                                    processedAt
                                    receiptJson
                                }
                            }
                        }
                        pageInfo {
                            hasNextPage
                            endCursor
                        }
                    }
                }
                """
                
                # Execute GraphQL query using the existing infrastructure
                result = await self.shopify_client.execute_query(
                    store_key=store_key,
                    query=query,
                    variables={"first": 10, "after": None, "query": filter_query}
                )
                
                logger.info(f"DEBUG: GraphQL result msg: {result.get('msg')}")
                logger.info(f"DEBUG: GraphQL result keys: {list(result.keys())}")
                
                if result.get("msg") == "success":
                    orders_data = result.get("data", {}).get("orders", {}).get("edges", [])
                    orders = [edge["node"] for edge in orders_data]
                    
                    logger.info(f"Retrieved {len(orders)} refunded orders from store {store_key}")
                    
                    return {
                        "msg": "success",
                        "data": orders
                    }
                else:
                    # Query failed, check if we should retry
                    error_msg = result.get('error', 'Unknown error')
                    logger.warning(f"Failed to fetch orders from store {store_key} (attempt {attempt + 1}/{max_retries}): {error_msg}")
                    
                    if attempt < max_retries - 1:  # Don't sleep on the last attempt
                        delay = base_delay * (2 ** attempt)  # Exponential backoff
                        logger.info(f"Retrying in {delay} seconds...")
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"All {max_retries} attempts failed for store {store_key}")
                        return {"msg": "failure", "error": error_msg}
                
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"Exception getting orders from store {store_key} (attempt {attempt + 1}/{max_retries}): {error_msg}")
                
                if attempt < max_retries - 1:  # Don't sleep on the last attempt
                    delay = base_delay * (2 ** attempt)  # Exponential backoff
                    logger.info(f"Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"All {max_retries} attempts failed for store {store_key}")
                    return {"msg": "failure", "error": error_msg}
        
        # This should never be reached, but just in case
        return {"msg": "failure", "error": "Max retries exceeded"}

    async def _process_store_returns(self, store_key: str, store_config: Dict[str, Any]):
        """
        Process returns for a specific store
        """
        try:
            # Get orders from this store
            orders_result = await self.get_orders_from_shopify(store_key)
            if orders_result["msg"] == "failure":
                logger.error(f"Failed to get orders from store {store_key}: {orders_result.get('error')}")
                return {"processed": 0, "successful": 0, "errors": 1}
            
            orders = orders_result["data"]
            if not orders:
                logger.info(f"No refunded orders found for store {store_key}")
                return {"processed": 0, "successful": 0, "errors": 0}
                
            logger.info(f"Found {len(orders)} refunded orders for store {store_key}")
            
            # BREAKPOINT: Check orders retrieved
            # import pdb; pdb.set_trace()
            
            processed = 0
            successful = 0
            errors = 0
            
            for order in orders:
                #BREAKPOINT: Check each order being processed
                #import pdb; pdb.set_trace()
                try:
                    await self._process_refunded_order(order, store_key, store_config)
                    successful += 1
                except Exception as e:
                    logger.error(f"Error processing order {order.get('name', '')}: {str(e)}")
                    errors += 1
                processed += 1
            
            return {"processed": processed, "successful": successful, "errors": errors}
                
        except Exception as e:
            logger.error(f"Error processing returns for store {store_key}: {str(e)}")
            return {"processed": 0, "successful": 0, "errors": 1}

    async def _process_refunded_order(self, order: Dict[str, Any], store_key: str, store_config: Dict[str, Any]):
        """
        Process a single refunded order
        """
        try:
            order_id = order.get("id", "")
            order_name = order.get("name", "")
            
            logger.info(f"Processing refunded order: {order_name} (ID: {order_id})")
            
            # Get warehouse code based on order type (POS vs Web)
            warehouse_code = "ONL"  # Default for online
            location_id = None
            
            # Check if this is a POS order first
            source_name = order.get("sourceName", "").lower()
            is_pos_order = source_name == "pos"
            
            if is_pos_order:
                # For POS orders, use retailLocation field
                retail_location = order.get("retailLocation", {})
                if retail_location and retail_location.get("id"):
                    # Extract location ID from GraphQL ID (e.g., "gid://shopify/Location/72406990914" -> "72406990914")
                    location_gid = retail_location["id"]
                    location_id = location_gid.split("/")[-1] if "/" in location_gid else location_gid
                    logger.info(f"Found retail location ID for POS order: {location_id}")
                    
                    # Get location mapping to get the location_cc (not warehouse code)
                    location_mapping = self.config.get_location_mapping_for_location(store_key, location_id)
                    warehouse_code = location_mapping.get('location_cc', 'ONL')  # Use location_cc for U_Location field
                    logger.info(f"Using location code '{warehouse_code}' for POS location '{location_id}'")
                else:
                    logger.warning("No retail location found in POS order, using default location code 'ONL'")
            else:
                # For web/online orders, use default location code
                logger.info("Web/online order detected, using default location code 'ONL'")
            
            # Determine if this is a POS order or online order
            is_pos_order = self._is_pos_order(order, store_key)
            
            if is_pos_order:
                logger.info(f"Processing POS order {order_name} - checking for gift card line items")
                # For POS orders, look for gift card line items (sku: null, variant: null)
                store_credit_refunds = self._extract_pos_gift_card_refunds(order)
            else:
                logger.info(f"Processing online order {order_name} - checking for store credit transactions")
                # For online orders, look for store credit transactions
                store_credit_refunds = self._extract_store_credit_refunds(order)
            
            if not store_credit_refunds:
                logger.info(f"No store credit refunds found for order {order_name}")
                return
                
            logger.info(f"Found {len(store_credit_refunds)} store credit refunds for order {order_name}")
            
            # Get SAP document entries from order tags (needed for payment method)
            sap_doc_entries = self._extract_sap_doc_entries(order)
            
            if not sap_doc_entries:
                logger.warning(f"No SAP document entries found in tags for order {order_name}")
                return
            
            if is_pos_order:
                logger.info(f"Processing POS order {order_name} - looking for existing gift cards")
                # For POS orders, find existing gift cards created after order date
                gift_cards = await self._get_gift_cards_for_order(order_id.split("/")[-1], order.get("createdAt", ""))
                
                if not gift_cards:
                    logger.error(f"No gift cards found for POS order {order_name}")
                    return
                
                # Match gift card by amount (store credit refund amount)
                total_refund_amount = sum(refund["amount"] for refund in store_credit_refunds)
                matching_gift_card = None
                
                for gift_card in gift_cards:
                    if abs(gift_card["initial_value"] - total_refund_amount) < 0.01:
                        matching_gift_card = gift_card
                        break
                
                if not matching_gift_card:
                    logger.error(f"No matching gift card found for POS order {order_name} with amount {total_refund_amount}")
                    return
                
                gift_card_id = matching_gift_card["id"]
                logger.info(f"Found matching gift card {gift_card_id} for POS order {order_name}")
            else:
                logger.info(f"Processing online order {order_name} - checking for existing gift card")
                # For online orders, check if gift card already exists
                existing_gift_card_id = self._get_existing_gift_card_id(order)
                
                if existing_gift_card_id:
                    logger.info(f"Found existing gift card {existing_gift_card_id} for order {order_name}")
                    gift_card_id = existing_gift_card_id
                else:
                    # Create gift card in Shopify
                    gift_card_id = await self._create_shopify_gift_card(order, store_credit_refunds, store_key)
                    
                    if not gift_card_id:
                        logger.error(f"Failed to create gift card for order {order_name}")
                        return
                    
                    # Add gift card tag to prevent duplicate creation
                    await self._add_order_tag_with_retry(order_id, f"giftcard_{gift_card_id}", store_key)
            
            # Always check and cancel original SAP documents if needed
            original_payment_details = await self._check_and_cancel_original_documents(sap_doc_entries, order_name)
            
            if not original_payment_details:
                logger.error(f"Failed to process original documents for order {order_name}")
                return
            
            # Check if invoice already exists
            existing_invoice_entry = self._get_existing_invoice_entry(order)
            
            if existing_invoice_entry:
                logger.info(f"Found existing invoice {existing_invoice_entry} for order {order_name}, skipping invoice creation")
                
                order_created_at = order.get("createdAt", "")
                from datetime import datetime
                parsed_date = datetime.fromisoformat(order_created_at.replace('Z', '+00:00'))
                doc_date = parsed_date.strftime("%Y-%m-%d")
                # Create a mock invoice result with existing DocEntry
                new_invoice_result = {
                    "msg": "success",
                    "sap_doc_entry": existing_invoice_entry,
                    "sap_doc_total": sum(refund["amount"] for refund in store_credit_refunds),
                    "sap_doc_date": doc_date
                }
            else:
                # Create new invoice in SAP for gift card
                new_invoice_result = await self._create_gift_card_invoice(order, gift_card_id, original_payment_details, store_key, store_config, store_credit_refunds, warehouse_code)
            
            if new_invoice_result["msg"] == "success":
                # Add invoice success tags immediately (only if not already tagged)
                if not existing_invoice_entry:
                    await self._add_order_tag_with_retry(order_id, "sap_giftcard_invoice_synced", store_key)
                    await self._add_order_tag_with_retry(order_id, f"sap_giftcard_invoice_{new_invoice_result.get('sap_doc_entry')}", store_key)
                    logger.info(f"✅ Invoice created and tagged for order {order_name}")
                else:
                    logger.info(f"✅ Using existing invoice {existing_invoice_entry} for order {order_name}")
                
                # Check if payment already exists
                existing_payment_entry = self._get_existing_payment_entry(order)
                
                if existing_payment_entry:
                    logger.info(f"Found existing payment {existing_payment_entry} for order {order_name}, skipping payment creation")
                    # Create a mock payment result with existing DocEntry
                    payment_result = {
                        "msg": "success",
                        "sap_doc_entry": existing_payment_entry
                    }
                else:
                    # Create incoming payment for the new invoice using original payment details
                    payment_result = await self._create_gift_card_payment(new_invoice_result, original_payment_details, order_name, order, store_key)
                
                if payment_result and payment_result.get("msg") == "success":
                    # Add payment success tags immediately (only if not already tagged)
                    if not existing_payment_entry:
                        await self._add_order_tag_with_retry(order_id, "sap_giftcard_payment_synced", store_key)
                        await self._add_order_tag_with_retry(order_id, f"sap_giftcard_payment_{payment_result.get('sap_doc_entry')}", store_key)
                        logger.info(f"✅ Payment created and tagged for order {order_name}")
                    else:
                        logger.info(f"✅ Using existing payment {existing_payment_entry} for order {order_name}")
                    
                    # Tag order as processed ONLY if payment was successful
                    await self._add_order_tag_with_retry(order_id, "sap_return_synced", store_key)
                    logger.info(f"✅ Successfully processed return for order {order_name}")
                else:
                    # Add payment failure tag immediately - DO NOT add sap_return_synced tag
                    await self._add_order_tag_with_retry(order_id, "sap_giftcard_payment_failed", store_key)
                    logger.error(f"Failed to create gift card payment for order {order_name}")
                    logger.error(f"Return processing failed for order {order_name} - payment creation failed")
            else:
                # Add invoice failure tag immediately
                await self._add_order_tag_with_retry(order_id, "sap_giftcard_invoice_failed", store_key)
                logger.error(f"Failed to create gift card invoice for order {order_name}")
                
        except Exception as e:
            logger.error(f"Error processing refunded order {order.get('name', '')}: {str(e)}")

    def _extract_store_credit_refunds(self, order: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract store credit refund transactions from order
        """
        store_credit_refunds = []
        
        transactions = order.get("transactions", [])
        
        for transaction in transactions:
            if (transaction.get("kind") == "REFUND" and 
                transaction.get("gateway") == "shopify_store_credit" and
                transaction.get("status") == "SUCCESS"):
                
                amount = float(transaction["amountSet"]["shopMoney"]["amount"])
                store_credit_refunds.append({
                    "transaction_id": transaction["id"],
                    "amount": amount,
                    "currency": transaction["amountSet"]["shopMoney"]["currencyCode"],
                    "processed_at": transaction["processedAt"]
                })
                
        return store_credit_refunds
    
    def _extract_pos_gift_card_refunds(self, order: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract gift card refunds from POS order line items (sku: null, variant: null)
        """
        store_credit_refunds = []
        line_items = order.get("lineItems", {}).get("edges", [])
        
        for item_edge in line_items:
            item = item_edge.get("node", {})
            
            # Check if this is a gift card line item using the isGiftCard field
            if (item.get("isGiftCard", False) and 
                item.get("sku") is None and 
                item.get("variant") is None):
                
                amount = float(item.get("originalUnitPriceSet", {}).get("shopMoney", {}).get("amount", 0))
                if amount > 0:
                    store_credit_refunds.append({
                        "amount": amount,
                        "currency": item.get("originalUnitPriceSet", {}).get("shopMoney", {}).get("currencyCode", "EGP"),
                        "line_item_id": item.get("id"),
                        "quantity": item.get("quantity", 1)
                    })
                    logger.info(f"Found POS gift card refund: {amount} {item.get('originalUnitPriceSet', {}).get('shopMoney', {}).get('currencyCode', 'EGP')}")
        
        return store_credit_refunds

    def _extract_sap_doc_entries(self, order: Dict[str, Any]) -> Dict[str, str]:
        """
        Extract SAP document entries from order tags
        """
        tags = order.get("tags", [])
        doc_entries = {}
        
        for tag in tags:
            if tag.startswith("sap_invoice_") and not tag.endswith("_synced"):
                # Extract invoice DocEntry (e.g., "sap_invoice_23163" -> "23163")
                doc_entries["invoice"] = tag.replace("sap_invoice_", "")
            elif tag.startswith("sap_payment_") and not tag.endswith("_synced"):
                # Extract payment DocEntry (e.g., "sap_payment_22349" -> "22349")
                doc_entries["payment"] = tag.replace("sap_payment_", "")
                
        return doc_entries

    def _get_existing_gift_card_id(self, order: Dict[str, Any]) -> Optional[str]:
        """
        Check if order already has a gift card created
        """
        tags = order.get("tags", [])
        
        for tag in tags:
            if tag.startswith("giftcard_"):
                # Extract gift card ID from tag (e.g., "giftcard_550361628738" -> "550361628738")
                return tag.replace("giftcard_", "")
        
        return None
    
    def _get_existing_invoice_entry(self, order: Dict[str, Any]) -> Optional[str]:
        """
        Check if order already has a gift card invoice DocEntry in tags
        """
        tags = order.get("tags", [])
        for tag in tags:
            if tag.startswith("sap_giftcard_invoice_") and tag != "sap_giftcard_invoice_synced":
                return tag.replace("sap_giftcard_invoice_", "")
        return None
    
    def _get_existing_payment_entry(self, order: Dict[str, Any]) -> Optional[str]:
        """
        Check if order already has a gift card payment DocEntry in tags
        """
        tags = order.get("tags", [])
        for tag in tags:
            if tag.startswith("sap_giftcard_payment_") and tag != "sap_giftcard_payment_synced":
                return tag.replace("sap_giftcard_payment_", "")
        return None
    
    def _is_pos_order(self, order: Dict[str, Any], store_key: str) -> bool:
        """
        Check if order is from a POS/store location using sourceName
        """
        try:
            # Check sourceName first - this is the most reliable indicator
            source_name = order.get("sourceName", "").lower()
            if source_name == "pos":
                logger.info("POS order detected based on sourceName")
                return True
            elif source_name in ["web", "online", "shopify"]:
                logger.info("Web/online order detected based on sourceName")
                return False
            
            # Fallback to original method if sourceName is not clear
            logger.info("Source name not clearly identified, using original location mapping method")
            from order_location_mapper import OrderLocationMapper
            location_analysis = OrderLocationMapper.analyze_order_source(order, store_key)
            return location_analysis.get("is_pos_order", False)
            
        except Exception as e:
            logger.error(f"Error determining order location type: {str(e)}")
            return False

    async def _get_gift_cards_for_order(self, order_id: str, order_created_at: str) -> List[Dict[str, Any]]:
        """
        Query Shopify Gift Cards API to get gift cards created for this order (for POS orders)
        """
        try:
            order_date = order_created_at.split("T")[0] if "T" in order_created_at else order_created_at
            query = """
            query getGiftCards($query: String!) {
                giftCards(first: 50, query: $query) {
                    edges {
                        node {
                            id   
                            order {
                                id
                            }     
                            initialValue {
                                amount
                                currencyCode
                            }
                            createdAt
                            expiresOn
                            customer {
                                id
                                email
                            }
                        }
                    }
                }
            }
            """
            query_string = f"createdAt:>={order_date}"
            
            # Add retry logic for GraphQL queries
            max_retries = 3
            retry_delay = 2
            
            for attempt in range(max_retries):
                try:
                    result = await self.shopify_client.execute_query("local", query, {"query": query_string})
                    
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
            
            if result["msg"] == "failure":
                logger.error(f"Failed to query gift cards: {result.get('error')}")
                return []
            
            gift_cards = []
            for edge in result["data"]["giftCards"]["edges"]:
                gift_card = edge["node"]
                # Check if this gift card belongs to our order
                order_info = gift_card.get("order")
                if order_info and order_info.get("id") == f"gid://shopify/Order/{order_id}":
                    gift_cards.append({
                        "id": gift_card["id"],
                        "order_id": order_id,
                        "initial_value": float(gift_card["initialValue"]["amount"]),
                        "currency": gift_card["initialValue"]["currencyCode"],
                        "created_at": gift_card["createdAt"],
                        "expires_on": gift_card.get("expiresOn"),
                        "customer_email": gift_card.get("customer", {}).get("email", "")
                    })
            
            logger.info(f"Found {len(gift_cards)} gift cards for order {order_id}")
            return gift_cards
            
        except Exception as e:
            logger.error(f"Error querying gift cards: {str(e)}")
            return []

    async def _prepare_gift_card_for_invoice(self, gift_card_id: str, amount: float, customer_card_code: str, warehouse_code: str = "ONL") -> Optional[str]:
        """
        Prepare gift card data for invoice line without creating SAP GiftCards entity entry
        """
        try:
            # Extract numeric ID from Shopify gift card ID
            numeric_id = gift_card_id.split("/")[-1] if "/" in gift_card_id else gift_card_id
            
            # Skip SAP GiftCards entity creation - just prepare data for invoice line
            logger.info(f"Preparing gift card data for invoice line: {numeric_id} - Amount: {amount}")
            return numeric_id
                
        except Exception as e:
            logger.error(f"Error preparing gift card data: {str(e)}")
            return None

    async def _check_gift_card_exists_in_sap(self, gift_card_id: str) -> bool:
        """
        Check if a gift card already exists in SAP GiftCards entity
        """
        try:
            result = await self.sap_client._make_request(
                method='GET',
                endpoint=f'GiftCards({gift_card_id})'
            )
            
            if result["msg"] == "success":
                logger.info(f"Gift card {gift_card_id} exists in SAP")
                return True
            else:
                logger.info(f"Gift card {gift_card_id} does not exist in SAP")
                return False
                
        except Exception as e:
            logger.error(f"Error checking gift card existence in SAP: {str(e)}")
            return False

    async def _check_and_cancel_original_documents(self, sap_doc_entries: Dict[str, str], order_name: str) -> Optional[Dict[str, Any]]:
        """
        Check and cancel original SAP documents if needed, return payment details for new payment
        """
        try:
            payment_details = None
            
            # Check and cancel incoming payment if needed
            if "payment" in sap_doc_entries:
                payment_entry = sap_doc_entries["payment"]
                logger.info(f"Checking incoming payment {payment_entry} for order {order_name}")
                
                # Get payment details first
                payment_result = await self.sap_client._make_request(
                    method='GET',
                    endpoint=f'IncomingPayments({payment_entry})',
                    params={
                        "$select": "TransferAccount,CashAccount,CardCode,CashSum,TransferSum,Series,Cancelled,PaymentCreditCards"
                    }
                )
                
                if payment_result["msg"] == "success":
                    payment_data = payment_result["data"]
                    
                    # Check if payment is already cancelled
                    if payment_data.get("Cancelled") == "tNO":
                        logger.info(f"Cancelling incoming payment {payment_entry}")
                        
                        cancel_result = await self.sap_client._make_request(
                            method='POST',
                            endpoint=f'IncomingPayments({payment_entry})/Cancel',
                            data={}
                        )
                        
                        if cancel_result["msg"] == "success":
                            logger.info(f"✅ Successfully cancelled incoming payment {payment_entry}")
                        else:
                            logger.error(f"Failed to cancel incoming payment {payment_entry}: {cancel_result.get('error')}")
                            return None
                    else:
                        logger.info(f"Incoming payment {payment_entry} is already cancelled")
                    
                    # Extract payment details for new payment
                    payment_details = {
                        "TransferAccount": payment_data.get("TransferAccount"),
                        "CashAccount": payment_data.get("CashAccount"),
                        "CardCode": payment_data.get("CardCode"),
                        "CashSum": payment_data.get("CashSum", 0),
                        "TransferSum": payment_data.get("TransferSum", 0),
                        "Series": payment_data.get("Series"),
                        "PaymentCreditCards": payment_data.get("PaymentCreditCards")
                    }
                else:
                    logger.error(f"Failed to get payment details: {payment_result.get('error')}")
                    return None
            
            # Check and cancel invoice if needed
            if "invoice" in sap_doc_entries:
                invoice_entry = sap_doc_entries["invoice"]
                logger.info(f"Checking invoice {invoice_entry} for order {order_name}")
                
                # Get invoice details
                invoice_result = await self.sap_client._make_request(
                    method='GET',
                    endpoint=f'Invoices({invoice_entry})',
                    params={
                        "$select": "Cancelled"
                    }
                )
                
                if invoice_result["msg"] == "success":
                    invoice_data = invoice_result["data"]
                    
                    # Check if invoice is already cancelled
                    if invoice_data.get("Cancelled") == "tNO":
                        logger.info(f"Cancelling invoice {invoice_entry}")
                        
                        cancel_result = await self.sap_client._make_request(
                            method='POST',
                            endpoint=f'Invoices({invoice_entry})/Cancel',
                            data={}
                        )
                        
                        if cancel_result["msg"] == "success":
                            logger.info(f"✅ Successfully cancelled invoice {invoice_entry}")
                        else:
                            logger.error(f"Failed to cancel invoice {invoice_entry}: {cancel_result.get('error')}")
                            return None
                    else:
                        logger.info(f"Invoice {invoice_entry} is already cancelled")
                else:
                    logger.error(f"Failed to get invoice details: {invoice_result.get('error')}")
                    return None
            
            return payment_details
            
        except Exception as e:
            logger.error(f"Error checking and cancelling original documents: {str(e)}")
            return None

    async def _cancel_sap_documents(self, sap_doc_entries: Dict[str, str], order_name: str):
        """
        Cancel SAP documents (payment first, then invoice)
        """
        try:
            # Cancel incoming payment first
            if "payment" in sap_doc_entries:
                payment_entry = sap_doc_entries["payment"]
                logger.info(f"Cancelling incoming payment {payment_entry} for order {order_name}")
                
                cancel_payment_result = await self.sap_client._make_request(
                    method='POST',
                    endpoint=f'IncomingPayments({payment_entry})/Cancel',
                    data={}
                )
                
                if cancel_payment_result["msg"] == "success":
                    logger.info(f"✅ Successfully cancelled incoming payment {payment_entry}")
                else:
                    logger.error(f"Failed to cancel incoming payment {payment_entry}: {cancel_payment_result.get('error')}")
                    return False
                    
            # Cancel invoice
            if "invoice" in sap_doc_entries:
                invoice_entry = sap_doc_entries["invoice"]
                logger.info(f"Cancelling invoice {invoice_entry} for order {order_name}")
                
                cancel_invoice_result = await self.sap_client._make_request(
                    method='POST',
                    endpoint=f'Invoices({invoice_entry})/Cancel',
                    data={}
                )
                
                if cancel_invoice_result["msg"] == "success":
                    logger.info(f"✅ Successfully cancelled invoice {invoice_entry}")
                else:
                    logger.error(f"Failed to cancel invoice {invoice_entry}: {cancel_invoice_result.get('error')}")
                    return False
                    
            return True
            
        except Exception as e:
            logger.error(f"Error cancelling SAP documents for order {order_name}: {str(e)}")
            return False

    async def _create_shopify_gift_card(self, order: Dict[str, Any], store_credit_refunds: List[Dict[str, Any]], store_key: str) -> Optional[str]:
        """
        Create gift card in Shopify for the customer
        """
        try:
            customer_id = order.get("customer", {}).get("id")
            if not customer_id:
                logger.error("No customer ID found for gift card creation")
                return None
            
            # Add note with order reference
            order_name = order.get("name", "")
            order_id = order.get("id", "")
            note = f"Refund for order {order_name.replace('#', '')} (ID: {order_id.split('/')[-1]})"
                
            # Calculate total store credit amount
            total_amount = sum(refund["amount"] for refund in store_credit_refunds)
            
            # Prepare gift card mutation
            mutation = """
            mutation giftCardCreate($input: GiftCardCreateInput!) {
                giftCardCreate(input: $input) {
                    giftCard {
                        id
                        expiresOn
                        initialValue {
                            amount
                        }
                        customer {
                            id
                        }
                    }
                    userErrors {
                        message
                        field
                        code
                    }
                }
            }
            """
            
            variables = {
                "input": {
                    "initialValue": str(total_amount),
                    "customerId": customer_id,
                    "recipientAttributes": None,
                    "note": note,
                    "expiresOn": (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
                }
            }
            
            
            
            # Execute GraphQL mutation
            result = await self.shopify_client.execute_query(
                store_key=store_key,
                query=mutation,
                variables=variables
            )
            
            if result.get("msg") == "success":
                data = result.get("data", {})
                if data.get("giftCardCreate", {}).get("giftCard"):
                    gift_card = data["giftCardCreate"]["giftCard"]
                    gift_card_id = gift_card["id"]
                    
                    logger.info(f"✅ Created gift card {gift_card_id} for customer {customer_id} with amount {total_amount}")
                    return gift_card_id
                else:
                    errors = data.get("giftCardCreate", {}).get("userErrors", [])
                    logger.error(f"Failed to create gift card: {errors}")
                    return None
            else:
                logger.error(f"Failed to execute gift card mutation: {result.get('error')}")
                return None
                
        except Exception as e:
            logger.error(f"Error creating Shopify gift card: {str(e)}")
            return None

    def _extract_non_returned_items(self, order: Dict[str, Any], sap_codes: Dict[str, str], warehouse_code: str = "ONL") -> List[Dict[str, Any]]:
        """
        Extract non-returned items (currentQuantity > 0) that are not gift cards
        """
        non_returned_items = []
        line_items = order.get("lineItems", {}).get("edges", [])
        
        for item_edge in line_items:
            item = item_edge.get("node", {})
            
            # Skip gift card items using the isGiftCard field
            if item.get("isGiftCard", False):
                logger.info(f"Skipping gift card item: {item.get('name', '')}")
                continue
            
            # Check if item has currentQuantity > 0 (not fully returned)
            current_quantity = item.get("currentQuantity", 0)
            if current_quantity <= 0:
                logger.info(f"Skipping fully returned item: {item.get('name', '')} (currentQuantity: {current_quantity})")
                continue
            
            # Get item details
            sku = item.get("sku", "")
            name = item.get("name", "")
            unit_price = float(item.get("originalUnitPriceSet", {}).get("shopMoney", {}).get("amount", 0))
            
            if not sku:
                logger.warning(f"Skipping item without SKU: {name}")
                continue
            
            # Use location-based costing codes
            default_codes = {
                'COGSCostingCode': 'ONL',
                'COGSCostingCode2': 'SAL', 
                'COGSCostingCode3': 'OnlineS',
                'CostingCode': 'ONL',
                'CostingCode2': 'SAL',
                'CostingCode3': 'OnlineS'
            }
            
            # Override with location-specific codes if available
            costing_codes = {key: sap_codes.get(key, default_codes[key]) for key in default_codes.keys()}
            
            line_total = unit_price * current_quantity
            
            line_item = {
                "ItemCode": sku,
                "Quantity": current_quantity,
                "UnitPrice": unit_price,
                "LineTotal": line_total,
                "WarehouseCode": warehouse_code,  # Use warehouse from location analysis
                "COGSCostingCode": costing_codes['COGSCostingCode'],
                "COGSCostingCode2": costing_codes['COGSCostingCode2'],
                "COGSCostingCode3": costing_codes['COGSCostingCode3'],
                "CostingCode": costing_codes['CostingCode'],
                "CostingCode2": costing_codes['CostingCode2'],
                "CostingCode3": costing_codes['CostingCode3']
            }
            
            non_returned_items.append(line_item)
            logger.info(f"Added non-returned item: {name} (SKU: {sku}, Qty: {current_quantity}, Price: {unit_price})")
        
        logger.info(f"Found {len(non_returned_items)} non-returned items")
        return non_returned_items

    def _calculate_freight_expenses(self, order: Dict[str, Any], store_key: str, sap_codes: Dict[str, str] = None) -> List[Dict[str, Any]]:
        """
        Calculate freight expenses based on shipping fee and store configuration
        """
        try:
            # Get shipping price from order
            shipping_price = float(order.get("totalShippingPriceSet", {}).get("shopMoney", {}).get("amount", 0))
            
            if shipping_price == 0:
                return []
            
            # Get freight configuration from config_data
            from app.core.config import config_data
            freight_config = config_data['shopify'].get("freight_config", {})
            store_freight_config = freight_config.get(store_key, {})
            
            expenses = []
            
            if store_key == "local":
                # Local store logic based on shipping fee
                shipping_price_str = str(int(shipping_price))
                
                if shipping_price_str in store_freight_config:
                    config = store_freight_config[shipping_price_str]
                    
                    # Add revenue expense
                    if "revenue" in config: 
                        config["revenue"]["DistributionRule"] = sap_codes.get('location_cc', 'ONL') if sap_codes else "ONL"                                               
                        config["revenue"]["DistributionRule2"] = sap_codes.get('department_cc', 'SAL') if sap_codes else "SAL"                                               
                        config["revenue"]["DistributionRule3"] = sap_codes.get('activity_cc', 'OnlineS') if sap_codes else "OnlineS"                                               
                        expenses.append(config["revenue"])
                    
                    # Add cost expense
                    if "cost" in config:
                        config["cost"]["DistributionRule"] = sap_codes.get('location_cc', 'ONL') if sap_codes else "ONL"                                               
                        config["cost"]["DistributionRule2"] = sap_codes.get('department_cc', 'SAL') if sap_codes else "SAL"                                               
                        config["cost"]["DistributionRule3"] = sap_codes.get('activity_cc', 'OnlineS') if sap_codes else "OnlineS"  
                        expenses.append(config["cost"])
                        
                    logger.info(f"Applied freight expenses for shipping fee {shipping_price}: {expenses}")
                else:
                    logger.warning(f"No freight configuration found for shipping fee {shipping_price} in local store")
                    
            elif store_key == "international":
                # International store logic - always add DHL expense
                dhl_config = store_freight_config.get("dhl", {})
                if dhl_config:
                    # Set the actual shipping price as the line total
                    dhl_expense = dhl_config.copy()
                    dhl_expense["LineTotal"] = shipping_price
                    expenses.append(dhl_expense)
                    
                    logger.info(f"Applied DHL freight expense for international order: {dhl_expense}")
                else:
                    logger.warning("No DHL configuration found for international store")
            
            return expenses
            
        except Exception as e:
            logger.error(f"Error calculating freight expenses: {str(e)}")
            return []

    async def _create_gift_card_invoice(self, order: Dict[str, Any], gift_card_id: str, original_payment_details: Dict[str, Any], store_key: str, store_config: Dict[str, Any], store_credit_refunds: List[Dict[str, Any]], warehouse_code: str) -> Dict[str, Any]:
        """
        Create new invoice in SAP for the gift card purchase and non-returned items
        """
        try:
            # Use CardCode from original payment details
            customer_card_code = original_payment_details.get("CardCode")
            
            if not customer_card_code:
                logger.error(f"No CardCode found in original payment details for order {order.get('name', '')}")
                return {"msg": "failure", "error": "No CardCode found in original payment details"}
                
            # Calculate total store credit amount from the passed parameter
            total_amount = sum(refund["amount"] for refund in store_credit_refunds)
            
            # Prepare gift card data for invoice line (skip SAP GiftCards entity creation)
            sap_gift_card_id = await self._prepare_gift_card_for_invoice(gift_card_id, total_amount, customer_card_code, warehouse_code)
            
            if not sap_gift_card_id:
                logger.error(f"Failed to prepare gift card data for invoice")
                return {"msg": "failure", "error": "Failed to prepare gift card data"}
            
            # Get gift card item code from configuration
            gift_card_item_code = self.config.get_gift_card_item_code()
            if not gift_card_item_code:
                logger.error("Gift card item code not found in configuration")
                return {"msg": "failure", "error": "Gift card item code not found"}
                
            # Prepare invoice data with gift card reference
            # Get location analysis using retailLocation field (same as orders_sync)
            location_analysis = self._analyze_order_location_from_retail_location(order, store_key)
            sap_codes = location_analysis.get('sap_codes', {})
            
            # Use location-based costing codes, fallback to defaults if not available
            default_codes = {
                'COGSCostingCode': 'ONL',
                'COGSCostingCode2': 'SAL', 
                'COGSCostingCode3': 'OnlineS',
                'CostingCode': 'ONL',
                'CostingCode2': 'SAL',
                'CostingCode3': 'OnlineS'
            }
            
            # Override with location-specific codes if available
            costing_codes = {key: sap_codes.get(key, default_codes[key]) for key in default_codes.keys()}
            
            # Get warehouse code from sap_codes (same as orders_sync)
            warehouse_code_from_location = sap_codes.get('Warehouse', 'SW') 
            logger.info(f"Using warehouse code '{warehouse_code_from_location}' for gift card invoice")
            
            # Extract non-returned items (currentQuantity > 0) and non-gift card items
            non_returned_items = self._extract_non_returned_items(order, sap_codes, warehouse_code_from_location)
            
            # Prepare line items - start with non-returned items
            line_items = non_returned_items.copy()
            
            # Add gift card line item
            gift_card_line = {
                "ItemCode": gift_card_item_code,  # Use the configured gift card item code
                "Quantity": 1,
                "UnitPrice": total_amount,
                "LineTotal": total_amount,
                "WarehouseCode": warehouse_code_from_location,  # Use warehouse from location analysis
                "U_GiftCard": sap_gift_card_id,  # Add gift card ID to specify this is a gift card line
                "COGSCostingCode": costing_codes['COGSCostingCode'],
                "COGSCostingCode2": costing_codes['COGSCostingCode2'],
                "COGSCostingCode3": costing_codes['COGSCostingCode3'],
                "CostingCode": costing_codes['CostingCode'],
                "CostingCode2": costing_codes['CostingCode2'],
                "CostingCode3": costing_codes['CostingCode3']
            }
            line_items.append(gift_card_line)
            
            # Calculate freight expenses if order had shipping
            freight_expenses = self._calculate_freight_expenses(order, store_key, sap_codes)
            
            # Extract gift card redemptions from the original order and add as expenses
            payment_info = self._extract_payment_info(order)
            gift_card_expenses = []
            if payment_info.get("gift_cards"):
                logger.info(f"🎁 Processing {len(payment_info['gift_cards'])} gift card redemption(s) from original order")
                for gift_card in payment_info["gift_cards"]:
                    gift_card_expense = {
                        "ExpenseCode": 2,  # Gift card expense code
                        "LineTotal": -float(gift_card["amount"]),  # Negative amount
                        "Remarks": f"Gift Card: {gift_card['last_characters']}",
                        "U_GiftCard": gift_card["gift_card_id"],  # Add gift card ID to expense entry
                        "DistributionRule": sap_codes.get('location_cc', 'ONL'),                                               
                        "DistributionRule2": sap_codes.get('department_cc', 'SAL'),                                               
                        "DistributionRule3": sap_codes.get('activity_cc', 'OnlineS')   
                    }
                    gift_card_expenses.append(gift_card_expense)
                    logger.info(f"🎁 Created gift card expense: {gift_card['last_characters']} - Amount: -{gift_card['amount']}")
            else:
                logger.info("🎁 No gift card redemptions found in original order")
            
            # Get location analysis for invoice preparation (same as orders_sync)
            location_analysis = self._analyze_order_location_from_retail_location(order, store_key)
            
            # Extract createdAt date from the original order for DocDate
            order_created_at = order.get("createdAt", "")
            if order_created_at:
                # Parse the ISO date and format it for SAP
                try:
                    from datetime import datetime
                    parsed_date = datetime.fromisoformat(order_created_at.replace('Z', '+00:00'))
                    doc_date = parsed_date.strftime("%Y-%m-%d")
                    logger.info(f"Using order createdAt date for gift card invoice DocDate: {doc_date}")
                except Exception as e:
                    logger.warning(f"Failed to parse order createdAt date '{order_created_at}': {str(e)}, using current date")
                    doc_date = datetime.now().strftime("%Y-%m-%d")
            else:
                logger.warning("No createdAt date found in order, using current date")
                doc_date = datetime.now().strftime("%Y-%m-%d")
            
            # Use centralized invoice preparation
            invoice_data = self.sap_operations.prepare_invoice_data(
                order_data=order,
                customer_card_code=customer_card_code,
                store_key=store_key,
                location_analysis=location_analysis,
                line_items=line_items,
                financial_status="PAID",
                fulfillment_status="FULFILLED",
                order_type="1",  # Gift card order
                doc_date=doc_date,
                comments=f"Gift card created for refund - Order {order.get('name', '')}",
                custom_fields={
                    "U_Shopify_Order_ID": order.get('id', '')
                }
            )
            
            # Add freight expenses if any
            if freight_expenses:
                invoice_data["DocumentAdditionalExpenses"] = freight_expenses
                logger.info(f"Added freight expenses to invoice: {freight_expenses}")
            
            # Add gift card redemption expenses if any
            if gift_card_expenses:
                # Combine freight and gift card expenses
                all_expenses = freight_expenses + gift_card_expenses
                invoice_data["DocumentAdditionalExpenses"] = all_expenses
                logger.info(f"Added gift card redemption expenses to invoice: {gift_card_expenses}")
            elif freight_expenses:
                # Only freight expenses, no gift cards
                invoice_data["DocumentAdditionalExpenses"] = freight_expenses
            
            # Create invoice in SAP using shared operations
            result = await self.sap_operations.create_invoice_in_sap(invoice_data, order.get('name', ''))
            
            if result["msg"] == "success":
                logger.info(f"✅ Created gift card invoice {result.get('sap_doc_entry')} for order {order.get('name', '')}")
                
                return {
                    "msg": "success",
                    "sap_doc_entry": result.get('sap_doc_entry'),
                    "sap_doc_num": result.get('sap_doc_num'),
                    "sap_trans_num": result.get('sap_trans_num'),
                    "sap_doc_total": result.get('sap_doc_total'),
                    "sap_doc_date": doc_date  # Use the doc_date we calculated, not from SAP response
                }
            else:
                logger.error(f"Failed to create gift card invoice: {result.get('error')}")
                return result
                
        except Exception as e:
            logger.error(f"Error creating gift card invoice: {str(e)}")
            return {"msg": "failure", "error": str(e)}

    async def _create_gift_card_payment(self, invoice_result: Dict[str, Any], original_payment_details: Dict[str, Any], order_name: str, order: Dict[str, Any], store_key: str):
        """
        Create incoming payment for the gift card invoice
        """
        try:
            if not original_payment_details:
                logger.error("No original payment details provided")
                return {"msg": "failure", "error": "No original payment details provided"}
                
            # Get location analysis for payment preparation using retailLocation
            location_analysis = self._get_location_analysis_from_retail_location(order, store_key)
            
            # Get the actual gateway from the order transactions
            gateway = "cash"  # Default for POS orders
            if order.get("transactions") and len(order["transactions"]) > 0:
                gateway = order["transactions"][0].get("gateway", "cash")
            
            # Determine payment type based on gateway
            payment_type = "PaidOnline" if gateway.lower() != "cash" else "Cash"
            
            # Copy the exact payment data from original payment
            payment_data = original_payment_details.copy()
            
            # Ensure PaymentCreditCards array is preserved if it exists in original payment
            if "PaymentCreditCards" in original_payment_details:
                payment_data["PaymentCreditCards"] = original_payment_details["PaymentCreditCards"]
                logger.info(f"Preserved PaymentCreditCards array with {len(original_payment_details['PaymentCreditCards'])} credit cards")
            
            # Update only the necessary fields for the new payment
            # Use the same DocDate as the invoice
            invoice_doc_date = invoice_result.get("sap_doc_date", datetime.now().strftime("%Y-%m-%d"))
            logger.info(f"Using invoice DocDate for gift card payment: {invoice_doc_date}")
            payment_data["DocDate"] = invoice_doc_date
            payment_data["U_Shopify_Order_ID"] = order.get("id", "").split("/")[-1] if "/" in order.get("id", "") else order.get("id", "")
            # Calculate total sum from all payment methods in original payment
            total_sum = 0
            if "CashSum" in original_payment_details:
                total_sum += original_payment_details["CashSum"]
            if "TransferSum" in original_payment_details:
                total_sum += original_payment_details["TransferSum"]
            if "PaymentCreditCards" in original_payment_details:
                for credit_card in original_payment_details["PaymentCreditCards"]:
                    total_sum += credit_card.get("CreditSum", 0)
            
            payment_data["PaymentInvoices"] = [{
                "DocEntry": invoice_result.get("sap_doc_entry"),
                "SumApplied": total_sum,
                "InvoiceType": "it_Invoice"
            }]
            
            logger.info(f"Using exact original payment data - Cash: {original_payment_details.get('CashSum', 0)}, Transfer: {original_payment_details.get('TransferSum', 0)}, CreditCards: {len(original_payment_details.get('PaymentCreditCards', []))} cards")
            
            # Log the final payment data structure being sent to SAP
            logger.info(f"Gift card payment data structure - CashSum: {payment_data.get('CashSum', 'N/A')}, TransferSum: {payment_data.get('TransferSum', 'N/A')}, PaymentCreditCards: {len(payment_data.get('PaymentCreditCards', []))} cards")
            if payment_data.get('PaymentCreditCards'):
                for i, card in enumerate(payment_data['PaymentCreditCards']):
                    logger.info(f"  Credit Card {i+1}: CreditCard={card.get('CreditCard')}, CreditSum={card.get('CreditSum')}, CreditCur={card.get('CreditCur')}")
            
            # Create incoming payment using shared operations
            result = await self.sap_operations.create_incoming_payment_in_sap(payment_data, order_name)
            
            if result["msg"] == "success":
                logger.info(f"✅ Created incoming payment {result.get('sap_doc_entry')} for gift card invoice")
                return {
                    "msg": "success",
                    "sap_doc_entry": result.get('sap_doc_entry')
                }
            else:
                logger.error(f"Failed to create incoming payment for gift card invoice: {result.get('error')}")
                return result
                
        except Exception as e:
            logger.error(f"Error creating gift card payment: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    

    async def _get_original_payment_method(self, payment_entry: str) -> Optional[Dict[str, Any]]:
        """
        Get the original payment method from the cancelled payment
        """
        try:
            if not payment_entry:
                return None
                
            # Get the cancelled payment details
            result = await self.sap_client._make_request(
                method='GET',
                endpoint=f'IncomingPayments({payment_entry})',
                params={
                    "$select": "TransferAccount,CashAccount"
                }
            )
            
            if result["msg"] == "success":
                payment_data = result["data"]
                return {
                    "TransferAccount": payment_data.get("TransferAccount"),
                    "CashAccount": payment_data.get("CashAccount")
                }
            else:
                logger.error(f"Failed to get original payment method: {result.get('error')}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting original payment method: {str(e)}")
            return None

    async def _get_or_create_customer(self, customer: Dict[str, Any], store_key: str) -> Optional[str]:
        """
        Get or create customer in SAP
        """
        try:
            from app.sync.sales.customers import CustomerManager
            
            customer_sync = CustomerManager()
            
            # Try to find existing customer by phone
            customer_phone = customer.get("phone")
            if customer_phone:
                existing_customer = await customer_sync.find_customer_by_phone(customer_phone)
                if existing_customer:
                    logger.info(f"Found existing customer: {existing_customer['CardCode']}")
                    return existing_customer["CardCode"]
            
            # If not found, create new customer
            logger.info(f"Creating new customer for phone: {customer_phone}")
            new_customer = await customer_sync.create_customer_in_sap(customer, store_key)
            
            if new_customer and new_customer.get("msg") == "success":
                return new_customer.get("sap_customer_code")
            else:
                logger.error(f"Failed to create customer: {new_customer.get('error', 'Unknown error')}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting/creating customer: {str(e)}")
            return None

    async def _add_order_tag_with_retry(self, order_id: str, tag: str, store_key: str, max_retries: int = 3):
        """
        Add tag to order with retry logic
        """
        for attempt in range(max_retries):
            try:
                result = await self.shopify_client.add_order_tag(
                    store_key=store_key,
                    order_id=order_id,
                    tag=tag
                )
                
                if result["msg"] == "success":
                    logger.info(f"✅ Successfully added tag '{tag}' to order {order_id}")
                    return result
                else:
                    error_msg = result.get('error', 'Unknown error')
                    logger.warning(f"⚠️ TAG ATTEMPT {attempt + 1} FAILED: {error_msg}")
                    
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                        logger.info(f"⏳ Retrying tag addition in {wait_time} seconds...")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"❌ TAG FAILED after {max_retries} attempts: {tag}")
                        
            except Exception as e:
                error_msg = str(e)
                logger.error(f"❌ TAG EXCEPTION on attempt {attempt + 1}: {error_msg}")
                
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.info(f"⏳ Retrying tag addition in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"❌ TAG FAILED after {max_retries} attempts due to exception: {tag}")

    def _get_date_filter(self) -> str:
        """
        Get date filter for orders (last 30 days)
        """
        date_filter = datetime.now() - timedelta(days=30)
        return date_filter.strftime("%Y-%m-%d")
    
    def _get_sap_codes_from_retail_location(self, order: Dict[str, Any], store_key: str) -> Dict[str, str]:
        """
        Get SAP codes from retailLocation field for POS orders, use default for web orders
        """
        try:
            # Check if this is a POS order first
            source_name = order.get("sourceName", "").lower()
            is_pos_order = source_name == "pos"
            
            if is_pos_order:
                # For POS orders, use retailLocation field
                retail_location = order.get("retailLocation", {})
                location_id = None
                
                if retail_location and retail_location.get("id"):
                    # Extract location ID from GraphQL ID (e.g., "gid://shopify/Location/72406990914" -> "72406990914")
                    location_gid = retail_location["id"]
                    location_id = location_gid.split("/")[-1] if "/" in location_gid else location_gid
                    
                    # Get location mapping for this specific location
                    location_mapping = self.config.get_location_mapping_for_location(store_key, location_id)
                    
                    if location_mapping:
                        logger.info(f"Using retail location SAP codes for POS order: {location_id}")
                        return {
                            'COGSCostingCode': location_mapping.get('location_cc', 'ONL'),
                            'COGSCostingCode2': location_mapping.get('department_cc', 'SAL'),
                            'COGSCostingCode3': location_mapping.get('activity_cc', 'OnlineS'),
                            'CostingCode': location_mapping.get('location_cc', 'ONL'),
                            'CostingCode2': location_mapping.get('department_cc', 'SAL'),
                            'CostingCode3': location_mapping.get('activity_cc', 'OnlineS'),
                            'Warehouse': location_mapping.get('warehouse', 'SW')
                        }
                
                # Fallback to default codes if no retail location or mapping found for POS order
                logger.warning("No retail location or mapping found for POS order, using default SAP codes")
            else:
                # For web/online orders, use default codes
                logger.info("Web/online order detected, using default SAP codes")
            
            # Return default codes for web orders or as fallback for POS orders
            # For web orders, get the default location mapping
            default_location_mapping = self.config.get_default_location_mapping(store_key)
            default_warehouse = default_location_mapping.get('warehouse', 'SW') if default_location_mapping else 'SW'
            
            return {
                'COGSCostingCode': 'ONL',
                'COGSCostingCode2': 'SAL',
                'COGSCostingCode3': 'OnlineS',
                'CostingCode': 'ONL',
                'CostingCode2': 'SAL',
                'CostingCode3': 'OnlineS',
                'Warehouse': default_warehouse
            }
            
        except Exception as e:
            logger.error(f"Error getting SAP codes from retail location: {str(e)}")
            # Return default codes on error
            default_location_mapping = self.config.get_default_location_mapping(store_key)
            default_warehouse = default_location_mapping.get('warehouse', 'SW') if default_location_mapping else 'SW'
            
            return {
                'COGSCostingCode': 'ONL',
                'COGSCostingCode2': 'SAL',
                'COGSCostingCode3': 'OnlineS',
                'CostingCode': 'ONL',
                'CostingCode2': 'SAL',
                'CostingCode3': 'OnlineS',
                'Warehouse': default_warehouse
            }
    
    def _extract_payment_info(self, order_node: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract payment information from Shopify order transactions including gift cards and store credit
        """
        payment_info = {
            "gateway": "Unknown",
            "card_type": "Unknown", 
            "last_4": "Unknown",
            "payment_id": "Unknown",
            "authorization": "Unknown",
            "amount": 0.0,
            "status": "Unknown",
            "processed_at": "Unknown",
            "is_online_payment": False,
            "gift_cards": [],
            "total_gift_card_amount": 0.0,
            "store_credit": {
                "amount": 0.0,
                "transactions": []
            },
            "payment_gateways": [],
            "total_payment_amount": 0.0
        }
        
        try:
            transactions = order_node.get("transactions", [])
            
            for transaction in transactions:
                
                # Look for successful payment transactions
                if (transaction.get("kind") == "SALE" and 
                    transaction.get("status") == "SUCCESS"):
                    
                    gateway = transaction.get("gateway", "Unknown")
                    amount = float(transaction.get("amountSet", {}).get("shopMoney", {}).get("amount", 0))
                    receipt_json = transaction.get("receiptJson", "{}")
                    
                    # Handle store credit transactions
                    if gateway == "shopify_store_credit":
                        store_credit_info = {
                            "transaction_id": transaction.get("id", "Unknown"),
                            "amount": amount,
                            "currency": transaction.get("amountSet", {}).get("shopMoney", {}).get("currencyCode", "Unknown"),
                            "processed_at": transaction.get("processedAt", "Unknown"),
                            "receipt_json": receipt_json
                        }
                        payment_info["store_credit"]["transactions"].append(store_credit_info)
                        payment_info["store_credit"]["amount"] += amount
                        logger.info(f"🏪 STORE CREDIT DETECTED: {amount} {store_credit_info['currency']} - Transaction ID: {store_credit_info['transaction_id']}")
                    
                    # Handle all payment gateway transactions except gift_card and store_credit (which have their own processing)
                    elif gateway != "Unknown" and gateway != "gift_card" and gateway != "shopify_store_credit":
                        # Create payment gateway info
                        gateway_info = {
                            "gateway": gateway,
                            "amount": amount,
                            "status": transaction.get("status", "Unknown"),
                            "processed_at": transaction.get("processedAt", "Unknown"),
                            "transaction_id": transaction.get("id", "Unknown"),
                            "receipt_json": receipt_json
                        }
                        
                        # Extract payment_id from receiptJson (for supported gateways)
                        try:
                            import json
                            receipt_data = json.loads(receipt_json)
                            gateway_info["payment_id"] = receipt_data.get("payment_id", transaction.get("id", "Unknown"))
                        except (json.JSONDecodeError, KeyError):
                            gateway_info["payment_id"] = transaction.get("id", "Unknown")
                        
                        # Add to payment gateways list
                        payment_info["payment_gateways"].append(gateway_info)
                        payment_info["total_payment_amount"] += amount
                        
                        # Set primary gateway info (for backward compatibility - use the first non-store-credit gateway)
                        if payment_info["gateway"] == "Unknown":
                            payment_info["gateway"] = gateway
                            payment_info["amount"] = amount
                            payment_info["status"] = transaction.get("status", "Unknown")
                            payment_info["processed_at"] = transaction.get("processedAt", "Unknown")
                            payment_info["payment_id"] = gateway_info["payment_id"]
                        
                        # Check if this is an online payment
                        source_name = order_node.get("sourceName", "")
                        if source_name:
                            source_name = source_name.lower()
                            if ("online store" in source_name or 
                                "web" in source_name or 
                                "shopify" in source_name or
                                "online" in source_name or
                                "mobile" in source_name or
                                "app" in source_name):
                                payment_info["is_online_payment"] = True
                    
                    # Handle gift card transactions
                    elif gateway == "gift_card":
                        try:
                            import json
                            receipt_data = json.loads(receipt_json)
                            
                            gift_card_info = {
                                "last_characters": receipt_data.get("gift_card_last_characters", "Unknown"),
                                "amount": amount,  # Use the transaction amount directly
                                "currency": transaction.get("amountSet", {}).get("shopMoney", {}).get("currencyCode", "Unknown"),
                                "gift_card_id": receipt_data.get("gift_card_id", "Unknown")
                            }
                            
                            payment_info["gift_cards"].append(gift_card_info)
                            payment_info["total_gift_card_amount"] += amount
                            
                        except (json.JSONDecodeError, KeyError) as e:
                            logger.warning(f"Error parsing gift card receipt JSON: {e}")
                            # Fallback gift card info
                            gift_card_info = {
                                "last_characters": "Unknown",
                                "amount": amount,
                                "currency": transaction.get("amountSet", {}).get("shopMoney", {}).get("currencyCode", "Unknown"),
                                "gift_card_id": "Unknown"
                            }
                            payment_info["gift_cards"].append(gift_card_info)
                            payment_info["total_gift_card_amount"] += amount
                    
                    # Handle other payment gateways
                    else:
                        payment_info["gateway"] = gateway
                        payment_info["amount"] = amount
                        payment_info["status"] = transaction.get("status", "Unknown")
                        payment_info["processed_at"] = transaction.get("processedAt", "Unknown")
                        payment_info["authorization"] = transaction.get("authorization", "Unknown")
                        
                        # Extract credit card information if available
                        payment_details = transaction.get("paymentDetails", {})
                        if payment_details:
                            payment_info["card_type"] = payment_details.get("creditCardCompany", "Unknown")
                            payment_info["last_4"] = payment_details.get("creditCardLastDigits", "Unknown")
                        else:
                            # Use gateway as card type if payment details not available
                            payment_info["card_type"] = gateway
                        
                        # Check if this is an online payment
                        source_name = order_node.get("sourceName", "")
                        if source_name:
                            source_name = source_name.lower()
                            if ("online store" in source_name or 
                                "web" in source_name or 
                                "shopify" in source_name or
                                "online" in source_name or
                                "mobile" in source_name or
                                "app" in source_name):
                                payment_info["is_online_payment"] = True
                                # For online payments, use the transaction ID as payment ID
                                payment_info["payment_id"] = transaction.get("id", "Unknown")
                    
        except Exception as e:
            logger.error(f"Error extracting payment info: {str(e)}")
        
        return payment_info

    def _analyze_order_location_from_retail_location(self, order_node: Dict[str, Any], store_key: str) -> Dict[str, Any]:
        """
        Analyze order location using retailLocation field for POS orders, fallback to original method for web orders
        """
        try:
            # Check if this is a POS order first
            source_name = order_node.get("sourceName", "").lower()
            is_pos_order = source_name == "pos"
            
            if is_pos_order:
                # For POS orders, use retailLocation field
                retail_location = order_node.get("retailLocation", {})
                location_id = None
                
                if retail_location and retail_location.get("id"):
                    # Extract location ID from GraphQL ID (e.g., "gid://shopify/Location/72406990914" -> "72406990914")
                    location_gid = retail_location["id"]
                    location_id = location_gid.split("/")[-1] if "/" in location_gid else location_gid
                    logger.info(f"Found retail location ID for POS order: {location_id}")
                else:
                    logger.warning("No retail location found in POS order, using default location mapping")
                    # Fallback to default location mapping if no retail location
                    from order_location_mapper import OrderLocationMapper
                    return OrderLocationMapper.analyze_order_source(order_node, store_key)
                
                if not location_id:
                    logger.warning("Could not extract location ID from retail location, using default location mapping")
                    from order_location_mapper import OrderLocationMapper
                    return OrderLocationMapper.analyze_order_source(order_node, store_key)
                
                # Get location mapping for this specific location
                logger.info(f"Looking for location mapping for location_id: {location_id} in store: {store_key}")
                location_mapping = self.config.get_location_mapping_for_location(store_key, location_id)
                logger.info(f"Location mapping result: {location_mapping}")
                
                if not location_mapping:
                    logger.warning(f"No location mapping found for location {location_id}, using default location mapping")
                    from order_location_mapper import OrderLocationMapper
                    return OrderLocationMapper.analyze_order_source(order_node, store_key)
                
                # Get SAP codes for this location
                warehouse_code = location_mapping.get('warehouse', 'SW')
                logger.info(f"Using warehouse code: {warehouse_code} for location {location_id}")
                
                sap_codes = {
                    'COGSCostingCode': location_mapping.get('location_cc', 'ONL'),
                    'COGSCostingCode2': location_mapping.get('department_cc', 'SAL'),
                    'COGSCostingCode3': location_mapping.get('activity_cc', 'OnlineS'),
                    'CostingCode': location_mapping.get('location_cc', 'ONL'),
                    'CostingCode2': location_mapping.get('department_cc', 'SAL'),
                    'CostingCode3': location_mapping.get('activity_cc', 'OnlineS'),
                    'Warehouse': warehouse_code
                }
                
                # Extract receipt number for POS orders
                extracted_receipt_number = None
                source_identifier = order_node.get("sourceIdentifier", "")
                if source_identifier and "-" in source_identifier:
                    # Extract receipt number from sourceIdentifier (e.g., "70074892354-1-1010" -> "1010")
                    parts = source_identifier.split("-")
                    if len(parts) >= 3:
                        extracted_receipt_number = parts[2]
                        logger.info(f"Extracted POS receipt number: {extracted_receipt_number}")
                
                return {
                    "location_id": location_id,
                    "location_mapping": location_mapping,
                    "is_pos_order": True,
                    "sap_codes": sap_codes,
                    "extracted_receipt_number": extracted_receipt_number
                }
            else:
                # For web/online orders, use the original method
                logger.info("Web/online order detected, using original location mapping method")
                from order_location_mapper import OrderLocationMapper
                return OrderLocationMapper.analyze_order_source(order_node, store_key)
            
        except Exception as e:
            logger.error(f"Error analyzing order location: {str(e)}")
            # Fallback to original method
            from order_location_mapper import OrderLocationMapper
            return OrderLocationMapper.analyze_order_source(order_node, store_key)

    def _get_location_analysis_from_retail_location(self, order: Dict[str, Any], store_key: str) -> Dict[str, Any]:
        """
        Get location analysis from retailLocation field for POS orders, use default for web orders
        """
        try:
            # Check if this is a POS order first
            source_name = order.get("sourceName", "").lower()
            is_pos_order = source_name == "pos"
            
            if is_pos_order:
                # For POS orders, use retailLocation field
                retail_location = order.get("retailLocation", {})
                location_id = None
                
                if retail_location and retail_location.get("id"):
                    # Extract location ID from GraphQL ID (e.g., "gid://shopify/Location/72406990914" -> "72406990914")
                    location_gid = retail_location["id"]
                    location_id = location_gid.split("/")[-1] if "/" in location_gid else location_gid
                    
                    # Get location mapping for this specific location
                    location_mapping = self.config.get_location_mapping_for_location(store_key, location_id)
                    
                    if location_mapping:
                        # Get SAP codes for this location
                        sap_codes = {
                            'COGSCostingCode': location_mapping.get('location_cc', 'ONL'),
                            'COGSCostingCode2': location_mapping.get('department_cc', 'SAL'),
                            'COGSCostingCode3': location_mapping.get('activity_cc', 'OnlineS'),
                            'CostingCode': location_mapping.get('location_cc', 'ONL'),
                            'CostingCode2': location_mapping.get('department_cc', 'SAL'),
                            'CostingCode3': location_mapping.get('activity_cc', 'OnlineS'),
                            'Warehouse': location_mapping.get('warehouse', 'SW')
                        }
                        
                        logger.info(f"Using retail location analysis for POS order: {location_id}")
                        return {
                            "location_id": location_id,
                            "location_mapping": location_mapping,
                            "is_pos_order": True,
                            "sap_codes": sap_codes
                        }
                
                # Fallback to default location analysis if no retail location or mapping found for POS order
                logger.warning("No retail location or mapping found for POS order, using default location analysis")
            else:
                # For web/online orders, use default location analysis
                logger.info("Web/online order detected, using default location analysis")
            
            # Return default location analysis for web orders or as fallback for POS orders
            # For web orders, get the default location mapping
            default_location_mapping = self.config.get_default_location_mapping(store_key)
            default_warehouse = default_location_mapping.get('warehouse', 'SW') if default_location_mapping else 'SW'
            
            return {
                "location_id": None,
                "location_mapping": {},
                "is_pos_order": False,
                "sap_codes": {
                    'COGSCostingCode': 'ONL',
                    'COGSCostingCode2': 'SAL',
                    'COGSCostingCode3': 'OnlineS',
                    'CostingCode': 'ONL',
                    'CostingCode2': 'SAL',
                    'CostingCode3': 'OnlineS',
                    'Warehouse': default_warehouse
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting location analysis from retail location: {str(e)}")
            # Return default location analysis on error
            default_location_mapping = self.config.get_default_location_mapping(store_key)
            default_warehouse = default_location_mapping.get('warehouse', 'SW') if default_location_mapping else 'SW'
            
            return {
                "location_id": None,
                "location_mapping": {},
                "is_pos_order": False,
                "sap_codes": {
                    'COGSCostingCode': 'ONL',
                    'COGSCostingCode2': 'SAL',
                    'COGSCostingCode3': 'OnlineS',
                    'CostingCode': 'ONL',
                    'CostingCode2': 'SAL',
                    'CostingCode3': 'OnlineS',
                    'Warehouse': default_warehouse
                }
            }
