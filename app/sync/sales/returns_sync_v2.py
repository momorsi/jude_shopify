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
            
            total_processed = 0
            total_successful = 0
            total_errors = 0
            
            for store_key, store_config in stores.items():
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
                    financial_status:refunded OR financial_status:partially_refunded 
                    tag:sap_invoice_synced 
                    tag:sap_payment_synced 
                    -tag:sap_return_synced 
                    -tag:sap_giftcard_invoice_failed 
                    -tag:sap_giftcard_payment_failed 
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
            
            processed = 0
            successful = 0
            errors = 0
            
            for order in orders:
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
            
            # Check if order has store credit refunds
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
            
            # Check if gift card already exists for this order
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
                # Create a mock invoice result with existing DocEntry
                new_invoice_result = {
                    "msg": "success",
                    "sap_doc_entry": existing_invoice_entry,
                    "sap_doc_total": sum(refund["amount"] for refund in store_credit_refunds)
                }
            else:
                # Create new invoice in SAP for gift card
                new_invoice_result = await self._create_gift_card_invoice(order, gift_card_id, original_payment_details, store_key, store_config)
            
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
                    
                    # Tag order as processed
                    await self._add_order_tag_with_retry(order_id, "sap_return_synced", store_key)
                    logger.info(f"✅ Successfully processed return for order {order_name}")
                else:
                    # Add payment failure tag immediately
                    await self._add_order_tag_with_retry(order_id, "sap_giftcard_payment_failed", store_key)
                    logger.error(f"Failed to create gift card payment for order {order_name}")
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

    async def _create_or_get_gift_card_in_sap(self, gift_card_id: str, amount: float, customer_card_code: str) -> Optional[str]:
        """
        Create or get gift card in SAP GiftCards entity
        """
        try:
            # Extract numeric ID from Shopify gift card ID
            numeric_id = gift_card_id.split("/")[-1] if "/" in gift_card_id else gift_card_id
            
            # Check if gift card already exists in SAP
            existing_gift_card = await self._check_gift_card_exists_in_sap(numeric_id)
            
            if existing_gift_card:
                logger.info(f"Gift card {numeric_id} already exists in SAP, using existing record")
                return numeric_id
            
            # Create gift card in SAP using the same technique as orders_sync
            from datetime import datetime, timedelta
            
            # Calculate expiration date (1 year from now)
            order_date = datetime.now().strftime("%Y-%m-%d")
            order_datetime = datetime.strptime(order_date, "%Y-%m-%d")
            expiration_date = order_datetime + timedelta(days=365)
            expiration_date_str = expiration_date.strftime("%Y-%m-%d")
            
            gift_card_data = {
                "Code": numeric_id,  # Use the actual gift card ID
                "U_ActiveDate": order_date,
                "U_ExpirDate": expiration_date_str,
                "U_Active": "Yes",
                "U_CardBal": amount,
                "U_Customer": customer_card_code,
                "U_Location": "ONL",
                "U_Consumed": 0,
                "U_CardAmount": amount,
                "U_Expired": "No"
            }
            
            # Create gift card in SAP using the same method as orders_sync
            result = await self.sap_client.create_gift_card(gift_card_data)
            
            if result["msg"] == "success":
                logger.info(f"✅ Created gift card in SAP: {numeric_id} - Amount: {amount}")
                return numeric_id
            else:
                # Check if it's an "already exists" error
                error_msg = result.get('error', '')
                if "already exists" in error_msg.lower() or "-2035" in error_msg:
                    logger.info(f"Gift card {numeric_id} already exists in SAP, using existing record")
                    return numeric_id
                else:
                    logger.error(f"Failed to create gift card in SAP: {result.get('error')}")
                    return None
                
        except Exception as e:
            logger.error(f"Error creating gift card in SAP: {str(e)}")
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
                        "$select": "TransferAccount, CashAccount, CardCode, Cancelled "
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
                        "CardCode": payment_data.get("CardCode")
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
                            endpoint=f'Invoices({invoice_entry})/CreateCancellationDocument',
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
                    endpoint=f'Invoices({invoice_entry})/CreateCancellationDocument',
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
                
            # Calculate total store credit amount
            total_amount = sum(refund["amount"] for refund in store_credit_refunds)
            
            # Prepare gift card mutation
            mutation = """
            mutation giftCardCreate($input: GiftCardCreateInput!) {
                giftCardCreate(input: $input) {
                    giftCard {
                        id
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
                    "recipientAttributes": None
                }
            }
            
            # Add note with order reference
            order_name = order.get("name", "")
            order_id = order.get("id", "")
            note = f"Refund for order {order_name} (ID: {order_id})"
            
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

    async def _create_gift_card_invoice(self, order: Dict[str, Any], gift_card_id: str, original_payment_details: Dict[str, Any], store_key: str, store_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create new invoice in SAP for the gift card purchase
        """
        try:
            # Use CardCode from original payment details
            customer_card_code = original_payment_details.get("CardCode")
            
            if not customer_card_code:
                logger.error(f"No CardCode found in original payment details for order {order.get('name', '')}")
                return {"msg": "failure", "error": "No CardCode found in original payment details"}
                
            # Calculate total store credit amount
            store_credit_refunds = self._extract_store_credit_refunds(order)
            total_amount = sum(refund["amount"] for refund in store_credit_refunds)
            
            # First, create or get the gift card in SAP GiftCards entity
            sap_gift_card_id = await self._create_or_get_gift_card_in_sap(gift_card_id, total_amount, customer_card_code)
            
            if not sap_gift_card_id:
                logger.error(f"Failed to create gift card in SAP GiftCards entity")
                return {"msg": "failure", "error": "Failed to create gift card in SAP"}
            
            # Get gift card item code from configuration
            gift_card_item_code = self.config.get_gift_card_item_code()
            if not gift_card_item_code:
                logger.error("Gift card item code not found in configuration")
                return {"msg": "failure", "error": "Gift card item code not found"}
                
            # Prepare invoice data with gift card reference
            # Get costing codes from OrderLocationMapper like orders_sync
            from order_location_mapper import OrderLocationMapper
            
            location_analysis = OrderLocationMapper.analyze_order_source(order, store_key)
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
            
            # Prepare line items
            line_items = [{
                "ItemCode": gift_card_item_code,  # Use the configured gift card item code
                "Quantity": 1,
                "UnitPrice": total_amount,
                "LineTotal": total_amount,
                "U_GiftCard": gift_card_id,  # Add gift card ID to specify this is a gift card line
                "COGSCostingCode": costing_codes['COGSCostingCode'],
                "COGSCostingCode2": costing_codes['COGSCostingCode2'],
                "COGSCostingCode3": costing_codes['COGSCostingCode3'],
                "CostingCode": costing_codes['CostingCode'],
                "CostingCode2": costing_codes['CostingCode2'],
                "CostingCode3": costing_codes['CostingCode3']
            }]
            
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
                doc_date=datetime.now().strftime("%Y-%m-%d"),
                comments=f"Gift card created for refund - Order {order.get('name', '')}",
                custom_fields={
                    "U_Shopify_Order_ID": f"Refund:{order.get('id', '')}"
                }
            )
            
            # Create invoice in SAP using shared operations
            result = await self.sap_operations.create_invoice_in_sap(invoice_data, order.get('name', ''))
            
            if result["msg"] == "success":
                logger.info(f"✅ Created gift card invoice {result.get('sap_doc_entry')} for order {order.get('name', '')}")
                
                return {
                    "msg": "success",
                    "sap_doc_entry": result.get('sap_doc_entry'),
                    "sap_doc_num": result.get('sap_doc_num'),
                    "sap_trans_num": result.get('sap_trans_num'),
                    "sap_doc_total": result.get('sap_doc_total')
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
                
            # Get location analysis for payment preparation
            from order_location_mapper import OrderLocationMapper
            location_analysis = OrderLocationMapper.analyze_order_source({"id": order.get("id", ""), "name": order.get("name", "")}, store_key)
            
            # Use centralized payment preparation
            payment_data = self.sap_operations.prepare_payment_data(
                order_data={"id": order.get("id", ""), "name": order.get("name", "")},
                customer_card_code=original_payment_details.get("CardCode"),
                store_key=store_key,
                location_analysis=location_analysis,
                invoice_doc_entry=invoice_result.get("sap_doc_entry"),
                payment_amount=invoice_result.get("sap_doc_total"),
                payment_type="PaidOnline",
                gateway="Paymob",
                custom_fields={
                    "TransferAccount": original_payment_details.get("TransferAccount"),
                    "TransferDate": datetime.now().strftime("%Y-%m-%d")
                }
            )
            
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
                endpoint=f'IncomingPayments({payment_entry})'
            )
            
            if result["msg"] == "success":
                payment_data = result["data"]
                return {
                    "TransferAccount": payment_data.get("TransferAccount"),
                    "TransferSum": payment_data.get("TransferSum")
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
