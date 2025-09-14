#!/usr/bin/env python3
"""
Returns Sync Module - Handles return processing from Shopify to SAP
"""

import asyncio
import json
import re
from decimal import Decimal
from typing import Dict, Any, List, Optional
from datetime import datetime

from app.core.config import ConfigSettings, config_settings
from app.services.sap.client import SAPClient
from app.services.shopify.multi_store_client import MultiStoreShopifyClient
from app.utils.logging import logger
from order_location_mapper import OrderLocationMapper

class ReturnsSync:
    """
    Handles synchronization of returns from Shopify to SAP
    """
    
    def __init__(self):
        self.config_settings = ConfigSettings()
        self.sap_client = SAPClient()
        self.multi_store_shopify_client = MultiStoreShopifyClient()
    
    async def get_returned_orders_from_shopify(self, store_key: str) -> Dict[str, Any]:
        """
        Get returned orders from Shopify store that need to be synced
        """
        try:
            # Query to get returned orders with specific tag conditions
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

                        # --- Customer Info ---
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
                        
                        # --- Metafields ---
                        metafields(first: 10) {
                        edges {
                            node {
                            namespace
                            key
                            value
                            }
                        }
                        }
                        
                        # --- Tags ---
                        tags

                        # --- Line Items ---
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

                        # --- Transactions ---
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
            
            # Build query filter for returned orders that need processing
            # We want orders that:
            # 1. Have sap_payment_synced tag (successfully synced payments)
            # 2. Have financial_status = "PARTIALLY_REFUNDED" or "REFUNDED" (indicates return)
            # 3. Don't have sap_return_synced or sap_return_failed tags
            from_date = config_settings.returns_from_date
            
            query_filter = f"tag:returntest tag:sap_payment_synced financial_status:partially_refunded -tag:sap_return_synced created_at:>={from_date}"
            
            logger.info(f"Fetching returned orders with filter: {query_filter}")
            
            # Add retry logic for GraphQL queries to handle rate limiting and temporary failures
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    logger.info(f"GraphQL query attempt {attempt + 1}/{max_retries} for store {store_key}")
                    
                    result = await self.multi_store_shopify_client.execute_query(
                        store_key, 
                        query, 
                        {
                            "first": 10,
                            "after": None,
                            "query": query_filter
                        }
                    )
                    
                    if result and result.get("msg") == "success" and "data" in result:
                        data = result["data"]
                        if "orders" in data:
                            orders = data["orders"]["edges"]
                            logger.info(f"✅ Retrieved {len(orders)} returned orders (limited to 10 most recent) from Shopify store {store_key}")
                            return data
                        else:
                            logger.warning(f"No orders data returned from Shopify for store {store_key}")
                            return {"orders": {"edges": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}
                    else:
                        # Check if this is a retryable error
                        error_msg = result.get("error", "Unknown error") if result else "No response"
                        logger.warning(f"GraphQL query attempt {attempt + 1} failed for store {store_key}: {error_msg}")
                        
                        if attempt == max_retries - 1:
                            logger.error(f"All {max_retries} attempts failed for store {store_key}")
                            return {"orders": {"edges": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}
                        
                        # Wait before retry
                        wait_time = 2 ** attempt
                        logger.info(f"Waiting {wait_time} seconds before retry...")
                        await asyncio.sleep(wait_time)
                        
                except Exception as e:
                    logger.error(f"GraphQL query attempt {attempt + 1} failed for store {store_key}: {str(e)}")
                    if attempt == max_retries - 1:
                        logger.error(f"All {max_retries} attempts failed for store {store_key}")
                        return {"orders": {"edges": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}
                    
                    # Wait before retry
                    wait_time = 2 ** attempt
                    logger.info(f"Waiting {wait_time} seconds before retry...")
                    await asyncio.sleep(wait_time)
            
        except Exception as e:
            logger.error(f"Failed to get returned orders from Shopify store {store_key}: {str(e)}")
            return {"orders": {"edges": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}
    
    def extract_invoice_entry_from_tags(self, tags: List[str]) -> Optional[str]:
        """
        Extract invoice entry from sap_invoice_{entry} tag
        """
        for tag in tags:
            if tag.startswith("sap_invoice_"):
                return tag.replace("sap_invoice_", "")
        return None
    
    async def fetch_sap_invoice(self, invoice_entry: str) -> Dict[str, Any]:
        """
        Fetch invoice details from SAP
        """
        try:
            logger.info(f"Fetching SAP invoice {invoice_entry}")
            
            # Make GET request to fetch invoice
            response = await self.sap_client._make_request(
                method="GET",
                endpoint=f"Invoices({invoice_entry})"
            )
            
            if response.get("msg") == "success":
                invoice_data = response.get("data", {})
                logger.info(f"Successfully fetched invoice {invoice_entry}")
                logger.info(f"Invoice data CardCode: '{invoice_data.get('CardCode', 'NOT_FOUND')}'")
                return {
                    "success": True,
                    "data": invoice_data,
                    "card_code": invoice_data.get("CardCode"),
                    "document_status": invoice_data.get("DocumentStatus"),
                    "document_lines": invoice_data.get("DocumentLines", [])
                }
            else:
                logger.error(f"Failed to fetch invoice {invoice_entry}: {response}")
                return {"success": False, "error": response.get("error", "Unknown error")}
                
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
                logger.info(f"Successfully reopened invoice {invoice_entry}")
                return True
            else:
                logger.error(f"Failed to reopen invoice {invoice_entry}: {response}")
                return False
                
        except Exception as e:
            logger.error(f"Error reopening invoice {invoice_entry}: {str(e)}")
            return False
    
    def map_shopify_return_to_sap_credit_note(self, shopify_order: Dict[str, Any], invoice_data: Dict[str, Any], mapping: bool, store_key: str) -> Dict[str, Any]:
        """
        Map Shopify return order to SAP credit note format
        """
        try:
            order_node = shopify_order["node"]
            order_name = order_node["name"]
            order_id = order_node["id"].split("/")[-1]
            
            # Extract customer info
            customer = order_node.get("customer", {})
            customer_name = f"{customer.get('firstName', '')} {customer.get('lastName', '')}".strip()
            customer_email = customer.get("email", "")
            
            # Debug: Log the invoice_data structure
            logger.info(f"Invoice data keys: {list(invoice_data.keys())}")
            logger.info(f"Invoice data card_code: '{invoice_data.get('card_code', 'NOT_FOUND')}'")
            
            # Get card code from invoice
            card_code = invoice_data.get("card_code", "")
            logger.info(f"Using CardCode: '{card_code}'")
            
            # If card_code is empty, try to get it from the invoice data
            if not card_code:
                invoice_data_inner = invoice_data.get("data", {})
                card_code = invoice_data_inner.get("CardCode", "")
                logger.info(f"Fallback CardCode from data: '{card_code}'")
            
            # Prepare credit note header
            credit_note = {
                "CardCode": card_code,
                "DocDate": datetime.now().strftime("%Y-%m-%d"),
                "Comments": f"Return for Shopify Order {order_name}",
                "Series": config_settings.get_series_for_location(store_key, location_analysis.get('location_mapping', {}), 'credit_notes'),
                "U_ShopifyOrderID": order_id,
                "DocumentLines": []
            }
            
            # Process line items
            line_items = []
            for item_edge in order_node["lineItems"]["edges"]:
                item = item_edge["node"]
                sku = item.get("sku")
                quantity = item["quantity"]
                
                # Get pricing information with priority: compareAtPrice > originalUnitPriceSet > variant price
                original_price = Decimal("0.00")
                sale_price = Decimal("0.00")
                
                # First, try to get compareAtPrice (original price before sale)
                if item.get("variant") and item["variant"].get("compareAtPrice"):
                    original_price = Decimal(item["variant"]["compareAtPrice"])
                    # Get the current sale price
                    if item.get("variant") and item["variant"].get("price"):
                        sale_price = Decimal(item["variant"]["price"])
                # Fallback to original unit price set
                elif item.get("originalUnitPriceSet") and item["originalUnitPriceSet"].get("shopMoney"):
                    original_price = Decimal(item["originalUnitPriceSet"]["shopMoney"]["amount"])
                    sale_price = original_price  # No sale, so sale price = original price
                # Final fallback to variant price
                elif item.get("variant") and item["variant"].get("price"):
                    original_price = Decimal(item["variant"]["price"])
                    sale_price = original_price  # No sale, so sale price = original price
                else:
                    # Fallback to a default price if variant price is not available
                    original_price = Decimal("0.00")
                    sale_price = Decimal("0.00")
                
                # Use the actual SKU as item code, or a default if not available
                if sku:
                    item_code = sku
                elif item.get("variant") and item["variant"].get("sku"):
                    item_code = item["variant"]["sku"]
                else:
                    item_code = "ACC-0000001"  # Default item only if no SKU available
                
                # Create line item
                line_item = {
                    "ItemCode": item_code,
                    "Quantity": quantity,
                    "UnitPrice": float(original_price),  # Always use original price (compareAtPrice)
                }
                
                # If mapping is true, add base entry information
                if mapping:
                    # Find corresponding line in original invoice
                    invoice_lines = invoice_data.get("document_lines", [])
                    invoice_doc_entry = invoice_data.get("data", {}).get("DocEntry")
                    for invoice_line in invoice_lines:
                        if invoice_line.get("ItemCode") == item_code:
                            line_item["BaseEntry"] = invoice_doc_entry
                            line_item["BaseType"] = 13  # Invoice document type
                            line_item["BaseLine"] = invoice_line.get("LineNum")
                            break
                
                # Calculate discount percentage based on compareAtPrice vs sale price
                if original_price > 0 and sale_price > 0 and original_price != sale_price:
                    # Calculate discount percentage: (original - sale) / original * 100
                    discount_amount = original_price - sale_price
                    discount_percentage = (discount_amount / original_price) * 100
                    line_item["DiscountPercent"] = float(discount_percentage)
                    #line_item["U_ItemDiscountAmount"] = float(discount_amount)
                    logger.info(f"🎯 Return pricing for {item_code}: Original={original_price}, Sale={sale_price}, Discount={discount_percentage:.1f}%")
                
                # Check for bin location allocation
                try:
                    # Get location mapping for this order
                    location_analysis = OrderLocationMapper.analyze_order_source(order_node, store_key)
                    location_mapping = location_analysis.get('location_mapping', {})
                    
                    # Check if this location has a bin_location configured
                    bin_location = location_mapping.get('bin_location')
                    if bin_location is not None:
                        # Add bin allocation to the line item
                        line_item["DocumentLinesBinAllocations"] = [
                            {
                                "BinAbsEntry": bin_location,
                                "Quantity": quantity
                            }
                        ]
                        logger.info(f"📦 Added bin allocation for {item_code}: BinAbsEntry={bin_location}, Quantity={quantity}")
                    else:
                        logger.info(f"📦 No bin_location configured for this order location, skipping bin allocation for {item_code}")
                        
                except Exception as e:
                    logger.warning(f"Error checking bin location for {item_code}: {str(e)}")
                
                line_items.append(line_item)
            
            credit_note["DocumentLines"] = line_items
            
            logger.info(f"📋 Mapped return order {order_name} to SAP credit note format with {len(line_items)} line items")
            return credit_note
            
        except Exception as e:
            logger.error(f"Error mapping Shopify return to SAP credit note: {str(e)}")
            raise
    
    async def create_sap_credit_note(self, credit_note_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create credit note in SAP
        """
        try:
            logger.info("Creating SAP credit note")
            logger.info(f"Credit note body: {credit_note_data}")
            
            # Make POST request to create credit note
            response = await self.sap_client._make_request(
                method="POST",
                endpoint="CreditNotes",
                data=credit_note_data
            )
            
            if response.get("msg") == "success":
                credit_note_data = response.get("data", {})
                doc_entry = credit_note_data.get("DocEntry")
                logger.info(f"Successfully created credit note with DocEntry: {doc_entry}")
                return {
                    "success": True,
                    "doc_entry": doc_entry,
                    "data": credit_note_data
                }
            else:
                logger.error(f"Failed to create credit note: {response}")
                return {"success": False, "error": response.get("error", "Unknown error")}
                
        except Exception as e:
            logger.error(f"Error creating credit note: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def add_shopify_tags(self, store_key: str, order_id: str, tags: List[str]) -> bool:
        """
        Add tags to Shopify order
        """
        try:
            logger.info(f"Adding tags {tags} to order {order_id}")
            
            # Get current order to retrieve existing tags
            order_query = """
            query getOrder($id: ID!) {
                order(id: $id) {
                    id
                    tags
                }
            }
            """
            
            # Add retry logic for GraphQL queries
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    logger.info(f"GraphQL query attempt {attempt + 1}/{max_retries} for retrieving order {order_id}")
                    
                    result = await self.multi_store_shopify_client.execute_query(
                        store_key,
                        order_query,
                        {"id": order_id}
                    )
                    
                    if result and result.get("msg") == "success" and "data" in result:
                        order_data = result["data"]
                        if "order" in order_data:
                            current_tags = order_data["order"].get("tags", [])
                            new_tags = list(set(current_tags + tags))  # Remove duplicates
                            
                            # Update order with new tags
                            update_mutation = """
                            mutation orderUpdate($input: OrderInput!) {
                                orderUpdate(input: $input) {
                                    order {
                                        id
                                        tags
                                    }
                                    userErrors {
                                        field
                                        message
                                    }
                                }
                            }
                            """
                            
                            update_result = await self.multi_store_shopify_client.execute_query(
                                store_key,
                                update_mutation,
                                {
                                    "input": {
                                        "id": order_id,
                                        "tags": new_tags
                                    }
                                }
                            )
                            
                            if update_result and update_result.get("msg") == "success" and "data" in update_result:
                                data = update_result["data"]
                                if "orderUpdate" in data:
                                    user_errors = data["orderUpdate"].get("userErrors", [])
                                    if user_errors:
                                        logger.error(f"GraphQL errors updating order {order_id}: {user_errors}")
                                        return False
                                    else:
                                        logger.info(f"Successfully added tags to order {order_id}")
                                        return True
                                else:
                                    logger.error(f"Failed to update order {order_id}")
                                    return False
                            else:
                                logger.error(f"Failed to update order {order_id}")
                                return False
                        else:
                            logger.error(f"Order not found in response for {order_id}")
                            return False
                    else:
                        # Check if this is a retryable error
                        error_msg = result.get("error", "Unknown error") if result else "No response"
                        logger.warning(f"GraphQL query attempt {attempt + 1} failed for order {order_id}: {error_msg}")
                        
                        if attempt == max_retries - 1:
                            logger.error(f"All {max_retries} attempts failed for order {order_id}")
                            return False
                        
                        # Wait before retry
                        wait_time = 2 ** attempt
                        logger.info(f"Waiting {wait_time} seconds before retry...")
                        await asyncio.sleep(wait_time)
                        
                except Exception as e:
                    logger.error(f"GraphQL query attempt {attempt + 1} failed for order {order_id}: {str(e)}")
                    if attempt == max_retries - 1:
                        logger.error(f"All {max_retries} attempts failed for order {order_id}")
                        return False
                    
                    # Wait before retry
                    wait_time = 2 ** attempt
                    logger.info(f"Waiting {wait_time} seconds before retry...")
                    await asyncio.sleep(wait_time)
                
        except Exception as e:
            logger.error(f"Error adding tags to order {order_id}: {str(e)}")
            return False
    
    async def process_return_order(self, store_key: str, order: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single return order
        """
        try:
            order_node = order["node"]
            order_name = order_node["name"]
            order_id = order_node["id"]
            tags = order_node.get("tags", [])
            
            logger.info(f"🔄 Processing return order {order_name}")
            
            # Extract invoice entry from tags
            invoice_entry = self.extract_invoice_entry_from_tags(tags)
            if not invoice_entry:
                logger.error(f"No invoice entry found in tags for order {order_name}")
                return {"success": False, "error": "No invoice entry found in tags"}
            
            logger.info(f"Found invoice entry {invoice_entry} for order {order_name}")
            
            # Fetch invoice from SAP
            invoice_result = await self.fetch_sap_invoice(invoice_entry)
            if not invoice_result["success"]:
                logger.error(f"Failed to fetch invoice {invoice_entry}: {invoice_result.get('error')}")
                return {"success": False, "error": f"Failed to fetch invoice: {invoice_result.get('error')}"}
            
            invoice_data = invoice_result["data"]
            document_status = invoice_result["document_status"]
            
            # Check document status and handle reopening if needed
            mapping = False
            if document_status == "bost_Open":
                logger.info(f"Invoice {invoice_entry} is already open, proceeding with mapping")
                mapping = True
            else:
                logger.info(f"Invoice {invoice_entry} is closed, attempting to reopen")
                reopen_success = await self.reopen_sap_invoice(invoice_entry)
                if reopen_success:
                    mapping = True
                    logger.info(f"Successfully reopened invoice {invoice_entry}")
                else:
                    logger.warning(f"Failed to reopen invoice {invoice_entry}, proceeding without base entry mapping")
                    mapping = False
            
            # Map order to SAP credit note format
            credit_note_data = self.map_shopify_return_to_sap_credit_note(order, invoice_result, mapping, store_key)
            
            # Create credit note in SAP
            credit_note_result = await self.create_sap_credit_note(credit_note_data)
            if not credit_note_result["success"]:
                logger.error(f"Failed to create credit note: {credit_note_result.get('error')}")
                return {"success": False, "error": f"Failed to create credit note: {credit_note_result.get('error')}"}
            
            doc_entry = credit_note_result["doc_entry"]
            logger.info(f"Successfully created credit note {doc_entry} for return order {order_name}")
            
            # Add success tags to Shopify order
            success_tags = [f"sap_return_synced", f"sap_return_{doc_entry}"]
            tag_success = await self.add_shopify_tags(store_key, order_id, success_tags)
            
            if tag_success:
                logger.info(f"✅ Successfully processed return order {order_name} -> Credit Note {doc_entry}")
                return {
                    "success": True,
                    "order_name": order_name,
                    "credit_note_entry": doc_entry,
                    "invoice_entry": invoice_entry
                }
            else:
                logger.warning(f"Credit note created but failed to add tags to order {order_name}")
                return {
                    "success": True,
                    "order_name": order_name,
                    "credit_note_entry": doc_entry,
                    "invoice_entry": invoice_entry,
                    "warning": "Failed to add success tags"
                }
                
        except Exception as e:
            logger.error(f"Error processing return order {order.get('node', {}).get('name', 'Unknown')}: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def sync_returns(self) -> Dict[str, Any]:
        """
        Main method to sync returns for all enabled stores
        """
        try:
            logger.info("Starting returns sync for all stores")
            
            enabled_stores = self.config_settings.get_enabled_stores()
            if not enabled_stores:
                logger.warning("No enabled stores found for returns sync")
                return {
                    "msg": "success",
                    "processed": 0,
                    "successful": 0,
                    "errors": 0,
                    "details": []
                }
            
            all_results = []
            total_processed = 0
            total_successful = 0
            total_errors = 0
            
            for store_key, store_config in enabled_stores.items():
                try:
                    logger.info(f"Processing returns for store: {store_key}")
                    
                    # Get returned orders from Shopify
                    orders_result = await self.get_returned_orders_from_shopify(store_key)
                    orders = orders_result.get("orders", {}).get("edges", [])
                    
                    if not orders:
                        logger.info(f"No returned orders to process for store {store_key}")
                        continue
                    
                    store_results = []
                    store_successful = 0
                    store_errors = 0
                    
                    for order in orders:
                        try:
                            result = await self.process_return_order(store_key, order)
                            store_results.append(result)
                            
                            if result["success"]:
                                store_successful += 1
                            else:
                                store_errors += 1
                                
                        except Exception as e:
                            logger.error(f"Error processing order: {str(e)}")
                            store_errors += 1
                            store_results.append({"success": False, "error": str(e)})
                    
                    logger.info(f"Returns sync completed for store {store_key}: {store_successful} successful, {store_errors} errors")
                    
                    all_results.extend(store_results)
                    total_processed += len(orders)
                    total_successful += store_successful
                    total_errors += store_errors
                    
                except Exception as e:
                    logger.error(f"Error in returns sync for store {store_key}: {str(e)}")
                    total_errors += 1
                    all_results.append({"success": False, "error": str(e)})
            
            logger.info(f"Returns sync completed: {total_successful} successful, {total_errors} errors")
            
            return {
                "msg": "success",
                "processed": total_processed,
                "successful": total_successful,
                "errors": total_errors,
                "details": all_results
            }
            
        except Exception as e:
            logger.error(f"Error in returns sync: {str(e)}")
            return {
                "msg": "failure",
                "error": str(e),
                "processed": 0,
                "successful": 0,
                "errors": 1
            }
