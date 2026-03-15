"""
Multi-Store Shopify Client
Handles multiple Shopify stores with different configurations.
Uses OAuth client credentials grant for token management (tokens expire every 24 hours).
"""

from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport
from app.core.config import config_settings
from app.utils.logging import logger, log_api_call
from app.utils.ssl_cert import get_ssl_context, get_cert_path

import json
import asyncio
import time
import httpx
from gql.transport.exceptions import TransportQueryError
from typing import Dict, Any, Optional, List


class ShopifyTokenManager:
    """
    Manages OAuth access tokens for Shopify stores using the client credentials grant.
    Tokens expire after 24 hours and are automatically refreshed with a safety margin.
    """

    TOKEN_REFRESH_MARGIN = 3600  # Refresh 1 hour before actual expiry

    def __init__(self):
        self._tokens: Dict[str, str] = {}
        self._expiry_times: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _is_token_valid(self, store_key: str) -> bool:
        if store_key not in self._tokens or store_key not in self._expiry_times:
            return False
        return time.time() < (self._expiry_times[store_key] - self.TOKEN_REFRESH_MARGIN)

    async def get_access_token(self, store_key: str) -> str:
        """Get a valid access token for the store, refreshing if needed."""
        if self._is_token_valid(store_key):
            return self._tokens[store_key]

        async with self._lock:
            # Double-check after acquiring lock (another coroutine may have refreshed)
            if self._is_token_valid(store_key):
                return self._tokens[store_key]
            return await self._fetch_token(store_key)

    async def _fetch_token(self, store_key: str) -> str:
        """Exchange client credentials for an access token."""
        store_config = config_settings.get_store_by_name(store_key)
        if not store_config:
            raise ValueError(f"Store configuration not found for {store_key}")

        url = f"https://{store_config.shop_url}/admin/oauth/access_token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": store_config.client_id,
            "client_secret": store_config.client_secret,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0, verify=get_ssl_context()) as client:
                response = await client.post(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )

            if response.status_code == 200:
                data = response.json()
                access_token = data["access_token"]
                expires_in = data.get("expires_in", 86399)

                self._tokens[store_key] = access_token
                self._expiry_times[store_key] = time.time() + expires_in

                logger.info(
                    f"Shopify token obtained for store {store_key} "
                    f"(expires in {expires_in // 3600}h {(expires_in % 3600) // 60}m)"
                )
                return access_token
            else:
                error_msg = (
                    f"Failed to obtain Shopify token for {store_key}: "
                    f"HTTP {response.status_code} - {response.text}"
                )
                logger.error(error_msg)
                raise ConnectionError(error_msg)

        except httpx.HTTPError as e:
            error_msg = f"HTTP error fetching Shopify token for {store_key}: {str(e)}"
            logger.error(error_msg)
            raise ConnectionError(error_msg) from e

    def invalidate(self, store_key: str):
        """Force token refresh on next call (e.g. after a 401)."""
        self._tokens.pop(store_key, None)
        self._expiry_times.pop(store_key, None)


# Shared token manager instance
shopify_token_manager = ShopifyTokenManager()


class MultiStoreShopifyClient:
    def __init__(self):
        self.clients: Dict[str, Client] = {}
        self._client_tokens: Dict[str, str] = {}
        self.token_manager = shopify_token_manager
        self._enabled_store_keys: List[str] = []
        self._initialize_store_keys()

    def _initialize_store_keys(self):
        """Record enabled store keys. GQL clients are created lazily on first query."""
        enabled_stores = config_settings.get_enabled_stores()
        self._enabled_store_keys = list(enabled_stores.keys())
        for store_key in self._enabled_store_keys:
            logger.info(f"Registered Shopify store: {store_key}")

    def _build_gql_client(self, store_key: str, access_token: str) -> Client:
        """Build a GQL Client with the given access token."""
        store_config = config_settings.get_store_by_name(store_key)
        transport = AIOHTTPTransport(
            url=f"https://{store_config.shop_url}/admin/api/{store_config.api_version}/graphql.json",
            headers={
                'X-Shopify-Access-Token': access_token,
                'Content-Type': 'application/json',
            },
            timeout=store_config.timeout,
            ssl=get_ssl_context()
        )
        return Client(transport=transport, fetch_schema_from_transport=False)

    async def _get_client(self, store_key: str) -> Client:
        """Get a GQL client with a valid token, rebuilding if token was refreshed."""
        access_token = await self.token_manager.get_access_token(store_key)

        if self._client_tokens.get(store_key) != access_token:
            self.clients[store_key] = self._build_gql_client(store_key, access_token)
            self._client_tokens[store_key] = access_token
            logger.info(f"Rebuilt GQL client for store {store_key} with refreshed token")

        return self.clients[store_key]

    async def get_rest_headers(self, store_key: str) -> Dict[str, str]:
        """Get REST API headers with a valid access token."""
        access_token = await self.token_manager.get_access_token(store_key)
        return {
            'X-Shopify-Access-Token': access_token,
            'Content-Type': 'application/json',
        }

    async def execute_query(self, store_key: str, query: str, variables: dict = None) -> Dict[str, Any]:
        """
        Execute a GraphQL query for a specific store.
        Automatically handles token refresh and GQL client rebuild.
        """
        if store_key not in self._enabled_store_keys:
            return {"msg": "failure", "error": f"Store {store_key} not found or not enabled"}

        try:
            client = await self._get_client(store_key)

            logger.info(f"Executing GraphQL query for store: {store_key}")
            log_api_call(
                service="shopify",
                endpoint=f"graphql_{store_key}",
                request_data={"query": query, "variables": variables}
            )

            result = await client.execute_async(
                gql(query),
                variable_values=variables
            )

            log_api_call(
                service="shopify",
                endpoint=f"graphql_{store_key}",
                response_data=result,
                status="success"
            )

            return {"msg": "success", "data": result}

        except TransportQueryError as e:
            error_msg = f"GraphQL query error for store {store_key}"

            if str(e) and str(e).strip():
                error_msg += f": {str(e)}"

            if hasattr(e, 'errors') and e.errors:
                error_msg += f"\nGraphQL Errors: {json.dumps(e.errors, indent=2)}"
            if hasattr(e, 'data') and e.data:
                error_msg += f"\nGraphQL Data: {json.dumps(e.data, indent=2)}"
            if hasattr(e, 'extensions') and e.extensions:
                error_msg += f"\nGraphQL Extensions: {json.dumps(e.extensions, indent=2)}"

            logger.error(error_msg)

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
            error_str = str(e).lower()

            # If we get a 401/unauthorized, invalidate token and retry once
            if "401" in error_str or "unauthorized" in error_str:
                logger.warning(f"Shopify token expired for {store_key}, refreshing and retrying...")
                self.token_manager.invalidate(store_key)
                try:
                    client = await self._get_client(store_key)
                    result = await client.execute_async(
                        gql(query),
                        variable_values=variables
                    )
                    return {"msg": "success", "data": result}
                except Exception as retry_e:
                    error_msg = f"GraphQL retry failed for store {store_key}: {str(retry_e)}"
                    logger.error(error_msg)
                    return {"msg": "failure", "error": error_msg}

            error_msg = f"GraphQL query error for store {store_key}: {str(e)}"
            logger.error(error_msg)

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
        if store_key not in self._enabled_store_keys:
            return {"msg": "failure", "error": f"Store {store_key} not found or not enabled"}
        
        try:
            store_config = config_settings.get_store_by_name(store_key)
            if not store_config:
                return {"msg": "failure", "error": f"Store configuration not found for {store_key}"}
            
            url = f"https://{store_config.shop_url}/admin/api/{store_config.api_version}/inventory_levels/set.json"
            headers = await self.get_rest_headers(store_key)
            
            request_data = {
                "location_id": update_data["location_id"],
                "inventory_item_id": update_data["inventory_item_id"],
                "available": update_data["available"]
            }
            
            log_api_call(
                service="shopify",
                endpoint=f"rest_inventory_{store_key}",
                request_data=request_data
            )
            
            async with httpx.AsyncClient(timeout=store_config.timeout, verify=get_ssl_context()) as client:
                response = await client.post(url, json=request_data, headers=headers)
                
                if response.status_code == 200:
                    response_data = response.json()
                    
                    log_api_call(
                        service="shopify",
                        endpoint=f"rest_inventory_{store_key}",
                        response_data=response_data,
                        status="success"
                    )
                    
                    return {"msg": "success", "data": response_data}
                else:
                    error_msg = f"HTTP {response.status_code}: {response.text}"
                    
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
    
    async def get_inventory_level(self, store_key: str, inventory_item_id: str, location_id: str) -> Dict[str, Any]:
        """
        Get current inventory level including committed quantity for a specific location
        Includes retry logic for handling transient failures (timeouts, etc.)
        Returns: {"msg": "success", "available": int, "committed": int, "onHand": int} or error
        """
        if store_key not in self._enabled_store_keys:
            return {"msg": "failure", "error": f"Store {store_key} not found or not enabled"}
        
        # Convert IDs to global format if they're not already
        # Check if inventory_item_id is already in global format
        if not inventory_item_id.startswith("gid://shopify/InventoryItem/"):
            # Extract numeric ID if it's in a different format, or use as-is if it's just a number
            inventory_item_id = f"gid://shopify/InventoryItem/{inventory_item_id}"
        
        # Check if location_id is already in global format
        if not location_id.startswith("gid://shopify/Location/"):
            # Extract numeric ID if it's in a different format, or use as-is if it's just a number
            location_id = f"gid://shopify/Location/{location_id}"
        
        query = """
        query getInventoryLevel($inventoryItemId: ID!, $locationId: ID!) {
            inventoryItem(id: $inventoryItemId) {
                inventoryLevel(locationId: $locationId) {
                    id
                    quantities(names: ["available", "on_hand", "committed"]) {
                        name
                        quantity
                    }
                }
            }
        }
        """
        
        variables = {
            "inventoryItemId": inventory_item_id,
            "locationId": location_id
        }
        
        # Retry logic for GraphQL query (similar to other sync processes)
        max_retries = config_settings.retry_max_attempts
        retry_delay = config_settings.retry_delay  # Start with configured delay
        
        for attempt in range(max_retries):
            try:
                result = await self.execute_query(store_key, query, variables)
                
                if result["msg"] == "success":
                    data = result.get("data", {})
                    inventory_item = data.get("inventoryItem", {})
                    inventory_level = inventory_item.get("inventoryLevel")
                    
                    if inventory_level:
                        # Parse quantities array to extract values
                        quantities = inventory_level.get("quantities", [])
                        quantity_map = {}
                        for qty in quantities:
                            quantity_map[qty.get("name")] = qty.get("quantity", 0)
                        
                        return {
                            "msg": "success",
                            "available": quantity_map.get("available", 0),
                            "committed": quantity_map.get("committed", 0),
                            "onHand": quantity_map.get("on_hand", 0)
                        }
                    else:
                        return {"msg": "failure", "error": "Inventory level not found for this location"}
                else:
                    # Check if this is a retryable error
                    error_msg = result.get("error", "").lower() if result else "Unknown error"
                    logger.warning(f"GraphQL attempt {attempt + 1}/{max_retries} failed for inventory level query: {error_msg}")
                    
                    # Check if error is retryable (timeout, rate limit, network issues, etc.)
                    retryable_keywords = ["timeout", "rate limit", "temporary", "network", "connection", "graphql query error"]
                    is_retryable = any(keyword in error_msg for keyword in retryable_keywords)
                    
                    if is_retryable and attempt < max_retries - 1:
                        logger.info(f"Retrying in {retry_delay} seconds...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                    else:
                        # Non-retryable error or last attempt, return failure
                        return result
                        
            except Exception as e:
                logger.error(f"Exception on attempt {attempt + 1}/{max_retries}: {str(e)}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    return {"msg": "failure", "error": f"All {max_retries} attempts failed: {str(e)}"}
        
        return {"msg": "failure", "error": "All retry attempts failed"}
    
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
        # Validate handle parameter
        if not handle or not isinstance(handle, str) or handle.strip() == "":
            error_msg = f"Invalid handle provided for store {store_key}: '{handle}'"
            logger.error(error_msg)
            return {"msg": "failure", "error": error_msg}
        
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
                options {
                    id
                    name
                    values
                    optionValues {
                        id
                        name
                    }
                }
                variants(first: 50) {
                    edges {
                        node {
                            id
                            sku
                            price
                            barcode
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
    
    async def update_variant(self, store_key: str, variant_id: str, variant_data: Dict[str, Any], product_id: str = None) -> Dict[str, Any]:
        """
        Update a variant using the correct Shopify API 2025-07 approach
        Use productVariantsBulkUpdate for variant-specific updates
        """
        # If product_id not provided, get it from the variant (fallback for backward compatibility)
        if not product_id:
            variant_info = await self.get_variant_by_id(store_key, variant_id)
            if variant_info["msg"] == "failure":
                return variant_info
            product_id = variant_info["data"]["productVariant"]["product"]["id"]
        
        # Prepare the variant update data
        variant_update_data = {
            "id": variant_id
        }
        
        # Add price if provided
        if "price" in variant_data:
            variant_update_data["price"] = variant_data["price"]
        
        # Add compare price if provided
        if "compareAtPrice" in variant_data:
            variant_update_data["compareAtPrice"] = variant_data["compareAtPrice"]
        
        # Use productVariantsBulkUpdate directly (productUpdate doesn't support variants field)
        mutation = """
        mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
            productVariantsBulkUpdate(productId: $productId, variants: $variants) {
                productVariants {
                    id
                    sku
                    price
                    compareAtPrice
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
        
        update_data = {
            "productId": product_id,
            "variants": [variant_update_data]
        }
        
        return await self.execute_query(store_key, mutation, update_data)
    
    async def update_variant_direct(self, store_key: str, variant_id: str, variant_data: Dict[str, Any], product_id: str = None) -> Dict[str, Any]:
        """
        Update a variant directly using productVariantsBulkUpdate - no lookups needed
        """
        # If product_id not provided, extract it from variant_id
        if not product_id:
            variant_parts = variant_id.split('/')
            if len(variant_parts) >= 2:
                variant_number = variant_parts[-1]
                product_id = f"gid://shopify/Product/{variant_number}"
            else:
                return {"msg": "failure", "error": f"Invalid variant ID format: {variant_id}"}
        
        # Prepare the variant update data
        variant_update_data = {
            "id": variant_id
        }
        
        # Add price if provided
        if "price" in variant_data:
            variant_update_data["price"] = variant_data["price"]
        
        # Add compare price if provided
        if "compareAtPrice" in variant_data:
            variant_update_data["compareAtPrice"] = variant_data["compareAtPrice"]
        
        # Use productVariantsBulkUpdate directly - this is the correct approach
        mutation = """
        mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
            productVariantsBulkUpdate(productId: $productId, variants: $variants) {
                productVariants {
                    id
                    sku
                    price
                    compareAtPrice
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
        
        update_data = {
            "productId": product_id,
            "variants": [variant_update_data]
        }
        
        return await self.execute_query(store_key, mutation, update_data)
    
    async def update_product(self, store_key: str, product_id: str, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update a product in Shopify (product-level fields only)
        """
        # Simple mutation for product-only updates
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
    
    async def update_variant_comprehensive(self, store_key: str, variant_id: str, variant_data: Dict[str, Any], product_id: str = None) -> Dict[str, Any]:
        """
        Update a variant comprehensively using the new Shopify API 2025-07 approach
        """
        # If product_id not provided, get it from the variant (fallback for backward compatibility)
        if not product_id:
            variant_info = await self.get_variant_by_id(store_key, variant_id)
            if variant_info["msg"] == "failure":
                return variant_info
            product_id = variant_info["data"]["productVariant"]["product"]["id"]
        
        # Get the current product to update the specific variant
        product_info = await self.get_product_by_id(store_key, product_id)
        if product_info["msg"] == "failure":
            return product_info
        
        product = product_info["data"]["product"]
        variants = product["variants"]["edges"]
        
        # Find and update the specific variant
        updated_variants = []
        for variant_edge in variants:
            variant = variant_edge["node"]
            if variant["id"] == variant_id:
                # Update this variant with new data
                updated_variant = {
                    "id": variant["id"],
                    "sku": variant["sku"],
                    "price": variant["price"],
                    "title": variant_data.get("title", variant.get("title", "")),
                    "barcode": variant_data.get("barcode", variant.get("barcode", ""))
                }
                
                # Add compare price if provided
                if "compareAtPrice" in variant_data:
                    updated_variant["compareAtPrice"] = variant_data["compareAtPrice"]
                
                updated_variants.append(updated_variant)
            else:
                # Keep other variants unchanged
                updated_variant = {
                    "id": variant["id"],
                    "sku": variant["sku"],
                    "price": variant["price"],
                    "title": variant.get("title", ""),
                    "barcode": variant.get("barcode", "")
                }
                updated_variants.append(updated_variant)
        
        # Use productVariantsBulkUpdate to update the variants (productUpdate doesn't support variants field)
        mutation = """
        mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
            productVariantsBulkUpdate(productId: $productId, variants: $variants) {
                productVariants {
                    id
                    sku
                    price
                    compareAtPrice
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
        
        update_data = {
            "productId": product_id,
            "variants": updated_variants
        }
        
        return await self.execute_query(store_key, mutation, update_data)
    
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
                compareAtPrice
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
    
    async def create_product_with_options(self, store_key: str, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create product with options using the new Shopify API 2025-07 approach
        This is step 1: Create the product with productOptions
        """
        mutation = """
        mutation productCreate($input: ProductInput!) {
            productCreate(input: $input) {
                product {
                    id
                    title
                    status
                    options {
                        id
                        name
                        position
                        optionValues {
                            id
                            name
                            hasVariants
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
    
    async def create_product_variants_bulk(self, store_key: str, product_id: str, variants: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Create product variants in bulk using the new Shopify API 2025-07 approach
        This is step 2: Add variants to the product using productVariantsBulkCreate
        """
        mutation = """
        mutation productVariantsBulkCreate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
            productVariantsBulkCreate(productId: $productId, variants: $variants, strategy: REMOVE_STANDALONE_VARIANT) {
                productVariants {
                    id
                    title
                    sku
                    price
                    selectedOptions {
                        name
                        value
                    }
                    inventoryItem {
                        id
                        sku
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
            "productId": product_id,
            "variants": variants
        }
        
        return await self.execute_query(store_key, mutation, variables)
    
    async def create_product_option(self, store_key: str, product_id: str, option_name: str) -> Dict[str, Any]:
        """
        Create a product option for an existing product
        """
        mutation = """
        mutation productOptionCreate($input: ProductOptionInput!) {
            productOptionCreate(input: $input) {
                productOption {
                    id
                    name
                    position
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
                "productId": product_id,
                "name": option_name
            }
        }
        
        try:
            result = await self.execute_query(store_key, mutation, variables)
            
            if result["msg"] == "failure":
                return result
            
            response_data = result["data"]["productOptionCreate"]
            if response_data.get("userErrors"):
                errors = [error["message"] for error in response_data["userErrors"]]
                error_msg = "; ".join(errors)
                return {"msg": "failure", "error": error_msg}
            
            product_option = response_data["productOption"]
            return {
                "msg": "success",
                "option_id": product_option["id"],
                "option_name": product_option["name"]
            }
            
        except Exception as e:
            return {"msg": "failure", "error": str(e)}
    
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
    
    async def add_order_tag(self, store_key: str, order_id: str, tag: str) -> Dict[str, Any]:
        """
        Add a tag to an order (appends to existing tags)
        """
        # First, get the current order with its tags
        get_order_query = """
        query getOrder($id: ID!) {
            order(id: $id) {
                id
                name
                tags
            }
        }
        """
        
        try:
            # Get current order data
            get_result = await self.execute_query(store_key, get_order_query, {"id": order_id})
            
            if get_result.get("msg") != "success":
                return {"msg": "failure", "error": f"Failed to get order: {get_result.get('error')}"}
            
            order_data = get_result.get("data", {}).get("order", {})
            current_tags = order_data.get("tags", [])
            
            # Check if tag already exists
            if tag in current_tags:
                return {"msg": "success", "note": f"Tag '{tag}' already exists on order"}
            
            # Add the new tag to existing tags
            updated_tags = current_tags + [tag]
            
            # Update the order with all tags
            update_mutation = """
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
            
            variables = {
                "input": {
                    "id": order_id,
                    "tags": updated_tags
                }
            }
            
            return await self.execute_query(store_key, update_mutation, variables)
            
        except Exception as e:
            return {"msg": "failure", "error": str(e)}
    
    async def remove_order_tag(self, store_key: str, order_id: str, tag: str) -> Dict[str, Any]:
        """
        Remove a tag from an order
        """
        # First, get the current order with its tags
        get_order_query = """
        query getOrder($id: ID!) {
            order(id: $id) {
                id
                name
                tags
            }
        }
        """
        
        try:
            # Get current order data
            get_result = await self.execute_query(store_key, get_order_query, {"id": order_id})
            
            if get_result.get("msg") != "success":
                return {"msg": "failure", "error": f"Failed to get order: {get_result.get('error')}"}
            
            order_data = get_result.get("data", {}).get("order", {})
            current_tags = order_data.get("tags", [])
            
            # Remove the tag if it exists
            if tag not in current_tags:
                return {"msg": "success", "note": f"Tag '{tag}' does not exist on order"}
            
            updated_tags = [t for t in current_tags if t != tag]
            
            # Update the order with modified tags
            update_mutation = """
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
            
            variables = {
                "input": {
                    "id": order_id,
                    "tags": updated_tags
                }
            }
            
            return await self.execute_query(store_key, update_mutation, variables)
            
        except Exception as e:
            return {"msg": "failure", "error": str(e)}
    
    async def get_color_metaobjects(self, store_key: str) -> Dict[str, Any]:
        """
        Get all color metaobjects from Shopify for a specific store
        Returns a mapping of color name (handle) to metaobject ID
        """
        query = """
        query GetAllColorMetaobjects {
            metaobjects(first: 250, type: "shopify--color-pattern") {
                edges {
                    node {
                        id
                        handle
                        fields {
                            key
                            value
                        }
                    }
                }
            }
        }
        """
        
        return await self.execute_query(store_key, query, {})
    
    async def update_product_option(self, store_key: str, product_id: str, option_id: str, option_name: str, option_values_to_add: List[Dict[str, Any]] = None, variant_strategy: str = "LEAVE_AS_IS") -> Dict[str, Any]:
        """
        Update product option and add new option values (for metafield-linked options)
        """
        mutation = """
        mutation updateOption(
            $productId: ID!,
            $option: OptionUpdateInput!,
            $optionValuesToAdd: [OptionValueCreateInput!],
            $variantStrategy: ProductOptionUpdateVariantStrategy
        ) {
            productOptionUpdate(
                productId: $productId,
                option: $option,
                optionValuesToAdd: $optionValuesToAdd,
                variantStrategy: $variantStrategy
            ) {
                userErrors { 
                    field 
                    message 
                    code 
                }
                product {
                    id
                    options {
                        id
                        name
                        values
                        optionValues {
                            id
                            name
                        }
                    }
                }
            }
        }
        """
        
        variables = {
            "productId": product_id,
            "option": {
                "id": option_id,
                "name": option_name
            },
            "variantStrategy": variant_strategy
        }
        
        if option_values_to_add:
            variables["optionValuesToAdd"] = option_values_to_add
        
        return await self.execute_query(store_key, mutation, variables)

# Create singleton instance
multi_store_shopify_client = MultiStoreShopifyClient() 