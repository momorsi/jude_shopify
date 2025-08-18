"""
Simple test to check GraphQL query structure
"""

import asyncio
import sys
import os

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.core.config import config_settings
from app.utils.logging import logger


async def test_graphql_query():
    """
    Test the GraphQL query structure
    """
    print("🔄 Testing GraphQL Query Structure")
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
            
            # Simple query without metafields first
            simple_query = """
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
                        }
                    }
                }
            }
            """
            
            print("Testing simple query...")
            result = await multi_store_shopify_client.execute_query(
                store_key,
                simple_query,
                {"first": 2}
            )
            
            if result["msg"] == "success":
                print("✅ Simple query works!")
                orders = result["data"]["orders"]["edges"]
                print(f"   Found {len(orders)} orders")
                for order in orders:
                    order_node = order["node"]
                    print(f"   - {order_node['name']}: {order_node['totalPriceSet']['shopMoney']['amount']} {order_node['totalPriceSet']['shopMoney']['currencyCode']}")
            else:
                print(f"❌ Simple query failed: {result.get('error')}")
                return
            
            # Now test with metafields
            metafields_query = """
            query getOrdersWithMetafields($first: Int!) {
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
            
            print("\nTesting metafields query...")
            result = await multi_store_shopify_client.execute_query(
                store_key,
                metafields_query,
                {"first": 2}
            )
            
            if result["msg"] == "success":
                print("✅ Metafields query works!")
                orders = result["data"]["orders"]["edges"]
                print(f"   Found {len(orders)} orders")
                for order in orders:
                    order_node = order["node"]
                    metafields = order_node.get("metafields", {}).get("edges", [])
                    print(f"   - {order_node['name']}: {len(metafields)} metafields")
                    for metafield_edge in metafields:
                        metafield = metafield_edge["node"]
                        print(f"     * {metafield['namespace']}.{metafield['key']} = {metafield['value']}")
            else:
                print(f"❌ Metafields query failed: {result.get('error')}")
                return
                
    except Exception as e:
        print(f"\n❌ Exception occurred: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_graphql_query())
