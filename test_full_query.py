"""
Test with the exact query from orders sync
"""

import asyncio
import sys
import os

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.core.config import config_settings
from app.utils.logging import logger


async def test_full_query():
    """
    Test with the exact query from orders sync
    """
    print("🔄 Testing Full Query from Orders Sync")
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
            
            # Exact query from orders sync
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
            
            print("Testing full query...")
            result = await multi_store_shopify_client.execute_query(
                store_key,
                query,
                {"first": 2, "after": None}
            )
            
            if result["msg"] == "success":
                print("✅ Full query works!")
                orders = result["data"]["orders"]["edges"]
                print(f"   Found {len(orders)} orders")
                for order in orders:
                    order_node = order["node"]
                    metafields = order_node.get("metafields", {}).get("edges", [])
                    shipping_price = order_node.get("totalShippingPriceSet", {}).get("shopMoney", {}).get("amount", "0")
                    print(f"   - {order_node['name']}: {len(metafields)} metafields, shipping: {shipping_price}")
            else:
                print(f"❌ Full query failed: {result.get('error')}")
                return
                
    except Exception as e:
        print(f"\n❌ Exception occurred: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_full_query())
