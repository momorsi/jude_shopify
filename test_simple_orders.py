"""
Simple test to check if we can get orders from Shopify
"""

import asyncio
import sys
import os

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.core.config import config_settings
from app.utils.logging import logger


async def test_simple_orders():
    """
    Simple test to get orders from Shopify
    """
    print("🔄 Testing Simple Orders Query")
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
            
            # Simple query to get orders
            query = """
            query getOrders($first: Int!) {
                orders(first: $first, sortKey: CREATED_AT, reverse: true) {
                    edges {
                        node {
                            id
                            name
                            createdAt
                            tags
                        }
                    }
                }
            }
            """
            
            result = await multi_store_shopify_client.execute_query(
                store_key,
                query,
                {"first": 5}
            )
            
            if result["msg"] == "success":
                orders = result["data"]["orders"]["edges"]
                print(f"✅ Successfully retrieved {len(orders)} orders")
                
                for order in orders:
                    order_node = order["node"]
                    tags = order_node.get("tags", [])
                    has_synced = "synced" in tags
                    print(f"   Order: {order_node['name']} | Tags: {tags} | Synced: {has_synced}")
            else:
                print(f"❌ Failed to get orders: {result.get('error')}")
                
    except Exception as e:
        print(f"\n❌ Exception occurred: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_simple_orders())
