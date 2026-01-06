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
from order_location_mapper import OrderLocationMapper


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

                        # --- Retail Location ---
                        retailLocation {
                            id
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
            from_date = config_settings.payment_recovery_from_date
            query_filter = f"(channel:{config_settings.payment_recovery_channel} financial_status:paid OR financial_status:partially_refunded OR financial_status:refunded) fulfillment_status:fulfilled tag:sap_invoice_synced -tag:sap_payment_synced -tag:sap_payment_failed created_at:>={from_date}"
            
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
                "$select": "DocEntry,CardCode,DocTotal,U_Shopify_Order_ID,DocDate,DocTotalFc",
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
    
    def prepare_payment_data(self, sap_invoice: Dict[str, Any], shopify_order: Dict[str, Any], store_key: str, location_analysis: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Prepare incoming payment data for SAP
        Handles gift cards, store credit, and multiple payment gateways
        """
        try:
            from datetime import datetime, timedelta
            
            # Extract order ID from GraphQL ID
            order_id = shopify_order.get("id", "")
            # Extract just the numeric ID from the full GID (e.g., "6342714261570" from "gid://shopify/Order/6342714261570")
            order_id_number = order_id.split("/")[-1] if "/" in order_id else order_id
            
            # Get payment information from transactions
            payment_info = self._extract_payment_info_from_transactions(shopify_order.get("transactions", []))
            
            # Get order channel information
            source_name = (shopify_order.get("sourceName") or "").lower()
            source_identifier = (shopify_order.get("sourceIdentifier") or "").lower()
            
            # Determine payment type based on channel and payment method
            location_type = config_settings.get_location_type(location_analysis.get('location_mapping', {})) if location_analysis else "online"
            payment_type = self._determine_payment_type(source_name, source_identifier, payment_info, location_type)
            
            # Initialize payment data
            # Use the same DocDate as the invoice
            invoice_doc_date = sap_invoice.get("DocDate", datetime.now().strftime("%Y-%m-%d"))
            payment_data = {
                "DocDate": invoice_doc_date,
                "CardCode": sap_invoice["CardCode"],
                "DocType": "rCustomer",
                "Series": config_settings.get_series_for_location(store_key, location_analysis.get('location_mapping', {}), 'incoming_payments') if location_analysis else 15,
                "TransferSum": 0.0,
                "TransferAccount": "",
                "U_Shopify_Order_ID": order_id_number
            }
            
            # Get invoice document entry
            invoice_doc_entry = sap_invoice.get("DocEntry", "")
            invoice_total = sap_invoice.get("DocTotal", 0.0)
            
            # Initialize variables for payment calculation
            calc_amount = 0.0
            cred_array = []
            location_mapping = location_analysis.get('location_mapping', {}) if location_analysis else {}
            
            # Check if this is a POS order (store location)
            if location_type == "store":
                logger.info(f"🏪 POS ORDER DETECTED - Processing multiple payment types")
                
                # Process each payment gateway transaction
                payment_gateways = payment_info.get("payment_gateways", [])
                
                for gateway_info in payment_gateways:
                    gateway = gateway_info["gateway"]
                    amount = gateway_info["amount"]
                    
                    if gateway.lower() == "cash":
                        # Handle cash transactions
                        cash_account = config_settings.get_cash_account_for_location(location_mapping)
                        if cash_account:
                            payment_data["CashSum"] = amount
                            payment_data["CashAccount"] = cash_account
                            calc_amount += amount
                            logger.info(f"💰 CASH TRANSACTION: {amount} EGP - Account: {cash_account}")
                        else:
                            logger.warning(f"No cash account configured for location")
                            
                    elif gateway in config_settings.get_credits_for_location(store_key, location_mapping):
                        # Handle credit card transactions
                        cred_obj = {}
                        
                        # Get credit account from configuration
                        credit_account = config_settings.get_credit_account_for_location(store_key, location_mapping, gateway)
                        if credit_account:
                            cred_obj['CreditCard'] = credit_account
                        else:
                            logger.warning(f"No credit account found for gateway: {gateway}")
                            continue
                        
                        cred_obj['CreditCardNumber'] = "1234"
                        
                        # Calculate next month date
                        next_month = datetime.now().replace(day=28) + timedelta(days=4)
                        res = next_month - timedelta(days=next_month.day)
                        cred_obj['CardValidUntil'] = str(res.date())
                        
                        cred_obj['VoucherNum'] = gateway
                        cred_obj['PaymentMethodCode'] = 1
                        cred_obj['CreditSum'] = amount
                        cred_obj['CreditCur'] = "EGP"
                        cred_obj['CreditType'] = "cr_Regular"
                        cred_obj['SplitPayments'] = "tNO"
                        
                        calc_amount += amount
                        cred_array.append(cred_obj)
                        logger.info(f"💳 CREDIT CARD TRANSACTION: {gateway} - {amount} EGP - Account: {credit_account}")
                        
                    elif gateway in config_settings.get_bank_transfers_for_location(store_key, location_mapping):
                        # Handle other payment gateways as bank transfers
                        transfer_account = config_settings.get_bank_transfer_for_location(
                            store_key, location_mapping, gateway
                        )
                        if transfer_account:
                            payment_data["TransferSum"] = amount
                            payment_data["TransferAccount"] = transfer_account
                            calc_amount += amount
                            logger.info(f"🏦 BANK TRANSFER TRANSACTION: {gateway} - {amount} EGP - Account: {transfer_account}")
                    else:
                        logger.warning(f"No bank transfer account found for gateway: {gateway}")
                
                # Process gift cards as credit card payments
                gift_cards = payment_info.get("gift_cards", [])
                if gift_cards:
                    logger.info(f"🎁 Processing {len(gift_cards)} gift card payment(s) for POS order")
                    
                    # Get gift card credit card ID from config (not the SAP account)
                    gift_card_credit_id = None
                    if location_mapping and 'credit' in location_mapping:
                        credit_accounts = location_mapping['credit']
                        if 'Gift Card' in credit_accounts:
                            gift_card_credit_id = credit_accounts['Gift Card']
                    
                    if not gift_card_credit_id:
                        logger.warning(f"No gift card credit ID configured for location, skipping gift card payments")
                    else:
                        for gift_card in gift_cards:
                            # Calculate CardValidUntil (next month's last day)
                            next_month = datetime.now().replace(day=28) + timedelta(days=4)
                            res = next_month - timedelta(days=next_month.day)
                            
                            cred_obj = {
                                "CreditCard": gift_card_credit_id,
                                "CreditCardNumber": gift_card.get('last_characters', 'Unknown'),
                                "CardValidUntil": str(res.date()),
                                "VoucherNum": gift_card.get('gift_card_id', 'Unknown'),
                                "PaymentMethodCode": 1,
                                "CreditSum": gift_card["amount"],
                                "CreditCur": "EGP",
                                "CreditType": "cr_Regular",
                                "SplitPayments": "tNO"
                            }
                            calc_amount += gift_card["amount"]
                            cred_array.append(cred_obj)
                            logger.info(f"🎁 Added gift card payment: {gift_card.get('last_characters', 'Unknown')} - {gift_card['amount']} EGP")
                
                # Add credit cards array if we have any
                if cred_array:
                    payment_data["PaymentCreditCards"] = cred_array
                
                # Set SumApplied to calculated amount
                sum_applied = calc_amount
                
            else:
                # Handle online orders
                logger.info(f"🌐 ONLINE ORDER DETECTED - Processing payment")
                
                # Calculate payment amount excluding store credit AND gift cards
                store_credit_amount = payment_info.get("store_credit", {}).get("amount", 0.0)
                total_gift_card_amount = payment_info.get("total_gift_card_amount", 0.0)
                total_payment_amount = payment_info.get("total_payment_amount", 0.0)
                
                # Use total_payment_amount if available (multiple gateways), otherwise fall back to calculation
                if total_payment_amount > 0:
                    payment_amount = total_payment_amount
                else:
                    payment_amount = invoice_total - store_credit_amount - total_gift_card_amount
                
                logger.info(f"💰 ONLINE PAYMENT CALCULATION: Payment Amount: {payment_amount} EGP | Store Credit: {store_credit_amount} EGP | Gift Cards: {total_gift_card_amount} EGP")
                
                # Process gift cards as credit card payments
                gift_cards = payment_info.get("gift_cards", [])
                if gift_cards:
                    logger.info(f"🎁 Processing {len(gift_cards)} gift card payment(s) for online order")
                    
                    # Get gift card credit card ID from config (not the SAP account)
                    gift_card_credit_id = None
                    if location_mapping and 'credit' in location_mapping:
                        credit_accounts = location_mapping['credit']
                        if 'Gift Card' in credit_accounts:
                            gift_card_credit_id = credit_accounts['Gift Card']
                    
                    if not gift_card_credit_id:
                        logger.warning(f"No gift card credit ID configured for location, skipping gift card payments")
                    else:
                        for gift_card in gift_cards:
                            # Calculate CardValidUntil (next month's last day)
                            next_month = datetime.now().replace(day=28) + timedelta(days=4)
                            res = next_month - timedelta(days=next_month.day)
                            
                            cred_obj = {
                                "CreditCard": gift_card_credit_id,
                                "CreditCardNumber": gift_card.get('last_characters', 'Unknown'),
                                "CardValidUntil": str(res.date()),
                                "VoucherNum": gift_card.get('gift_card_id', 'Unknown'),
                                "PaymentMethodCode": 1,
                                "CreditSum": gift_card["amount"],
                                "CreditCur": "EGP",
                                "CreditType": "cr_Regular",
                                "SplitPayments": "tNO"
                            }
                            cred_array.append(cred_obj)
                            calc_amount += gift_card["amount"]
                            logger.info(f"🎁 Added gift card payment: {gift_card.get('last_characters', 'Unknown')} - {gift_card['amount']} EGP")
                
                # Set payment method based on type and location
                if payment_type == "PaidOnline":
                    # Online payments - use location-based bank transfer account
                    if payment_amount > 0:  # Only set if there's remaining amount after gift cards
                        payment_data["TransferSum"] = payment_amount
                        
                        # Get the actual gateway from payment info
                        gateway = payment_info.get('gateway', 'Paymob')
                        
                        # Get bank transfer account using new location-based method
                        transfer_account = config_settings.get_bank_transfer_for_location(
                            store_key, 
                            location_mapping, 
                            gateway
                        )
                        
                        payment_data["TransferAccount"] = transfer_account
                        logger.info(f"Online payment - using {gateway} account: {transfer_account}")
                    
                elif payment_type == "COD":
                    # Cash on delivery - handle courier-specific accounts for online locations
                    if payment_amount > 0:  # Only set if there's remaining amount after gift cards
                        payment_data["TransferSum"] = payment_amount
                        
                        # Extract courier name from metafields for COD payments
                        courier_name = ""
                        if location_type == "online":
                            # Extract courier name from metafields
                            metafields = shopify_order.get("metafields", {}).get("edges", [])
                            for metafield_edge in metafields:
                                metafield = metafield_edge.get("node", {})
                                namespace = metafield.get("namespace", "")
                                key = metafield.get("key", "")
                                value = metafield.get("value", "")
                                
                                if namespace == "custom" and key == "courier" and value:
                                    # Handle JSON array format like '["4 - Tuyingo"]'
                                    import json
                                    try:
                                        if value.startswith('[') and value.endswith(']'):
                                            # Parse JSON array and take first element
                                            courier_list = json.loads(value)
                                            if courier_list and len(courier_list) > 0:
                                                value = courier_list[0]
                                    except (json.JSONDecodeError, IndexError):
                                        pass  # Use original value if JSON parsing fails
                                    
                                    parts = value.split("-")
                                    if len(parts) >= 2:
                                        courier_name = parts[1].strip()
                                        break
                        
                        # Get bank transfer account using new location-based method with courier
                        transfer_account = config_settings.get_bank_transfer_for_location(
                            store_key, 
                            location_mapping, 
                            "Cash on Delivery (COD)",
                            courier_name
                        )
                        
                        payment_data["TransferAccount"] = transfer_account
                        logger.info(f"COD payment - using COD account: {transfer_account} (courier: {courier_name})")
                    
                else:
                    # Default case - treat as online payment
                    if payment_amount > 0:  # Only set if there's remaining amount after gift cards
                        payment_data["TransferSum"] = payment_amount
                        gateway = payment_info.get('gateway', 'Paymob')
                        
                        transfer_account = config_settings.get_bank_transfer_for_location(
                            store_key, 
                            location_mapping, 
                            gateway
                        )
                        
                        payment_data["TransferAccount"] = transfer_account
                        logger.info(f"Default payment - using {gateway} account: {transfer_account}")
                
                # Add gift card credit cards array if we have any
                if cred_array:
                    payment_data["PaymentCreditCards"] = cred_array
                
                # Calculate total payment amount (gateway payments + gift cards)
                sum_applied = calc_amount + payment_amount
                
                logger.info(f"💰 ONLINE PAYMENT SUMMARY: Gateway: {payment_amount} EGP | Gift Cards: {calc_amount} EGP | Total: {sum_applied} EGP")
            
            # Create invoice object for payment
            inv_obj = {
                "DocEntry": invoice_doc_entry,
                "SumApplied": sum_applied,
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
        Extract payment information from Shopify order transactions including gift cards and store credit
        """
        payment_info = {
            "gateway": "Unknown",
            "card_type": "Unknown", 
            "last_4": "Unknown",
            "payment_id": "Unknown",
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
                    
                    # Handle all payment gateway transactions except gift_card and store_credit
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
                        if gateway.lower() in ["paymob", "stripe", "paypal"]:
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
                            logger.info(f"🎁 GIFT CARD DETECTED: {gift_card_info['last_characters']} - {amount} {gift_card_info['currency']}")
                            
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
                        payment_info["payment_id"] = transaction.get("id", "Unknown")
                        
                        # Use gateway as card type if payment details not available
                        payment_info["card_type"] = gateway
                        
                        # Check if this is an online payment
                        if gateway.lower() in ["paymob", "stripe", "paypal"]:
                            payment_info["is_online_payment"] = True
                    
        except Exception as e:
            logger.error(f"Error extracting payment info: {str(e)}")
        
        return payment_info
    
    def _determine_payment_type(self, source_name: str, source_identifier: str, payment_info: Dict[str, Any], location_type: str = "online") -> str:
        """
        Determine payment type based on order channel and payment information
        """
        # Convert to lowercase for case-insensitive matching
        source_name_lower = (source_name or "").lower()
        source_identifier_lower = (source_identifier or "").lower()
        gateway = payment_info.get('gateway', '').lower()
        card_type = payment_info.get('card_type', '').lower()
        
        # For online locations
        if location_type == "online":
            # Check for COD (Cash on Delivery)
            if "cod" in gateway or "cash on delivery" in gateway or "cash on delivery" in card_type:
                return "COD"
            
            # All other online payments are considered online payments
            return "PaidOnline"
        
        # For store locations
        elif location_type == "store":
            # Check for COD (Cash on Delivery)
            if "cod" in gateway or "cash on delivery" in gateway or "cash on delivery" in card_type:
                return "COD"
            
            # Check for cash payments
            if "cash" in gateway or "cash" in card_type:
                return "Cash"
            
            # Check for credit card payments
            if any(card in card_type for card in ["visa", "mastercard", "amex", "american express", "discover"]):
                return "CreditCard"
            
            # Default for store orders
            return "Cash"
        
        # Legacy logic for backward compatibility
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
            # Check for COD (Cash on Delivery)
            if ("cod" in gateway or 
                "cash on delivery" in gateway or 
                "cash on delivery" in card_type):
                return "COD"
            
            # Check for cash payments
            if ("cash" in gateway or "cash" in card_type):
                return "Cash"
            
            # Check for credit card payments
            if any(card in card_type for card in ["visa", "mastercard", "amex", "american express", "discover"]):
                return "CreditCard"
            
            # Default for POS orders
            return "Cash"
        
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
        Add tag to order to track payment sync status with retry logic
        """
        import httpx
        import asyncio
        
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
        
        # Retry logic for tag addition
        max_retries = 3
        retry_delay = 2  # Start with 2 seconds
        
        for attempt in range(max_retries):
            try:
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
                if e.response.status_code == 429:  # Rate limited
                    # Use safe_log to prevent logging errors from interrupting the process
                    from app.utils.logging import safe_log
                    safe_log('warning', f"Rate limited adding tag to order {order_id}, attempt {attempt + 1}/{max_retries}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                else:
                    # Use safe_log to prevent logging errors from interrupting the process
                    from app.utils.logging import safe_log
                    safe_log('error', f"HTTP error adding tag to order {order_id}: {e.response.status_code} - {e.response.text}")
                    return {"msg": "failure", "error": f"HTTP error: {e.response.status_code}"}
            except Exception as e:
                # Use safe_log to prevent logging errors from interrupting the process
                from app.utils.logging import safe_log
                safe_log('warning', f"Error adding tag to order {order_id}, attempt {attempt + 1}/{max_retries}: {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                    continue
                else:
                    safe_log('error', f"Failed to add tag to order {order_id} after {max_retries} attempts: {str(e)}")
                    return {"msg": "failure", "error": str(e)}
        
        # If we get here, all retries failed
        from app.utils.logging import safe_log
        safe_log('error', f"Failed to add tag '{tag}' to order {order_id} after {max_retries} attempts")
        return {"msg": "failure", "error": "Max retries exceeded"}
    
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
            
            # Get location mapping for this order using retailLocation
            location_analysis = self._analyze_order_location_from_retail_location(order_node, store_key)
            
            logger.info(f"Processing payment recovery for order: {order_name} | Payment: {financial_status} | Fulfillment: {fulfillment_status}")
            
            # Check if order is PAID or PARTIALLY_REFUNDED (treat PARTIALLY_REFUNDED as PAID for payment recovery)
            if financial_status not in ["PAID", "PARTIALLY_REFUNDED"]:
                logger.info(f"Order {order_name} is not PAID or PARTIALLY_REFUNDED (status: {financial_status}) - skipping payment recovery")
                return {
                    "msg": "skipped",
                    "order_id": order_id_number,
                    "order_name": order_name,
                    "reason": f"Order not PAID or PARTIALLY_REFUNDED (status: {financial_status})"
                }
            
            # Extract tags and get SAP invoice DocEntry
            tags_raw = order_node.get("tags", [])
            if isinstance(tags_raw, str):
                tags = tags_raw.split(",") if tags_raw else []
            else:
                tags = tags_raw if tags_raw else []
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
                
                # Add payment sync tags to order
                payment_tag = f"sap_payment_{payment_exists_result['doc_entry']}"
                tag_update_result = await self.add_order_tag(
                    store_key,
                    order_id,
                    payment_tag
                )
                # Also add the general payment synced tag
                synced_tag_result = await self.add_order_tag(store_key, order_id, "sap_payment_synced")
                if synced_tag_result["msg"] == "failure":
                    logger.warning(f"Failed to add sap_payment_synced tag for {order_name}: {synced_tag_result.get('error')}")
                
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
            payment_data = self.prepare_payment_data(sap_invoice, order_node, store_key, location_analysis)
            
            # Create incoming payment in SAP
            payment_result = await self.create_incoming_payment_in_sap(payment_data, order_id_number)
            
            if payment_result["msg"] == "success":
                sap_payment_number = payment_result["sap_payment_number"]
                logger.info(f"✅ Successfully created payment for order {order_name} -> SAP Invoice: {doc_entry} -> Payment: {sap_payment_number}")
                
                # Add payment sync tags
                payment_tag = f"sap_payment_{sap_payment_number}"
                metafield_result = await self.add_order_tag(store_key, order_id, payment_tag)
                if metafield_result["msg"] == "failure":
                    logger.warning(f"Failed to add payment sync tag for {order_name}: {metafield_result.get('error')}")
                
                # Also add the general payment synced tag
                synced_tag_result = await self.add_order_tag(store_key, order_id, "sap_payment_synced")
                if synced_tag_result["msg"] == "failure":
                    logger.warning(f"Failed to add sap_payment_synced tag for {order_name}: {synced_tag_result.get('error')}")
                
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
                location_mapping = config_settings.get_location_mapping_for_location(store_key, location_id)
                
                if not location_mapping:
                    logger.warning(f"No location mapping found for location {location_id}, using default location mapping")
                    from order_location_mapper import OrderLocationMapper
                    return OrderLocationMapper.analyze_order_source(order_node, store_key)
                
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
