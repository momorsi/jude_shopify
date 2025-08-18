"""
Test to identify which field is causing the GraphQL query error
"""

import asyncio
import sys
import os

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.core.config import config_settings
from app.utils.logging import logger


async def test_query_debug():
    """
    Test to identify which field is causing the GraphQL query error
    """
    print("🔄 Testing Query Fields to Identify Issue")
    print("="*60)
    
    try:
        # Get enabled stores
        enabled_stores = config_settings.get_enabled_stores()
        if not enabled_stores:
            print("❌ No enabled stores found")
            return
        
        print(f"Found {len(enabled_stores)} enabled stores")
        
        for store_key, store_config in enabled_stores.items():
            print(f"\n🏪 Testing store: {store_key}")
            
            # Test basic fields first
            basic_query = """
            query getOrders($first: Int!) {
                orders(first: $first, sortKey: CREATED_AT, reverse: true) {
                    edges {
                        node {
                            id
                            name
                            createdAt
                            displayFinancialStatus
                            displayFulfillmentStatus
                            sourceName
                            sourceIdentifier
                        }
                    }
                }
            }
            """
            
            print("Testing basic fields...")
            result = await multi_store_shopify_client.execute_query(
                store_key,
                basic_query,
                {"first": 1}
            )
            
            if result["msg"] == "success":
                print("✅ Basic fields work!")
            else:
                print(f"❌ Basic fields failed: {result.get('error')}")
                return
            
            # Test with metafields
            metafields_query = """
            query getOrders($first: Int!) {
                orders(first: $first, sortKey: CREATED_AT, reverse: true) {
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
                        }
                    }
                }
            }
            """
            
            print("Testing with metafields...")
            result = await multi_store_shopify_client.execute_query(
                store_key,
                metafields_query,
                {"first": 1}
            )
            
            if result["msg"] == "success":
                print("✅ Metafields work!")
            else:
                print(f"❌ Metafields failed: {result.get('error')}")
                return
            
            # Test with price fields
            price_query = """
            query getOrders($first: Int!) {
                orders(first: $first, sortKey: CREATED_AT, reverse: true) {
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
                            totalShippingPriceSet {
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
            
            print("Testing with price fields...")
            result = await multi_store_shopify_client.execute_query(
                store_key,
                price_query,
                {"first": 1}
            )
            
            if result["msg"] == "success":
                print("✅ Price fields work!")
            else:
                print(f"❌ Price fields failed: {result.get('error')}")
                return
            
            # Test with customer fields
            customer_query = """
            query getOrders($first: Int!) {
                orders(first: $first, sortKey: CREATED_AT, reverse: true) {
                    edges {
                        node {
                            id
                            name
                            createdAt
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
                        }
                    }
                }
            }
            """
            
            print("Testing with customer fields...")
            result = await multi_store_shopify_client.execute_query(
                store_key,
                customer_query,
                {"first": 1}
            )
            
            if result["msg"] == "success":
                print("✅ Customer fields work!")
            else:
                print(f"❌ Customer fields failed: {result.get('error')}")
                return
            
            # Test with address fields
            address_query = """
            query getOrders($first: Int!) {
                orders(first: $first, sortKey: CREATED_AT, reverse: true) {
                    edges {
                        node {
                            id
                            name
                            createdAt
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
                        }
                    }
                }
            }
            """
            
            print("Testing with address fields...")
            result = await multi_store_shopify_client.execute_query(
                store_key,
                address_query,
                {"first": 1}
            )
            
            if result["msg"] == "success":
                print("✅ Address fields work!")
            else:
                print(f"❌ Address fields failed: {result.get('error')}")
                return
            
            # Test with line items
            line_items_query = """
            query getOrders($first: Int!) {
                orders(first: $first, sortKey: CREATED_AT, reverse: true) {
                    edges {
                        node {
                            id
                            name
                            createdAt
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
                        }
                    }
                }
            }
            """
            
            print("Testing with line items...")
            result = await multi_store_shopify_client.execute_query(
                store_key,
                line_items_query,
                {"first": 1}
            )
            
            if result["msg"] == "success":
                print("✅ Line items work!")
            else:
                print(f"❌ Line items failed: {result.get('error')}")
                return
            
            # Test with transactions
            transactions_query = """
            query getOrders($first: Int!) {
                orders(first: $first, sortKey: CREATED_AT, reverse: true) {
                    edges {
                        node {
                            id
                            name
                            createdAt
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
                }
            }
            """
            
            print("Testing with transactions...")
            result = await multi_store_shopify_client.execute_query(
                store_key,
                transactions_query,
                {"first": 1}
            )
            
            if result["msg"] == "success":
                print("✅ Transactions work!")
            else:
                print(f"❌ Transactions failed: {result.get('error')}")
                return
                
    except Exception as e:
        print(f"\n❌ Exception occurred: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_query_debug())
