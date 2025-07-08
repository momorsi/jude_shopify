"""
Multi-Store Shopify Client
Handles multiple Shopify stores with different configurations
"""

from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport
from app.core.config import config_settings
from app.utils.logging import logger, log_api_call
import json
from gql.transport.exceptions import TransportQueryError
from typing import Dict, Any, Optional

class MultiStoreShopifyClient:
    def __init__(self):
        self.clients: Dict[str, Client] = {}
        self._initialize_clients()
    
    def _initialize_clients(self):
        """Initialize GraphQL clients for all enabled stores"""
        enabled_stores = config_settings.get_enabled_stores()
        
        for store_key, store_config in enabled_stores.items():
            try:
                transport = AIOHTTPTransport(
                    url=f"https://{store_config.shop_url}/admin/api/{store_config.api_version}/graphql.json",
                    headers={
                        'X-Shopify-Access-Token': store_config.access_token,
                        'Content-Type': 'application/json',
                    }
                )
                
                client = Client(transport=transport, fetch_schema_from_transport=False)
                self.clients[store_key] = client
                
                logger.info(f"Initialized Shopify client for store: {store_config.name} ({store_key})")
                
            except Exception as e:
                logger.error(f"Failed to initialize client for store {store_key}: {str(e)}")
    
    async def execute_query(self, store_key: str, query: str, variables: dict = None) -> Dict[str, Any]:
        """
        Execute a GraphQL query for a specific store
        """
        if store_key not in self.clients:
            return {"msg": "failure", "error": f"Store {store_key} not found or not enabled"}
        
        try:
            # Log the request
            log_api_call(
                service="shopify",
                endpoint=f"graphql_{store_key}",
                request_data={"query": query, "variables": variables}
            )

            # Execute the query
            result = await self.clients[store_key].execute_async(
                gql(query),
                variable_values=variables
            )

            # Log the response
            log_api_call(
                service="shopify",
                endpoint=f"graphql_{store_key}",
                response_data=result,
                status="success"
            )

            return {"msg": "success", "data": result}

        except TransportQueryError as e:
            error_msg = f"GraphQL query error for store {store_key}: {str(e)}"
            if hasattr(e, 'errors'):
                error_msg += f"\nGraphQL Errors: {json.dumps(e.errors, indent=2)}"
            logger.error(error_msg)
            return {"msg": "failure", "error": error_msg}
        except Exception as e:
            error_msg = f"GraphQL query error for store {store_key}: {str(e)}"
            logger.error(error_msg)
            return {"msg": "failure", "error": error_msg}
    
    async def create_product(self, store_key: str, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create product in a specific store
        Enhanced to return all variants for proper SAP mapping
        """
        mutation = """
        mutation productCreate($input: ProductInput!) {
            productCreate(input: $input) {
                product {
                    id
                    title
                    handle
                    variants(first: 50) {
                        edges {
                            node {
                                id
                                sku
                                inventoryItem {
                                    id
                                }
                                selectedOptions {
                                    name
                                    value
                                }
                            }
                        }
                    }
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """
        
        return await self.execute_query(store_key, mutation, {"input": product_data})
    
    async def update_inventory(self, store_key: str, inventory_item_id: str, available: int) -> Dict[str, Any]:
        """
        Update inventory levels for a specific store
        """
        mutation = """
        mutation inventoryAdjustQuantity($input: InventoryAdjustQuantityInput!) {
            inventoryAdjustQuantity(input: $input) {
                inventoryLevel {
                    available
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """
        
        variables = {
            "input": {
                "inventoryItemId": inventory_item_id,
                "availableDelta": available
            }
        }
        
        return await self.execute_query(store_key, mutation, variables)
    
    async def get_products(self, store_key: str, first: int = 10, after: str = None) -> Dict[str, Any]:
        """
        Get products from a specific store
        """
        query = """
        query GetProducts($first: Int!, $after: String) {
            products(first: $first, after: $after) {
                pageInfo {
                    hasNextPage
                    endCursor
                }
                edges {
                    node {
                        id
                        title
                        handle
                        description
                        variants(first: 1) {
                            edges {
                                node {
                                    id
                                    sku
                                    price
                                    inventoryQuantity
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        
        variables = {
            "first": first,
            "after": after
        }
        
        return await self.execute_query(store_key, query, variables)
    
    async def get_locations(self, store_key: str) -> Dict[str, Any]:
        """
        Get locations from a specific store
        """
        query = """
        query {
            locations(first: 10) {
                edges {
                    node {
                        id
                        name
                        address {
                            address1
                            city
                            country
                        }
                        isActive
                    }
                }
            }
        }
        """
        
        return await self.execute_query(store_key, query)
    
    def get_store_config(self, store_key: str) -> Optional[Any]:
        """
        Get store configuration
        """
        return config_settings.get_store_by_name(store_key)
    
    def get_enabled_stores(self) -> Dict[str, Any]:
        """
        Get all enabled stores
        """
        return config_settings.get_enabled_stores()
    
    async def execute_for_all_stores(self, operation_name: str, operation_func) -> Dict[str, Any]:
        """
        Execute an operation for all enabled stores
        """
        results = {}
        enabled_stores = self.get_enabled_stores()
        
        for store_key in enabled_stores.keys():
            try:
                result = await operation_func(store_key)
                results[store_key] = result
            except Exception as e:
                logger.error(f"Error executing {operation_name} for store {store_key}: {str(e)}")
                results[store_key] = {"msg": "failure", "error": str(e)}
        
        return results

# Create singleton instance
multi_store_shopify_client = MultiStoreShopifyClient() 