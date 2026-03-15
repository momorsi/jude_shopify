from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport
from app.core.config import config_settings
from app.utils.logging import logger, log_api_call
from app.services.shopify.multi_store_client import shopify_token_manager
from app.utils.ssl_cert import get_ssl_context
import json
from gql.transport.exceptions import TransportQueryError


class ShopifyGraphQLClient:
    """Legacy single-store client. Uses the first enabled store and shared token manager."""

    def __init__(self):
        self._client: Client = None
        self._current_token: str = None
        enabled_stores = config_settings.get_enabled_stores()
        self._store_key = list(enabled_stores.keys())[0] if enabled_stores else None

    def _build_client(self, access_token: str) -> Client:
        transport = AIOHTTPTransport(
            url=f"https://{config_settings.shopify_shop_url}/admin/api/{config_settings.shopify_api_version}/graphql.json",
            headers={
                'X-Shopify-Access-Token': access_token,
                'Content-Type': 'application/json',
            },
            ssl=get_ssl_context()
        )
        return Client(transport=transport, fetch_schema_from_transport=False)

    async def _get_client(self) -> Client:
        if not self._store_key:
            raise ValueError("No enabled Shopify stores found")
        access_token = await shopify_token_manager.get_access_token(self._store_key)
        if self._current_token != access_token:
            self._client = self._build_client(access_token)
            self._current_token = access_token
        return self._client

    async def execute_query(self, query: str, variables: dict = None):
        """Execute a GraphQL query"""
        try:
            log_api_call(
                service="shopify",
                endpoint="graphql",
                request_data={"query": query, "variables": variables}
            )

            client = await self._get_client()
            result = await client.execute_async(
                gql(query),
                variable_values=variables
            )

            log_api_call(
                service="shopify",
                endpoint="graphql",
                response_data=result,
                status="success"
            )

            return {"msg": "success", "data": result}

        except TransportQueryError as e:
            error_msg = f"GraphQL query error: {str(e)}"
            if hasattr(e, 'errors'):
                error_msg += f"\nGraphQL Errors: {json.dumps(e.errors, indent=2)}"
            logger.error(error_msg)
            return {"msg": "failure", "error": error_msg}
        except Exception as e:
            error_msg = f"GraphQL query error: {str(e)}"
            logger.error(error_msg)
            return {"msg": "failure", "error": error_msg}

    # Example query methods
    async def get_products(self, first: int = 10, after: str = None):
        """
        Get products from Shopify
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
        return await self.execute_query(query, variables)

    async def update_inventory(self, inventory_item_id: str, available: int):
        """
        Update inventory levels
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
        return await self.execute_query(mutation, variables)

    async def get_orders(self, first: int = 10, after: str = None):
        """
        Get orders from Shopify
        """
        query = """
        query GetOrders($first: Int!, $after: String) {
            orders(first: $first, after: $after) {
                pageInfo {
                    hasNextPage
                    endCursor
                }
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
                        lineItems(first: 10) {
                            edges {
                                node {
                                    id
                                    title
                                    quantity
                                    sku
                                    variant {
                                        id
                                        sku
                                    }
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
        return await self.execute_query(query, variables)

# Create a singleton instance
shopify_client = ShopifyGraphQLClient() 