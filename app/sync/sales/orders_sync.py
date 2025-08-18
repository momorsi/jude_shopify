"""
Orders Sync for Sales Module
Syncs orders from Shopify to SAP with customer management and invoice creation
"""

import asyncio
from typing import Dict, Any, List, Optional
from decimal import Decimal
from app.services.sap.client import sap_client
from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.core.config import config_settings
from app.utils.logging import logger, log_sync_event
from app.sync.sales.customers import CustomerManager
from datetime import datetime


class OrdersSalesSync:
    """
    Handles orders synchronization from Shopify to SAP
    """
    
    def __init__(self):
        self.batch_size = config_settings.sales_orders_batch_size
        self.customer_manager = CustomerManager()
    
    async def get_orders_from_shopify(self, store_key: str) -> Dict[str, Any]:
        """
        Get orders from Shopify store that need to be synced
        """
        try:
            # Query to get orders with payment and fulfillment status
            query = """
            query getOrders($first: Int!, $after: String) {
                orders(first: $first, after: $after, sortKey: CREATED_AT, reverse: true) {
                    edges {
                        node {
                            id
                            name
                            createdAt
                            metafields(first: 10, namespace: "custom") {
                                edges {
                                    node {
                                        id
                                        namespace
                                        key
                                        value
                                        type
                                    }
                                }
                            }
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
                                        variant {
                                            id
                                            sku
                                            price
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
            
            result = await multi_store_shopify_client.execute_query(
                store_key,
                query,
                {"first": self.batch_size, "after": None}
            )
            
            if result["msg"] == "failure":
                return result
            
            orders = result["data"]["orders"]["edges"]
            
            # Filter orders that don't have the synced metafield
            unsynced_orders = []
            for order in orders:
                order_node = order["node"]
                metafields = order_node.get("metafields", {}).get("edges", [])
                
                # Check if order has synced metafield
                has_synced_metafield = False
                for metafield_edge in metafields:
                    metafield = metafield_edge["node"]
                    if metafield["namespace"] == "custom" and metafield["key"] == "sap_sync":
                        has_synced_metafield = True
                        break
                
                if not has_synced_metafield:
                    unsynced_orders.append(order)
            
            logger.info(f"Retrieved {len(orders)} total orders, {len(unsynced_orders)} unsynced orders from Shopify store {store_key}")
            
            return {"msg": "success", "data": unsynced_orders}
            
        except Exception as e:
            logger.error(f"Error getting orders from Shopify: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    

    

    
    def map_shopify_order_to_sap(self, shopify_order: Dict[str, Any], customer_card_code: str, store_key: str) -> Dict[str, Any]:
        """
        Map Shopify order data to SAP invoice format
        """
        try:
            # Extract order data
            order_node = shopify_order["node"]
            order_name = order_node["name"]
            created_at = order_node["createdAt"]
            total_price = Decimal(order_node["totalPriceSet"]["shopMoney"]["amount"])
            currency = order_node["totalPriceSet"]["shopMoney"]["currencyCode"]
            
            # Get payment and fulfillment status
            financial_status = order_node.get("displayFinancialStatus", "PENDING")
            fulfillment_status = order_node.get("displayFulfillmentStatus", "UNFULFILLED")
            
            # Map line items
            line_items = []
            for item_edge in order_node["lineItems"]["edges"]:
                item = item_edge["node"]
                sku = item.get("sku")
                quantity = item["quantity"]
                
                # Get price from variant if available, otherwise use a default
                if item.get("variant") and item["variant"].get("price"):
                    price = Decimal(item["variant"]["price"])
                else:
                    # Fallback to a default price if variant price is not available
                    price = Decimal("0.00")
                
                # Use the actual SKU as item code, or a default if not available
                if sku:
                    item_code = sku  # Use the actual SKU from Shopify
                else:
                    item_code = "ACC-0000001"  # Default item only if no SKU
                
                # Get warehouse code based on order location
                warehouse_code = config_settings.get_warehouse_code_for_order(store_key, order_node)
                
                line_item = {
                    "ItemCode": item_code,
                    "Quantity": quantity,
                    "UnitPrice": float(price),
                    "WarehouseCode": warehouse_code,
                    "COGSCostingCode": "ONL",
                    "COGSCostingCode2": "SAL",
                    "COGSCostingCode3": "OnlineS",
                    "CostingCode": "ONL",
                    "CostingCode2": "SAL",
                    "CostingCode3": "OnlineS"                    
                }
                line_items.append(line_item)
            
            # Parse date
            doc_date = created_at.split("T")[0] if "T" in created_at else created_at
            
            # Calculate freight expenses
            freight_expenses = self._calculate_freight_expenses(order_node, store_key)
            
            # Create invoice data
            invoice_data = {
                "DocDate": doc_date,
                "CardCode": customer_card_code,
                "NumAtCard": order_name,
                "Series": 82,
                "Comments": f"Shopify Order: {order_name} | Payment: {financial_status} | Fulfillment: {fulfillment_status}",
                #"U_Shopify_Order_ID": order_name,
                #"U_Shopify_Financial_Status": financial_status,
                #"U_Shopify_Fulfillment_Status": fulfillment_status,
                "SalesPersonCode": 28,
                "DocumentLines": line_items,
                "U_Pay_type": 1
            }
            
            # Add freight expenses if any
            if freight_expenses:
                invoice_data["DocumentAdditionalExpenses"] = freight_expenses
            
            return invoice_data
            
        except Exception as e:
            logger.error(f"Error mapping order to SAP format: {str(e)}")
            raise
    
    def _extract_gift_card_lines(self, order_node: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract gift card redemption lines from order
        """
        gift_card_lines = []
        
        # Check discount applications for gift card redemptions
        discount_applications = order_node.get("discountApplications", {}).get("edges", [])
        
        for discount_edge in discount_applications:
            discount = discount_edge["node"]
            
            # Check if this is a gift card discount
            if discount.get("type") == "DISCOUNT_CODE":
                # This might be a gift card redemption
                # You'll need to implement logic to identify gift card discounts
                # For now, we'll create a placeholder line
                gift_card_line = {
                    "ItemCode": "GIFT_CARD_REDEMPTION",  # You'll need to create this item in SAP
                    "Quantity": 1,
                    "UnitPrice": -float(discount["value"]["amount"]),  # Negative amount
                    "LineTotal": -float(discount["value"]["amount"]),
                    "U_ShopifyDiscountID": discount.get("id", ""),
                    "U_IsGiftCardRedemption": "Y"
                }
                gift_card_lines.append(gift_card_line)
        
        return gift_card_lines
    
    def _calculate_freight_expenses(self, order_node: Dict[str, Any], store_key: str) -> List[Dict[str, Any]]:
        """
        Calculate freight expenses based on shipping fee and store configuration
        """
        try:
            # Get shipping price from order
            shipping_price = float(order_node.get("totalShippingPriceSet", {}).get("shopMoney", {}).get("amount", 0))
            
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
                        config["revenue"]["DistributionRule"] = "ONL"                                               
                        config["revenue"]["DistributionRule2"] = "SAL"                                               
                        config["revenue"]["DistributionRule3"] = "OnlineS"                                               
                        expenses.append(config["revenue"])
                    
                    # Add cost expense
                    if "cost" in config:
                        config["cost"]["DistributionRule"] = "ONL"                                               
                        config["cost"]["DistributionRule2"] = "SAL"                                               
                        config["cost"]["DistributionRule3"] = "OnlineS"  
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
    
    async def create_invoice_in_sap(self, invoice_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create invoice in SAP
        """
        try:
            result = await sap_client._make_request(
                method='POST',
                endpoint='Invoices',
                data=invoice_data
            )
            
            if result["msg"] == "failure":
                logger.error(f"Failed to create invoice in SAP: {result.get('error')}")
                return result
            
            created_invoice = result["data"]
            invoice_number = created_invoice.get('DocEntry', '')
            
            logger.info(f"Created invoice in SAP: {invoice_number}")
            
            return {
                "msg": "success",
                "sap_invoice_number": invoice_number,
                "sap_doc_entry": created_invoice.get('DocEntry', ''),
                "sap_doc_num": created_invoice.get('DocNum', '')
            }
            
        except Exception as e:
            logger.error(f"Error creating invoice in SAP: {str(e)}")
            return {"msg": "failure", "error": str(e)}

    def prepare_incoming_payment_data(self, shopify_order: Dict[str, Any], sap_invoice_data: Dict[str, Any], 
                                    customer_card_code: str, store_key: str) -> Dict[str, Any]:
        """
        Prepare incoming payment data for SAP based on Shopify order payment information
        """
        try:
            order_node = shopify_order["node"]
            order_name = order_node["name"]
            total_amount = float(order_node["totalPriceSet"]["shopMoney"]["amount"])
            
            # Get payment information from transactions
            payment_info = self._extract_payment_info(order_node)
            
            # Get order channel information
            source_name = (order_node.get("sourceName") or "").lower()
            source_identifier = (order_node.get("sourceIdentifier") or "").lower()
            
            # Determine payment type based on channel and payment method
            payment_type = self._determine_payment_type(source_name, source_identifier, payment_info)
            
            # Get invoice document entry from SAP invoice data
            invoice_doc_entry = sap_invoice_data.get("DocEntry", "")
            if not invoice_doc_entry:
                logger.error("No DocEntry found in SAP invoice data")
                raise ValueError("No DocEntry found in SAP invoice data")
            
            # Initialize payment data with the correct structure
            payment_data = {
                "DocDate": datetime.now().strftime("%Y-%m-%d"),
                "CardCode": customer_card_code,
                "DocType": "rCustomer",
                "Series": 15,  # Series for incoming payments
                "TransferSum": 0.0,
                "TransferAccount": ""
            }
            
            # Set payment method based on type
            if payment_type == "PaidOnline":
                # Online store payments - use Paymob account
                payment_data["TransferSum"] = total_amount
                transfer_account = config_settings.get_bank_transfer_account(store_key, "Paymob")
                payment_data["TransferAccount"] = transfer_account
                logger.info(f"Online store payment - using Paymob account: {transfer_account}")
                
            elif payment_type == "COD":
                # Cash on delivery - use COD account
                payment_data["TransferSum"] = total_amount
                transfer_account = config_settings.get_bank_transfer_account(store_key, "Cash on Delivery (COD)")
                payment_data["TransferAccount"] = transfer_account
                logger.info(f"COD payment - using COD account: {transfer_account}")
                
            elif payment_type == "Cash":
                # Cash payment at store
                payment_data["TransferSum"] = total_amount
                # For cash payments, we might need a different account or handle differently
                logger.info(f"Cash payment at store - using transfer sum")
                
            elif payment_type == "CreditCard":
                # Credit card payment at store
                payment_data["TransferSum"] = total_amount
                logger.info(f"Credit card payment at store - using transfer sum")
                
            else:
                # Default to transfer for unknown payment types
                payment_data["TransferSum"] = total_amount
                logger.warning(f"Unknown payment type '{payment_type}' - defaulting to transfer")
            
            # Create invoice object for payment
            inv_obj = {
                "DocEntry": invoice_doc_entry,
                "SumApplied": total_amount,
                "InvoiceType": "it_Invoice"
            }
            
            # Add invoice to payment data
            payment_data["PaymentInvoices"] = [inv_obj]
            
            return payment_data
            
        except Exception as e:
            logger.error(f"Error preparing incoming payment data: {str(e)}")
            raise

    def _extract_payment_info(self, order_node: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract payment information from Shopify order transactions
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
            "is_online_payment": False
        }
        
        try:
            transactions = order_node.get("transactions", [])
            
            for transaction in transactions:
                
                # Look for successful payment transactions
                if (transaction.get("kind") == "SALE" and 
                    transaction.get("status") == "SUCCESS"):
                    
                    payment_info["gateway"] = transaction.get("gateway", "Unknown")
                    payment_info["amount"] = float(transaction.get("amountSet", {}).get("shopMoney", {}).get("amount", 0))
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
                        payment_info["card_type"] = transaction.get("gateway", "Unknown")
                    
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

    async def create_incoming_payment_in_sap(self, payment_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create incoming payment in SAP
        """
        try:
            result = await sap_client._make_request(
                method='POST',
                endpoint='IncomingPayments',
                data=payment_data
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



    async def update_order_metafield(self, store_key: str, order_id: str, status: str) -> Dict[str, Any]:
        """
        Update order metafield to track sync status
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
                # Get current metafields
                metafields_url = f"https://{store_config.shop_url}/admin/api/2024-01/orders/{order_id_number}/metafields.json"
                metafields_response = await client.get(metafields_url, headers=headers)
                metafields_response.raise_for_status()
                metafields_data = metafields_response.json()
                metafields = metafields_data.get('metafields', [])
                
                # Check if metafield already exists
                existing_metafield = None
                for metafield in metafields:
                    if metafield.get('namespace') == 'custom' and metafield.get('key') == 'sap_sync':
                        existing_metafield = metafield
                        break
                
                if existing_metafield:
                    # Update existing metafield
                    update_url = f"https://{store_config.shop_url}/admin/api/2024-01/metafields/{existing_metafield['id']}.json"
                    update_data = {
                        "metafield": {
                            "value": status
                        }
                    }
                    
                    update_response = await client.put(update_url, headers=headers, json=update_data)
                    update_response.raise_for_status()
                    
                    logger.info(f"Updated metafield custom.sap_sync = {status} for order {order_id}")
                else:
                    # Create new metafield
                    create_data = {
                        "metafield": {
                            "namespace": "custom",
                            "key": "sap_sync",
                            "value": status,
                            "type": "single_line_text_field"
                        }
                    }
                    
                    create_response = await client.post(metafields_url, headers=headers, json=create_data)
                    create_response.raise_for_status()
                    
                    logger.info(f"Created metafield custom.sap_sync = {status} for order {order_id}")
                
            return {"msg": "success"}
            
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error setting metafield for order {order_id}: {e.response.status_code} - {e.response.text}")
            return {"msg": "failure", "error": f"HTTP error: {e.response.status_code}"}
        except Exception as e:
            logger.error(f"Error setting metafield for order {order_id}: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def process_order(self, store_key: str, shopify_order: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single order from Shopify to SAP
        """
        try:
            order_node = shopify_order["node"]
            order_id = order_node["id"]
            order_name = order_node["name"]
            
            # Check payment and fulfillment status
            financial_status = order_node.get("displayFinancialStatus", "PENDING")
            fulfillment_status = order_node.get("displayFulfillmentStatus", "UNFULFILLED")
            
            # Extract payment information
            payment_info = self._extract_payment_info(order_node)
            
            # Extract address information
            shipping_address = order_node.get("shippingAddress", {})
            billing_address = order_node.get("billingAddress", {})
            
            logger.info(f"Processing order: {order_name} | Payment: {financial_status} | Fulfillment: {fulfillment_status}")
            logger.info(f"Payment Gateway: {payment_info['gateway']} | Card Type: {payment_info['card_type']} | Amount: {payment_info['amount']}")
            
            if payment_info['is_online_payment']:
                logger.info(f"🔑 ONLINE PAYMENT ID: {payment_info['payment_id']}")
            
            # Log address information
            if shipping_address:
                ship_to = f"{shipping_address.get('firstName', '')} {shipping_address.get('lastName', '')} | {shipping_address.get('address1', '')} | {shipping_address.get('city', '')}, {shipping_address.get('province', '')} | {shipping_address.get('phone', 'No phone')}"
                logger.info(f"📍 SHIP TO: {ship_to}")
            
            if billing_address:
                bill_to = f"{billing_address.get('firstName', '')} {billing_address.get('lastName', '')} | {billing_address.get('address1', '')} | {billing_address.get('city', '')}, {billing_address.get('province', '')} | {billing_address.get('phone', 'No phone')}"
                logger.info(f"📍 BILL TO: {bill_to}")
            
            # For now, we'll process all orders regardless of status
            # Later you can add logic to handle different statuses differently
            if financial_status == "PENDING":
                logger.info(f"Order {order_name} is pending payment - will process anyway")
            
            if fulfillment_status == "UNFULFILLED":
                logger.info(f"Order {order_name} is unfulfilled - will process anyway")
            
            # Get or create customer in SAP
            customer = order_node.get("customer")
            if not customer:
                logger.warning(f"No customer found for order {order_name}")
                return {"msg": "failure", "error": "No customer found"}
            
            # Extract phone number from customer, then fall back to shipping/billing addresses
            phone = self.customer_manager._extract_phone_from_customer(customer)
            if not phone:
                shipping_phone = (order_node.get("shippingAddress") or {}).get("phone")
                billing_phone = (order_node.get("billingAddress") or {}).get("phone")
                phone = shipping_phone or billing_phone
            if not phone:
                logger.warning(f"No phone number found for customer in order {order_name}")
                return {"msg": "failure", "error": "No phone number found for customer"}
            
            # Check if customer exists in SAP by phone
            existing_customer = await self.customer_manager.find_customer_by_phone(phone)
            
            if existing_customer:
                logger.info(f"Found existing customer: {existing_customer.get('CardCode', 'Unknown')}")
                sap_customer = existing_customer
            else:
                # Create new customer in SAP
                logger.info("Creating new customer in SAP")
                sap_customer = await self.customer_manager.create_customer_in_sap(customer)
            if not sap_customer:
                    logger.error(f"Failed to create customer for order {order_name}")
                    return {"msg": "failure", "error": "Failed to create customer"}
            
            # Map order to SAP format
            sap_invoice_data = self.map_shopify_order_to_sap(shopify_order, sap_customer["CardCode"], store_key)
            if not sap_invoice_data:
                logger.error(f"Failed to map order {order_name} to SAP format")
                return {"msg": "failure", "error": "Failed to map order to SAP format"}
            
            # Create invoice in SAP
            invoice_result = await self.create_invoice_in_sap(sap_invoice_data)
            if invoice_result["msg"] == "failure":
                return invoice_result
            
            # Get the created invoice data with DocEntry
            created_invoice_data = {
                "DocEntry": invoice_result["sap_doc_entry"],
                "DocNum": invoice_result["sap_doc_num"]
            }
            
            logger.info(f"Created invoice data: {created_invoice_data}")
            
            # Check if order is paid and create incoming payment
            sap_payment_number = None
            if financial_status == "PAID":
                logger.info(f"Order {order_name} is paid - creating incoming payment in SAP")
                
                # Prepare incoming payment data
                payment_data = self.prepare_incoming_payment_data(
                    shopify_order, 
                    created_invoice_data, 
                    sap_customer["CardCode"], 
                    store_key
                )
                
                # Create incoming payment in SAP
                payment_result = await self.create_incoming_payment_in_sap(payment_data)
                if payment_result["msg"] == "success":
                    sap_payment_number = payment_result["sap_payment_number"]
                    logger.info(f"Successfully created incoming payment: {sap_payment_number}")
                else:
                    logger.warning(f"Failed to create incoming payment for {order_name}: {payment_result.get('error')}")
                    # Don't fail the entire process if payment creation fails
            else:
                logger.info(f"Order {order_name} is not paid (status: {financial_status}) - skipping payment creation")
            
            # Update order metafield in Shopify
            metafield_update_result = await self.update_order_metafield(
                store_key,
                order_id,
                "synced"
            )
            
            if metafield_update_result["msg"] == "failure":
                logger.warning(f"Failed to update order metafield for {order_name}: {metafield_update_result.get('error')}")
                # Don't fail the entire process if metafield update fails
            
            logger.info(f"Successfully processed order {order_name}")
            
            return {
                "msg": "success",
                "order_name": order_name,
                "sap_invoice_number": invoice_result["sap_invoice_number"],
                "sap_payment_number": sap_payment_number,
                "customer_card_code": sap_customer["CardCode"],
                "financial_status": financial_status,
                "fulfillment_status": fulfillment_status,
                "payment_id": payment_info.get("payment_id", "Unknown"),
                "payment_gateway": payment_info.get("gateway", "Unknown"),
                "payment_amount": payment_info.get("amount", 0.0),
                "is_online_payment": payment_info.get("is_online_payment", False),
                "shipping_address": shipping_address,
                "billing_address": billing_address
            }
            
        except Exception as e:
            logger.error(f"Error processing order {order_name}: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def sync_orders(self) -> Dict[str, Any]:
        """
        Main orders sync process
        """
        logger.info("Starting orders sync...")
        
        try:
            # Get enabled stores
            enabled_stores = config_settings.get_enabled_stores()
            if not enabled_stores:
                logger.warning("No enabled stores found")
                return {"msg": "failure", "error": "No enabled stores found"}
            
            total_processed = 0
            total_success = 0
            total_errors = 0
            
            # Process orders for each enabled store
            for store_key, store_config in enabled_stores.items():
                try:
                    # Get orders from this store
                    orders_result = await self.get_orders_from_shopify(store_key)
                    if orders_result["msg"] == "failure":
                        logger.error(f"Failed to get orders from store {store_key}: {orders_result.get('error')}")
                        continue
                    
                    orders = orders_result["data"]
                    if not orders:
                        logger.info(f"No orders to process for store {store_key}")
                        continue
                    
                    logger.info(f"Processing {len(orders)} orders from store {store_key}")
                    
                    # Process each order
                    for shopify_order in orders:
                        try:
                            order_node = shopify_order["node"]
                            order_id = order_node["id"]
                            
                            logger.info(f"Processing order {order_node.get('name', 'Unknown')} (ID: {order_id})")
                            result = await self.process_order(store_key, shopify_order)
                            
                            if result["msg"] == "success":
                                total_success += 1
                                logger.info(f"✅ Processed order {result['order_name']} -> SAP Invoice: {result['sap_invoice_number']}")
                                
                                # Log additional payment and address information
                                if result.get("is_online_payment"):
                                    logger.info(f"   🔑 Payment ID: {result.get('payment_id', 'Unknown')}")
                                
                                logger.info(f"   💳 Gateway: {result.get('payment_gateway', 'Unknown')} | Amount: {result.get('payment_amount', 0.0)}")
                                
                                # Log address summary
                                shipping_addr = result.get("shipping_address", {})
                                if shipping_addr:
                                    ship_to_summary = f"{shipping_addr.get('firstName', '')} {shipping_addr.get('lastName', '')} - {shipping_addr.get('city', '')}"
                                    logger.info(f"   📍 Ship To: {ship_to_summary}")
                                
                                billing_addr = result.get("billing_address", {})
                                if billing_addr:
                                    bill_to_summary = f"{billing_addr.get('firstName', '')} {billing_addr.get('lastName', '')} - {billing_addr.get('city', '')}"
                                    logger.info(f"   📍 Bill To: {bill_to_summary}")
                                
                            else:
                                total_errors += 1
                                logger.error(f"❌ Failed to process order: {result.get('error')}")
                            
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
                sync_type="sales_orders",
                items_processed=total_processed,
                success_count=total_success,
                error_count=total_errors
            )
            
            logger.info(f"Orders sync completed. Processed: {total_processed}, Success: {total_success}, Errors: {total_errors}")
            
            return {
                "msg": "success",
                "processed": total_processed,
                "success": total_success,
                "errors": total_errors
            }
            
        except Exception as e:
            logger.error(f"Error in orders sync: {str(e)}")
            return {"msg": "failure", "error": str(e)}



    def _determine_payment_type(self, source_name: str, source_identifier: str, payment_info: Dict[str, Any]) -> str:

        """

        Determine payment type based on order channel and payment information

        """

        # Convert to lowercase for case-insensitive matching

        source_name_lower = source_name.lower()

        source_identifier_lower = source_identifier.lower()

        

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



    async def create_incoming_payment_in_sap(self, payment_data: Dict[str, Any]) -> Dict[str, Any]:

        """

        Create incoming payment in SAP

        """

        try:

            result = await sap_client._make_request(

                method='POST',

                endpoint='IncomingPayments',

                data=payment_data

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





    async def update_order_metafield(self, store_key: str, order_id: str, status: str) -> Dict[str, Any]:
        """

        Update order metafield to track sync status
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
                # Get current metafields
                metafields_url = f"https://{store_config.shop_url}/admin/api/2024-01/orders/{order_id_number}/metafields.json"
                metafields_response = await client.get(metafields_url, headers=headers)
                metafields_response.raise_for_status()
                metafields_data = metafields_response.json()
                metafields = metafields_data.get('metafields', [])
                
                # Check if metafield already exists
                existing_metafield = None
                for metafield in metafields:
                    if metafield.get('namespace') == 'custom' and metafield.get('key') == 'sap_sync':
                        existing_metafield = metafield
                        break
                
                if existing_metafield:
                    # Update existing metafield
                    update_url = f"https://{store_config.shop_url}/admin/api/2024-01/metafields/{existing_metafield['id']}.json"
                    update_data = {
                        "metafield": {
                            "value": status
                        }
                    }
                    
                    update_response = await client.put(update_url, headers=headers, json=update_data)
                    update_response.raise_for_status()
                    
                    logger.info(f"Updated metafield custom.sap_sync = {status} for order {order_id}")
                else:
                    # Create new metafield
                    create_data = {
                        "metafield": {
                            "namespace": "custom",
                            "key": "sap_sync",
                            "value": status,
                            "type": "single_line_text_field"
                        }
                    }
                    
                    create_response = await client.post(metafields_url, headers=headers, json=create_data)
                    create_response.raise_for_status()
                    
                    logger.info(f"Created metafield custom.sap_sync = {status} for order {order_id}")
                
            return {"msg": "success"}

            

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error setting metafield for order {order_id}: {e.response.status_code} - {e.response.text}")
            return {"msg": "failure", "error": f"HTTP error: {e.response.status_code}"}
        except Exception as e:

            logger.error(f"Error setting metafield for order {order_id}: {str(e)}")
            return {"msg": "failure", "error": str(e)}

    

    async def process_order(self, store_key: str, shopify_order: Dict[str, Any]) -> Dict[str, Any]:

        """

        Process a single order from Shopify to SAP

        """

        try:

            order_node = shopify_order["node"]

            order_id = order_node["id"]

            order_name = order_node["name"]

            

            # Check payment and fulfillment status

            financial_status = order_node.get("displayFinancialStatus", "PENDING")
            fulfillment_status = order_node.get("displayFulfillmentStatus", "UNFULFILLED")
            
            # Extract payment information
            payment_info = self._extract_payment_info(order_node)
            
            # Extract address information
            shipping_address = order_node.get("shippingAddress", {})
            billing_address = order_node.get("billingAddress", {})
            

            logger.info(f"Processing order: {order_name} | Payment: {financial_status} | Fulfillment: {fulfillment_status}")

            logger.info(f"Payment Gateway: {payment_info['gateway']} | Card Type: {payment_info['card_type']} | Amount: {payment_info['amount']}")
            
            if payment_info['is_online_payment']:
                logger.info(f"🔑 ONLINE PAYMENT ID: {payment_info['payment_id']}")
            
            # Log address information
            if shipping_address:
                ship_to = f"{shipping_address.get('firstName', '')} {shipping_address.get('lastName', '')} | {shipping_address.get('address1', '')} | {shipping_address.get('city', '')}, {shipping_address.get('province', '')} | {shipping_address.get('phone', 'No phone')}"
                logger.info(f"📍 SHIP TO: {ship_to}")
            
            if billing_address:
                bill_to = f"{billing_address.get('firstName', '')} {billing_address.get('lastName', '')} | {billing_address.get('address1', '')} | {billing_address.get('city', '')}, {billing_address.get('province', '')} | {billing_address.get('phone', 'No phone')}"
                logger.info(f"📍 BILL TO: {bill_to}")
            

            # For now, we'll process all orders regardless of status

            # Later you can add logic to handle different statuses differently

            if financial_status == "PENDING":

                logger.info(f"Order {order_name} is pending payment - will process anyway")

            

            if fulfillment_status == "UNFULFILLED":

                logger.info(f"Order {order_name} is unfulfilled - will process anyway")

            

            # Get or create customer in SAP

            customer = order_node.get("customer")

            if not customer:

                logger.warning(f"No customer found for order {order_name}")

                return {"msg": "failure", "error": "No customer found"}

            

            # Extract phone number from customer, then fall back to shipping/billing addresses
            phone = self.customer_manager._extract_phone_from_customer(customer)

            if not phone:
                shipping_phone = (order_node.get("shippingAddress") or {}).get("phone")
                billing_phone = (order_node.get("billingAddress") or {}).get("phone")
                phone = shipping_phone or billing_phone
            if not phone:

                logger.warning(f"No phone number found for customer in order {order_name}")

                return {"msg": "failure", "error": "No phone number found for customer"}

            

            # Check if customer exists in SAP by phone

            existing_customer = await self.customer_manager.find_customer_by_phone(phone)

            

            if existing_customer:

                logger.info(f"Found existing customer: {existing_customer.get('CardCode', 'Unknown')}")

                sap_customer = existing_customer

            else:

                # Create new customer in SAP

                logger.info("Creating new customer in SAP")

                sap_customer = await self.customer_manager.create_customer_in_sap(customer)

            if not sap_customer:

                    logger.error(f"Failed to create customer for order {order_name}")

                    return {"msg": "failure", "error": "Failed to create customer"}

            

            # Map order to SAP format

            sap_invoice_data = self.map_shopify_order_to_sap(shopify_order, sap_customer["CardCode"], store_key)
            if not sap_invoice_data:

                logger.error(f"Failed to map order {order_name} to SAP format")

                return {"msg": "failure", "error": "Failed to map order to SAP format"}

            

            # Create invoice in SAP

            invoice_result = await self.create_invoice_in_sap(sap_invoice_data)

            if invoice_result["msg"] == "failure":

                return invoice_result

            # Build created invoice data to include DocEntry for payment linkage
            created_invoice_data = {
                "DocEntry": invoice_result["sap_doc_entry"],
                "DocNum": invoice_result["sap_doc_num"]
            }

            # Check if order is paid and create incoming payment

            sap_payment_number = None

            if financial_status == "PAID":

                logger.info(f"Order {order_name} is paid - creating incoming payment in SAP")

                

                # Prepare incoming payment data

                payment_data = self.prepare_incoming_payment_data(

                    shopify_order, 

                    created_invoice_data, 

                    sap_customer["CardCode"], 

                    store_key

                )

                

                # Create incoming payment in SAP

                payment_result = await self.create_incoming_payment_in_sap(payment_data)

                if payment_result["msg"] == "success":

                    sap_payment_number = payment_result["sap_payment_number"]

                    logger.info(f"Successfully created incoming payment: {sap_payment_number}")

                else:

                    logger.warning(f"Failed to create incoming payment for {order_name}: {payment_result.get('error')}")

                    # Don't fail the entire process if payment creation fails

            else:

                logger.info(f"Order {order_name} is not paid (status: {financial_status}) - skipping payment creation")

            

            # Update order metafield in Shopify
            metafield_update_result = await self.update_order_metafield(
                store_key,

                order_id,

                "synced"
            )
            
            if metafield_update_result["msg"] == "failure":
                logger.warning(f"Failed to update order metafield for {order_name}: {metafield_update_result.get('error')}")
                # Don't fail the entire process if metafield update fails
            

            logger.info(f"Successfully processed order {order_name}")

            

            return {

                "msg": "success",

                "order_name": order_name,

                "sap_invoice_number": invoice_result["sap_invoice_number"],

                "sap_payment_number": sap_payment_number,

                "customer_card_code": sap_customer["CardCode"],

                "financial_status": financial_status,

                "fulfillment_status": fulfillment_status,
                "payment_id": payment_info.get("payment_id", "Unknown"),
                "payment_gateway": payment_info.get("gateway", "Unknown"),
                "payment_amount": payment_info.get("amount", 0.0),
                "is_online_payment": payment_info.get("is_online_payment", False),
                "shipping_address": shipping_address,
                "billing_address": billing_address
            }

            

        except Exception as e:

            logger.error(f"Error processing order {order_name}: {str(e)}")

            return {"msg": "failure", "error": str(e)}

    

    async def sync_orders(self) -> Dict[str, Any]:

        """

        Main orders sync process

        """

        logger.info("Starting orders sync...")

        

        try:

            # Get enabled stores

            enabled_stores = config_settings.get_enabled_stores()

            if not enabled_stores:

                logger.warning("No enabled stores found")

                return {"msg": "failure", "error": "No enabled stores found"}

            

            total_processed = 0

            total_success = 0

            total_errors = 0

            

            # Process orders for each enabled store

            for store_key, store_config in enabled_stores.items():

                try:

                    # Get orders from this store

                    orders_result = await self.get_orders_from_shopify(store_key)

                    if orders_result["msg"] == "failure":

                        logger.error(f"Failed to get orders from store {store_key}: {orders_result.get('error')}")

                        continue

                    

                    orders = orders_result["data"]

                    if not orders:

                        logger.info(f"No orders to process for store {store_key}")

                        continue

                    

                    logger.info(f"Processing {len(orders)} orders from store {store_key}")

                    

                    # Process each order

                    for shopify_order in orders:

                        try:

                            order_node = shopify_order["node"]
                            order_id = order_node["id"]
                            
                            logger.info(f"Processing order {order_node.get('name', 'Unknown')} (ID: {order_id})")
                            result = await self.process_order(store_key, shopify_order)

                            

                            if result["msg"] == "success":

                                total_success += 1

                                logger.info(f"✅ Processed order {result['order_name']} -> SAP Invoice: {result['sap_invoice_number']}")

                                
                                # Log additional payment and address information
                                if result.get("is_online_payment"):
                                    logger.info(f"   🔑 Payment ID: {result.get('payment_id', 'Unknown')}")
                                
                                logger.info(f"   💳 Gateway: {result.get('payment_gateway', 'Unknown')} | Amount: {result.get('payment_amount', 0.0)}")
                                
                                # Log address summary
                                shipping_addr = result.get("shipping_address", {})
                                if shipping_addr:
                                    ship_to_summary = f"{shipping_addr.get('firstName', '')} {shipping_addr.get('lastName', '')} - {shipping_addr.get('city', '')}"
                                    logger.info(f"   📍 Ship To: {ship_to_summary}")
                                
                                billing_addr = result.get("billing_address", {})
                                if billing_addr:
                                    bill_to_summary = f"{billing_addr.get('firstName', '')} {billing_addr.get('lastName', '')} - {billing_addr.get('city', '')}"
                                    logger.info(f"   📍 Bill To: {bill_to_summary}")
                                
                            else:

                                total_errors += 1

                                logger.error(f"❌ Failed to process order: {result.get('error')}")

                            

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

                sync_type="sales_orders",

                items_processed=total_processed,

                success_count=total_success,

                error_count=total_errors

            )

            

            logger.info(f"Orders sync completed. Processed: {total_processed}, Success: {total_success}, Errors: {total_errors}")

            

            return {

                "msg": "success",

                "processed": total_processed,

                "success": total_success,

                "errors": total_errors

            }

            

        except Exception as e:

            logger.error(f"Error in orders sync: {str(e)}")

            return {"msg": "failure", "error": str(e)} 
