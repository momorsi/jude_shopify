"""
Direct test script to retrieve and display comprehensive order data
Bypasses sync configuration and directly queries Shopify
"""

import asyncio
import sys
import os
from decimal import Decimal
from typing import Dict, Any

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.core.config import config_settings
from app.utils.logging import logger


async def get_order_data_direct(order_id: str) -> Dict[str, Any]:
    """
    Get comprehensive order data directly from Shopify store
    """
    try:
        # Get store configuration directly
        stores_config = config_settings.shopify_stores
        
        # Query to get order with all necessary data
        query = """
        query getOrder($id: ID!) {
            order(id: $id) {
                id
                name
                createdAt
                tags
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
                    test
                }
                note
            }
        }
        """
        
        # Try to find the order in all stores (enabled or not)
        for store_key, store_config in stores_config.items():
            try:
                print(f"🔍 Searching for order {order_id} in store: {store_key} ({store_config.name})")
                
                # Try with the full Shopify ID first
                result = await multi_store_shopify_client.execute_query(
                    store_key,
                    query,
                    {"id": f"gid://shopify/Order/{order_id}"}
                )
                
                if result["msg"] == "success" and result["data"]["order"]:
                    print(f"✅ Found order {order_id} in store: {store_key}")
                    return {
                        "msg": "success",
                        "store_key": store_key,
                        "order_data": result["data"]["order"]
                    }
                else:
                    print(f"❌ Order {order_id} not found in store: {store_key}")
                    if result["msg"] == "failure":
                        print(f"   Error: {result.get('error', 'Unknown error')}")
                    
            except Exception as e:
                print(f"❌ Error searching store {store_key}: {str(e)}")
                continue
        
        return {"msg": "failure", "error": f"Order {order_id} not found in any store"}
        
    except Exception as e:
        print(f"❌ Error getting order data: {str(e)}")
        return {"msg": "failure", "error": str(e)}


async def get_order_by_name(store_key: str, order_name: str) -> Dict[str, Any]:
    """
    Get order data by order name (like #1533)
    """
    try:
        # Query to get orders and filter by name
        query = """
        query getOrdersByName($first: Int!, $query: String!) {
            orders(first: $first, query: $query, sortKey: CREATED_AT, reverse: true) {
                edges {
                    node {
                        id
                        name
                        createdAt
                        tags
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
                            test
                        }
                        note
                    }
                }
            }
        }
        """
        
        result = await multi_store_shopify_client.execute_query(
            store_key,
            query,
            {"first": 10, "query": f"name:{order_name}"}
        )
        
        if result["msg"] == "success":
            orders = result["data"]["orders"]["edges"]
            if orders:
                # Return the first matching order
                return {
                    "msg": "success",
                    "order_data": orders[0]["node"]
                }
            else:
                return {"msg": "failure", "error": f"Order {order_name} not found"}
        else:
            return result
            
    except Exception as e:
        return {"msg": "failure", "error": str(e)}


async def get_recent_orders(store_key: str, limit: int = 5) -> Dict[str, Any]:
    """
    Get recent orders to see what orders are available
    """
    try:
        query = """
        query getRecentOrders($first: Int!) {
            orders(first: $first, sortKey: CREATED_AT, reverse: true) {
                edges {
                    node {
                        id
                        name
                        createdAt
                        displayFinancialStatus
                        displayFulfillmentStatus
                        sourceName
                        totalPriceSet {
                            shopMoney {
                                amount
                                currencyCode
                            }
                        }
                    }
                }
            }
        }
        """
        
        result = await multi_store_shopify_client.execute_query(
            store_key,
            query,
            {"first": limit}
        )
        
        if result["msg"] == "success":
            return {
                "msg": "success",
                "orders": result["data"]["orders"]["edges"]
            }
        else:
            return result
            
    except Exception as e:
        return {"msg": "failure", "error": str(e)}


def extract_payment_info(order_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract comprehensive payment information from order transactions
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
        transactions = order_data.get("transactions", [])
        
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
                # Note: paymentDetails is a union type, so we'll get basic info from gateway
                payment_info["card_type"] = transaction.get("gateway", "Unknown")
                payment_info["last_4"] = "Unknown"  # Not available in simplified query
                
                # Check if this is an online payment
                source_name = order_data.get("sourceName", "").lower()
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
        print(f"Error extracting payment info: {str(e)}")
    
    return payment_info


def format_address(address: Dict[str, Any], address_type: str) -> str:
    """
    Format address for display
    """
    if not address:
        return f"{address_type}: Not provided"
    
    parts = []
    
    # Add name if available
    if address.get("firstName") or address.get("lastName"):
        name_parts = []
        if address.get("firstName"):
            name_parts.append(address["firstName"])
        if address.get("lastName"):
            name_parts.append(address["lastName"])
        parts.append(" ".join(name_parts))
    
    # Add company if available
    if address.get("company"):
        parts.append(address["company"])
    
    # Add address lines
    if address.get("address1"):
        parts.append(address["address1"])
    if address.get("address2"):
        parts.append(address["address2"])
    
    # Add city, province, zip, country
    city_parts = []
    if address.get("city"):
        city_parts.append(address["city"])
    if address.get("province"):
        city_parts.append(address["province"])
    if address.get("zip"):
        city_parts.append(address["zip"])
    
    if city_parts:
        parts.append(", ".join(city_parts))
    
    if address.get("country"):
        parts.append(address["country"])
    
    # Add phone if available
    if address.get("phone"):
        parts.append(f"Phone: {address['phone']}")
    
    return f"{address_type}: " + " | ".join(parts) if parts else f"{address_type}: Not provided"


def display_order_data(order_data: Dict[str, Any], store_key: str):
    """
    Display comprehensive order data
    """
    print("\n" + "="*80)
    print("ORDER DATA ANALYSIS")
    print("="*80)
    
    # Basic order information
    print(f"📦 Order ID: {order_data['name']}")
    print(f"🆔 Shopify ID: {order_data['id']}")
    print(f"📅 Created: {order_data['createdAt']}")
    print(f"🏪 Store: {store_key}")
    print(f"💰 Financial Status: {order_data.get('displayFinancialStatus', 'Unknown')}")
    print(f"📦 Fulfillment Status: {order_data.get('displayFulfillmentStatus', 'Unknown')}")
    print(f"📱 Source: {order_data.get('sourceName', 'Unknown')}")
    print(f"🏷️ Tags: {', '.join(order_data.get('tags', []))}")
    
    # Pricing information
    print(f"\n💰 PRICING:")
    print(f"   Total: {order_data['totalPriceSet']['shopMoney']['amount']} {order_data['totalPriceSet']['shopMoney']['currencyCode']}")
    print(f"   Subtotal: {order_data['subtotalPriceSet']['shopMoney']['amount']} {order_data['subtotalPriceSet']['shopMoney']['currencyCode']}")
    print(f"   Tax: {order_data['totalTaxSet']['shopMoney']['amount']} {order_data['totalTaxSet']['shopMoney']['currencyCode']}")
    print(f"   Shipping: {order_data['totalShippingPriceSet']['shopMoney']['amount']} {order_data['totalShippingPriceSet']['shopMoney']['currencyCode']}")
    
    # Customer information
    customer = order_data.get('customer')
    if customer:
        print(f"\n👤 CUSTOMER:")
        print(f"   Name: {customer.get('firstName', '')} {customer.get('lastName', '')}")
        print(f"   Email: {customer.get('email', 'Not provided')}")
        print(f"   Phone: {customer.get('phone', 'Not provided')}")
        print(f"   Shopify ID: {customer.get('id', 'Unknown')}")
    
    # Addresses
    print(f"\n📍 ADDRESSES:")
    print(f"   {format_address(order_data.get('shippingAddress'), 'Ship To')}")
    print(f"   {format_address(order_data.get('billingAddress'), 'Bill To')}")
    
    # Payment information
    payment_info = extract_payment_info(order_data)
    print(f"\n💳 PAYMENT INFORMATION:")
    print(f"   Gateway: {payment_info['gateway']}")
    print(f"   Card Type: {payment_info['card_type']}")
    print(f"   Last 4 Digits: {payment_info['last_4']}")
    print(f"   Amount: {payment_info['amount']}")
    print(f"   Status: {payment_info['status']}")
    print(f"   Processed At: {payment_info['processed_at']}")
    print(f"   Authorization: {payment_info['authorization']}")
    print(f"   Is Online Payment: {payment_info['is_online_payment']}")
    
    if payment_info['is_online_payment']:
        print(f"   🔑 PAYMENT ID (Online): {payment_info['payment_id']}")
    
    # Line items
    print(f"\n📋 LINE ITEMS:")
    line_items = order_data.get('lineItems', {}).get('edges', [])
    for i, item_edge in enumerate(line_items, 1):
        item = item_edge['node']
        variant = item.get('variant', {})
        print(f"   {i}. {item.get('title', 'Unknown Product')}")
        print(f"      SKU: {item.get('sku', 'No SKU')}")
        print(f"      Quantity: {item.get('quantity', 0)}")
        print(f"      Price: {variant.get('price', 'Unknown')}")
        print(f"      Total: {item['discountedTotalSet']['shopMoney']['amount']} {item['discountedTotalSet']['shopMoney']['currencyCode']}")
    
    # Transactions
    print(f"\n💳 TRANSACTIONS:")
    transactions = order_data.get('transactions', [])
    for i, transaction in enumerate(transactions, 1):
        print(f"   {i}. {transaction.get('kind', 'Unknown')} - {transaction.get('status', 'Unknown')}")
        print(f"      Gateway: {transaction.get('gateway', 'Unknown')}")
        print(f"      Amount: {transaction.get('amountSet', {}).get('shopMoney', {}).get('amount', 'Unknown')}")
        print(f"      ID: {transaction.get('id', 'Unknown')}")
        
        # Payment details (simplified)
        print(f"      Gateway: {transaction.get('gateway', 'Unknown')}")
        print(f"      Test: {transaction.get('test', 'Unknown')}")
    
    # Note
    if order_data.get('note'):
        print(f"\n📝 NOTE:")
        print(f"   {order_data['note']}")
    
    print("\n" + "="*80)


async def main():
    """
    Main function to test order data retrieval
    """
    order_id = "6338569175106"
    
    print(f"🔍 Retrieving data for order: {order_id}")
    print("="*60)
    
    try:
        # First, let's see what recent orders are available
        print("\n📋 Checking recent orders in the store...")
        stores_config = config_settings.shopify_stores
        
        for store_key, store_config in stores_config.items():
            print(f"\n🏪 Store: {store_key} ({store_config.name})")
            recent_orders = await get_recent_orders(store_key, 5)
            
            if recent_orders["msg"] == "success":
                print("   Recent orders:")
                for order_edge in recent_orders["orders"]:
                    order = order_edge["node"]
                    print(f"   - {order['name']} | {order['displayFinancialStatus']} | {order['createdAt']}")
            else:
                print(f"   Error: {recent_orders.get('error')}")
        
        # Now try to get the specific order
        print(f"\n🔍 Now trying to get specific order: {order_id}")
        result = await get_order_data_direct(order_id)
        
        if result["msg"] == "success":
            order_data = result["order_data"]
            store_key = result["store_key"]
            
            display_order_data(order_data, store_key)
            
        else:
            print(f"❌ Failed to retrieve order data by ID: {result.get('error')}")
            
            # Try getting by order name (#1533)
            print(f"\n🔍 Trying to get order by name: #1533")
            for store_key, store_config in stores_config.items():
                try:
                    result_by_name = await get_order_by_name(store_key, "#1533")
                    if result_by_name["msg"] == "success":
                        print(f"✅ Found order #1533 in store: {store_key}")
                        display_order_data(result_by_name["order_data"], store_key)
                        break
                    else:
                        print(f"❌ Order #1533 not found in store: {store_key}")
                except Exception as e:
                    print(f"❌ Error searching store {store_key}: {str(e)}")
                    continue
            
    except Exception as e:
        print(f"❌ Exception occurred: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
