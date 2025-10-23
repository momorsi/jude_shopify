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
from datetime import datetime, date
from order_location_mapper import OrderLocationMapper


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
            # Filter to exclude orders that already have sap_invoice_* tags
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

                        # --- Discounts applied ---
                        discountApplications(first: 10) {
                        edges {
                            node {
                            targetType        # ORDER or LINE_ITEM
                            allocationMethod  # ACROSS / EACH / ONE
                            value {
                                __typename
                                ... on PricingPercentageValue {
                                percentage
                                }
                                ... on MoneyV2 {
                                amount
                                currencyCode
                                }
                            }
                            ... on DiscountCodeApplication {
                                code
                            }
                            ... on AutomaticDiscountApplication {
                                title
                            }
                            }
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

                        # --- Line Items with Discount Allocations ---
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
                            discountAllocations {
                                allocatedAmount {
                                    amount
                                    currencyCode
                                }
                                discountApplication {
                                    __typename
                                    ... on AutomaticDiscountApplication {
                                        title
                                    }
                                    ... on DiscountCodeApplication {
                                        code
                                    }
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

                        # --- Transactions (Gift cards show up here as gateway = "gift_card") ---
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
                        receiptJson   # contains gift_card_id, last_characters etc if gift card used
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
            
            # Add retry logic for GraphQL queries to handle rate limiting
            max_retries = 3
            retry_delay = 2  # Start with 2 seconds
            
            # Filter to only include orders with "take" tag and exclude orders that already have sap_invoice_synced or sap_invoice_failed tags
            # Also filter to get orders starting from today
            from_date = config_settings.sales_orders_from_date
            query_filter = f"tag:salestest fulfillment_status:fulfilled -tag:sap_invoice_synced -tag:sap_invoice_failed created_at:>={from_date}"
            logger.info(f"Fetching orders with filter: {query_filter}")
            
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
            
            # Take only the last 5 most recent orders (already filtered by query)
            #orders = orders[:5]
            
            logger.info(f"Retrieved {len(orders)} unsynced orders (limited to 5 most recent) from Shopify store {store_key}")
            
            return {"msg": "success", "data": orders}
            
        except Exception as e:
            logger.error(f"Error getting orders from Shopify: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    

    

    
    def map_shopify_order_to_sap(self, shopify_order: Dict[str, Any], customer_card_code: str, store_key: str, created_gift_cards: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Map Shopify order data to SAP invoice format
        """
        try:
            # Extract order data
            
            order_node = shopify_order["node"]
            order_id = order_node["id"]
            # Extract just the numeric ID from the full GID (e.g., "6342714261570" from "gid://shopify/Order/6342714261570")
            order_id_number = order_id.split("/")[-1] if "/" in order_id else order_id
            order_name = order_node["name"]
            created_at = order_node["createdAt"]
            total_price = Decimal(order_node["totalPriceSet"]["shopMoney"]["amount"])
            currency = order_node["totalPriceSet"]["shopMoney"]["currencyCode"]
            
            # Get payment and fulfillment status
            financial_status = order_node.get("displayFinancialStatus", "PENDING")
            fulfillment_status = order_node.get("displayFulfillmentStatus", "UNFULFILLED")
            
            # Get location mapping for this order using retailLocation field
            location_analysis = self._analyze_order_location_from_retail_location(order_node, store_key)
            sap_codes = location_analysis.get('sap_codes', {})
            location_type = config_settings.get_location_type(location_analysis.get('location_mapping', {}))
            
            # Use location-based costing codes, fallback to defaults if not available
            default_codes = {
                'COGSCostingCode': 'ONL',
                'COGSCostingCode2': 'SAL', 
                'COGSCostingCode3': 'OnlineS',
                'CostingCode': 'ONL',
                'CostingCode2': 'SAL',
                'CostingCode3': 'OnlineS',
                'Warehouse': 'SW'
            }
            
            # Override with location-specific codes if available
            costing_codes = {key: sap_codes.get(key, default_codes[key]) for key in default_codes.keys()}
            
            logger.info(f"Using location-based costing codes for order {order_node.get('name', 'Unknown')}: {costing_codes}")
            
            # Map line items with discount information
            line_items = []
            for item_edge in order_node["lineItems"]["edges"]:
                item = item_edge["node"]
                sku = item.get("sku")
                quantity = item["quantity"]
                
                # Skip gift card line items (POS refunds) - these have sku: null and variant: null
                if (item.get("name") == "Gift Card" and 
                    sku is None and 
                    item.get("variant") is None):
                    logger.info(f"Skipping gift card line item for POS refund: {item.get('name')} - Amount: {item.get('originalUnitPriceSet', {}).get('shopMoney', {}).get('amount', 0)}")
                    continue
                
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
                # Check line item SKU first, then variant SKU
                if sku:
                    item_code = sku  # Use the actual SKU from Shopify line item
                elif item.get("variant") and item["variant"].get("sku"):
                    item_code = item["variant"]["sku"]  # Use variant SKU if line item SKU is empty
                else:
                    item_code = "ACC-0000001"  # Default item only if no SKU available
                
                # Get warehouse code based on order location (use location-based warehouse if available)
                warehouse_code = costing_codes.get('Warehouse', config_settings.get_warehouse_code_for_order(store_key, order_node))
                
                # Check if this is a gift card line item
                is_gift_card_item = False
                if created_gift_cards:
                    # Check if this line item matches any gift card by SKU and unit price
                    for gift_card_info in created_gift_cards:
                        if (gift_card_info.get("sku") == item_code and 
                            abs(gift_card_info.get("amount", 0) - float(original_price)) < 0.01):
                            is_gift_card_item = True
                            break
                
                # For gift card items with quantity > 1, create separate lines
                if is_gift_card_item and quantity > 1:
                    logger.info(f"Creating {quantity} separate lines for gift card item: {item_code}")
                    
                    # Create separate lines for each gift card
                    for i in range(quantity):
                        # Find the corresponding gift card for this line
                        matching_gift_card = None
                        for gift_card_info in created_gift_cards:
                            if (gift_card_info.get("sku") == item_code and 
                                abs(gift_card_info.get("amount", 0) - float(original_price)) < 0.01):
                                matching_gift_card = gift_card_info
                                # Remove from list to avoid duplicate matching
                                created_gift_cards.remove(gift_card_info)
                                break
                        
                        line_item = {
                            "ItemCode": item_code,
                            "Quantity": 1,  # Each line has quantity 1
                            "UnitPrice": float(original_price),  # Always use original price (compareAtPrice)
                            "WarehouseCode": warehouse_code,
                            "COGSCostingCode": costing_codes['COGSCostingCode'],
                            "COGSCostingCode2": costing_codes['COGSCostingCode2'],
                            "COGSCostingCode3": costing_codes['COGSCostingCode3'],
                            "CostingCode": costing_codes['CostingCode'],
                            "CostingCode2": costing_codes['CostingCode2'],
                            "CostingCode3": costing_codes['CostingCode3']
                        }
                        
                        # Add gift card ID to this line
                        if matching_gift_card:
                            line_item["U_GiftCard"] = matching_gift_card.get("gift_card_id")
                            logger.info(f"Added U_GiftCard field to line item: {matching_gift_card.get('gift_card_id')} for gift card {i+1}/{quantity}")
                        
                        # Calculate discount percentage based on compareAtPrice vs sale price
                        if original_price > 0 and sale_price > 0 and original_price != sale_price:
                            # Calculate discount percentage: (original - sale) / original * 100
                            discount_amount = original_price - sale_price
                            discount_percentage = (discount_amount / original_price) * 100
                            line_item["DiscountPercent"] = float(discount_percentage)
                            line_item["U_ItemDiscountAmount"] = float(discount_amount)
                            logger.info(f"🎯 Pricing for {item_code}: Original={original_price}, Sale={sale_price}, Discount={discount_percentage:.1f}%")
                        
                        # Also check for additional discount allocations (coupons, etc.)
                        discount_allocations = item.get("discountAllocations", [])
                        if discount_allocations:
                            total_item_discount = sum(
                                float(allocation.get("allocatedAmount", {}).get("amount", 0))
                                for allocation in discount_allocations
                            )
                            if total_item_discount > 0:
                                
                                # Recalculate total discount percentage
                                if original_price > 0:
                                    total_discount_percentage = (line_item["U_ItemDiscountAmount"] / float(original_price)) * 100
                                    line_item["DiscountPercent"] = total_discount_percentage
                                    logger.info(f"🎯 Additional discount for {item_code}: {total_item_discount}, Total Discount: {total_discount_percentage:.1f}%")
                        
                        line_items.append(line_item)
                else:
                    # Regular line item (non-gift card or gift card with quantity 1)
                    line_item = {
                        "ItemCode": item_code,
                        "Quantity": quantity,
                        "UnitPrice": float(original_price),  # Always use original price (compareAtPrice)
                        "WarehouseCode": warehouse_code,
                        "COGSCostingCode": costing_codes['COGSCostingCode'],
                        "COGSCostingCode2": costing_codes['COGSCostingCode2'],
                        "COGSCostingCode3": costing_codes['COGSCostingCode3'],
                        "CostingCode": costing_codes['CostingCode'],
                        "CostingCode2": costing_codes['CostingCode2'],
                        "CostingCode3": costing_codes['CostingCode3']                    
                    }
                    
                    # Calculate discount percentage based on compareAtPrice vs sale price
                    if original_price > 0 and sale_price > 0 and original_price != sale_price:
                        # Calculate discount percentage: (original - sale) / original * 100
                        discount_amount = original_price - sale_price
                        discount_percentage = (discount_amount / original_price) * 100
                        line_item["DiscountPercent"] = float(discount_percentage)
                        line_item["U_ItemDiscountAmount"] = float(discount_amount)
                        logger.info(f"🎯 Pricing for {item_code}: Original={original_price}, Sale={sale_price}, Discount={discount_percentage:.1f}%")
                    
                    # Also check for additional discount allocations (coupons, etc.)
                    discount_allocations = item.get("discountAllocations", [])
                    if discount_allocations:
                        total_item_discount = sum(
                            float(allocation.get("allocatedAmount", {}).get("amount", 0))
                            for allocation in discount_allocations
                        )
                        if total_item_discount > 0:
                            # Add additional discount amount to existing discount
                            if "U_ItemDiscountAmount" in line_item:
                                line_item["U_ItemDiscountAmount"] += total_item_discount
                            else:
                                line_item["U_ItemDiscountAmount"] = total_item_discount
                            
                            # Recalculate total discount percentage
                            if original_price > 0:
                                total_discount_percentage = (line_item["U_ItemDiscountAmount"] / float(original_price)) * 100
                                line_item["DiscountPercent"] = total_discount_percentage
                                logger.info(f"🎯 Additional discount for {item_code}: {total_item_discount}, Total Discount: {total_discount_percentage:.1f}%")
                    
                    # Check if this is a gift card line item and add U_GiftCard field
                    if is_gift_card_item and created_gift_cards:
                        # Find matching gift card for this line item
                        for gift_card_info in created_gift_cards:
                            if (gift_card_info.get("sku") == item_code and 
                                abs(gift_card_info.get("amount", 0) - float(original_price)) < 0.01):
                                # This is a gift card line item, add the gift card ID
                                line_item["U_GiftCard"] = gift_card_info.get("gift_card_id")
                                logger.info(f"Added U_GiftCard field to line item: {gift_card_info.get('gift_card_id')} for amount: {float(original_price)}")
                                # Remove from list to avoid duplicate matching
                                created_gift_cards.remove(gift_card_info)
                                break
                    
                    line_items.append(line_item)
            
            # Add gift card expense entries if any gift cards were used
            payment_info = self._extract_payment_info(order_node)
            gift_card_expenses = []
            if payment_info.get("gift_cards"):
                logger.info(f"🎁 Processing {len(payment_info['gift_cards'])} gift card redemption(s)")
                for gift_card in payment_info["gift_cards"]:
                    gift_card_expense = {
                        "ExpenseCode": 2,  # Gift card expense code
                        "LineTotal": -float(gift_card["amount"]),  # Negative amount
                        "Remarks": f"Gift Card: {gift_card['last_characters']}",
                        "U_GiftCard": gift_card["gift_card_id"],  # Add gift card ID to expense entry
                        "DistributionRule": costing_codes.get('CostingCode', 'ONL') if costing_codes else "ONL",                                               
                        "DistributionRule2": costing_codes.get('CostingCode2', 'ONL') if costing_codes else "ONL",                                               
                        "DistributionRule3": costing_codes.get('CostingCode3', 'ONL') if costing_codes else "ONL"   
                    }
                    gift_card_expenses.append(gift_card_expense)
                    logger.info(f"🎁 Created gift card expense: {gift_card['last_characters']} - Amount: -{gift_card['amount']}")
            else:
                logger.info("🎁 No gift card redemptions found in this order")
            
            # Parse date
            doc_date = created_at.split("T")[0] if "T" in created_at else created_at
            
            # Calculate freight expenses
            freight_expenses = self._calculate_freight_expenses(order_node, store_key, sap_codes, costing_codes)
            
            # Generate address strings
            shipping_address = order_node.get("shippingAddress", {})
            billing_address = order_node.get("billingAddress", {})
            
            delivery_address = self._generate_address_string(shipping_address)
            billing_address_str = self._generate_address_string(billing_address)
            
            # Determine U_OrderType based on order characteristics
            order_type = self._determine_order_type(order_node)
            
            # Create invoice data
            invoice_data = {
                "DocDate": doc_date,
                "CardCode": customer_card_code,
                "NumAtCard": order_name.replace("#", ""),
                "Series": config_settings.get_series_for_location(store_key, location_analysis.get('location_mapping', {}), 'invoices'),
                "Comments": f"Shopify Order: {order_name} | Payment: {financial_status} | Fulfillment: {fulfillment_status}",
                #"U_Shopify_Order_ID": order_name,
                #"U_Shopify_Financial_Status": financial_status,
                #"U_Shopify_Fulfillment_Status": fulfillment_status,
                "SalesPersonCode": location_analysis.get('location_mapping', {}).get('sales_employee', 28),
                "DocumentLines": line_items,
                "U_Pay_type": 1 if financial_status in ["PAID", "PARTIALLY_REFUNDED"] else 2 if store_key == "local" else 3,
                "U_Shopify_Order_ID": order_id_number,
                "U_DeliveryAddress": delivery_address,
                "U_BillingAddress": billing_address_str,
                "U_OrderType": order_type,
                "ImportFileNum": order_name.replace("#", ""),
                "DocCurrency": config_settings.get_currency_for_store(store_key)
            }
            
            # Add POS receipt number if this is a POS order
            if location_analysis.get('is_pos_order') and location_analysis.get('extracted_receipt_number'):
                invoice_data["U_POS_Receipt_Number"] = location_analysis['extracted_receipt_number']
                logger.info(f"Added POS receipt number to invoice: {location_analysis['extracted_receipt_number']}")
            
            # Handle order-level discounts
            discount_applications = order_node.get("discountApplications", {}).get("edges", [])
            discount_reasons = []
            
            for discount_edge in discount_applications:
                discount = discount_edge["node"]
                target_type = discount.get("targetType", "UNKNOWN")
                
                # Extract discount reason/code for both order and line item discounts
                discount_code = discount.get("code", "")
                discount_title = discount.get("title", "")
                
                # Build discount reason string
                if discount_code and discount_title:
                    discount_reason = f"{discount_code} - {discount_title}"
                elif discount_code:
                    discount_reason = discount_code
                elif discount_title:
                    discount_reason = discount_title
                else:
                    discount_reason = "Unknown Discount"
                
                discount_reasons.append(discount_reason)
                
                if target_type == "ORDER":
                    # Order-level discount
                    value = discount.get("value", {})
                    discount_amount = 0.0
                    discount_percentage = 0.0
                    
                    if value.get("__typename") == "PricingPercentageValue":
                        # Percentage discount
                        discount_percentage = float(value.get("percentage", 0))
                        # Calculate discount amount from order subtotal
                        subtotal = float(order_node.get("subtotalPriceSet", {}).get("shopMoney", {}).get("amount", 0))
                        discount_amount = (discount_percentage / 100) * subtotal
                    elif value.get("__typename") == "MoneyV2":
                        # Fixed amount discount
                        discount_amount = float(value.get("amount", 0))
                        # Calculate discount percentage from order subtotal
                        subtotal = float(order_node.get("subtotalPriceSet", {}).get("shopMoney", {}).get("amount", 0))
                        if subtotal > 0:
                            discount_percentage = (discount_amount / subtotal) * 100
                    
                    if discount_percentage > 0:
                        invoice_data["DiscountPercent"] = discount_percentage
                        invoice_data["U_OrderDiscountAmount"] = discount_amount
                        invoice_data["U_OrderDiscountCode"] = discount.get("code", "")
                        logger.info(f"Applied order-level discount: {discount_percentage}% ({discount_amount} EGP) - Code: {discount.get('code', 'N/A')}")
            
            # Add discount reason to invoice header if any discounts were found
            if discount_reasons:
                invoice_data["U_CustomerAddress"] = " | ".join(discount_reasons)
                logger.info(f"Added discount reason to invoice: {invoice_data['U_CustomerAddress']}")
            
            # Add freight expenses if any
            if freight_expenses:
                invoice_data["DocumentAdditionalExpenses"] = freight_expenses
            
            # Add gift card expenses if any
            if gift_card_expenses:
                if "DocumentAdditionalExpenses" not in invoice_data:
                    invoice_data["DocumentAdditionalExpenses"] = []
                invoice_data["DocumentAdditionalExpenses"].extend(gift_card_expenses)
            
            return invoice_data
            
        except Exception as e:
            logger.error(f"Error mapping order to SAP format: {str(e)}")
            raise

    def _extract_courier_info(self, order_node: Dict[str, Any]) -> str:
        """
        Extract courier information for U_OrderType from metafields
        """
        courier_metafield = None
        for metafield_edge in order_node.get("metafields", {}).get("edges", []):
            metafield = metafield_edge["node"]
            if metafield["namespace"] == "custom" and metafield["key"] == "courier":
                courier_metafield = metafield["value"]
                break
        
        # Extract first character from courier value for U_OrderType
        order_type = ""
        if courier_metafield and isinstance(courier_metafield, str) and courier_metafield.strip():
            courier_value = courier_metafield.strip()
            
            # Handle JSON array format like ["4 - Tuyingo"]
            if courier_value.startswith("[") and courier_value.endswith("]"):
                try:
                    import json
                    courier_array = json.loads(courier_value)
                    if courier_array and len(courier_array) > 0:
                        # Extract first character from first element
                        first_element = str(courier_array[0])
                        if first_element and first_element.strip():
                            order_type = first_element.strip()[0]
                except (json.JSONDecodeError, IndexError):
                    # Fallback to original logic if JSON parsing fails
                    order_type = courier_value[0]
            else:
                # Handle simple string format
                order_type = courier_value[0]
        
        return order_type

    def _determine_order_type(self, order_node: Dict[str, Any]) -> str:
        """
        Determine U_OrderType based on order characteristics:
        - "1" for gift card purchases or pickup orders (no shipping)
        - Courier metafield first character for regular orders
        """
        # Check if this is a gift card purchase order
        line_items = order_node.get("lineItems", {}).get("edges", [])
        for item_edge in line_items:
            item = item_edge["node"]
            # Check SKU from line item first, then from variant
            sku = (item.get('sku') or '').lower()
            variant = item.get('variant') or {}
            variant_sku = (variant.get('sku') or '').lower()
            name = (item.get('name') or '').lower()
            
            # Check for gift card patterns in line item SKU, variant SKU, or name
            if ('gift' in sku or 'gift' in name or 'card' in sku or 'card' in name or
                'gift' in variant_sku or 'card' in variant_sku):
                return "1"
        
        # Check if this is a pickup order (no shipping address)
        shipping_address = order_node.get("shippingAddress")
        if not shipping_address or not shipping_address.get("address1"):
            return "1"
        
        # For regular orders, use courier metafield
        return self._extract_courier_info(order_node)

    def _detect_gift_card_purchases(self, order_node: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Detect gift card purchases in the order and return gift card details
        """
        gift_cards = []
        line_items = order_node.get("lineItems", {}).get("edges", [])
        
        for item_edge in line_items:
            item = item_edge["node"]
            # Check SKU from line item first, then from variant
            sku = (item.get('sku') or '').lower()
            variant = item.get('variant') or {}
            variant_sku = (variant.get('sku') or '').lower()
            name = (item.get('name') or '').lower()
            
            # Log all line items for debugging
            logger.info(f"Checking line item for gift card: SKU='{sku}', VariantSKU='{variant_sku}', Name='{name}'")
            
            # Check for gift card patterns in line item SKU, variant SKU, or name
            # Also check for common gift card terms and Shopify's gift card product type
            is_gift_card = (
                'gift' in sku or 'gift' in name or 'card' in sku or 'card' in name or
                'gift' in variant_sku or 'card' in variant_sku or
                'voucher' in sku or 'voucher' in name or 'voucher' in variant_sku or
                'credit' in sku or 'credit' in name or 'credit' in variant_sku or
                'prepaid' in sku or 'prepaid' in name or 'prepaid' in variant_sku or
                # Check if this is Shopify's built-in gift card product type
                item.get('variant', {}).get('product', {}).get('productType', '').lower() == 'gift card'
            )
            
            if is_gift_card:
                # Calculate line total
                quantity = item["quantity"]
                if item.get("discountedUnitPriceSet") and item["discountedUnitPriceSet"].get("shopMoney"):
                    price = Decimal(item["discountedUnitPriceSet"]["shopMoney"]["amount"])
                elif item.get("variant") and item["variant"].get("price"):
                    price = Decimal(item["variant"]["price"])
                else:
                    price = Decimal("0.00")
                
                line_total = float(price * quantity)
                
                # Use variant SKU if line item SKU is empty
                variant = item.get("variant") or {}
                final_sku = item.get("sku") or variant.get("sku", "")
                
                gift_card_info = {
                    "sku": final_sku,
                    "name": item.get("name", ""),
                    "quantity": quantity,
                    "unit_price": float(price),
                    "line_total": line_total,
                    "variant_id": variant.get("id", ""),
                    "product_id": variant.get("product", {}).get("id", "")
                }
                gift_cards.append(gift_card_info)
        
        return gift_cards

    async def _get_gift_cards_for_order(self, order_id: str, order_created_at: str) -> List[Dict[str, Any]]:
        """
        Query Shopify Gift Cards API to get gift cards created for this order
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
                    result = await multi_store_shopify_client.execute_query("local", query, {"query": query_string})
                    
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
            
            # Check if result has the expected data structure
            if not result.get("data") or not result["data"].get("giftCards"):
                logger.warning(f"No gift cards data found in result: {result}")
                return []
            
            gift_cards = []
            gift_cards_edges = result["data"]["giftCards"].get("edges", [])
            for edge in gift_cards_edges:
                try:
                    gift_card = edge.get("node", {})
                    if not gift_card:
                        logger.warning(f"Empty gift card node found: {edge}")
                        continue
                    
                    # Check if this gift card belongs to our order
                    order_info = gift_card.get("order", {})
                    if order_info.get("id") == f"gid://shopify/Order/{order_id}":
                        # Safely extract gift card data
                        initial_value = gift_card.get("initialValue", {})
                        if not initial_value:
                            logger.warning(f"No initialValue found for gift card: {gift_card}")
                            continue
                            
                        gift_cards.append({
                            "id": gift_card.get("id", ""),
                            "order_id": order_id,
                            "initial_value": float(initial_value.get("amount", 0)),
                            "currency": initial_value.get("currencyCode", "EGP"),
                            "created_at": gift_card.get("createdAt", ""),
                            "customer_email": gift_card.get("customer", {}).get("email", "")
                        })
                except Exception as e:
                    logger.error(f"Error processing gift card edge: {str(e)} - Edge: {edge}")
                    continue
            
            logger.info(f"Found {len(gift_cards)} gift cards for order {order_id}")
            return gift_cards
            
        except Exception as e:
            logger.error(f"Error querying gift cards: {str(e)}")
            return []

    async def _create_gift_cards_in_sap(self, gift_cards: List[Dict[str, Any]], order_date: str, customer_card_code: str, order_name: str, order_id: str, order_created_at: str, shopify_gift_cards: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Prepare gift card data for invoice lines without creating SAP GiftCards entity entries
        For multiple gift cards of same amount, create separate entries for each
        """
        created_gift_cards = []
        
        # If shopify_gift_cards not provided, query them
        if shopify_gift_cards is None:
            shopify_gift_cards = await self._get_gift_cards_for_order(order_id, order_created_at)
        
        if not shopify_gift_cards:
            logger.warning(f"No gift cards found in Shopify for order {order_id} - will create with generated IDs")
            # Continue processing even if no Shopify gift cards found
            # This handles cases where gift cards might not be properly linked in Shopify
        
        for gift_card in gift_cards:
            try:
                quantity = gift_card["quantity"]
                unit_price = gift_card["unit_price"]
                
                # For each gift card, create separate entries based on quantity
                for i in range(quantity):
                    # Find matching Shopify gift card by unit price (not line total)
                    matching_shopify_gift_card = None
                    
                    # Debug: Log available gift cards and what we're looking for
                    logger.info(f"Looking for gift card with unit price: {unit_price}")
                    logger.info(f"Available Shopify gift cards: {[{'id': gc['id'], 'amount': gc['initial_value']} for gc in shopify_gift_cards]}")
                    
                    for shopify_gc in shopify_gift_cards:
                        logger.info(f"Checking gift card {shopify_gc['id']} with amount {shopify_gc['initial_value']} against unit price {unit_price}")
                        if abs(shopify_gc["initial_value"] - unit_price) < 0.01:
                            matching_shopify_gift_card = shopify_gc
                            logger.info(f"✅ Found matching gift card: {shopify_gc['id']}")
                            break
                    
                    if not matching_shopify_gift_card:
                        logger.warning(f"No matching gift card found in Shopify for unit price {unit_price} - creating with generated ID")
                        # Generate a unique ID for this gift card
                        numeric_id = f"GC{order_id}_{unit_price}_{len(created_gift_cards)}"
                    else:
                        # Use the actual Shopify gift card ID
                        shopify_gift_card_id = matching_shopify_gift_card["id"]
                        numeric_id = shopify_gift_card_id.split("/")[-1] if "/" in shopify_gift_card_id else shopify_gift_card_id
                        # Remove the matched gift card from the list to avoid duplicate matching
                        shopify_gift_cards.remove(matching_shopify_gift_card)
                    
                    # Skip SAP GiftCards entity creation - just prepare data for invoice lines
                    logger.info(f"Preparing gift card data for invoice line: {numeric_id} - Amount: {unit_price} - SKU: {gift_card['sku']}")
                    created_gift_cards.append({
                        "gift_card_id": numeric_id,
                        "amount": unit_price,  # Use unit price, not line total
                        "sku": gift_card["sku"],
                        "sap_result": {"msg": "success", "skipped_entity_creation": True}
                    })
                        
            except Exception as e:
                logger.error(f"Error preparing gift card data: {str(e)}")
        
        return created_gift_cards

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

    async def _check_gift_card_exists_in_sap(self, gift_card_id: str) -> bool:
        """
        Check if a gift card already exists in SAP GiftCards entity
        """
        try:
            # Query SAP for gift card with specific ID
            endpoint = f"GiftCards('{gift_card_id}')"
            
            result = await sap_client._make_request(
                method='GET',
                endpoint=endpoint
            )
            
            if result["msg"] == "success":
                # Gift card exists
                logger.info(f"Gift card {gift_card_id} exists in SAP")
                return True
            else:
                # Gift card doesn't exist
                logger.info(f"Gift card {gift_card_id} does not exist in SAP")
                return False
                
        except Exception as e:
            logger.error(f"Error checking gift card existence in SAP: {str(e)}")
            return False
    

    
    def _generate_address_string(self, address: Dict[str, Any]) -> str:
        """
        Generate address string in the format: address/street + zipcode (if exists) + city + province + country
        """
        if not address:
            return ""
        
        address_parts = []
        
        # Add address/street
        address1 = address.get("address1", "") or ""
        address2 = address.get("address2", "") or ""
        
        if address1.strip():
            address_parts.append(address1.strip())
        if address2.strip():
            address_parts.append(address2.strip())
        
        # Add zipcode if exists
        zip_code = address.get("zip", "") or ""
        if zip_code.strip():
            address_parts.append(zip_code.strip())
        
        # Add city
        city = address.get("city", "") or ""
        if city.strip():
            address_parts.append(city.strip())
        
        # Add province/state
        province = address.get("province", "") or ""
        if province.strip():
            address_parts.append(province.strip())
        
        # Add country
        country = address.get("country", "") or ""
        if country.strip():
            address_parts.append(country.strip())
        
        # Join with commas and newlines for better readability
        if len(address_parts) > 3:
            # For longer addresses, use newlines after street and city
            if len(address_parts) >= 4:
                # Format: street, zip, city\nprovince, country
                if len(address_parts) >= 5:
                    return f"{', '.join(address_parts[:3])}\n{', '.join(address_parts[3:])}"
                else:
                    return f"{', '.join(address_parts[:3])}\n{address_parts[3]}"
            else:
                return ", ".join(address_parts)
        else:
            return ", ".join(address_parts)

    def _calculate_freight_expenses(self, order_node: Dict[str, Any], store_key: str, sap_codes: Dict[str, str] = None, costing_codes: Dict[str, str] = None) -> List[Dict[str, Any]]:
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
                        config["revenue"]["DistributionRule"] = costing_codes.get('CostingCode', 'ONL') if costing_codes else "ONL"                                             
                        config["revenue"]["DistributionRule2"] = costing_codes.get('CostingCode2', 'ONL') if costing_codes else "ONL"                                             
                        config["revenue"]["DistributionRule3"] = costing_codes.get('CostingCode3', 'ONL') if costing_codes else "ONL"                                                                                          
                        expenses.append(config["revenue"])
                    
                    # Add cost expense
                    if "cost" in config:
                        config["cost"]["DistributionRule"] = costing_codes.get('CostingCode', 'ONL') if costing_codes else "ONL"                                             
                        config["cost"]["DistributionRule2"] = costing_codes.get('CostingCode2', 'ONL') if costing_codes else "ONL"                                             
                        config["cost"]["DistributionRule3"] = costing_codes.get('CostingCode3', 'ONL') if costing_codes else "ONL"                                             
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
                    
                    # Apply location-specific costing codes to DHL expense
                    if sap_codes:
                        dhl_expense["DistributionRule"] = costing_codes.get('CostingCode', 'ONL') if costing_codes else "ONL"                                             
                        dhl_expense["DistributionRule2"] = costing_codes.get('CostingCode2', 'ONL') if costing_codes else "ONL"                                             
                        dhl_expense["DistributionRule3"] = costing_codes.get('CostingCode3', 'ONL') if costing_codes else "ONL"                                             
                    
                    expenses.append(dhl_expense)
                    
                    logger.info(f"Applied DHL freight expense for international order: {dhl_expense}")
                else:
                    logger.warning("No DHL configuration found for international store")
            
            return expenses
            
        except Exception as e:
            logger.error(f"Error calculating freight expenses: {str(e)}")
            return []
    
    async def create_invoice_in_sap(self, invoice_data: Dict[str, Any], order_id: str = "") -> Dict[str, Any]:
        """
        Create invoice in SAP
        """
        try:
            result = await sap_client._make_request(
                method='POST',
                endpoint='Invoices',
                data=invoice_data,
                order_id=order_id
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
                "sap_doc_num": created_invoice.get('DocNum', ''),
                "sap_trans_num": created_invoice.get('TransNum', ''),
                "sap_doc_total": created_invoice.get('DocTotal', 0.0),
                "sap_doc_date": created_invoice.get('DocDate', datetime.now().strftime("%Y-%m-%d"))
            }
            
        except Exception as e:
            logger.error(f"Error creating invoice in SAP: {str(e)}")
            return {"msg": "failure", "error": str(e)}

    def prepare_incoming_payment_data(self, shopify_order: Dict[str, Any], sap_invoice_data: Dict[str, Any], 
                                    customer_card_code: str, store_key: str, location_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare incoming payment data for SAP based on Shopify order payment information
        Handles POS-specific payment logic with multiple transaction types
        """
        try:
            order_node = shopify_order["node"]
            order_id = order_node["id"]
            # Extract just the numeric ID from the full GID (e.g., "6342714261570" from "gid://shopify/Order/6342714261570")
            order_id_number = order_id.split("/")[-1] if "/" in order_id else order_id
            order_name = order_node["name"]
            total_amount = float(order_node["totalPriceSet"]["shopMoney"]["amount"])
            
            # Get payment information from transactions
            payment_info = self._extract_payment_info(order_node)
            
            # Get order channel information
            source_name = (order_node.get("sourceName") or "").lower()
            source_identifier = (order_node.get("sourceIdentifier") or "").lower()
            
            # Get location type and determine payment type
            location_type = config_settings.get_location_type(location_analysis.get('location_mapping', {}))
            payment_type = self._determine_payment_type(source_name, source_identifier, payment_info, location_type, location_analysis.get('location_mapping', {}))
            
            # Get invoice document entry from SAP invoice data
            invoice_doc_entry = sap_invoice_data.get("DocEntry", "")
            if not invoice_doc_entry:
                logger.error("No DocEntry found in SAP invoice data")
                raise ValueError("No DocEntry found in SAP invoice data")
            
            # Initialize payment data with the correct structure
            # Use the same DocDate as the invoice
            invoice_doc_date = sap_invoice_data.get("DocDate", datetime.now().strftime("%Y-%m-%d"))
            payment_data = {
                "DocDate": invoice_doc_date,
                "CardCode": customer_card_code,
                "DocType": "rCustomer",
                "Series": config_settings.get_series_for_location(store_key, location_analysis.get('location_mapping', {}), 'incoming_payments'),
                "TransferSum": 0.0,
                "TransferAccount": "",
                "U_Shopify_Order_ID": order_id_number
            }
            
            # Check if this is a POS order (store location)
            if location_type == "store":
                logger.info(f"🏪 POS ORDER DETECTED - Processing multiple payment types")
                return self._prepare_pos_payment_data(
                    payment_data, payment_info, location_analysis, store_key, invoice_doc_entry, total_amount
                )
            else:
                # Handle online orders with existing logic
                return self._prepare_online_payment_data(
                    payment_data, payment_info, location_analysis, store_key, invoice_doc_entry, payment_type, order_node, location_type
                )
            
        except Exception as e:
            logger.error(f"Error preparing incoming payment data: {str(e)}")
            raise

    def _prepare_pos_payment_data(self, payment_data: Dict[str, Any], payment_info: Dict[str, Any], 
                                 location_analysis: Dict[str, Any], store_key: str, 
                                 invoice_doc_entry: str, total_amount: float) -> Dict[str, Any]:
        """
        Prepare payment data specifically for POS orders with multiple transaction types
        """
        try:
            from datetime import datetime, timedelta
            
            # Initialize variables
            calc_amount = 0.0
            cred_array = []
            
            # Get location mapping for credit accounts
            location_mapping = location_analysis.get('location_mapping', {})
            
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
                    #cred_obj['CreditCard'] = 1
                    
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

            # Add credit cards array if we have any
            if cred_array:
                payment_data["PaymentCreditCards"] = cred_array
            
            # Create invoice object for payment
            inv_obj = {
                "DocEntry": invoice_doc_entry,
                "SumApplied": calc_amount,
                "InvoiceType": "it_Invoice"
            }
            
            # Add invoice to payment data
            payment_data["PaymentInvoices"] = [inv_obj]
            
            logger.info(f"🏪 POS PAYMENT SUMMARY: Total Calculated Amount: {calc_amount} EGP")
            
            return payment_data
            
        except Exception as e:
            logger.error(f"Error preparing POS payment data: {str(e)}")
            raise

    def _prepare_online_payment_data(self, payment_data: Dict[str, Any], payment_info: Dict[str, Any], 
                                   location_analysis: Dict[str, Any], store_key: str, 
                                   invoice_doc_entry: str, payment_type: str, 
                                   order_node: Dict[str, Any], location_type: str) -> Dict[str, Any]:
        """
        Prepare payment data for online orders using existing logic
        """
        try:
            # Calculate payment amount excluding store credit
            store_credit_amount = payment_info.get("store_credit", {}).get("amount", 0.0)
            total_payment_amount = payment_info.get("total_payment_amount", 0.0)
            
            # Use total_payment_amount if available (multiple gateways), otherwise fall back to calculation
            if total_payment_amount > 0:
                payment_amount = total_payment_amount
            else:
                total_amount = float(order_node["totalPriceSet"]["shopMoney"]["amount"])
                payment_amount = total_amount - store_credit_amount
            
            logger.info(f"💰 ONLINE PAYMENT CALCULATION: Payment Amount: {payment_amount} EGP | Store Credit: {store_credit_amount} EGP")
            
            # Set payment method based on type and location
            if payment_type == "PaidOnline":
                # Online payments - use location-based bank transfer account
                payment_data["TransferSum"] = payment_amount
                
                # Get the actual gateway from payment info
                gateway = payment_info.get('gateway', 'Paymob')
                
                # Get bank transfer account using new location-based method
                transfer_account = config_settings.get_bank_transfer_for_location(
                    store_key, 
                    location_analysis.get('location_mapping', {}), 
                    gateway
                )
                
                payment_data["TransferAccount"] = transfer_account
                logger.info(f"Online payment - using {gateway} account: {transfer_account}")
                
            elif payment_type == "COD":
                # Cash on delivery - handle courier-specific accounts for online locations
                payment_data["TransferSum"] = payment_amount
                
                # Extract courier name from metafields for COD payments
                courier_name = ""
                if location_type == "online":
                    courier_name = self._extract_courier_from_metafields(order_node)
                
                # Get bank transfer account using new location-based method with courier
                transfer_account = config_settings.get_bank_transfer_for_location(
                    store_key, 
                    location_analysis.get('location_mapping', {}), 
                    "Cash on Delivery (COD)",
                    courier_name
                )
                
                payment_data["TransferAccount"] = transfer_account
                logger.info(f"COD payment - using COD account: {transfer_account} (courier: {courier_name})")
                
            else:
                # Default case - treat as online payment
                payment_data["TransferSum"] = payment_amount
                gateway = payment_info.get('gateway', 'Paymob')
                
                transfer_account = config_settings.get_bank_transfer_for_location(
                    store_key, 
                    location_analysis.get('location_mapping', {}), 
                    gateway
                )
                
                payment_data["TransferAccount"] = transfer_account
                logger.info(f"Default payment - using {gateway} account: {transfer_account}")
            
            # Create invoice object for payment
            inv_obj = {
                "DocEntry": invoice_doc_entry,
                "SumApplied": payment_amount,
                "InvoiceType": "it_Invoice"
            }
            
            # Add invoice to payment data
            payment_data["PaymentInvoices"] = [inv_obj]
            
            return payment_data
            
        except Exception as e:
            logger.error(f"Error preparing online payment data: {str(e)}")
            raise

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

    def _extract_discount_info(self, order_node: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract discount information from Shopify order including order-level and item-level discounts
        """
        discount_info = {
            "order_level_discounts": [],
            "item_level_discounts": [],
            "total_order_discount": 0.0,
            "total_item_discount": 0.0
        }
        
        try:
            # Extract order-level discounts
            discount_applications = order_node.get("discountApplications", {}).get("edges", [])
            
            for discount_edge in discount_applications:
                discount = discount_edge["node"]
                target_type = discount.get("targetType", "UNKNOWN")
                
                if target_type == "ORDER":
                    # Order-level discount
                    discount_data = {
                        "type": "ORDER_LEVEL",
                        "allocation_method": discount.get("allocationMethod", "UNKNOWN"),
                        "title": discount.get("title", "Unknown Discount"),
                        "code": discount.get("code", ""),
                        "value_type": "UNKNOWN",
                        "value": 0.0,
                        "currency": "Unknown"
                    }
                    
                    # Extract discount value
                    value = discount.get("value", {})
                    if value.get("__typename") == "PricingPercentageValue":
                        discount_data["value_type"] = "PERCENTAGE"
                        discount_data["value"] = float(value.get("percentage", 0))
                    elif value.get("__typename") == "MoneyV2":
                        discount_data["value_type"] = "FIXED_AMOUNT"
                        discount_data["value"] = float(value.get("amount", 0))
                        discount_data["currency"] = value.get("currencyCode", "Unknown")
                    
                    discount_info["order_level_discounts"].append(discount_data)
                    
                elif target_type == "LINE_ITEM":
                    # Item-level discount
                    discount_data = {
                        "type": "ITEM_LEVEL",
                        "title": discount.get("title", "Unknown Discount"),
                        "code": discount.get("code", ""),
                        "value_type": "UNKNOWN",
                        "value": 0.0
                    }
                    
                    # Extract discount value
                    value = discount.get("value", {})
                    if value.get("__typename") == "PricingPercentageValue":
                        discount_data["value_type"] = "PERCENTAGE"
                        discount_data["value"] = float(value.get("percentage", 0))
                    elif value.get("__typename") == "MoneyV2":
                        discount_data["value_type"] = "FIXED_AMOUNT"
                        discount_data["value"] = float(value.get("amount", 0))
                    
                    discount_info["item_level_discounts"].append(discount_data)
            
            # Extract item-level discount allocations
            line_items = order_node.get("lineItems", {}).get("edges", [])
            
            for item_edge in line_items:
                item = item_edge["node"]
                item_name = item.get("name", "Unknown Item")
                discount_allocations = item.get("discountAllocations", [])
                
                for allocation in discount_allocations:
                    allocated_amount = allocation.get("allocatedAmount", {})
                    discount_application = allocation.get("discountApplication", {})
                    
                    # Get original price for percentage calculation
                    original_price = 0.0
                    if item.get("originalUnitPriceSet") and item["originalUnitPriceSet"].get("shopMoney"):
                        original_price = float(item["originalUnitPriceSet"]["shopMoney"]["amount"])
                    elif item.get("variant") and item["variant"].get("price"):
                        original_price = float(item["variant"]["price"])
                    
                    allocated_amount_value = float(allocated_amount.get("amount", 0))
                    discount_percentage = 0.0
                    if original_price > 0:
                        discount_percentage = (allocated_amount_value / original_price) * 100
                    
                    item_discount_data = {
                        "item_name": item_name,
                        "item_sku": item.get("sku", "Unknown"),
                        "allocated_amount": allocated_amount_value,
                        "currency": allocated_amount.get("currencyCode", "Unknown"),
                        "discount_percentage": discount_percentage,
                        "discount_title": discount_application.get("title", "Unknown Discount"),
                        "discount_code": discount_application.get("code", "")
                    }
                    
                    discount_info["item_level_discounts"].append(item_discount_data)
                    discount_info["total_item_discount"] += item_discount_data["allocated_amount"]
            
            # Calculate total order discount
            for discount in discount_info["order_level_discounts"]:
                if discount["value_type"] == "FIXED_AMOUNT":
                    discount_info["total_order_discount"] += discount["value"]
                elif discount["value_type"] == "PERCENTAGE":
                    # Calculate discount amount from order subtotal
                    subtotal = float(order_node.get("subtotalPriceSet", {}).get("shopMoney", {}).get("amount", 0))
                    discount_amount = (discount["value"] / 100) * subtotal
                    discount_info["total_order_discount"] += discount_amount
            
        except Exception as e:
            logger.error(f"Error extracting discount info: {str(e)}")
        
        return discount_info

    def _extract_courier_from_metafields(self, order_node: Dict[str, Any]) -> str:
        """
        Extract courier name from order metafields for COD payments
        
        Args:
            order_node: Order node from Shopify GraphQL response
            
        Returns:
            Courier name or empty string if not found
        """
        try:
            metafields = order_node.get("metafields", {}).get("edges", [])
            for metafield_edge in metafields:
                metafield = metafield_edge.get("node", {})
                namespace = metafield.get("namespace", "")
                key = metafield.get("key", "")
                value = metafield.get("value", "")
                
                # Check for courier metafield
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
                    
                    # Split by "-" and get the second part (courier name)
                    parts = value.split("-")
                    if len(parts) >= 2:
                        courier_name = parts[1].strip()
                        logger.info(f"Extracted courier name: '{courier_name}' from metafield value: '{value}'")
                        return courier_name
            
            return ""
            
        except Exception as e:
            logger.error(f"Error extracting courier from metafields: {str(e)}")
            return ""
    
    def _determine_payment_type(self, source_name: str, source_identifier: str, payment_info: Dict[str, Any], location_type: str = "online", location_mapping: Dict[str, Any] = None) -> str:
        """
        Determine payment type based on order channel, payment information, and location type
        
        Args:
            source_name: Source name from order
            source_identifier: Source identifier from order
            payment_info: Payment information dictionary
            location_type: Location type ('online' or 'store')
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
            
            # Check if gateway exists in configured bank transfers (credit card payments)
            if location_mapping and 'bank_transfers' in location_mapping:
                bank_transfers = location_mapping['bank_transfers']
                
                # Case-insensitive comparison
                gateway_lower = gateway.lower()
                for config_gateway in bank_transfers.keys():
                    if gateway_lower == config_gateway.lower():
                        return "CreditCard"
            
            # Check for credit card payments (fallback to hardcoded patterns)
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

    async def check_order_exists_in_sap(self, shopify_order_id: str) -> Dict[str, Any]:
        """
        Check if order already exists in SAP by U_Shopify_Order_ID field
        """
        try:
            # Query SAP for invoice with specific Shopify Order ID
            endpoint = "Invoices"
            params = {
                "$select": "DocEntry,DocNum,U_Shopify_Order_ID",
                "$filter": f"U_Shopify_Order_ID eq '{shopify_order_id}' and Cancelled eq 'tNO'"
            }
            
            result = await sap_client._make_request(
                method='GET',
                endpoint=endpoint,
                params=params
            )
            
            if result["msg"] == "failure":
                logger.error(f"Failed to check order existence in SAP: {result.get('error')}")
                return result
            
            invoices = result["data"]["value"] if "value" in result["data"] else result["data"]
            
            if invoices:
                # Order exists in SAP
                invoice = invoices[0]
                logger.info(f"Order {shopify_order_id} already exists in SAP with DocEntry: {invoice.get('DocEntry')}")
                return {
                    "msg": "success",
                    "exists": True,
                    "doc_entry": invoice.get('DocEntry'),
                    "doc_num": invoice.get('DocNum')
                }
            else:
                # Order doesn't exist in SAP
                return {
                    "msg": "success",
                    "exists": False
                }
            
        except Exception as e:
            logger.error(f"Error checking order existence in SAP: {str(e)}")
            return {"msg": "failure", "error": str(e)}

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

    async def get_open_credit_notes_for_customer(self, customer_card_code: str) -> Dict[str, Any]:
        """
        Get all open credit notes for a customer from SAP
        """
        try:
            # Query SAP for open credit notes
            query = f"CreditNotes?$select=DocEntry,DocTotal,TransNum&$filter=CardCode eq '{customer_card_code}' and DocumentStatus eq 'bost_Open'&$orderby=DocEntry"
            
            result = await sap_client._make_request(
                "GET",
                query
            )
            
            if result["msg"] == "failure":
                logger.error(f"Failed to get open credit notes for customer {customer_card_code}: {result.get('error')}")
                return result
            
            credit_notes = result["data"].get("value", [])
            logger.info(f"Found {len(credit_notes)} open credit notes for customer {customer_card_code}")
            
            return {
                "msg": "success",
                "data": credit_notes
            }
            
        except Exception as e:
            logger.error(f"Error getting open credit notes for customer {customer_card_code}: {str(e)}")
            return {"msg": "failure", "error": str(e)}

    async def create_reconciliation_in_sap(self, reconciliation_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create reconciliation in SAP
        """
        try:
            result = await sap_client._make_request(
                "POST",
                "InternalReconciliations",
                reconciliation_data
            )
            
            if result["msg"] == "failure":
                logger.error(f"Failed to create reconciliation in SAP: {result.get('error')}")
                return result
            
            created_reconciliation = result["data"]
            reconciliation_id = created_reconciliation.get('ReconNum', '')
            
            logger.info(f"Created reconciliation in SAP: {reconciliation_id}")
            
            return {
                "msg": "success",
                "reconciliation_id": reconciliation_id,
                "data": created_reconciliation
            }
            
        except Exception as e:
            logger.error(f"Error creating reconciliation in SAP: {str(e)}")
            return {"msg": "failure", "error": str(e)}

    async def _add_order_tag_with_retry(self, store_key: str, order_id: str, tag: str, tag_description: str, max_retries: int = 3) -> None:
        """
        Add order tag with retry logic
        """
        for attempt in range(max_retries):
            try:
                logger.info(f"🏷️ TAG ATTEMPT {attempt + 1}/{max_retries}: Adding {tag_description}")
                
                result = await self.add_order_tag(store_key, order_id, tag)
                
                if result["msg"] == "success":
                    logger.info(f"✅ TAG SUCCESS on attempt {attempt + 1}: {tag}")
                    return
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

    def prepare_reconciliation_data(self, store_credit_amount: float, customer_card_code: str, 
                                  invoice_doc_entry: int, invoice_trans_num: int, credit_notes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Prepare reconciliation data for SAP
        """
        try:
            from datetime import datetime
            
            # Calculate total amount to reconcile
            total_amount = store_credit_amount
            
            # Prepare reconciliation rows
            reconciliation_rows = []
            
            # Add invoice row (debit)
            invoice_row = {
                "ShortName": customer_card_code,
                "TransId": invoice_trans_num,  # Use TransNum from invoice
                "TransRowId": 0,
                "SrcObjTyp": "13",  # Invoice
                "SrcObjAbs": invoice_doc_entry,
                "CreditOrDebit": "codDebit",
                "ReconcileAmount": total_amount,
                "Selected": "tYES"
            }
            reconciliation_rows.append(invoice_row)
            
            # Add credit note rows (credit)
            remaining_amount = total_amount
            for credit_note in credit_notes:
                if remaining_amount <= 0:
                    break
                    
                doc_entry = credit_note.get("DocEntry")
                doc_total = float(credit_note.get("DocTotal", 0))
                trans_num = credit_note.get("TransNum")
                
                # Use the smaller of remaining amount or credit note total
                reconcile_amount = min(remaining_amount, doc_total)
                
                credit_row = {
                    "ShortName": customer_card_code,
                    "TransId": trans_num,
                    "TransRowId": 0,
                    "SrcObjTyp": "14",  # Credit Note
                    "SrcObjAbs": doc_entry,
                    "CreditOrDebit": "codCredit",
                    "ReconcileAmount": reconcile_amount,
                    "Selected": "tYES"
                }
                reconciliation_rows.append(credit_row)
                
                remaining_amount -= reconcile_amount
                
                logger.info(f"📋 RECONCILIATION ROW: Credit Note {doc_entry} - Amount: {reconcile_amount} EGP")
            
            # Prepare reconciliation data
            reconciliation_data = {
                "ReconDate": datetime.now().strftime("%Y-%m-%d"),
                "CardOrAccount": "coaCard",
                "InternalReconciliationOpenTransRows": reconciliation_rows
            }
            
            logger.info(f"📋 RECONCILIATION PREPARED: Total Amount: {total_amount} EGP, Rows: {len(reconciliation_rows)}")
            
            return reconciliation_data
            
        except Exception as e:
            logger.error(f"Error preparing reconciliation data: {str(e)}")
            raise



    async def _handle_order_failure(self, store_key: str, order_id: str, order_name: str, error_msg: str) -> Dict[str, Any]:
        """
        Helper method to handle order processing failures and add failed tag
        """
        logger.error(f"Failed to process order {order_name}: {error_msg}")
        
        # Add failed tag to order
        try:
            await self.add_order_tag(
                store_key,
                order_id,
                "sap_invoice_failed"
            )
            logger.info(f"Added invoice failed tag to order {order_name}")
        except Exception as tag_error:
            logger.warning(f"Failed to add invoice failed tag for order {order_name}: {str(tag_error)}")
        
        return {"msg": "failure", "error": error_msg}

    async def add_order_tag(self, store_key: str, order_id: str, tag: str) -> Dict[str, Any]:
        """
        Add tag to order to track sync status
        """
        try:
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
            
            # Add retry logic with exponential backoff
            max_retries = 3
            retry_delay = 1
            
            for attempt in range(max_retries):
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        # Get current order to see existing tags
                        order_url = f"https://{store_config.shop_url}/admin/api/2024-01/orders/{order_id_number}.json"
                        
                        # First, get the current order
                        order_response = await client.get(order_url, headers=headers)
                        order_response.raise_for_status()
                        order_data = order_response.json()
                        
                        # Get existing tags and handle edge cases
                        existing_tags_raw = order_data.get('order', {}).get('tags', '')
                        if isinstance(existing_tags_raw, str):
                            existing_tags = [tag.strip() for tag in existing_tags_raw.split(',') if tag.strip()]
                        elif isinstance(existing_tags_raw, list):
                            existing_tags = [str(tag).strip() for tag in existing_tags_raw if tag]
                        else:
                            existing_tags = []
                        
                        # Add new tag if not already present
                        if tag not in existing_tags:
                            existing_tags.append(tag)
                        
                        # Update order with new tags
                        update_data = {
                            "order": {
                                "id": int(order_id_number),  # Ensure ID is integer
                                "tags": ", ".join(existing_tags)
                            }
                        }
                        
                        # Add small delay to avoid rate limiting
                        await asyncio.sleep(0.5)
                        
                        update_response = await client.put(order_url, headers=headers, json=update_data)
                        update_response.raise_for_status()
                        
                        logger.info(f"Added tag '{tag}' to order {order_id}")
                        return {"msg": "success"}
                        
                except httpx.HTTPStatusError as e:
                    error_msg = f"HTTP error adding tag to order {order_id}: {e.response.status_code} - {e.response.text}"
                    logger.error(error_msg)
                    
                    # If it's a rate limit error, retry with backoff
                    if e.response.status_code == 429:
                        if attempt < max_retries - 1:
                            logger.warning(f"Rate limited, retrying in {retry_delay} seconds...")
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2
                            continue
                    
                    return {"msg": "failure", "error": f"HTTP error: {e.response.status_code}"}
                    
                except Exception as e:
                    error_msg = f"Error adding tag to order {order_id}: {str(e)}"
                    logger.error(error_msg)
                    
                    if attempt < max_retries - 1:
                        logger.warning(f"Attempt {attempt + 1} failed, retrying in {retry_delay} seconds...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    else:
                        return {"msg": "failure", "error": str(e)}
            
            return {"msg": "failure", "error": "All retry attempts failed"}
            
        except Exception as e:
            error_msg = f"Unexpected error adding tag to order {order_id}: {str(e)}"
            logger.error(error_msg)
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
            
            # Extract discount information
            discount_info = self._extract_discount_info(order_node)
            
            # Extract address information
            shipping_address = order_node.get("shippingAddress", {})
            billing_address = order_node.get("billingAddress", {})
            
            # Get location mapping for this order using retail location
            location_analysis = self._analyze_order_location_from_retail_location(order_node, store_key)
            sap_codes = location_analysis.get('sap_codes', {})
            
            logger.info(f"Processing order: {order_name} | Payment: {financial_status} | Fulfillment: {fulfillment_status}")
            logger.info(f"Payment Gateway: {payment_info['gateway']} | Card Type: {payment_info['card_type']} | Amount: {payment_info['amount']}")
            
            if payment_info['is_online_payment']:
                logger.info(f"🔑 ONLINE PAYMENT ID: {payment_info['payment_id']}")
            
            # Log gift card information
            if payment_info.get("gift_cards"):
                logger.info(f"🎁 GIFT CARDS USED: {len(payment_info['gift_cards'])} cards, Total Amount: {payment_info['total_gift_card_amount']}")
                for i, gift_card in enumerate(payment_info["gift_cards"], 1):
                    logger.info(f"   🎁 Gift Card {i}: {gift_card['last_characters']} - {gift_card['amount']} {gift_card['currency']}")
            
            # Log store credit information
            if payment_info.get("store_credit", {}).get("amount", 0) > 0:
                store_credit_amount = payment_info["store_credit"]["amount"]
                store_credit_transactions = payment_info["store_credit"]["transactions"]
                logger.info(f"🏪 STORE CREDIT USED: {len(store_credit_transactions)} transactions, Total Amount: {store_credit_amount} EGP")
                for i, store_credit in enumerate(store_credit_transactions, 1):
                    logger.info(f"   🏪 Store Credit {i}: {store_credit['amount']} {store_credit['currency']} - Transaction ID: {store_credit['transaction_id']}")
            
            # Log multiple payment gateways information
            if payment_info.get("payment_gateways"):
                payment_gateways = payment_info["payment_gateways"]
                total_payment_amount = payment_info.get("total_payment_amount", 0.0)
                logger.info(f"💳 PAYMENT GATEWAYS USED: {len(payment_gateways)} gateways, Total Amount: {total_payment_amount} EGP")
                for i, gateway in enumerate(payment_gateways, 1):
                    logger.info(f"   💳 Gateway {i}: {gateway['gateway']} - {gateway['amount']} EGP - Transaction ID: {gateway['transaction_id']}")
            
            # Log discount information
            if discount_info["order_level_discounts"]:
                logger.info(f"💰 ORDER-LEVEL DISCOUNTS: {len(discount_info['order_level_discounts'])} discounts")
                for discount in discount_info["order_level_discounts"]:
                    if discount["value_type"] == "PERCENTAGE":
                        logger.info(f"   💰 {discount['title']}: {discount['value']}% ({discount['allocation_method']})")
                    else:
                        logger.info(f"   💰 {discount['title']}: {discount['value']} {discount['currency']} ({discount['allocation_method']})")
            
            if discount_info["item_level_discounts"]:
                logger.info(f"🏷️ ITEM-LEVEL DISCOUNTS: {len(discount_info['item_level_discounts'])} items with discounts")
                for discount in discount_info["item_level_discounts"]:
                    if "item_name" in discount:  # This is from discount allocations
                        logger.info(f"   🏷️ {discount['item_name']}: {discount['allocated_amount']} {discount['currency']} ({discount['discount_title']})")
                    else:  # This is from discount applications
                        if discount["value_type"] == "PERCENTAGE":
                            logger.info(f"   🏷️ {discount['title']}: {discount['value']}%")
                        else:
                            logger.info(f"   🏷️ {discount['title']}: {discount['value']}")
            
            # Log address information
            if shipping_address:
                ship_to = f"{shipping_address.get('firstName', '')} {shipping_address.get('lastName', '')} | {shipping_address.get('address1', '')} | {shipping_address.get('city', '')}, {shipping_address.get('province', '')} | {shipping_address.get('phone', 'No phone')}"
                logger.info(f"📍 SHIP TO: {ship_to}")
                
                # Log generated delivery address for SAP
                delivery_address = self._generate_address_string(shipping_address)
                logger.info(f"📍 SAP DELIVERY ADDRESS: {delivery_address}")
            
            if billing_address:
                bill_to = f"{billing_address.get('firstName', '')} {billing_address.get('lastName', '')} | {billing_address.get('address1', '')} | {billing_address.get('city', '')}, {billing_address.get('province', '')} | {billing_address.get('phone', 'No phone')}"
                logger.info(f"📍 BILL TO: {bill_to}")
                
                # Log generated billing address for SAP
                billing_address_str = self._generate_address_string(billing_address)
                logger.info(f"📍 SAP BILLING ADDRESS: {billing_address_str}")
            
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
                sap_customer = await self.customer_manager.create_customer_in_sap(customer, store_key, location_analysis)
            if not sap_customer:
                    logger.error(f"Failed to create customer for order {order_name}")
                    return {"msg": "failure", "error": "Failed to create customer"}
            
            # Extract numeric order ID for logging (needed for gift card creation)
            order_id_number = order_id.split("/")[-1] if "/" in order_id else order_id
            
            # Check for gift card purchases and create gift cards in SAP FIRST
            gift_card_purchases = self._detect_gift_card_purchases(order_node)
            created_gift_cards = []
            
            if gift_card_purchases:
                logger.info(f"Found {len(gift_card_purchases)} gift card purchase(s) in order {order_name}")
                
                # Parse order date for gift card creation
                created_at = order_node["createdAt"]
                order_date = created_at.split("T")[0] if "T" in created_at else created_at
                
                # Create gift cards in SAP FIRST (before invoice creation)
                created_gift_cards = await self._create_gift_cards_in_sap(
                    gift_card_purchases, 
                    order_date, 
                    sap_customer["CardCode"], 
                    order_name,
                    order_id_number,
                    created_at
                )
                
                if created_gift_cards:
                    logger.info(f"Successfully created {len(created_gift_cards)} gift card(s) in SAP")
                else:
                    logger.warning(f"Failed to create gift cards in SAP for order {order_name}")
                    # Continue with invoice creation even if gift card creation fails
            
            # Map order to SAP format (pass created gift cards for line item mapping)
            sap_invoice_data = self.map_shopify_order_to_sap(shopify_order, sap_customer["CardCode"], store_key, created_gift_cards)
            if not sap_invoice_data:
                logger.error(f"Failed to map order {order_name} to SAP format")
                return {"msg": "failure", "error": "Failed to map order to SAP format"}
            
            # Check if order already exists in SAP
            order_exists_result = await self.check_order_exists_in_sap(order_id_number)
            if order_exists_result["msg"] == "failure":
                logger.error(f"Failed to check order existence for {order_name}: {order_exists_result.get('error')}")
                return order_exists_result
            
            if order_exists_result["exists"]:
                # Order already exists in SAP, add invoice sync tag and skip processing
                logger.info(f"Order {order_name} already exists in SAP with DocEntry: {order_exists_result['doc_entry']}")
                
                # Add invoice sync tags to order
                invoice_tag = f"sap_invoice_{order_exists_result['doc_entry']}"
                invoice_synced_tag = "sap_invoice_synced"
                
                # Add specific invoice tag
                tag_update_result = await self.add_order_tag(
                    store_key,
                    order_id,
                    invoice_tag
                )
                
                # Add general synced tag
                synced_tag_result = await self.add_order_tag(
                    store_key,
                    order_id,
                    invoice_synced_tag
                )
                
                if tag_update_result["msg"] == "failure":
                    logger.warning(f"Failed to add invoice sync tag for {order_name}: {tag_update_result.get('error')}")
                
                if synced_tag_result["msg"] == "failure":
                    logger.warning(f"Failed to add invoice synced tag for {order_name}: {synced_tag_result.get('error')}")
                
                return {
                    "msg": "skipped",
                    "order_name": order_name,
                    "reason": "Order already exists in SAP",
                    "sap_invoice_number": order_exists_result["doc_entry"],
                    "customer_card_code": sap_customer["CardCode"],
                    "financial_status": financial_status,
                    "fulfillment_status": fulfillment_status
                }
            
            # Create invoice in SAP
            invoice_result = await self.create_invoice_in_sap(sap_invoice_data, order_id_number)
            if invoice_result["msg"] == "failure":
                return invoice_result
            
            # Get the created invoice data with DocEntry, DocTotal, and TransNum
            created_invoice_data = {
                "DocEntry": invoice_result["sap_doc_entry"],
                "DocNum": invoice_result["sap_doc_num"],
                "DocTotal": invoice_result["sap_doc_total"],
                "TransNum": invoice_result["sap_trans_num"],
                "DocDate": invoice_result["sap_doc_date"]
            }
            
            logger.info(f"Created invoice data: {created_invoice_data}")
            
            # Add invoice tags immediately after successful invoice creation
            invoice_tag = f"sap_invoice_{invoice_result['sap_doc_entry']}"
            invoice_synced_tag = "sap_invoice_synced"
            
            # Add specific invoice tag
            tag_update_result = await self.add_order_tag(
                store_key,
                order_id,
                invoice_tag
            )
            
            # Add general synced tag
            synced_tag_result = await self.add_order_tag(
                store_key,
                order_id,
                invoice_synced_tag
            )
            
            if tag_update_result["msg"] == "failure":
                logger.warning(f"Failed to add invoice sync tag for {order_name}: {tag_update_result.get('error')}")
            
            if synced_tag_result["msg"] == "failure":
                logger.warning(f"Failed to add invoice synced tag for {order_name}: {synced_tag_result.get('error')}")
            
            logger.info(f"✅ Invoice created and tagged for order {order_name}")
            
            # Check if order is paid and create incoming payment
            # Treat PARTIALLY_REFUNDED as PAID for payment processing (order was paid, then partially refunded)
            sap_payment_number = None
            is_paid_for_payment_processing = financial_status in ["PAID", "PARTIALLY_REFUNDED"]
            
            if is_paid_for_payment_processing:
                if financial_status == "PARTIALLY_REFUNDED":
                    logger.info(f"Order {order_name} is PARTIALLY_REFUNDED - treating as PAID for payment processing (order was paid, then partially refunded)")
                else:
                    logger.info(f"Order {order_name} is paid - creating incoming payment in SAP")
                
                # Prepare incoming payment data
                payment_data = self.prepare_incoming_payment_data(
                    shopify_order, 
                    created_invoice_data, 
                    sap_customer["CardCode"], 
                    store_key,
                    location_analysis
                )
                
                # Create incoming payment in SAP
                payment_result = await self.create_incoming_payment_in_sap(payment_data, order_id_number)
                if payment_result["msg"] == "success":
                    sap_payment_number = payment_result["sap_payment_number"]
                    logger.info(f"Successfully created incoming payment: {sap_payment_number}")
                    
                    # Handle store credit reconciliation if store credit was used
                    store_credit_amount = payment_info.get("store_credit", {}).get("amount", 0.0)
                    if store_credit_amount > 0:
                        logger.info(f"🏪 STORE CREDIT RECONCILIATION: Processing {store_credit_amount} EGP store credit")
                        
                        # Get open credit notes for the customer
                        credit_notes_result = await self.get_open_credit_notes_for_customer(sap_customer["CardCode"])
                        if credit_notes_result["msg"] == "success":
                            credit_notes = credit_notes_result["data"]
                            
                            if credit_notes:
                                # Prepare reconciliation data
                                reconciliation_data = self.prepare_reconciliation_data(
                                    store_credit_amount,
                                    sap_customer["CardCode"],
                                    created_invoice_data["DocEntry"],
                                    created_invoice_data["TransNum"],
                                    credit_notes
                                )
                                
                                # Create reconciliation in SAP
                                reconciliation_result = await self.create_reconciliation_in_sap(reconciliation_data)
                                if reconciliation_result["msg"] == "success":
                                    reconciliation_id = reconciliation_result["reconciliation_id"]
                                    logger.info(f"✅ STORE CREDIT RECONCILIATION SUCCESS: {reconciliation_id}")
                                    
                                    # Add reconciliation success tags with retry logic
                                    recon_tag = f"sap_recon_{reconciliation_id}"
                                    recon_synced_tag = "sap_recon_synced"
                                    
                                    # Add reconciliation tag with retry
                                    await self._add_order_tag_with_retry(store_key, order_id, recon_tag, "reconciliation tag")
                                    
                                    # Add reconciliation synced tag with retry
                                    await self._add_order_tag_with_retry(store_key, order_id, recon_synced_tag, "reconciliation synced tag")
                                        
                                else:
                                    logger.warning(f"⚠️ STORE CREDIT RECONCILIATION FAILED: {reconciliation_result.get('error')}")
                                    
                                    # Add reconciliation failure tag with retry
                                    await self._add_order_tag_with_retry(store_key, order_id, "sap_recon_failed", "reconciliation failed tag")
                            else:
                                logger.warning(f"⚠️ NO OPEN CREDIT NOTES FOUND for customer {sap_customer['CardCode']} - Store credit {store_credit_amount} EGP cannot be reconciled")
                                
                                # Add reconciliation failure tag when no credit notes found with retry
                                await self._add_order_tag_with_retry(store_key, order_id, "sap_recon_failed", "reconciliation failed tag (no credit notes)")
                        else:
                            logger.warning(f"⚠️ FAILED TO GET CREDIT NOTES for customer {sap_customer['CardCode']}: {credit_notes_result.get('error')}")
                            
                            # Add reconciliation failure tag when credit notes query fails with retry
                            await self._add_order_tag_with_retry(store_key, order_id, "sap_recon_failed", "reconciliation failed tag (query failed)")
                    
                    # Add payment sync tags
                    payment_tag = f"sap_payment_{sap_payment_number}"
                    payment_synced_tag = "sap_payment_synced"
                    
                    # Add specific payment tag
                    payment_tag_result = await self.add_order_tag(
                        store_key,
                        order_id,
                        payment_tag
                    )
                    
                    # Add general payment synced tag
                    synced_tag_result = await self.add_order_tag(
                        store_key,
                        order_id,
                        payment_synced_tag
                    )
                    
                    if payment_tag_result["msg"] == "failure":
                        logger.warning(f"Failed to add payment sync tag for {order_name}: {payment_tag_result.get('error')}")
                    
                    if synced_tag_result["msg"] == "failure":
                        logger.warning(f"Failed to add payment synced tag for {order_name}: {synced_tag_result.get('error')}")
                else:
                    logger.warning(f"Failed to create incoming payment for {order_name}: {payment_result.get('error')}")
                    
                    # Add payment failed tag
                    payment_failed_tag = "sap_payment_failed"
                    payment_tag_result = await self.add_order_tag(
                        store_key,
                        order_id,
                        payment_failed_tag
                    )
                    if payment_tag_result["msg"] == "failure":
                        logger.warning(f"Failed to add payment failed tag for {order_name}: {payment_tag_result.get('error')}")
                    
                    # Don't fail the entire process if payment creation fails
            else:
                logger.info(f"Order {order_name} is not paid (status: {financial_status}) - skipping payment creation")
            
            # Invoice tags already added immediately after invoice creation
            
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
                "gift_cards": payment_info.get("gift_cards", []),
                "total_gift_card_amount": payment_info.get("total_gift_card_amount", 0.0),
                "discount_info": discount_info,
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
                                
                                # Log gift card information
                                if result.get("gift_cards"):
                                    logger.info(f"   🎁 Gift Cards: {len(result['gift_cards'])} cards, Total: {result.get('total_gift_card_amount', 0.0)}")
                                
                                # Log discount information
                                discount_info = result.get("discount_info", {})
                                if discount_info.get("order_level_discounts"):
                                    logger.info(f"   💰 Order Discounts: {len(discount_info['order_level_discounts'])}")
                                if discount_info.get("item_level_discounts"):
                                    logger.info(f"   🏷️ Item Discounts: {len(discount_info['item_level_discounts'])}")
                                
                                # Log address summary
                                shipping_addr = result.get("shipping_address", {})
                                if shipping_addr:
                                    ship_to_summary = f"{shipping_addr.get('firstName', '')} {shipping_addr.get('lastName', '')} - {shipping_addr.get('city', '')}"
                                    logger.info(f"   📍 Ship To: {ship_to_summary}")
                                
                                billing_addr = result.get("billing_address", {})
                                if billing_addr:
                                    bill_to_summary = f"{billing_addr.get('firstName', '')} {billing_addr.get('lastName', '')} - {billing_addr.get('city', '')}"
                                    logger.info(f"   📍 Bill To: {bill_to_summary}")
                                
                            elif result["msg"] == "skipped":
                                logger.info(f"⏭️ Skipped order {result['order_name']} - {result['reason']}")
                                
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
