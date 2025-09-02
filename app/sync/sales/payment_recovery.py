"""
Payment Recovery Module
Queries Shopify for orders with invoice tags but no payment tags and status PAID, 
then creates payments in SAP
"""

import asyncio
from typing import Dict, Any, List, Optional
from decimal import Decimal
from app.services.sap.client import sap_client
from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.core.config import config_settings
from app.utils.logging import logger, log_sync_event
from datetime import datetime


class PaymentRecoverySync:
    """
    Handles payment recovery for orders that were synced to SAP but payments weren't created
    """
    
    def __init__(self):
        self.batch_size = config_settings.sales_orders_batch_size
    
    async def get_orders_from_shopify(self, store_key: str) -> Dict[str, Any]:
        """
        Get orders from Shopify store that need payment recovery
        """
        try:
            # Query to get orders with specific tag conditions
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
            
            # Build query filter for orders that need payment recovery
            # We want orders that:
            # 1. Have sap_invoice_synced tag (successfully synced invoices)
            # 2. Don't have sap_payment_synced or sap_payment_failed tags
            # 3. Are PAID
            query_filter = "financial_status:paid AND tag:sap_invoice_synced AND -tag:sap_payment_synced AND -tag:sap_payment_failed"
            
            # Add retry logic for GraphQL queries to handle rate limiting
            max_retries = 3
            retry_delay = 2  # Start with 2 seconds
            
            for attempt in range(max_retries):
                try:
                    result = await multi_store_shopify_client.execute_query(
                        store_key,
                        query,
                        {"first": self.batch_size, "after": None, "query": query_filter}
                    )
                    
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
                return result
            
            orders = result["data"]["orders"]["edges"]
            
            # Take only the last 10 most recent orders for payment recovery
            payment_recovery_orders = orders[:10]
            
            logger.info(f"Retrieved {len(orders)} orders that need payment recovery from Shopify store {store_key}")
            
            return {"msg": "success", "data": payment_recovery_orders}
            
        except Exception as e:
            logger.error(f"Error getting orders from Shopify: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    def extract_sap_invoice_doc_entry(self, tags: List[str]) -> Optional[str]:
        """
        Extract SAP invoice DocEntry from tags
        """
        for tag in tags:
            if tag.startswith("sap_invoice_"):
                # Extract DocEntry from tag (format: "sap_invoice_12345")
                doc_entry = tag.replace("sap_invoice_", "")
                return doc_entry
        return None
    
    async def check_payment_exists_in_sap(self, shopify_order_id: str) -> Dict[str, Any]:
        """
        Check if payment already exists in SAP by U_Shopify_Order_ID field
        """
        try:
            # Query SAP for incoming payment with specific Shopify Order ID
            endpoint = "IncomingPayments"
            params = {
                "$select": "DocEntry,DocNum,U_Shopify_Order_ID",
                "$filter": f"U_Shopify_Order_ID eq '{shopify_order_id}'"
            }
            
            result = await sap_client._make_request(
                method='GET',
                endpoint=endpoint,
                params=params
            )
            
            if result["msg"] == "failure":
                logger.error(f"Failed to check payment existence in SAP: {result.get('error')}")
                return result
            
            payments = result["data"]["value"] if "value" in result["data"] else result["data"]
            
            if payments:
                # Payment exists in SAP
                payment = payments[0]
                logger.info(f"Payment for order {shopify_order_id} already exists in SAP with DocEntry: {payment.get('DocEntry')}")
                return {
                    "msg": "success",
                    "exists": True,
                    "doc_entry": payment.get('DocEntry'),
                    "doc_num": payment.get('DocNum')
                }
            else:
                # Payment doesn't exist in SAP
                return {
                    "msg": "success",
                    "exists": False
                }
            
        except Exception as e:
            logger.error(f"Error checking payment existence in SAP: {str(e)}")
            return {"msg": "failure", "error": str(e)}

    async def get_sap_invoice_by_doc_entry(self, doc_entry: str) -> Dict[str, Any]:
        """
        Get SAP invoice data by DocEntry
        """
        try:
            # Query SAP for invoice with specific DocEntry
            endpoint = "Invoices"
            params = {
                "$select": "DocEntry,CardCode,DocTotal,U_Shopify_Order_ID",
                "$filter": f"DocEntry eq {doc_entry}"
            }
            
            result = await sap_client._make_request(
                method='GET',
                endpoint=endpoint,
                params=params
            )
            
            if result["msg"] == "failure":
                logger.error(f"Failed to get SAP invoice DocEntry {doc_entry}: {result.get('error')}")
                return result
            
            invoices = result["data"]["value"] if "value" in result["data"] else result["data"]
            
            if not invoices:
                logger.warning(f"No SAP invoice found for DocEntry {doc_entry}")
                return {"msg": "failure", "error": f"No SAP invoice found for DocEntry {doc_entry}"}
            
            # Return the first invoice (should be only one)
            invoice = invoices[0]
            logger.info(f"Found SAP invoice DocEntry: {invoice.get('DocEntry')}")
            
            return {"msg": "success", "data": invoice}
            
        except Exception as e:
            logger.error(f"Error getting SAP invoice for DocEntry {doc_entry}: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    def prepare_payment_data(self, sap_invoice: Dict[str, Any], shopify_order: Dict[str, Any], store_key: str) -> Dict[str, Any]:
        """
        Prepare incoming payment data for SAP
        """
        try:
            # Extract order ID from GraphQL ID
            order_id = shopify_order.get("id", "")
            # Extract just the numeric ID from the full GID (e.g., "6342714261570" from "gid://shopify/Order/6342714261570")
            order_id_number = order_id.split("/")[-1] if "/" in order_id else order_id
            
            # Get payment information from transactions
            payment_info = self._extract_payment_info_from_transactions(shopify_order["transactions"])
            
            # Get order channel information
            source_name = (shopify_order.get("sourceName") or "").lower()
            source_identifier = (shopify_order.get("sourceIdentifier") or "").lower()
            
            # Determine payment type based on channel and payment method
            payment_type = self._determine_payment_type(source_name, source_identifier, payment_info)
            
            # Initialize payment data
            payment_data = {
                "DocDate": datetime.now().strftime("%Y-%m-%d"),
                "CardCode": sap_invoice["CardCode"],
                "DocType": "rCustomer",
                "Series": 15,  # Series for incoming payments
                "TransferSum": sap_invoice["DocTotal"],  # Use the invoice total from SAP
                "TransferAccount": "",
                "U_Shopify_Order_ID": order_id_number  # Add Shopify Order ID (numeric)
            }
            
            # Set payment method based on type
            if payment_type == "PaidOnline":
                # Online store payments - use Paymob account
                transfer_account = config_settings.get_bank_transfer_account(store_key, "Paymob")
                payment_data["TransferAccount"] = transfer_account
                logger.info(f"Online store payment - using Paymob account: {transfer_account}")
                
            elif payment_type == "COD":
                # Cash on delivery - use COD account
                transfer_account = config_settings.get_bank_transfer_account(store_key, "Cash on Delivery (COD)")
                payment_data["TransferAccount"] = transfer_account
                logger.info(f"COD payment - using COD account: {transfer_account}")
                
            elif payment_type == "Cash":
                # Cash payment at store
                logger.info(f"Cash payment at store - using transfer sum")
                
            elif payment_type == "CreditCard":
                # Credit card payment at store
                logger.info(f"Credit card payment at store - using transfer sum")
                
            else:
                # Default to transfer for unknown payment types
                logger.warning(f"Unknown payment type '{payment_type}' - defaulting to transfer")
            
            # Create invoice object for payment
            inv_obj = {
                "DocEntry": sap_invoice["DocEntry"],
                "SumApplied": sap_invoice["DocTotal"],  # Use the invoice total from SAP
                "InvoiceType": "it_Invoice"
            }
            
            # Add invoice to payment data
            payment_data["PaymentInvoices"] = [inv_obj]
            
            return payment_data
            
        except Exception as e:
            logger.error(f"Error preparing payment data: {str(e)}")
            raise
    
    def _extract_payment_info_from_transactions(self, transactions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract payment information from Shopify order transactions
        """
        payment_info = {
            "gateway": "Unknown",
            "card_type": "Unknown", 
            "last_4": "Unknown",
            "payment_id": "Unknown",
            "amount": 0.0,
            "status": "Unknown",
            "processed_at": "Unknown",
            "is_online_payment": False
        }
        
        try:
            for transaction in transactions:
                # Look for successful payment transactions
                if (transaction.get("kind") == "SALE" and 
                    transaction.get("status") == "SUCCESS"):
                    
                    gateway = transaction.get("gateway", "Unknown")
                    amount = float(transaction.get("amountSet", {}).get("shopMoney", {}).get("amount", 0))
                    
                    payment_info["gateway"] = gateway
                    payment_info["amount"] = amount
                    payment_info["status"] = transaction.get("status", "Unknown")
                    payment_info["processed_at"] = transaction.get("processedAt", "Unknown")
                    payment_info["payment_id"] = transaction.get("id", "Unknown")
                    
                    # Use gateway as card type if payment details not available
                    payment_info["card_type"] = gateway
                    
                    # Check if this is an online payment
                    if gateway.lower() in ["paymob", "stripe", "paypal"]:
                        payment_info["is_online_payment"] = True
                    
                    # Use the first successful payment transaction
                    break
                    
        except Exception as e:
            logger.error(f"Error extracting payment info: {str(e)}")
        
        return payment_info
    
    def _determine_payment_type(self, source_name: str, source_identifier: str, payment_info: Dict[str, Any]) -> str:
        """
        Determine payment type based on order channel and payment information
        """
        # Convert to lowercase for case-insensitive matching
        source_name_lower = (source_name or "").lower()
        source_identifier_lower = (source_identifier or "").lower()
        
        # Check if it's an online store order
        if ("online store" in source_name_lower or 
            "web" in source_name_lower or 
            "shopify" in source_name_lower or
            "online" in source_name_lower):
            return "PaidOnline"
        
        # Check if it's a mobile app order
        if ("mobile" in source_name_lower or 
            "app" in source_name_lower or
            "mobile app" in source_name_lower):
            return "PaidOnline"
        
        # Check if it's a POS order (store location)
        if ("pos" in source_name_lower or 
            "point of sale" in source_name_lower or
            "point of sale" in source_identifier_lower):
            # For POS orders, check the payment method
            gateway = payment_info.get('gateway', '').lower()
            card_type = payment_info.get('card_type', '').lower()
            
            # Check for COD (Cash on Delivery)
            if "cod" in gateway or "cash on delivery" in gateway or "cash on delivery" in card_type:
                return "COD"
            
            # Check for cash payments
            if "cash" in gateway or "cash" in card_type:
                return "Cash"
            
            # Check for credit card payments
            if any(card in card_type for card in ["visa", "mastercard", "amex", "american express", "discover"]):
                return "CreditCard"
            
            # Default for POS orders
            return "Cash"
        
        # Check for other channels (like phone, email, etc.)
        if ("phone" in source_name_lower or 
            "email" in source_name_lower or
            "phone" in source_identifier_lower):
            # For phone/email orders, check payment method
            gateway = payment_info.get('gateway', '').lower()
            card_type = payment_info.get('card_type', '').lower()
            
            if "cod" in gateway or "cash on delivery" in gateway or "cash on delivery" in card_type:
                return "COD"
            elif any(card in card_type for card in ["visa", "mastercard", "amex", "american express", "discover"]):
                return "CreditCard"
            else:
                return "PaidOnline"  # Default to online payment for phone/email orders
        
        # Default case - assume online store if we can't determine
        logger.warning(f"Could not determine payment type for source: {source_name}, identifier: {source_identifier}")
        return "PaidOnline"
    
    async def create_incoming_payment_in_sap(self, payment_data: Dict[str, Any], order_id: str = "") -> Dict[str, Any]:
        """
        Create incoming payment in SAP
        """
        try:
            result = await sap_client._make_request(
                method='POST',
                endpoint='IncomingPayments',
                data=payment_data,
                order_id=order_id
            )
            
            if result["msg"] == "failure":
                logger.error(f"Failed to create incoming payment in SAP: {result.get('error')}")
                return result
            
            created_payment = result["data"]
            payment_number = created_payment.get('DocEntry', '')
            
            logger.info(f"Created incoming payment in SAP: {payment_number}")
            
            return {
                "msg": "success",
                "sap_payment_number": payment_number,
                "sap_doc_entry": created_payment.get('DocEntry', ''),
                "sap_doc_num": created_payment.get('DocNum', '')
            }
            
        except Exception as e:
            logger.error(f"Error creating incoming payment in SAP: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def add_order_tag(self, store_key: str, order_id: str, tag: str) -> Dict[str, Any]:
        """
        Add tag to order to track payment sync status
        """
        try:
            import httpx
            
            # Get store configuration
            enabled_stores = config_settings.get_enabled_stores()
            store_config = enabled_stores.get(store_key)
            
            if not store_config:
                logger.error(f"Store configuration not found for {store_key}")
                return {"msg": "failure", "error": "Store configuration not found"}
            
            # Extract order ID number from GraphQL ID
            order_id_number = order_id.split("/")[-1] if "/" in order_id else order_id
            
            headers = {
                'X-Shopify-Access-Token': store_config.access_token,
                'Content-Type': 'application/json',
            }
            
            async with httpx.AsyncClient() as client:
                # Get current order to see existing tags
                order_url = f"https://{store_config.shop_url}/admin/api/2024-01/orders/{order_id_number}.json"
                order_response = await client.get(order_url, headers=headers)
                order_response.raise_for_status()
                order_data = order_response.json()
                
                # Get existing tags
                existing_tags = order_data.get('order', {}).get('tags', '').split(',') if order_data.get('order', {}).get('tags') else []
                existing_tags = [tag.strip() for tag in existing_tags if tag.strip()]
                
                # Add new tag if not already present
                if tag not in existing_tags:
                    existing_tags.append(tag)
                
                # Update order with new tags
                update_data = {
                    "order": {
                        "id": order_id_number,
                        "tags": ", ".join(existing_tags)
                    }
                }
                
                update_response = await client.put(order_url, headers=headers, json=update_data)
                update_response.raise_for_status()
                
                logger.info(f"Added tag '{tag}' to order {order_id}")
                
            return {"msg": "success"}
            
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error adding tag to order {order_id}: {e.response.status_code} - {e.response.text}")
            return {"msg": "failure", "error": f"HTTP error: {e.response.status_code}"}
        except Exception as e:
            logger.error(f"Error adding tag to order {order_id}: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def process_order_payment_recovery(self, store_key: str, shopify_order: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process payment recovery for a single order
        """
        try:
            order_node = shopify_order["node"]
            order_id = order_node["id"]
            order_name = order_node["name"]
            order_id_number = order_id.split("/")[-1] if "/" in order_id else order_id
            
            # Check payment and fulfillment status
            financial_status = order_node.get("displayFinancialStatus", "PENDING")
            fulfillment_status = order_node.get("displayFulfillmentStatus", "UNFULFILLED")
            
            logger.info(f"Processing payment recovery for order: {order_name} | Payment: {financial_status} | Fulfillment: {fulfillment_status}")
            
            # Check if order is PAID
            if financial_status != "PAID":
                logger.info(f"Order {order_name} is not PAID (status: {financial_status}) - skipping payment recovery")
                return {
                    "msg": "skipped",
                    "order_id": order_id_number,
                    "order_name": order_name,
                    "reason": f"Order not PAID (status: {financial_status})"
                }
            
            # Extract tags and get SAP invoice DocEntry
            tags = order_node.get("tags", "").split(",") if order_node.get("tags") else []
            tags = [tag.strip() for tag in tags if tag.strip()]
            
            doc_entry = self.extract_sap_invoice_doc_entry(tags)
            if not doc_entry:
                logger.error(f"No SAP invoice DocEntry found in tags for order {order_name}")
                
                # Add payment failed tag
                await self.add_order_tag(store_key, order_id, "sap_payment_failed")
                
                return {"msg": "failure", "error": "No SAP invoice DocEntry found in tags"}
            
            logger.info(f"Found SAP invoice DocEntry: {doc_entry} for order {order_name}")
            
            # Get SAP invoice data for this DocEntry
            sap_invoice_result = await self.get_sap_invoice_by_doc_entry(doc_entry)
            if sap_invoice_result["msg"] == "failure":
                logger.error(f"Failed to get SAP invoice for order {order_name}: {sap_invoice_result.get('error')}")
                
                # Add payment failed tag
                await self.add_order_tag(store_key, order_id, "sap_payment_failed")
                
                return {"msg": "failure", "error": f"Failed to get SAP invoice: {sap_invoice_result.get('error')}"}
            
            sap_invoice = sap_invoice_result["data"]
            
            logger.info(f"Found SAP invoice DocEntry: {sap_invoice.get('DocEntry')} for order {order_name}")
            
            # Check if payment already exists in SAP
            payment_exists_result = await self.check_payment_exists_in_sap(order_id_number)
            if payment_exists_result["msg"] == "failure":
                logger.error(f"Failed to check payment existence for {order_name}: {payment_exists_result.get('error')}")
                return payment_exists_result
            
            if payment_exists_result["exists"]:
                # Payment already exists in SAP, add payment sync tag and skip processing
                logger.info(f"Payment for order {order_name} already exists in SAP with DocEntry: {payment_exists_result['doc_entry']}")
                
                # Add payment sync tag to order
                payment_tag = f"sap_payment_{payment_exists_result['doc_entry']}"
                tag_update_result = await self.add_order_tag(
                    store_key,
                    order_id,
                    payment_tag
                )
                
                if tag_update_result["msg"] == "failure":
                    logger.warning(f"Failed to add payment sync tag for {order_name}: {tag_update_result.get('error')}")
                
                return {
                    "msg": "skipped",
                    "order_id": order_id_number,
                    "order_name": order_name,
                    "reason": "Payment already exists in SAP",
                    "sap_payment_number": payment_exists_result["doc_entry"],
                    "amount": sap_invoice["DocTotal"]
                }
            
            # Prepare payment data
            payment_data = self.prepare_payment_data(sap_invoice, order_node, store_key)
            
            # Create incoming payment in SAP
            payment_result = await self.create_incoming_payment_in_sap(payment_data, order_id_number)
            
            if payment_result["msg"] == "success":
                sap_payment_number = payment_result["sap_payment_number"]
                logger.info(f"✅ Successfully created payment for order {order_name} -> SAP Invoice: {doc_entry} -> Payment: {sap_payment_number}")
                
                # Add payment sync tag
                payment_tag = f"sap_payment_{sap_payment_number}"
                metafield_result = await self.add_order_tag(store_key, order_id, payment_tag)
                if metafield_result["msg"] == "failure":
                    logger.warning(f"Failed to add payment sync tag for {order_name}: {metafield_result.get('error')}")
                
                return {
                    "msg": "success",
                    "order_id": order_id_number,
                    "order_name": order_name,
                    "sap_invoice_doc_entry": doc_entry,
                    "sap_payment_number": sap_payment_number,
                    "amount": sap_invoice["DocTotal"]
                }
            else:
                logger.error(f"❌ Failed to create payment for order {order_name}: {payment_result.get('error')}")
                
                # Add payment failed tag
                metafield_result = await self.add_order_tag(store_key, order_id, "sap_payment_failed")
                if metafield_result["msg"] == "failure":
                    logger.warning(f"Failed to add payment failed tag for {order_name}: {metafield_result.get('error')}")
                
                return {"msg": "failure", "error": f"Payment creation failed: {payment_result.get('error')}"}
            
        except Exception as e:
            logger.error(f"Error processing payment recovery for order {order_name}: {str(e)}")
            
            # Add payment failed tag
            try:
                await self.add_order_tag(store_key, order_id, "sap_payment_failed")
            except:
                pass  # Don't fail if tag update fails
            
            return {"msg": "failure", "error": str(e)}
    
    async def sync_payment_recovery(self) -> Dict[str, Any]:
        """
        Main payment recovery sync process
        """
        logger.info("Starting payment recovery sync...")
        
        try:
            # Get enabled stores
            enabled_stores = config_settings.get_enabled_stores()
            if not enabled_stores:
                logger.warning("No enabled stores found")
                return {"msg": "failure", "error": "No enabled stores found"}
            
            total_processed = 0
            total_success = 0
            total_skipped = 0
            total_errors = 0
            
            # Process orders for each enabled store
            for store_key, store_config in enabled_stores.items():
                try:
                    # Get orders from this store that need payment recovery
                    orders_result = await self.get_orders_from_shopify(store_key)
                    if orders_result["msg"] == "failure":
                        logger.error(f"Failed to get orders from store {store_key}: {orders_result.get('error')}")
                        continue
                    
                    orders = orders_result["data"]
                    if not orders:
                        logger.info(f"No orders need payment recovery for store {store_key}")
                        continue
                    
                    logger.info(f"Processing {len(orders)} orders for payment recovery from store {store_key}")
                    
                    # Process each order
                    for shopify_order in orders:
                        try:
                            order_node = shopify_order["node"]
                            order_id = order_node["id"]
                            
                            logger.info(f"Processing payment recovery for order {order_node.get('name', 'Unknown')} (ID: {order_id})")
                            result = await self.process_order_payment_recovery(store_key, shopify_order)
                            
                            if result["msg"] == "success":
                                total_success += 1
                                logger.info(f"✅ Payment recovery successful for order {result['order_name']} -> SAP Invoice: {result['sap_invoice_doc_entry']} -> Payment: {result['sap_payment_number']}")
                            
                            elif result["msg"] == "skipped":
                                total_skipped += 1
                                logger.info(f"⏭️ Skipped order {result['order_name']} - {result['reason']}")
                            
                            else:
                                total_errors += 1
                                logger.error(f"❌ Payment recovery failed for order: {result.get('error')}")
                            
                            total_processed += 1
                            
                        except Exception as e:
                            total_errors += 1
                            logger.error(f"Error processing order: {str(e)}")
                            continue
                    
                except Exception as e:
                    logger.error(f"Error processing store {store_key}: {str(e)}")
                    continue
            
            # Log sync event
            log_sync_event(
                sync_type="payment_recovery",
                items_processed=total_processed,
                success_count=total_success,
                error_count=total_errors
            )
            
            logger.info(f"Payment recovery sync completed. Processed: {total_processed}, Success: {total_success}, Skipped: {total_skipped}, Errors: {total_errors}")
            
            return {
                "msg": "success",
                "processed": total_processed,
                "success": total_success,
                "skipped": total_skipped,
                "errors": total_errors
            }
            
        except Exception as e:
            logger.error(f"Error in payment recovery sync: {str(e)}")
            return {"msg": "failure", "error": str(e)}
