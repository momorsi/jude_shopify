import asyncio
from app.services.shopify.multi_store_client import multi_store_shopify_client

async def main():
    enabled_stores = multi_store_shopify_client.get_enabled_stores()
    for store_key, store_config in enabled_stores.items():
        print(f"\nStore: {store_config.name} ({store_key})")
        result = await multi_store_shopify_client.get_locations(store_key)
        if result["msg"] == "success":
            locations = result["data"]["locations"]["edges"]
            for loc in locations:
                loc_data = loc["node"]
                highlight = "<--" if loc_data["name"].lower() == "cairo" else ""
                print(f"  Name: {loc_data['name']}, ID: {loc_data['id']} {highlight}")
        else:
            print(f"  Failed to fetch locations: {result.get('error')}")

if __name__ == "__main__":
    asyncio.run(main()) 