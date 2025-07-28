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
            # Query to get orders that haven't been synced yet
            query = """
            query getOrders($first: Int!, $after: String) {
                orders(first: $first, after: $after, query: "status:any -tag:synced") {
                    edges {
                        node {
                            id
                            name
                            createdAt
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
            logger.info(f"Retrieved {len(orders)} orders from Shopify store {store_key}")
            
            return {"msg": "success", "data": orders}
            
        except Exception as e:
            logger.error(f"Error getting orders from Shopify: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    def map_shopify_order_to_sap(self, shopify_order: Dict[str, Any], customer_card_code: str) -> Dict[str, Any]:
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
            
            # Map line items
            line_items = []
            for item_edge in order_node["lineItems"]["edges"]:
                item = item_edge["node"]
                variant = item["variant"]
                
                line_item = {
                    "ItemCode": item["sku"] or variant["sku"],
                    "Quantity": item["quantity"],
                    "UnitPrice": float(item["discountedTotalSet"]["shopMoney"]["amount"]) / item["quantity"],
                    "LineTotal": float(item["discountedTotalSet"]["shopMoney"]["amount"]),
                    "U_ShopifyLineItemID": item["id"]
                }
                line_items.append(line_item)
            
            # Handle gift card redemptions
            gift_card_lines = self._extract_gift_card_lines(order_node)
            line_items.extend(gift_card_lines)
            
            # Calculate freight
            freight_amount = self._calculate_freight(order_node)
            
            # Prepare SAP invoice data
            sap_invoice = {
                "CardCode": customer_card_code,
                "DocDate": created_at[:10],  # YYYY-MM-DD format
                "DocDueDate": created_at[:10],
                "DocumentLines": line_items,
                "U_ShopifyOrderID": order_name,
                "U_ShopifyOrderNumber": order_name,
                "U_ShopifyCreatedAt": created_at,
                "U_ShopifyCurrency": currency,
                "U_ShopifyTotal": float(total_price),
                "U_ShopifySubtotal": float(order_node["subtotalPriceSet"]["shopMoney"]["amount"]),
                "U_ShopifyTax": float(order_node["totalTaxSet"]["shopMoney"]["amount"]),
                "U_ShopifyShipping": float(order_node["totalShippingPriceSet"]["shopMoney"]["amount"]),
                "U_FreightAmount": freight_amount,
                "Comments": order_node.get("note", "")
            }
            
            return sap_invoice
            
        except Exception as e:
            logger.error(f"Error mapping Shopify order to SAP: {str(e)}")
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
            
            logger.info(f"Processing order: {order_name}")
            
            # Get or create customer in SAP
            customer = order_node.get("customer")
            if not customer:
                logger.warning(f"No customer found for order {order_name}")
                return {"msg": "failure", "error": "No customer found"}
            
            sap_customer = await self.customer_manager.get_or_create_customer(customer)
            if not sap_customer:
                logger.error(f"Failed to get or create customer for order {order_name}")
                return {"msg": "failure", "error": "Failed to get or create customer"}
            
            # Map order to SAP format
            sap_invoice_data = self.map_shopify_order_to_sap(shopify_order, sap_customer["CardCode"])
            
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
                "customer_card_code": sap_customer["CardCode"]
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