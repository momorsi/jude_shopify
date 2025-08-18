"""
Test script to isolate metafields GraphQL query issue
"""

import asyncio
import sys
import os
from typing import Dict, Any

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.core.config import config_settings
from app.utils.logging import logger


async def test_basic_query():
    """Test basic query without metafields"""
    try:
        query = """
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
        
        variables = {"first": 5}
        result = await multi_store_shopify_client.execute_query("local", query, variables)
        
        if result["msg"] == "success":
            logger.info("Basic query successful")
            logger.info(f"Found {len(result['data']['orders']['edges'])} orders")
            return True
        else:
            logger.error(f"Basic query failed: {result.get('error', 'Unknown error')}")
            return False
        
    except Exception as e:
        logger.error(f"Basic query failed: {e}")
        return False


async def test_metafields_query():
    """Test query with metafields"""
    try:
        query = """
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
        
        variables = {"first": 5}
        result = await multi_store_shopify_client.execute_query("local", query, variables)
        
        if result["msg"] == "success":
            logger.info("Metafields query successful")
            logger.info(f"Found {len(result['data']['orders']['edges'])} orders")
            return True
        else:
            logger.error(f"Metafields query failed: {result.get('error', 'Unknown error')}")
            return False
        
    except Exception as e:
        logger.error(f"Metafields query failed: {e}")
        return False


async def test_shipping_price_query():
    """Test query with shipping price"""
    try:
        query = """
        query getOrders($first: Int!) {
            orders(first: $first, sortKey: CREATED_AT, reverse: true) {
                edges {
                    node {
                        id
                        name
                        createdAt
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
        
        variables = {"first": 5}
        result = await multi_store_shopify_client.execute_query("local", query, variables)
        
        if result["msg"] == "success":
            logger.info("Shipping price query successful")
            logger.info(f"Found {len(result['data']['orders']['edges'])} orders")
            return True
        else:
            logger.error(f"Shipping price query failed: {result.get('error', 'Unknown error')}")
            return False
        
    except Exception as e:
        logger.error(f"Shipping price query failed: {e}")
        return False


async def main():
    logger.info("Testing GraphQL queries to isolate the issue...")
    
    # Test 1: Basic query
    logger.info("\n=== Test 1: Basic Query ===")
    basic_success = await test_basic_query()
    
    # Test 2: Metafields query
    logger.info("\n=== Test 2: Metafields Query ===")
    metafields_success = await test_metafields_query()
    
    # Test 3: Shipping price query
    logger.info("\n=== Test 3: Shipping Price Query ===")
    shipping_success = await test_shipping_price_query()
    
    # Summary
    logger.info("\n=== Summary ===")
    logger.info(f"Basic query: {'✓' if basic_success else '✗'}")
    logger.info(f"Metafields query: {'✓' if metafields_success else '✗'}")
    logger.info(f"Shipping price query: {'✓' if shipping_success else '✗'}")


if __name__ == "__main__":
    asyncio.run(main())
