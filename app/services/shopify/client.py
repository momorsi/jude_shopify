from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport
from app.core.config import config_settings
from app.utils.logging import logger, log_api_call
import json
from gql.transport.exceptions import TransportQueryError

class ShopifyGraphQLClient:
    def __init__(self):
        self.transport = AIOHTTPTransport(
            url=f"https://{config_settings.shopify_shop_url}/admin/api/{config_settings.shopify_api_version}/graphql.json",
            headers={
                'X-Shopify-Access-Token': config_settings.shopify_access_token,
                'Content-Type': 'application/json',
            }
        )
        # Initialize client without schema fetching
        self.client = Client(transport=self.transport, fetch_schema_from_transport=False)

    async def execute_query(self, query: str, variables: dict = None):
        """
        Execute a GraphQL query
        """
        try:
            # Log the request
            log_api_call(
                service="shopify",
                endpoint="graphql",
                request_data={"query": query, "variables": variables}
            )

            # Execute the query
            result = await self.client.execute_async(
                gql(query),
                variable_values=variables
            )

            # Log the response
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