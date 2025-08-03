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
from typing import Dict, Any, Optional, List

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
            if hasattr(e, 'data'):
                error_msg += f"\nGraphQL Data: {json.dumps(e.data, indent=2)}"
            if hasattr(e, 'extensions'):
                error_msg += f"\nGraphQL Extensions: {json.dumps(e.extensions, indent=2)}"
            logger.error(error_msg)
            
            # Log the detailed error to SAP
            try:
                from app.services.sap.api_logger import sl_add_log
                await sl_add_log(
                    server="shopify",
                    endpoint=f"/admin/api/graphql_{store_key}",
                    response_data={
                        "error": error_msg, 
                        "graphql_errors": e.errors if hasattr(e, 'errors') else None,
                        "graphql_data": e.data if hasattr(e, 'data') else None,
                        "graphql_extensions": e.extensions if hasattr(e, 'extensions') else None,
                        "full_exception": str(e)
                    },
                    status="failure",
                    action="graphql_error",
                    value=f"GraphQL error for store {store_key}: {str(e)}"
                )
            except:
                pass
                
            return {"msg": "failure", "error": error_msg}
        except Exception as e:
            error_msg = f"GraphQL query error for store {store_key}: {str(e)}"
            logger.error(error_msg)
            
            # Log the detailed error to SAP
            try:
                from app.services.sap.api_logger import sl_add_log
                await sl_add_log(
                    server="shopify",
                    endpoint=f"/admin/api/graphql_{store_key}",
                    response_data={
                        "error": error_msg,
                        "exception_type": type(e).__name__,
                        "full_exception": str(e)
                    },
                    status="failure",
                    action="graphql_error",
                    value=f"GraphQL error for store {store_key}: {str(e)}"
                )
            except:
                pass
                
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
        Update inventory levels for a specific store using GraphQL
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
    
    async def update_inventory_level(self, store_key: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update inventory levels for a specific store using REST API
        More direct and reliable for inventory updates
        """
        if store_key not in self.clients:
            return {"msg": "failure", "error": f"Store {store_key} not found or not enabled"}
        
        try:
            store_config = config_settings.get_store_by_name(store_key)
            if not store_config:
                return {"msg": "failure", "error": f"Store configuration not found for {store_key}"}
            
            import httpx
            
            # Build REST API URL
            url = f"https://{store_config.shop_url}/admin/api/{store_config.api_version}/inventory_levels/set.json"
            
            # Prepare headers
            headers = {
                'X-Shopify-Access-Token': store_config.access_token,
                'Content-Type': 'application/json',
            }
            
            # Prepare request data
            request_data = {
                "location_id": update_data["location_id"],
                "inventory_item_id": update_data["inventory_item_id"],
                "available": update_data["available"]
            }
            
            # Log the request
            log_api_call(
                service="shopify",
                endpoint=f"rest_inventory_{store_key}",
                request_data=request_data
            )
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=request_data, headers=headers)
                
                if response.status_code == 200:
                    response_data = response.json()
                    
                    # Log the response
                    log_api_call(
                        service="shopify",
                        endpoint=f"rest_inventory_{store_key}",
                        response_data=response_data,
                        status="success"
                    )
                    
                    return {"msg": "success", "data": response_data}
                else:
                    error_msg = f"HTTP {response.status_code}: {response.text}"
                    
                    # Log the error
                    log_api_call(
                        service="shopify",
                        endpoint=f"rest_inventory_{store_key}",
                        response_data={"error": error_msg},
                        status="failure"
                    )
                    
                    return {"msg": "failure", "error": error_msg}
                    
        except Exception as e:
            error_msg = f"Error updating inventory level for store {store_key}: {str(e)}"
            logger.error(error_msg)
            return {"msg": "failure", "error": error_msg}
    
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
    
    async def get_product_by_handle(self, store_key: str, handle: str) -> Dict[str, Any]:
        """
        Get product by handle from a specific store
        """
        query = """
        query GetProductByHandle($handle: String!) {
            productByHandle(handle: $handle) {
                id
                title
                handle
                description
                variants(first: 50) {
                    edges {
                        node {
                            id
                            sku
                            price
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
        }
        """
        
        return await self.execute_query(store_key, query, {"handle": handle})
    
    async def get_product_by_id(self, store_key: str, product_id: str) -> Dict[str, Any]:
        """
        Get product by ID from a specific store
        """
        query = """
        query GetProduct($id: ID!) {
            product(id: $id) {
                id
                title
                handle
                description
                variants(first: 50) {
                    edges {
                        node {
                            id
                            sku
                            price
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
        }
        """
        
        return await self.execute_query(store_key, query, {"id": product_id})
    
    async def add_variant_to_product(self, store_key: str, product_id: str, variant_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add a variant to an existing product
        """
        mutation = """
        mutation productVariantCreate($input: ProductVariantInput!) {
            productVariantCreate(input: $input) {
                productVariant {
                    id
                    sku
                    price
                    inventoryItem {
                        id
                    }
                    selectedOptions {
                        name
                        value
                    }
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """
        
        # Add the product ID to the variant data
        variant_data["productId"] = product_id
        
        return await self.execute_query(store_key, mutation, {"input": variant_data})
    
    async def update_product_options(self, store_key: str, product_id: str, options: List[str]) -> Dict[str, Any]:
        """
        Update product options (like adding Color option)
        """
        mutation = """
        mutation productUpdate($input: ProductInput!) {
            productUpdate(input: $input) {
                product {
                    id
                    title
                    options {
                        id
                        name
                        values
                    }
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
                "id": product_id,
                "options": options
            }
        }
        
        return await self.execute_query(store_key, mutation, variables)
    
    async def update_variant(self, store_key: str, variant_id: str, variant_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update a variant (e.g., to set the title/option1)
        """
        mutation = """
        mutation productVariantUpdate($input: ProductVariantInput!) {
            productVariantUpdate(input: $input) {
                productVariant {
                    id
                    sku
                    title
                    selectedOptions {
                        name
                        value
                    }
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """
        
        # Add the variant ID to the data
        variant_data["id"] = variant_id
        
        return await self.execute_query(store_key, mutation, {"input": variant_data})
    
    async def update_product(self, store_key: str, product_id: str, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update a product in Shopify
        """
        mutation = """
        mutation productUpdate($input: ProductInput!) {
            productUpdate(input: $input) {
                product {
                    id
                    title
                    status
                    vendor
                    descriptionHtml
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """
        
        # Add the product ID to the data
        product_data["id"] = product_id
        
        return await self.execute_query(store_key, mutation, {"input": product_data})
    
    async def get_variant_by_id(self, store_key: str, variant_id: str) -> Dict[str, Any]:
        """
        Get variant by ID from a specific store
        """
        query = """
        query GetVariant($id: ID!) {
            productVariant(id: $id) {
                id
                sku
                price
                product {
                    id
                    title
                    status
                }
                selectedOptions {
                    name
                    value
                }
            }
        }
        """
        
        return await self.execute_query(store_key, query, {"id": variant_id})
    
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

# Create singleton instance
multi_store_shopify_client = MultiStoreShopifyClient() 