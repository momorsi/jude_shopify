"""
Returns Sync V3 - Handle returns with Credit Notes and Gift Cards/Outgoing Payments
Scenario 1: Return with NO money back (Store Credit/Gift Card) - Create CN, Gift Card Invoice, Reconcile
Scenario 2: Return with REFUND (Money back) - Create CN, Outgoing Payment
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

class ReturnsSyncV3:
    def __init__(self):
        self.shopify_client = MultiStoreShopifyClient()
        self.sap_client = SAPClient()
        self.sap_operations = SAPOperations(self.sap_client)
        self.config = config_settings
        
    async def sync_returns(self):
        """
        Main method to sync returns using Credit Note approach
        """
        try:
            logger.info("Starting returns sync V3 - Credit Note approach")
            
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
            
            logger.info(f"Returns sync V3 completed. Processed: {total_processed}, Success: {total_successful}, Errors: {total_errors}")
            
            return {
                "msg": "success",
                "processed": total_processed,
                "successful": total_successful,
                "errors": total_errors
            }
                
        except Exception as e:
            logger.error(f"Error in returns sync V3: {str(e)}")
            return {
                "msg": "failure",
                "error": str(e)
            }

    async def get_orders_from_shopify(self, store_key: str) -> Dict[str, Any]:
        """
        Get refunded orders from Shopify store that need to be processed
        """
        max_retries = 3
        base_delay = 2  # seconds
        #(financial_status:refunded OR financial_status:partially_refunded OR return_status:RETURNED)
        for attempt in range(max_retries):
            try:
                # Query for refunded orders that need processing
                filter_query = (
                    f"""channel:{self.config.returns_channel}
                    fulfillment_status:fulfilled 
                    -financial_status:PENDING -financial_status:VOIDED -return_status:NO_RETURN 
                    (financial_status:refunded OR financial_status:partially_refunded OR return_status:RETURNED)
                    tag:sap_invoice_synced 
                    -tag:sap_return_synced
                    -tag:sap_return_failed
                    created_at:>={self.config.returns_from_date}"""
                )
                
                query = """
                query getOrders($first: Int!, $after: String, $query: String) {
                    orders(first: $first, after: $after, sortKey: CREATED_AT, reverse: false, query: $query) {
                        edges {
                            node {
                                id
                                name
                                createdAt
                                displayFinancialStatus
                                displayFulfillmentStatus
                                sourceName
                                sourceIdentifier
                                retailLocation {
                                    id
                                }
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
                                        firstName
                                        lastName
                                        company
                                    }
                                }
                                tags
                                lineItems(first: 50) {
                                    edges {
                                        node {
                                            id
                                            name
                                            quantity
                                            currentQuantity
                                            sku
                                            isGiftCard
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
                
                result = await self.shopify_client.execute_query(
                    store_key,
                    query,
                    {
                        "first": self.config.returns_batch_size,
                        "after": None,
                        "query": filter_query
                    }
                )
                
                if result.get("msg") == "success" and "data" in result:
                    orders = result["data"].get("orders", {}).get("edges", [])
                    logger.info(f"Retrieved {len(orders)} refunded orders from Shopify store {store_key}")
                    return result["data"]
                else:
                    error_msg = result.get("error", "Unknown error") if result else "No response"
                    logger.warning(f"GraphQL query attempt {attempt + 1} failed: {error_msg}")
                    
                    if attempt < max_retries - 1:
                        wait_time = base_delay * (2 ** attempt)
                        logger.info(f"Retrying in {wait_time} seconds...")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"All {max_retries} attempts failed")
                        return {"orders": {"edges": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}
                        
            except Exception as e:
                logger.error(f"GraphQL query attempt {attempt + 1} exception: {str(e)}")
                if attempt < max_retries - 1:
                    wait_time = base_delay * (2 ** attempt)
                    await asyncio.sleep(wait_time)
                else:
                    return {"orders": {"edges": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        
        return {"orders": {"edges": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}

    async def _process_store_returns(self, store_key: str, store_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process returns for a specific store
        """
        try:
            orders_result = await self.get_orders_from_shopify(store_key)
            orders = orders_result.get("orders", {}).get("edges", [])
            
            if not orders:
                logger.info(f"No refunded orders to process for store {store_key}")
                return {"processed": 0, "successful": 0, "errors": 0}
            
            processed = 0
            successful = 0
            errors = 0
            
            for order_edge in orders:
                order = order_edge.get("node", {})
                try:
                    result = await self._process_refunded_order(order, store_key, store_config)
                    processed += 1
                    if result.get("success"):
                        successful += 1
                    else:
                        errors += 1
                except Exception as e:
                    logger.error(f"Error processing order {order.get('name', 'Unknown')}: {str(e)}")
                    errors += 1
            
            return {
                "processed": processed,
                "successful": successful,
                "errors": errors
            }
            
        except Exception as e:
            logger.error(f"Error processing store returns for {store_key}: {str(e)}")
            return {"processed": 0, "successful": 0, "errors": 1}

    def _determine_scenario(self, order: Dict[str, Any]) -> str:
        """
        Determine which scenario based on financial status
        Returns: "refund" (Scenario 2) or "store_credit" (Scenario 1)
        """
        financial_status = order.get("displayFinancialStatus", "").upper()
        
        if financial_status == "REFUNDED":
            logger.info(f"Order {order.get('name', '')} is REFUNDED - Scenario 2: Actual Refund")
            return "refund"
        else:
            logger.info(f"Order {order.get('name', '')} is {financial_status} - Scenario 1: Store Credit/Gift Card")
            return "store_credit"

    async def _process_refunded_order(self, order: Dict[str, Any], store_key: str, store_config: Dict[str, Any]):
        """
        Process a single refunded order
        Handles idempotency - checks for existing documents and continues from where it left off
        """
        try:
            order_id = order.get("id", "")
            order_name = order.get("name", "")
            
            logger.info(f"🔄 Processing refunded order: {order_name} (ID: {order_id})")
            
            # Check if already fully synced
            tags = order.get("tags", [])
            if "sap_return_synced" in tags:
                logger.info(f"Order {order_name} already fully synced, skipping")
                return {"success": True, "skipped": True, "reason": "Already synced"}
            
            # Determine scenario
            scenario = self._determine_scenario(order)
            
            # Extract SAP document entries from tags
            sap_doc_entries = self._extract_sap_doc_entries(order)
            if not sap_doc_entries or "invoice" not in sap_doc_entries:
                logger.error(f"No SAP invoice entry found in tags for order {order_name}")
                await self._add_order_tag_with_retry(order_id, "sap_return_failed", store_key)
                return {"success": False, "error": "No SAP invoice entry found"}
            
            # Check for existing credit note
            existing_cn_entry = self._get_existing_credit_note_entry(order)
            
            if existing_cn_entry:
                logger.info(f"Found existing Credit Note {existing_cn_entry} for order {order_name}, reusing it")
                # Fetch credit note details from SAP (including DocDate and SalesPersonCode)
                cn_result = await self.sap_client._make_request(
                    method='GET',
                    endpoint=f'CreditNotes({existing_cn_entry})',
                    params={"$select": "DocEntry,DocTotal,TransNum,CardCode,DocDate,SalesPersonCode"}
                )
                
                if cn_result.get("msg") == "success":
                    credit_note_data = cn_result["data"]
                    credit_note_doc_entry = int(existing_cn_entry)
                    credit_note_total = credit_note_data.get("DocTotal", 0)
                    logger.info(f"✅ Reusing Credit Note {credit_note_doc_entry} with total {credit_note_total}")
                else:
                    logger.error(f"Failed to fetch existing credit note {existing_cn_entry}: {cn_result.get('error')}")
                    await self._add_order_tag_with_retry(order_id, "sap_return_failed", store_key)
                    return {"success": False, "error": f"Failed to fetch existing credit note: {cn_result.get('error')}"}
                
                # If SalesPersonCode not in credit note, get it from original invoice
                if not credit_note_data.get("SalesPersonCode"):
                    invoice_entry = sap_doc_entries["invoice"]
                    invoice_result = await self._get_original_invoice(invoice_entry)
                    if invoice_result.get("success"):
                        original_sales_person_code = invoice_result.get("sales_person_code")
                        if original_sales_person_code:
                            logger.info(f"SalesPersonCode not in credit note, using from original invoice: {original_sales_person_code}")
                            credit_note_data["SalesPersonCode"] = original_sales_person_code
                
                # Get original payment details for scenario processing
                original_payment_details = await self._get_original_payment_details(sap_doc_entries, order_name, order_id, store_key)
            else:
                # No existing credit note, create new one
                invoice_entry = sap_doc_entries["invoice"]
                invoice_result = await self._get_original_invoice(invoice_entry)
                if not invoice_result.get("success"):
                    logger.error(f"Failed to fetch original invoice {invoice_entry}: {invoice_result.get('error')}")
                    await self._add_order_tag_with_retry(order_id, "sap_return_failed", store_key)
                    return {"success": False, "error": f"Failed to fetch invoice: {invoice_result.get('error')}"}
                
                invoice_data = invoice_result["data"]
                document_status = invoice_result.get("document_status")
                customer_card_code = invoice_result.get("card_code")
                original_sales_person_code = invoice_result.get("sales_person_code")
                
                if not customer_card_code:
                    logger.error(f"No CardCode found in invoice {invoice_entry}")
                    await self._add_order_tag_with_retry(order_id, "sap_return_failed", store_key)
                    return {"success": False, "error": "No CardCode found in invoice"}
                
                # Check document status and reopen if needed
                mapping = False
                if document_status == "bost_Open":
                    logger.info(f"Invoice {invoice_entry} is already open, proceeding with BaseEntry mapping")
                    mapping = True
                else:
                    logger.info(f"Invoice {invoice_entry} is closed (status: {document_status}), attempting to reopen")
                    reopen_success = await self.reopen_sap_invoice(invoice_entry)
                    if reopen_success:
                        mapping = True
                        logger.info(f"✅ Successfully reopened invoice {invoice_entry}, will use BaseEntry mapping")
                    else:
                        logger.warning(f"⚠️ Failed to reopen invoice {invoice_entry}, proceeding without BaseEntry mapping")
                        mapping = False
                
                # Get original payment details (NO cancellation)
                original_payment_details = await self._get_original_payment_details(sap_doc_entries, order_name, order_id, store_key)
                
                # Extract returned items using currentQuantity logic
                returned_items = self._extract_returned_items(order, invoice_result)
                if not returned_items:
                    logger.warning(f"No returned items found for order {order_name}")
                    await self._add_order_tag_with_retry(order_id, "sap_return_failed", store_key)
                    return {"success": False, "error": "No returned items found"}
                
                # Create Credit Note for returned items (pass SalesPersonCode from original invoice)
                credit_note_result = await self._create_credit_note(
                    order, invoice_result, returned_items, customer_card_code, store_key, mapping, original_sales_person_code
                )
                
                if not credit_note_result.get("success"):
                    logger.error(f"Failed to create credit note: {credit_note_result.get('error')}")
                    await self._add_order_tag_with_retry(order_id, "sap_return_failed", store_key)
                    return {"success": False, "error": f"Failed to create credit note: {credit_note_result.get('error')}"}
                
                credit_note_doc_entry = credit_note_result["doc_entry"]
                credit_note_data = credit_note_result["data"]
                credit_note_total = credit_note_data.get("DocTotal", 0)
                
                logger.info(f"✅ Created Credit Note {credit_note_doc_entry} with total {credit_note_total}")
                
                # Add credit note tag
                await self._add_order_tag_with_retry(order_id, f"sap_return_cn_{credit_note_doc_entry}", store_key)
            
            # Process based on scenario
            if scenario == "refund":
                # Scenario 2: Create Outgoing Payment
                result = await self._process_scenario_2_refund(
                    order, credit_note_doc_entry, credit_note_data, original_payment_details, store_key
                )
            else:
                # Scenario 1: Create Gift Card Invoice and Reconcile
                result = await self._process_scenario_1_store_credit(
                    order, credit_note_doc_entry, credit_note_data, credit_note_total, 
                    original_payment_details, store_key, store_config
                )
            
            if result.get("success"):
                await self._add_order_tag_with_retry(order_id, "sap_return_synced", store_key)
                logger.info(f"✅ Successfully processed return for order {order_name}")
            else:
                await self._add_order_tag_with_retry(order_id, "sap_return_failed", store_key)
                logger.error(f"Failed to process return for order {order_name}: {result.get('error')}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing refunded order {order.get('name', 'Unknown')}: {str(e)}")
            await self._add_order_tag_with_retry(order.get("id", ""), "sap_return_failed", store_key)
            return {"success": False, "error": str(e)}

    async def _process_scenario_1_store_credit(
        self, order: Dict[str, Any], credit_note_doc_entry: int, credit_note_data: Dict[str, Any],
        credit_note_total: float, original_payment_details: Dict[str, Any], 
        store_key: str, store_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Scenario 1: Create Gift Card Invoice and Reconcile with Credit Note
        Handles idempotency - checks for existing gift card invoice and continues from where it left off
        """
        try:
            order_id = order.get("id", "")
            order_name = order.get("name", "")
            
            logger.info(f"📋 Scenario 1: Processing store credit return for order {order_name}")
            logger.info(f"Credit Note total: {credit_note_total}")
            
            # Extract Credit Note DocDate to use for Gift Card Invoice
            credit_note_doc_date = credit_note_data.get("DocDate")
            if not credit_note_doc_date:
                # If not in data, use today's date (same as Credit Note creation)
                credit_note_doc_date = datetime.now().strftime("%Y-%m-%d")
                logger.info(f"Credit Note DocDate not found in data, using today's date: {credit_note_doc_date}")
            else:
                logger.info(f"Using Credit Note DocDate: {credit_note_doc_date}")
            
            # Extract SalesPersonCode from Credit Note (or will get from original invoice if not available)
            credit_note_sales_person = credit_note_data.get("SalesPersonCode")
            if not credit_note_sales_person:
                # Try to get from original invoice if not in credit note
                # This should have been handled above, but just in case
                logger.warning(f"SalesPersonCode not found in credit note, will use location default")
            
            # Check for existing gift card invoice
            existing_invoice_entry = self._get_existing_gift_card_invoice_entry(order)
            
            if existing_invoice_entry:
                logger.info(f"Found existing Gift Card Invoice {existing_invoice_entry} for order {order_name}, reusing it")
                # Fetch invoice details from SAP
                invoice_result = await self.sap_client._make_request(
                    method='GET',
                    endpoint=f'Invoices({existing_invoice_entry})',
                    params={"$select": "DocEntry,DocTotal,TransNum,CardCode"}
                )
                
                if invoice_result.get("msg") == "success":
                    invoice_data = invoice_result["data"]
                    invoice_doc_entry = int(existing_invoice_entry)
                    invoice_trans_num = invoice_data.get("TransNum")
                    logger.info(f"✅ Reusing Gift Card Invoice {invoice_doc_entry}")
                else:
                    logger.error(f"Failed to fetch existing invoice {existing_invoice_entry}: {invoice_result.get('error')}")
                    return {"success": False, "error": f"Failed to fetch existing invoice: {invoice_result.get('error')}"}
            else:
                # No existing invoice, proceed with gift card and invoice creation
                # Determine if order is online/web or POS
                is_pos_order = self._is_pos_order(order, store_key)
                
                gift_card_id = None
                
                if is_pos_order:
                    # For POS orders, find existing gift cards by matching amount
                    logger.info(f"POS order detected, searching for matching gift card")
                    order_id_numeric = order_id.split("/")[-1]
                    gift_cards = await self._get_gift_cards_for_order(order_id_numeric, order.get("createdAt", ""))
                    matching_gift_card = None
                    for gift_card in gift_cards:
                        if abs(gift_card["initial_value"] - credit_note_total) < 0.01:
                            matching_gift_card = gift_card
                            break
                    
                    if not matching_gift_card:
                        logger.error(f"No matching gift card found for POS order {order_name}")
                        return {"success": False, "error": "No matching gift card found"}
                    
                    gift_card_id = matching_gift_card["id"]
                    logger.info(f"Found matching gift card {gift_card_id} for POS order")
                else:
                    # For online/web orders, check if gift card already exists and is linked to order
                    logger.info(f"Online/web order detected, checking for existing gift card linked to order")
                    order_id_numeric = order_id.split("/")[-1]
                    gift_cards = await self._get_gift_cards_for_order(order_id_numeric, order.get("createdAt", ""))
                    
                    if gift_cards:
                        # Use the first gift card found that's linked to this order
                        gift_card_id = gift_cards[0]["id"]
                        logger.info(f"Found existing gift card {gift_card_id} linked to order {order_name}")
                    else:
                        # No gift card found, create new one with Credit Note total
                        logger.info(f"No existing gift card found, creating new gift card with amount {credit_note_total}")
                        gift_card_id = await self._create_shopify_gift_card_for_amount(
                            order, credit_note_total, store_key
                        )
                        if not gift_card_id:
                            logger.error(f"Failed to create gift card for order {order_name}")
                            return {"success": False, "error": "Failed to create gift card"}
                        await self._add_order_tag_with_retry(order_id, f"giftcard_{gift_card_id}", store_key)
                
                # Create Gift Card Invoice (ONLY gift card line, amount = Credit Note total)
                # Use Credit Note DocDate and SalesPersonCode for the invoice
                gift_card_invoice_result = await self._create_gift_card_invoice(
                    order, gift_card_id, credit_note_total, original_payment_details, 
                    store_key, store_config, doc_date=credit_note_doc_date, 
                    sales_person_code=credit_note_sales_person
                )
                
                if not gift_card_invoice_result.get("success"):
                    logger.error(f"Failed to create gift card invoice: {gift_card_invoice_result.get('error')}")
                    return {"success": False, "error": f"Failed to create gift card invoice: {gift_card_invoice_result.get('error')}"}
                
                invoice_doc_entry = gift_card_invoice_result["doc_entry"]
                invoice_data = gift_card_invoice_result["data"]
                invoice_trans_num = invoice_data.get("TransNum")
                
                logger.info(f"✅ Created Gift Card Invoice {invoice_doc_entry}")
                await self._add_order_tag_with_retry(order_id, f"sap_giftcard_invoice_{invoice_doc_entry}", store_key)
                await self._add_order_tag_with_retry(order_id, "sap_giftcard_invoice_synced", store_key)
            
            # Attempt reconciliation (will handle if already reconciled)
            reconciliation_result = await self._reconcile_credit_note_with_invoice(
                credit_note_doc_entry, credit_note_data.get("TransNum"),
                invoice_doc_entry, invoice_trans_num,
                invoice_data.get("CardCode"), credit_note_total
            )
            
            if reconciliation_result.get("success"):
                logger.info(f"✅ Successfully reconciled Credit Note {credit_note_doc_entry} with Invoice {invoice_doc_entry}")
                return {
                    "success": True,
                    "credit_note_entry": credit_note_doc_entry,
                    "invoice_entry": invoice_doc_entry,
                    "reconciliation_id": reconciliation_result.get("reconciliation_id")
                }
            else:
                logger.warning(f"⚠️ Reconciliation failed: {reconciliation_result.get('error')}")
                return {
                    "success": False,
                    "error": f"Reconciliation failed: {reconciliation_result.get('error')}",
                    "credit_note_entry": credit_note_doc_entry,
                    "invoice_entry": invoice_doc_entry
                }
                
        except Exception as e:
            logger.error(f"Error in Scenario 1 processing: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _process_scenario_2_refund(
        self, order: Dict[str, Any], credit_note_doc_entry: int, credit_note_data: Dict[str, Any],
        original_payment_details: Dict[str, Any], store_key: str
    ) -> Dict[str, Any]:
        """
        Scenario 2: Create Outgoing Payment for Credit Note
        """
        try:
            order_id = order.get("id", "")
            order_name = order.get("name", "")
            
            logger.info(f"💰 Scenario 2: Processing actual refund for order {order_name}")
            
            if not original_payment_details:
                logger.error(f"No original payment details found for order {order_name}")
                return {"success": False, "error": "No original payment details found"}
            
            # Create Outgoing Payment (VendorPayments)
            outgoing_payment_result = await self._create_outgoing_payment(
                order, credit_note_doc_entry, credit_note_data, original_payment_details, store_key
            )
            
            if not outgoing_payment_result.get("success"):
                logger.error(f"Failed to create outgoing payment: {outgoing_payment_result.get('error')}")
                return {"success": False, "error": f"Failed to create outgoing payment: {outgoing_payment_result.get('error')}"}
            
            payment_doc_entry = outgoing_payment_result["doc_entry"]
            logger.info(f"✅ Created Outgoing Payment {payment_doc_entry} for Credit Note {credit_note_doc_entry}")
            
            await self._add_order_tag_with_retry(order_id, f"sap_outgoing_payment_{payment_doc_entry}", store_key)
            
            return {
                "success": True,
                "credit_note_entry": credit_note_doc_entry,
                "outgoing_payment_entry": payment_doc_entry
            }
            
        except Exception as e:
            logger.error(f"Error in Scenario 2 processing: {str(e)}")
            return {"success": False, "error": str(e)}

    # Common Methods
    def _extract_sap_doc_entries(self, order: Dict[str, Any]) -> Dict[str, str]:
        """
        Extract SAP document entries from order tags
        """
        tags = order.get("tags", [])
        doc_entries = {}
        
        for tag in tags:
            if tag.startswith("sap_invoice_") and not tag.endswith("_synced"):
                doc_entries["invoice"] = tag.replace("sap_invoice_", "")
            elif tag.startswith("sap_payment_") and not tag.endswith("_synced"):
                doc_entries["payment"] = tag.replace("sap_payment_", "")
                
        return doc_entries

    def _get_existing_credit_note_entry(self, order: Dict[str, Any]) -> Optional[str]:
        """Check if credit note already exists for this order"""
        tags = order.get("tags", [])
        for tag in tags:
            if tag.startswith("sap_return_cn_"):
                return tag.replace("sap_return_cn_", "")
        return None

    def _get_existing_gift_card_invoice_entry(self, order: Dict[str, Any]) -> Optional[str]:
        """Check if gift card invoice already exists for this order"""
        tags = order.get("tags", [])
        for tag in tags:
            if tag.startswith("sap_giftcard_invoice_") and not tag.endswith("_synced"):
                invoice_entry = tag.replace("sap_giftcard_invoice_", "")
                # Validate that it's a numeric invoice entry (not a word like "failed")
                if invoice_entry.isdigit():
                    return invoice_entry
                else:
                    logger.warning(f"Invalid gift card invoice tag found: {tag}, skipping")
        return None

    async def _get_original_invoice(self, invoice_entry: str) -> Dict[str, Any]:
        """
        Get original invoice from SAP (NO cancellation)
        Fetches all invoice line fields including warehouse, costing codes, and bin allocations
        """
        try:
            logger.info(f"Fetching original invoice {invoice_entry} with all line item details")
            
            result = await self.sap_client._make_request(
                method='GET',
                endpoint=f'Invoices({invoice_entry})',
                params={
                    "$select": "DocEntry,DocNum,DocTotal,CardCode,DocDate,TransNum,DocumentStatus,DocumentLines,SalesPersonCode"                    
                }
            )
            
            if result["msg"] == "success":
                invoice_data = result["data"]
                # Ensure DocEntry is in the data structure for _extract_returned_items
                invoice_data_with_doc_entry = invoice_data.copy()
                invoice_data_with_doc_entry["DocEntry"] = invoice_entry
                return {
                    "success": True,
                    "data": invoice_data_with_doc_entry,
                    "card_code": invoice_data.get("CardCode"),
                    "document_status": invoice_data.get("DocumentStatus"),
                    "sales_person_code": invoice_data.get("SalesPersonCode"),
                    "document_lines": invoice_data.get("DocumentLines", [])
                }
            else:
                logger.error(f"Failed to fetch invoice {invoice_entry}: {result.get('error')}")
                return {"success": False, "error": result.get("error", "Unknown error")}
                
        except Exception as e:
            logger.error(f"Error fetching invoice {invoice_entry}: {str(e)}")
            return {"success": False, "error": str(e)}

    async def reopen_sap_invoice(self, invoice_entry: str) -> bool:
        """
        Reopen a closed SAP invoice
        """
        try:
            logger.info(f"Attempting to reopen SAP invoice {invoice_entry}")
            
            # Make POST request to reopen invoice
            response = await self.sap_client._make_request(
                method="POST",
                endpoint=f"Invoices({invoice_entry})/Reopen"
            )
            
            if response.get("msg") == "success":
                logger.info(f"✅ Successfully reopened invoice {invoice_entry}")
                return True
            else:
                logger.error(f"Failed to reopen invoice {invoice_entry}: {response.get('error')}")
                return False
                
        except Exception as e:
            logger.error(f"Error reopening invoice {invoice_entry}: {str(e)}")
            return False

    async def _get_original_payment_details(
        self, sap_doc_entries: Dict[str, str], order_name: str, order_id: str, store_key: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get original payment details from SAP (NO cancellation, just extract)
        """
        try:
            payment_details = None
            
            if "payment" in sap_doc_entries:
                payment_entry = sap_doc_entries["payment"]
                
                if payment_entry == "0000" or not payment_entry or payment_entry == "0":
                    logger.info(f"No payment entry for order {order_name}")
                    return {"_no_payment": True}
                
                logger.info(f"Getting payment details from {payment_entry} for order {order_name}")
                
                payment_result = await self.sap_client._make_request(
                    method='GET',
                    endpoint=f'IncomingPayments({payment_entry})',
                    params={
                        "$select": "TransferAccount,CashAccount,CardCode,CashSum,TransferSum,Series,Cancelled,PaymentCreditCards"
                    }
                )
                
                if payment_result["msg"] == "success":
                    payment_data = payment_result["data"]
                    
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
                    logger.warning(f"Failed to get payment details: {payment_result.get('error')}")
                    return None
            else:
                logger.info(f"No payment entry found in tags for order {order_name}")
                payment_details = {"_no_payment": True}
            
            return payment_details
            
        except Exception as e:
            logger.error(f"Error getting original payment details: {str(e)}")
            return None

    def _extract_returned_items(self, order: Dict[str, Any], invoice_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract returned items using currentQuantity logic
        Returns items where currentQuantity < quantity (meaning they were returned)
        Note: BaseEntry mapping is handled in _create_credit_note based on mapping flag
        """
        returned_items = []
        line_items = order.get("lineItems", {}).get("edges", [])
        
        for item_edge in line_items:
            item = item_edge.get("node", {})
            quantity = item.get("quantity", 0)
            current_quantity = item.get("currentQuantity", quantity)
            
            # If currentQuantity < quantity, item was returned
            if current_quantity < quantity:
                returned_qty = quantity - current_quantity
                
                # Get pricing information
                original_price = Decimal("0.00")
                sale_price = Decimal("0.00")
                
                if item.get("originalUnitPriceSet") and item["originalUnitPriceSet"].get("shopMoney"):
                    original_unit_price = Decimal(item["originalUnitPriceSet"]["shopMoney"]["amount"])
                    
                    if item.get("discountedUnitPriceSet") and item["discountedUnitPriceSet"].get("shopMoney"):
                        discounted_unit_price = Decimal(item["discountedUnitPriceSet"]["shopMoney"]["amount"])
                        sale_price = discounted_unit_price
                        
                        if discounted_unit_price < original_unit_price:
                            original_price = original_unit_price
                        else:
                            if item.get("variant") and item["variant"].get("compareAtPrice"):
                                variant_compare = Decimal(item["variant"]["compareAtPrice"])
                                if variant_compare > discounted_unit_price:
                                    original_price = variant_compare
                                else:
                                    original_price = original_unit_price
                            else:
                                original_price = original_unit_price
                    else:
                        if item.get("variant") and item["variant"].get("compareAtPrice"):
                            variant_compare = Decimal(item["variant"]["compareAtPrice"])
                            if variant_compare > original_unit_price:
                                original_price = variant_compare
                                sale_price = original_unit_price
                            else:
                                original_price = original_unit_price
                                sale_price = original_unit_price
                        else:
                            original_price = original_unit_price
                            sale_price = original_unit_price
                elif item.get("variant") and item["variant"].get("compareAtPrice"):
                    original_price = Decimal(item["variant"]["compareAtPrice"])
                    if item.get("variant") and item["variant"].get("price"):
                        sale_price = Decimal(item["variant"]["price"])
                    else:
                        sale_price = original_price
                elif item.get("variant") and item["variant"].get("price"):
                    original_price = Decimal(item["variant"]["price"])
                    sale_price = original_price
                
                # Get item code
                sku = item.get("sku")
                if sku:
                    item_code = sku
                elif item.get("variant") and item["variant"].get("sku"):
                    item_code = item["variant"]["sku"]
                else:
                    item_code = "ACC-0000001"
                
                returned_item = {
                    "ItemCode": item_code,
                    "Quantity": returned_qty,
                    "UnitPrice": float(original_price)
                }
                
                # Calculate discount if applicable
                if original_price > 0 and sale_price > 0 and original_price != sale_price:
                    discount_amount = original_price - sale_price
                    discount_percentage = (discount_amount / original_price) * 100
                    returned_item["DiscountPercent"] = float(discount_percentage)
                
                # Note: BaseEntry mapping will be added in _create_credit_note if mapping=True
                
                returned_items.append(returned_item)
                logger.info(f"Found returned item: {item_code}, Qty: {returned_qty}/{quantity}, Price: {original_price}")
        
        return returned_items

    async def _create_credit_note(
        self, order: Dict[str, Any], invoice_result: Dict[str, Any], 
        returned_items: List[Dict[str, Any]], customer_card_code: str, 
        store_key: str, mapping: bool = False, sales_person_code: int = None
    ) -> Dict[str, Any]:
        """
        Create Credit Note for returned items
        Copies warehouse code, costing codes, and bin allocations from original invoice lines
        - mapping: If True, add BaseEntry mapping to original invoice lines
        """
        try:
            order_name = order.get("name", "")
            order_id = order.get("id", "").split("/")[-1]
            invoice_data = invoice_result.get("data", {})
            invoice_lines = invoice_result.get("document_lines", [])
            
            # Create a map of ItemCode -> invoice line for copying all fields
            invoice_line_map = {}
            for inv_line in invoice_lines:
                item_code = inv_line.get("ItemCode")
                if item_code:
                    invoice_line_map[item_code] = inv_line
            
            invoice_doc_entry = invoice_data.get("DocEntry")
            
            # Copy fields from invoice lines to returned items
            for returned_item in returned_items:
                item_code = returned_item.get("ItemCode")
                
                if item_code in invoice_line_map:
                    invoice_line = invoice_line_map[item_code]
                    
                    # Copy warehouse code
                    if invoice_line.get("WarehouseCode"):
                        returned_item["WarehouseCode"] = invoice_line.get("WarehouseCode")
                    
                    # Copy costing codes
                    if invoice_line.get("COGSCostingCode"):
                        returned_item["COGSCostingCode"] = invoice_line.get("COGSCostingCode")
                    if invoice_line.get("COGSCostingCode2"):
                        returned_item["COGSCostingCode2"] = invoice_line.get("COGSCostingCode2")
                    if invoice_line.get("COGSCostingCode3"):
                        returned_item["COGSCostingCode3"] = invoice_line.get("COGSCostingCode3")
                    if invoice_line.get("CostingCode"):
                        returned_item["CostingCode"] = invoice_line.get("CostingCode")
                    if invoice_line.get("CostingCode2"):
                        returned_item["CostingCode2"] = invoice_line.get("CostingCode2")
                    if invoice_line.get("CostingCode3"):
                        returned_item["CostingCode3"] = invoice_line.get("CostingCode3")
                    
                    # Copy bin allocations from invoice line and adjust quantity to match returned quantity
                    if invoice_line.get("DocumentLinesBinAllocations"):
                        bin_allocations = invoice_line.get("DocumentLinesBinAllocations")
                        returned_qty = returned_item.get("Quantity", 0)
                        
                        # Adjust bin allocation quantities to match returned quantity
                        adjusted_bin_allocations = []
                        for bin_alloc in bin_allocations:
                            adjusted_bin_alloc = bin_alloc.copy()
                            adjusted_bin_alloc["Quantity"] = returned_qty
                            adjusted_bin_allocations.append(adjusted_bin_alloc)
                        
                        returned_item["DocumentLinesBinAllocations"] = adjusted_bin_allocations
                        logger.info(f"Copied bin allocations from invoice line for {item_code} (adjusted quantity to {returned_qty})")
                    
                    # Add BaseEntry mapping if mapping=True (invoice is open/reopened)
                    if mapping and invoice_doc_entry:
                        returned_item["BaseEntry"] = int(invoice_doc_entry)
                        returned_item["BaseType"] = 13  # Invoice document type
                        returned_item["BaseLine"] = invoice_line.get("LineNum")
                        logger.info(f"Added BaseEntry mapping for {item_code}: BaseEntry={invoice_doc_entry}, BaseLine={invoice_line.get('LineNum')}")
                    
                    logger.info(f"Copied invoice line fields for {item_code}: Warehouse={returned_item.get('WarehouseCode')}, CostingCodes={returned_item.get('COGSCostingCode')}/{returned_item.get('COGSCostingCode2')}/{returned_item.get('COGSCostingCode3')}")
                else:
                    logger.warning(f"No matching invoice line found for {item_code}, credit note line will have minimal fields")
            
            # Get location analysis ONLY for series (not for warehouse/costing codes)
            location_analysis = self._analyze_order_location_from_retail_location(order, store_key)
            
            # Prepare credit note header
            credit_note = {
                "CardCode": customer_card_code,
                "DocDate": datetime.now().strftime("%Y-%m-%d"),
                "Comments": f"Return for Shopify Order {order_name}",
                "Series": self.config.get_series_for_location(
                    store_key, 
                    location_analysis.get('location_mapping', {}), 
                    'credit_notes'
                ),
                "U_ShopifyOrderID": order_id,
                "DocumentLines": returned_items
            }
            
            # Add SalesPersonCode from original invoice if provided
            if sales_person_code:
                credit_note["SalesPersonCode"] = sales_person_code
                logger.info(f"Using SalesPersonCode from original invoice: {sales_person_code}")
            
            logger.info(f"Creating Credit Note with {len(returned_items)} line items")
            
            # Create credit note in SAP
            result = await self.sap_client._make_request(
                method='POST',
                endpoint='CreditNotes',
                data=credit_note
            )
            
            if result["msg"] == "success":
                credit_note_data = result["data"]
                doc_entry = credit_note_data.get("DocEntry")
                logger.info(f"✅ Successfully created Credit Note {doc_entry}")
                return {
                    "success": True,
                    "doc_entry": doc_entry,
                    "data": credit_note_data
                }
            else:
                logger.error(f"Failed to create credit note: {result.get('error')}")
                return {"success": False, "error": result.get("error", "Unknown error")}
                
        except Exception as e:
            logger.error(f"Error creating credit note: {str(e)}")
            return {"success": False, "error": str(e)}

    # Scenario 1 Methods
    async def _create_gift_card_invoice(
        self, order: Dict[str, Any], gift_card_id: str, total_amount: float,
        original_payment_details: Dict[str, Any], store_key: str, store_config: Dict[str, Any],
        doc_date: str = None, sales_person_code: int = None
    ) -> Dict[str, Any]:
        """
        Create Gift Card Invoice with ONLY gift card line item
        Amount = Credit Note total
        doc_date: Optional DocDate to use (should match Credit Note DocDate). If not provided, uses order creation date.
        sales_person_code: Optional SalesPersonCode from original invoice or credit note. If not provided, uses location default.
        """
        try:
            order_name = order.get("name", "")
            customer_card_code = original_payment_details.get("CardCode")
            
            if not customer_card_code:
                logger.error(f"No CardCode found in payment details for order {order_name}")
                return {"success": False, "error": "No CardCode found"}
            
            # Prepare gift card data for invoice line
            sap_gift_card_id = await self._prepare_gift_card_for_invoice(
                gift_card_id, total_amount, customer_card_code, "SW"
            )
            
            if not sap_gift_card_id:
                logger.error(f"Failed to prepare gift card data for invoice")
                return {"success": False, "error": "Failed to prepare gift card data"}
            
            # Get gift card item code from configuration
            gift_card_item_code = self.config.get_gift_card_item_code()
            if not gift_card_item_code:
                logger.error("Gift card item code not found in configuration")
                return {"success": False, "error": "Gift card item code not found"}
            
            # Get location analysis
            location_analysis = self._analyze_order_location_from_retail_location(order, store_key)
            sap_codes = location_analysis.get('sap_codes', {})
            
            default_codes = {
                'COGSCostingCode': 'ONL',
                'COGSCostingCode2': 'SAL', 
                'COGSCostingCode3': 'OnlineS',
                'CostingCode': 'ONL',
                'CostingCode2': 'SAL',
                'CostingCode3': 'OnlineS'
            }
            
            costing_codes = {key: sap_codes.get(key, default_codes[key]) for key in default_codes.keys()}
            warehouse_code = sap_codes.get('Warehouse', 'SW')
            
            # Use provided doc_date (from Credit Note) or fall back to order creation date
            if not doc_date:
                order_created_at = order.get("createdAt", "")
                parsed_date = datetime.fromisoformat(order_created_at.replace('Z', '+00:00'))
                doc_date = parsed_date.strftime("%Y-%m-%d")
            else:
                logger.info(f"Using Credit Note DocDate for Gift Card Invoice: {doc_date}")
            
            gift_card_line = {
                "ItemCode": gift_card_item_code,
                "Quantity": 1,
                "UnitPrice": total_amount,
                "WarehouseCode": warehouse_code,
                "U_GiftCard": sap_gift_card_id,
                "COGSCostingCode": costing_codes['COGSCostingCode'],
                "COGSCostingCode2": costing_codes['COGSCostingCode2'],
                "COGSCostingCode3": costing_codes['COGSCostingCode3'],
                "CostingCode": costing_codes['CostingCode'],
                "CostingCode2": costing_codes['CostingCode2'],
                "CostingCode3": costing_codes['CostingCode3']
            }
            
            invoice_data = {
                "DocDate": doc_date,
                "CardCode": customer_card_code,
                "NumAtCard": order_name.replace("#", ""),
                "Series": self.config.get_series_for_location(
                    store_key,
                    location_analysis.get('location_mapping', {}),
                    'invoices'
                ),
                "Comments": f"Gift Card Invoice for Return - Order {order_name}",
                "DocumentLines": [gift_card_line],
                "U_Pay_type": 1,  # PAID
                "U_Shopify_Order_ID": order.get("id", "").split("/")[-1] if "/" in order.get("id", "") else order.get("id", ""),
                "U_OrderType": "1",
                "ImportFileNum": order_name.replace("#", ""),
                "DocCurrency": self.config.get_currency_for_store(store_key)
            }
            
            # Add SalesPersonCode if provided (from original invoice or credit note)
            if sales_person_code:
                invoice_data["SalesPersonCode"] = sales_person_code
                logger.info(f"Using SalesPersonCode from original invoice/credit note: {sales_person_code}")
            else:
                # Fallback to location default
                default_sales_person = location_analysis.get('location_mapping', {}).get('sales_employee', 28)
                invoice_data["SalesPersonCode"] = default_sales_person
                logger.info(f"Using default SalesPersonCode from location: {default_sales_person}")
            
            logger.info(f"Creating Gift Card Invoice with amount {total_amount}")
            
            # Create invoice using SAP operations
            result = await self.sap_operations.create_invoice_in_sap(invoice_data, order_name)
            
            if result["msg"] == "success":
                logger.info(f"✅ Successfully created Gift Card Invoice {result.get('sap_doc_entry')}")
                return {
                    "success": True,
                    "doc_entry": result.get('sap_doc_entry'),
                    "data": {
                        "DocEntry": result.get('sap_doc_entry'),
                        "DocNum": result.get('sap_doc_num'),
                        "DocTotal": total_amount,
                        "TransNum": result.get('sap_trans_num'),
                        "CardCode": customer_card_code
                    }
                }
            else:
                logger.error(f"Failed to create gift card invoice: {result.get('error')}")
                return {"success": False, "error": result.get("error", "Unknown error")}
                
        except Exception as e:
            logger.error(f"Error creating gift card invoice: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _reconcile_credit_note_with_invoice(
        self, credit_note_doc_entry: int, credit_note_trans_num: int,
        invoice_doc_entry: int, invoice_trans_num: int,
        customer_card_code: str, total_amount: float
    ) -> Dict[str, Any]:
        """
        Reconcile Credit Note with Gift Card Invoice
        """
        try:
            reconciliation_data = self._prepare_reconciliation_data(
                credit_note_doc_entry, credit_note_trans_num,
                invoice_doc_entry, invoice_trans_num,
                customer_card_code, total_amount
            )
            
            logger.info(f"Reconciling Credit Note {credit_note_doc_entry} with Invoice {invoice_doc_entry}")
            
            result = await self.sap_client._make_request(
                method='POST',
                endpoint='InternalReconciliations',
                data=reconciliation_data
            )
            
            if result["msg"] == "success":
                reconciliation_data_result = result["data"]
                reconciliation_id = reconciliation_data_result.get('ReconNum', '')
                logger.info(f"✅ Successfully created reconciliation {reconciliation_id}")
                return {
                    "success": True,
                    "reconciliation_id": reconciliation_id,
                    "data": reconciliation_data_result
                }
            else:
                logger.error(f"Failed to create reconciliation: {result.get('error')}")
                return {"success": False, "error": result.get("error", "Unknown error")}
                
        except Exception as e:
            logger.error(f"Error creating reconciliation: {str(e)}")
            return {"success": False, "error": str(e)}

    def _prepare_reconciliation_data(
        self, credit_note_doc_entry: int, credit_note_trans_num: int,
        invoice_doc_entry: int, invoice_trans_num: int,
        customer_card_code: str, total_amount: float
    ) -> Dict[str, Any]:
        """
        Prepare reconciliation data: Credit Note (credit) ↔ Invoice (debit)
        """
        reconciliation_rows = []
        
        # Credit Note row (credit)
        credit_row = {
            "ShortName": customer_card_code,
            "TransId": credit_note_trans_num,
            "TransRowId": 0,
            "SrcObjTyp": "14",  # Credit Note
            "SrcObjAbs": credit_note_doc_entry,
            "CreditOrDebit": "codCredit",
            "ReconcileAmount": total_amount,
            "Selected": "tYES"
        }
        reconciliation_rows.append(credit_row)
        
        # Invoice row (debit)
        invoice_row = {
            "ShortName": customer_card_code,
            "TransId": invoice_trans_num,
            "TransRowId": 0,
            "SrcObjTyp": "13",  # Invoice
            "SrcObjAbs": invoice_doc_entry,
            "CreditOrDebit": "codDebit",
            "ReconcileAmount": total_amount,
            "Selected": "tYES"
        }
        reconciliation_rows.append(invoice_row)
        
        return {
            "ReconDate": datetime.now().strftime("%Y-%m-%d"),
            "CardOrAccount": "coaCard",
            "InternalReconciliationOpenTransRows": reconciliation_rows
        }

    # Scenario 2 Methods
    async def _create_outgoing_payment(
        self, order: Dict[str, Any], credit_note_doc_entry: int, credit_note_data: Dict[str, Any],
        original_payment_details: Dict[str, Any], store_key: str
    ) -> Dict[str, Any]:
        """
        Create Outgoing Payment (VendorPayments) for Credit Note
        """
        try:
            order_name = order.get("name", "")
            credit_note_total = credit_note_data.get("DocTotal", 0)
            
            # Prepare payment data with InvoiceType="it_CreditNote" and DocType="rCustomer"
            payment_data = self._prepare_payment_data(
                original_payment_details, credit_note_doc_entry, credit_note_total,
                "it_CredItnote", order, store_key
            )
            
            logger.info(f"Creating Outgoing Payment for Credit Note {credit_note_doc_entry}")
            
            # Create outgoing payment using VendorPayments endpoint
            result = await self.sap_client._make_request(
                method='POST',
                endpoint='VendorPayments',
                data=payment_data
            )
            
            if result["msg"] == "success":
                payment_data_result = result["data"]
                doc_entry = payment_data_result.get("DocEntry")
                logger.info(f"✅ Successfully created Outgoing Payment {doc_entry}")
                return {
                    "success": True,
                    "doc_entry": doc_entry,
                    "data": payment_data_result
                }
            else:
                logger.error(f"Failed to create outgoing payment: {result.get('error')}")
                return {"success": False, "error": result.get("error", "Unknown error")}
                
        except Exception as e:
            logger.error(f"Error creating outgoing payment: {str(e)}")
            return {"success": False, "error": str(e)}

    def _prepare_payment_data(
        self, original_payment_details: Dict[str, Any], document_entry: int,
        total_amount: float, invoice_type: str, order: Dict[str, Any], store_key: str
    ) -> Dict[str, Any]:
        """
        Prepare payment data (incoming or outgoing)
        - invoice_type: "it_Invoice" for incoming, "it_CreditNote" for outgoing
        """
        # Copy original payment details
        payment_data = original_payment_details.copy()
        
        # Always set DocType
        payment_data["DocType"] = "rCustomer"
        
        # Use Credit Note DocDate
        credit_note_doc_date = datetime.now().strftime("%Y-%m-%d")
        payment_data["DocDate"] = credit_note_doc_date
        payment_data["TaxDate"] = credit_note_doc_date
        payment_data["DueDate"] = credit_note_doc_date
        
        payment_data["U_Shopify_Order_ID"] = order.get("id", "").split("/")[-1] if "/" in order.get("id", "") else order.get("id", "")
        
        # Get location mapping for series
        location_analysis = self._analyze_order_location_from_retail_location(order, store_key)
        location_mapping = location_analysis.get('location_mapping', {})
        
        # Set Series using outgoing_payments series from config
        payment_data["Series"] = self.config.get_series_for_location(
            store_key,
            location_mapping,
            'outgoing_payments'
        )
        
        # Rebuild PaymentCreditCards with only the same fields used in incoming payments (from orders_sync.py)
        if "PaymentCreditCards" in original_payment_details and original_payment_details["PaymentCreditCards"]:
            rebuilt_credit_cards = []
            for credit_card in original_payment_details["PaymentCreditCards"]:
                # Only include the same fields used in incoming payments
                cred_obj = {
                    "CreditCard": credit_card.get("CreditCard"),  # Account from original payment
                    "CreditCardNumber": "1234",  # Hardcoded same as incoming payments
                    "CardValidUntil": credit_card.get("CardValidUntil"),  # Keep original if exists
                    "VoucherNum": credit_card.get("VoucherNum"),  # Gateway from original payment
                    "PaymentMethodCode": 1,  # Hardcoded same as incoming payments
                    "CreditSum": credit_card.get("CreditSum"),  # Amount from original payment
                    "CreditCur": "EGP",  # Hardcoded same as incoming payments
                    "CreditType": "cr_Regular",  # Hardcoded same as incoming payments
                    "SplitPayments": "tNO"  # Hardcoded same as incoming payments
                }
                
                cred_obj['CreditAcct'] = config_settings.credit_cards[str(credit_card.get("CreditCard"))]
                
                # Calculate CardValidUntil if not present (same logic as incoming payments)
                if not cred_obj.get("CardValidUntil"):
                    from datetime import timedelta
                    next_month = datetime.now().replace(day=28) + timedelta(days=4)
                    res = next_month - timedelta(days=next_month.day)
                    cred_obj["CardValidUntil"] = str(res.date())
                
                rebuilt_credit_cards.append(cred_obj)
            
            payment_data["PaymentCreditCards"] = rebuilt_credit_cards
        
        # Calculate total sum from all payment methods
        total_sum = 0
        if "CashSum" in original_payment_details:
            total_sum += original_payment_details["CashSum"]
        if "TransferSum" in original_payment_details:
            total_sum += original_payment_details["TransferSum"]
        if "PaymentCreditCards" in payment_data:
            for credit_card in payment_data["PaymentCreditCards"]:
                total_sum += credit_card.get("CreditSum", 0)
        
        # Set PaymentInvoices with appropriate InvoiceType
        payment_data["PaymentInvoices"] = [{
            "DocEntry": document_entry,
            "SumApplied": total_sum,
            "InvoiceType": invoice_type  # "it_Invoice" or "it_CreditNote"
        }]
        
        logger.info(f"Prepared payment data - DocType: rCustomer, InvoiceType: {invoice_type}, Amount: {total_sum}, Series: {payment_data.get('Series')}")
        
        return payment_data

    # Helper Methods (reused from v2)
    def _extract_store_credit_refunds(self, order: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract store credit refund transactions from order"""
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
        """Extract gift card refunds from POS order line items"""
        store_credit_refunds = []
        line_items = order.get("lineItems", {}).get("edges", [])
        
        for item_edge in line_items:
            item = item_edge.get("node", {})
            
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
        
        return store_credit_refunds

    def _get_existing_gift_card_id(self, order: Dict[str, Any]) -> Optional[str]:
        """Check if order already has a gift card created"""
        tags = order.get("tags", [])
        for tag in tags:
            if tag.startswith("giftcard_"):
                return tag.replace("giftcard_", "")
        return None

    def _is_pos_order(self, order: Dict[str, Any], store_key: str) -> bool:
        """Check if order is from a POS/store location"""
        try:
            source_name = order.get("sourceName", "").lower()
            if source_name == "pos":
                return True
            elif source_name in ["web", "online", "shopify"]:
                return False
            
            from order_location_mapper import OrderLocationMapper
            location_analysis = OrderLocationMapper.analyze_order_source(order, store_key)
            return location_analysis.get("is_pos_order", False)
        except Exception as e:
            logger.error(f"Error determining order location type: {str(e)}")
            return False

    async def _get_gift_cards_for_order(self, order_id: str, order_created_at: str) -> List[Dict[str, Any]]:
        """Query Shopify Gift Cards API to get gift cards created for this order"""
        try:
            order_date = order_created_at.split("T")[0] if "T" in order_created_at else order_created_at
            query = """
            query getGiftCards($query: String!) {
                giftCards(first: 150, query: $query) {
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
            query_string = f"created_at:>={order_date}T00:00:00Z status:enabled"
            
            max_retries = 3
            retry_delay = 2
            
            for attempt in range(max_retries):
                try:
                    result = await self.shopify_client.execute_query("local", query, {"query": query_string})
                    
                    if result["msg"] == "success":
                        break
                    else:
                        logger.warning(f"GraphQL attempt {attempt + 1}/{max_retries} failed: {result.get('error', 'Unknown error')}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2
                except Exception as e:
                    logger.error(f"GraphQL attempt {attempt + 1}/{max_retries} exception: {str(e)}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        result = {"msg": "failure", "error": f"All {max_retries} attempts failed: {str(e)}"}
            
            if result["msg"] == "failure":
                logger.error(f"Failed to query gift cards: {result.get('error')}")
                return []
            
            if not result.get("data") or not result["data"].get("giftCards"):
                logger.warning(f"No gift cards data found in result")
                return []
            
            gift_cards = []
            gift_cards_edges = result["data"]["giftCards"].get("edges", [])
            for edge in gift_cards_edges:
                try:
                    gift_card = edge.get("node", {})
                    if not gift_card:
                        continue
                    
                    order_info = gift_card.get("order")
                    if not order_info:
                        continue
                        
                    if order_info.get("id") == f"gid://shopify/Order/{order_id}":
                        initial_value = gift_card.get("initialValue")
                        if not initial_value:
                            continue
                        
                        # Safely extract customer email (handle None customer - gift cards can exist without customers)
                        customer = gift_card.get("customer")
                        customer_email = customer.get("email", "") if customer else ""
                            
                        gift_cards.append({
                            "id": gift_card.get("id", ""),
                            "order_id": order_id,
                            "initial_value": float(initial_value.get("amount", 0)),
                            "currency": initial_value.get("currencyCode", "EGP"),
                            "created_at": gift_card.get("createdAt", ""),
                            "expires_on": gift_card.get("expiresOn"),
                            "customer_email": customer_email
                        })
                except Exception as e:
                    logger.error(f"Error processing gift card edge: {str(e)}")
                    continue
            
            return gift_cards
            
        except Exception as e:
            logger.error(f"Error querying gift cards: {str(e)}")
            return []

    async def _create_shopify_gift_card(
        self, order: Dict[str, Any], store_credit_refunds: List[Dict[str, Any]], store_key: str
    ) -> Optional[str]:
        """Create gift card in Shopify"""
        try:
            total_amount = sum(refund["amount"] for refund in store_credit_refunds)
            currency = store_credit_refunds[0]["currency"] if store_credit_refunds else "EGP"
            
            mutation = """
            mutation createGiftCard($input: GiftCardCreateInput!) {
                giftCardCreate(input: $input) {
                    giftCard {
                        id
                    }
                    userErrors {
                        field
                        message
                    }
                }
            }
            """
            
            variables = {
                "input": {
                    "initialValue": {
                        "amount": total_amount,
                        "currencyCode": currency
                    },
                    "note": f"Store credit for return - Order {order.get('name', '')}"
                }
            }
            
            result = await self.shopify_client.execute_query(store_key, mutation, variables)
            
            if result.get("msg") == "success" and "data" in result:
                data = result["data"]
                if "giftCardCreate" in data:
                    user_errors = data["giftCardCreate"].get("userErrors", [])
                    if user_errors:
                        logger.error(f"Gift card creation errors: {user_errors}")
                        return None
                    gift_card = data["giftCardCreate"].get("giftCard")
                    if gift_card:
                        gift_card_id = gift_card.get("id")
                        logger.info(f"✅ Created gift card {gift_card_id} in Shopify")
                        return gift_card_id
            
            logger.error(f"Failed to create gift card: {result.get('error', 'Unknown error')}")
            return None
            
        except Exception as e:
            logger.error(f"Error creating gift card in Shopify: {str(e)}")
            return None

    async def _create_shopify_gift_card_for_amount(
        self, order: Dict[str, Any], amount: float, store_key: str
    ) -> Optional[str]:
        """
        Create gift card in Shopify with specific amount (matching returns_v2 logic)
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
                    "initialValue": str(amount),
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
                    
                    logger.info(f"✅ Created gift card {gift_card_id} for customer {customer_id} with amount {amount}")
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

    async def _prepare_gift_card_for_invoice(
        self, gift_card_id: str, amount: float, customer_card_code: str, warehouse_code: str = "SW"
    ) -> Optional[str]:
        """Prepare gift card data for invoice line without creating SAP GiftCards entity entry"""
        try:
            # Extract numeric ID from GraphQL ID
            numeric_id = gift_card_id.split("/")[-1] if "/" in gift_card_id else gift_card_id
            logger.info(f"Prepared gift card data for invoice line: {numeric_id} - Amount: {amount}")
            return numeric_id
        except Exception as e:
            logger.error(f"Error preparing gift card data: {str(e)}")
            return None

    def _analyze_order_location_from_retail_location(self, order: Dict[str, Any], store_key: str) -> Dict[str, Any]:
        """Analyze order location using retailLocation field"""
        try:
            source_name = order.get("sourceName", "").lower()
            is_pos_order = source_name == "pos"
            
            if is_pos_order:
                retail_location = order.get("retailLocation", {})
                location_id = None
                
                if retail_location and retail_location.get("id"):
                    location_gid = retail_location["id"]
                    location_id = location_gid.split("/")[-1] if "/" in location_gid else location_gid
                else:
                    from order_location_mapper import OrderLocationMapper
                    return OrderLocationMapper.analyze_order_source(order, store_key)
                
                if not location_id:
                    from order_location_mapper import OrderLocationMapper
                    return OrderLocationMapper.analyze_order_source(order, store_key)
                
                location_mapping = self.config.get_location_mapping_for_location(store_key, location_id)
                
                if not location_mapping:
                    from order_location_mapper import OrderLocationMapper
                    return OrderLocationMapper.analyze_order_source(order, store_key)
                
                sap_codes = {
                    'COGSCostingCode': location_mapping.get('location_cc', 'ONL'),
                    'COGSCostingCode2': location_mapping.get('department_cc', 'SAL'),
                    'COGSCostingCode3': location_mapping.get('activity_cc', 'OnlineS'),
                    'CostingCode': location_mapping.get('location_cc', 'ONL'),
                    'CostingCode2': location_mapping.get('department_cc', 'SAL'),
                    'CostingCode3': location_mapping.get('activity_cc', 'OnlineS'),
                    'Warehouse': location_mapping.get('warehouse', 'SW')
                }
                
                return {
                    "location_id": location_id,
                    "location_mapping": location_mapping,
                    "is_pos_order": True,
                    "sap_codes": sap_codes
                }
            else:
                from order_location_mapper import OrderLocationMapper
                return OrderLocationMapper.analyze_order_source(order, store_key)
            
        except Exception as e:
            logger.error(f"Error analyzing order location: {str(e)}")
            from order_location_mapper import OrderLocationMapper
            return OrderLocationMapper.analyze_order_source(order, store_key)

    async def _add_order_tag_with_retry(self, order_id: str, tag: str, store_key: str, max_retries: int = 3):
        """Add tag to order with retry logic"""
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
                        wait_time = 2 ** attempt
                        logger.info(f"⏳ Retrying tag addition in {wait_time} seconds...")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"❌ TAG FAILED after {max_retries} attempts: {tag}")
                        return {"msg": "failure", "error": f"Failed after {max_retries} attempts"}
                        
            except Exception as e:
                error_msg = str(e)
                logger.error(f"❌ TAG EXCEPTION on attempt {attempt + 1}: {error_msg}")
                
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.info(f"⏳ Retrying tag addition in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"❌ TAG FAILED after {max_retries} attempts due to exception: {tag}")
                    return {"msg": "failure", "error": f"Failed after {max_retries} attempts: {error_msg}"}
        
        return {"msg": "failure", "error": "Max retries exceeded"}

