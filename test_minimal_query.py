"""
Test with a minimal query to identify the issue
"""

import asyncio
import sys
import os

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.core.config import config_settings
from app.utils.logging import logger


async def test_minimal_query():
    """
    Test with a minimal query to identify the issue
    """
    print("🔄 Testing Minimal Query")
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
            
            # Minimal query
            minimal_query = """
            query getOrders($first: Int!) {
                orders(first: $first, sortKey: CREATED_AT, reverse: true) {
                    edges {
                        node {
                            id
                            name
                            createdAt
                        }
                    }
                }
            }
            """
            
            print("Testing minimal query...")
            result = await multi_store_shopify_client.execute_query(
                store_key,
                minimal_query,
                {"first": 1}
            )
            
            if result["msg"] == "success":
                print("✅ Minimal query works!")
                orders = result["data"]["orders"]["edges"]
                print(f"   Found {len(orders)} orders")
                for order in orders:
                    order_node = order["node"]
                    print(f"   - {order_node['name']}: {order_node['id']}")
            else:
                print(f"❌ Minimal query failed: {result.get('error')}")
                return
            
            # Test with financial status
            financial_query = """
            query getOrders($first: Int!) {
                orders(first: $first, sortKey: CREATED_AT, reverse: true) {
                    edges {
                        node {
                            id
                            name
                            createdAt
                            financialStatus
                            fulfillmentStatus
                        }
                    }
                }
            }
            """
            
            print("Testing with financial status...")
            result = await multi_store_shopify_client.execute_query(
                store_key,
                financial_query,
                {"first": 1}
            )
            
            if result["msg"] == "success":
                print("✅ Financial status works!")
            else:
                print(f"❌ Financial status failed: {result.get('error')}")
                return
                
    except Exception as e:
        print(f"\n❌ Exception occurred: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_minimal_query())
