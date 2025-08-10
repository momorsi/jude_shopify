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
                            tags
                            financialStatus
                            fulfillmentStatus
                            location {
                                id
                                name
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
                            totalTaxSet {
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
                            }
                            billingAddress {
                                address1
                                address2
                                city
                                province
                                zip
                                country
                                phone
                            }
                            lineItems(first: 50) {
                                edges {
                                    node {
                                        id
                                        quantity
                                        sku
                                        title
                                        variant {
                                            id
                                            sku
                                            price
                                            product {
                                                id
                                                title
                                            }
                                        }
                                        discountedTotalSet {
                                            shopMoney {
                                                amount
                                                currencyCode
                                            }
                                        }
                                    }
                                }
                            }
                            note
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
            
            # Filter orders that don't have the synced tag
            unsynced_orders = []
            for order in orders:
                order_node = order["node"]
                tags = order_node.get("tags", [])
                
                # Check if order has synced tag
                has_synced_tag = "synced" in tags
                
                if not has_synced_tag:
                    unsynced_orders.append(order)
            
            logger.info(f"Retrieved {len(orders)} total orders, {len(unsynced_orders)} unsynced orders from Shopify store {store_key}")
            
            return {"msg": "success", "data": unsynced_orders}
            
        except Exception as e:
            logger.error(f"Error getting orders from Shopify: {str(e)}")
            return {"msg": "failure", "error": str(e)}

    async def get_orders_with_metafields(self, store_key: str) -> Dict[str, Any]:
        """
        Get orders from Shopify store that need to be synced using metafields
        """
        try:
            # Query to get orders with metafields, ordered by creation date desc
            query = """
            query getOrdersWithMetafields($first: Int!, $after: String) {
                orders(first: $first, after: $after, sortKey: CREATED_AT, reverse: true) {
                    edges {
                        node {
                            id
                            name
                            createdAt
                            metafields(first: 10, namespace: "sap_sync") {
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
                            totalTaxSet {
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
                            }
                            billingAddress {
                                address1
                                address2
                                city
                                province
                                zip
                                country
                                phone
                            }
                            lineItems(first: 50) {
                                edges {
                                    node {
                                        id
                                        quantity
                                        sku
                                        title
                                        variant {
                                            id
                                            sku
                                            price
                                            product {
                                                id
                                                title
                                            }
                                        }
                                        discountedTotalSet {
                                            shopMoney {
                                                amount
                                                currencyCode
                                            }
                                        }
                                    }
                                }
                            }
                            discountApplications(first: 10) {
                                edges {
                                    node {
                                        type
                                        value {
                                            ... on MoneyV2 {
                                                amount
                                                currencyCode
                                            }
                                            ... on PricingPercentageValue {
                                                percentage
                                            }
                                        }
                                        target {
                                            ... on OrderLineItem {
                                                id
                                            }
                                        }
                                    }
                                }
                            }
                            tags
                            note
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
                    if metafield["namespace"] == "sap_sync" and metafield["key"] == "synced":
                        has_synced_metafield = True
                        break
                
                if not has_synced_metafield:
                    unsynced_orders.append(order)
            
            logger.info(f"Retrieved {len(orders)} total orders, {len(unsynced_orders)} unsynced orders from Shopify store {store_key}")
            
            return {"msg": "success", "data": unsynced_orders}
            
        except Exception as e:
            logger.error(f"Error getting orders from Shopify: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def get_single_order_for_testing(self, store_key: str) -> Dict[str, Any]:
        """
        Get a single order to test and understand the metafield structure
        """
        try:
            # Query to get a single order with all metafields
            query = """
            query getSingleOrder($first: Int!) {
                orders(first: $first, sortKey: CREATED_AT, reverse: true) {
                    edges {
                        node {
                            id
                            name
                            createdAt
                            metafields(first: 50) {
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
                            totalPriceSet {
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
                            }
                            lineItems(first: 5) {
                                edges {
                                    node {
                                        id
                                        quantity
                                        sku
                                        title
                                        variant {
                                            id
                                            sku
                                            price
                                        }
                                        discountedTotalSet {
                                            shopMoney {
                                                amount
                                                currencyCode
                                            }
                                        }
                                    }
                                }
                            }
                            tags
                        }
                    }
                }
            }
            """
            
            result = await multi_store_shopify_client.execute_query(
                store_key,
                query,
                {"first": 1}
            )
            
            if result["msg"] == "failure":
                return result
            
            if not result["data"]["orders"]["edges"]:
                return {"msg": "failure", "error": "No orders found"}
            
            order = result["data"]["orders"]["edges"][0]
            order_node = order["node"]
            
            # Print important details
            logger.info("=== SINGLE ORDER TEST ===")
            logger.info(f"Order ID: {order_node['id']}")
            logger.info(f"Order Name: {order_node['name']}")
            logger.info(f"Created At: {order_node['createdAt']}")
            logger.info(f"Total Price: {order_node['totalPriceSet']['shopMoney']['amount']} {order_node['totalPriceSet']['shopMoney']['currencyCode']}")
            
            # Print metafields
            metafields = order_node.get("metafields", {}).get("edges", [])
            logger.info(f"Number of metafields: {len(metafields)}")
            
            for metafield_edge in metafields:
                metafield = metafield_edge["node"]
                logger.info(f"Metafield: namespace='{metafield['namespace']}', key='{metafield['key']}', value='{metafield['value']}', type='{metafield['type']}'")
            
            # Print customer info
            customer = order_node.get("customer")
            if customer:
                logger.info(f"Customer: {customer['firstName']} {customer['lastName']} ({customer['email']})")
            
            # Print line items
            line_items = order_node.get("lineItems", {}).get("edges", [])
            logger.info(f"Number of line items: {len(line_items)}")
            
            for item_edge in line_items:
                item = item_edge["node"]
                variant = item.get("variant", {})
                logger.info(f"Line Item: {item['title']} (SKU: {item['sku'] or variant.get('sku', 'N/A')}, Qty: {item['quantity']}, Price: {item['discountedTotalSet']['shopMoney']['amount']})")
            
            logger.info("=== END SINGLE ORDER TEST ===")
            
            return {"msg": "success", "data": order}
            
        except Exception as e:
            logger.error(f"Error getting single order for testing: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    def map_shopify_order_to_sap(self, shopify_order: Dict[str, Any], customer_card_code: str, ship_to_code: str, store_key: str) -> Dict[str, Any]:
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
            financial_status = order_node.get("financialStatus", "PENDING")
            fulfillment_status = order_node.get("fulfillmentStatus", "UNFULFILLED")
            
            # Map line items
            line_items = []
            for item_edge in order_node["lineItems"]["edges"]:
                item = item_edge["node"]
                sku = item.get("sku")
                quantity = item["quantity"]
                price = Decimal(item["discountedTotalSet"]["shopMoney"]["amount"])
                
                # Use a default item if SKU doesn't exist in SAP
                item_code = "ACC-0000001"  # Default item
                if sku:
                    # In a real implementation, you might want to map SKUs to SAP ItemCodes
                    # For now, we'll use the default item
                    item_code = "ACC-0000001"
                
                # Get warehouse code based on order location
                warehouse_code = config_settings.get_warehouse_code_for_order(store_key, order_node)
                
                line_item = {
                    "ItemCode": item_code,
                    "Quantity": quantity,
                    "UnitPrice": float(price),
                    "WarehouseCode": warehouse_code
                }
                line_items.append(line_item)
            
            # Parse date
            doc_date = created_at.split("T")[0] if "T" in created_at else created_at
            
            # Create invoice data
            invoice_data = {
                "DocDate": doc_date,
                "CardCode": customer_card_code,
                "NumAtCard": order_name,
                "Series": 82,
                "Comments": f"Shopify Order: {order_name} | Payment: {financial_status} | Fulfillment: {fulfillment_status}",
                #"ShipToCode": ship_to_code,
                #"U_Shopify_Order_ID": order_name,
                #"U_Shopify_Financial_Status": financial_status,
                #"U_Shopify_Fulfillment_Status": fulfillment_status,
                "SalesPersonCode": 28,
                "DocumentLines": line_items
                # Removed DocumentAdditionalExpenses to avoid ExpenseCode issues
            }
            
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
    
    def _calculate_freight(self, order_node: Dict[str, Any]) -> float:
        """
        Calculate freight amount based on shipping address and order details
        """
        try:
            # Get shipping address
            shipping_address = order_node.get("shippingAddress")
            if not shipping_address:
                return 0.0
            
            # Get shipping price from order
            shipping_price = float(order_node["totalShippingPriceSet"]["shopMoney"]["amount"])
            
            # You can implement more complex freight calculation logic here
            # For example, based on country, weight, or other factors
            
            return shipping_price
            
        except Exception as e:
            logger.error(f"Error calculating freight: {str(e)}")
            return 0.0
    
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
    
    async def update_order_meta_fields(self, store_key: str, order_id: str, 
                                     synced_status: str, sap_invoice_number: str) -> Dict[str, Any]:
        """
        Update order meta fields in Shopify
        """
        try:
            # Mutation to update order meta fields
            mutation = """
            mutation orderUpdate($input: OrderInput!) {
                orderUpdate(input: $input) {
                    order {
                        id
                        name
                        tags
                    }
                    userErrors {
                        field
                        message
                    }
                }
            }
            """
            
            # Prepare update data
            update_data = {
                "id": order_id,
                "tags": [synced_status, f"sap_invoice:{sap_invoice_number}"]
            }
            
            result = await multi_store_shopify_client.execute_query(
                store_key,
                mutation,
                {"input": update_data}
            )
            
            if result["msg"] == "failure":
                return result
            
            response_data = result["data"]["orderUpdate"]
            
            if response_data.get("userErrors"):
                errors = [error["message"] for error in response_data["userErrors"]]
                return {"msg": "failure", "error": "; ".join(errors)}
            
            logger.info(f"Updated order meta fields: {order_id}")
            return {"msg": "success"}
            
        except Exception as e:
            logger.error(f"Error updating order meta fields: {str(e)}")
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
            financial_status = order_node.get("financialStatus", "PENDING")
            fulfillment_status = order_node.get("fulfillmentStatus", "UNFULFILLED")
            
            logger.info(f"Processing order: {order_name} | Payment: {financial_status} | Fulfillment: {fulfillment_status}")
            
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
            
            # Extract phone number from customer
            phone = self.customer_manager._extract_phone_from_customer(customer)
            if not phone:
                logger.warning(f"No phone number found for customer in order {order_name}")
                return {"msg": "failure", "error": "No phone number found for customer"}
            
            # Check if customer exists in SAP by phone
            existing_customer = await self.customer_manager.find_customer_by_phone(phone)
            
            if existing_customer:
                logger.info(f"Found existing customer: {existing_customer.get('CardCode', 'Unknown')}")
                sap_customer = existing_customer
                # Use the ShipToDefault from the existing customer
                ship_to_code = existing_customer.get('ShipToDefault', '')
            else:
                # Create new customer in SAP
                logger.info("Creating new customer in SAP")
                sap_customer = await self.customer_manager.create_customer_in_sap(customer)
            if not sap_customer:
                    logger.error(f"Failed to create customer for order {order_name}")
                    return {"msg": "failure", "error": "Failed to create customer"}
                
                # Use the ShipToDefault from the newly created customer
                #ship_to_code = sap_customer.get('ShipToDefault', '')
            
            # Map order to SAP format
            sap_invoice_data = self.map_shopify_order_to_sap(shopify_order, sap_customer["CardCode"], ship_to_code, store_key)
            if not sap_invoice_data:
                logger.error(f"Failed to map order {order_name} to SAP format")
                return {"msg": "failure", "error": "Failed to map order to SAP format"}
            
            # Create invoice in SAP
            invoice_result = await self.create_invoice_in_sap(sap_invoice_data)
            if invoice_result["msg"] == "failure":
                return invoice_result
            
            # Update order meta fields in Shopify
            meta_update_result = await self.update_order_meta_fields(
                store_key,
                order_id,
                "synced",
                str(invoice_result["sap_invoice_number"])
            )
            
            if meta_update_result["msg"] == "failure":
                logger.warning(f"Failed to update order meta fields for {order_name}: {meta_update_result.get('error')}")
                # Don't fail the entire process if meta update fails
            
            logger.info(f"Successfully processed order {order_name}")
            
            return {
                "msg": "success",
                "order_name": order_name,
                "sap_invoice_number": invoice_result["sap_invoice_number"],
                "customer_card_code": sap_customer["CardCode"],
                "ship_to_code": ship_to_code,
                "financial_status": financial_status,
                "fulfillment_status": fulfillment_status
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
                            result = await self.process_order(store_key, shopify_order)
                            
                            if result["msg"] == "success":
                                total_success += 1
                                logger.info(f"✅ Processed order {result['order_name']} -> SAP Invoice: {result['sap_invoice_number']}")
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