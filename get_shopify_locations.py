#!/usr/bin/env python3
"""
Script to get all Shopify locations and display their names and IDs
"""

import asyncio
import sys
import os

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.core.config import config_settings
from app.utils.logging import logger

async def get_all_locations():
    """
    Get locations from all enabled Shopify stores
    """
    print("🔍 Fetching Shopify locations...")
    print("=" * 50)
    
    # Get all enabled stores
    enabled_stores = config_settings.get_enabled_stores()
    
    if not enabled_stores:
        print("❌ No enabled stores found in configuration")
        return
    
    for store_key, store_config in enabled_stores.items():
        print(f"\n🏪 Store: {store_config.name} ({store_key})")
        print(f"   URL: {store_config.shop_url}")
        print("-" * 40)
        
        try:
            # Get locations for this store
            result = await multi_store_shopify_client.get_locations(store_key)
            
            if result["msg"] == "success":
                locations = result["data"]["locations"]["edges"]
                
                if not locations:
                    print("   📍 No locations found")
                else:
                    print(f"   📍 Found {len(locations)} location(s):")
                    print()
                    
                    for i, location_edge in enumerate(locations, 1):
                        location = location_edge["node"]
                        location_id = location["id"].split("/")[-1]  # Extract ID from GraphQL global ID
                        name = location["name"]
                        is_active = location["isActive"]
                        address = location.get("address", {})
                        
                        status_icon = "✅" if is_active else "❌"
                        print(f"   {i}. {status_icon} {name}")
                        print(f"      ID: {location_id}")
                        
                        if address.get("address1"):
                            city = address.get("city", "")
                            country = address.get("country", "")
                            address_str = f"{address['address1']}"
                            if city:
                                address_str += f", {city}"
                            if country:
                                address_str += f", {country}"
                            print(f"      Address: {address_str}")
                        
                        print()
            else:
                print(f"   ❌ Error: {result.get('error', 'Unknown error')}")
                
        except Exception as e:
            print(f"   ❌ Exception: {str(e)}")
    
    print("=" * 50)
    print("✅ Location fetch completed!")

async def main():
    """
    Main function to run the location fetch
    """
    try:
        await get_all_locations()
    except KeyboardInterrupt:
        print("\n⏹️  Operation cancelled by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {str(e)}")
        logger.error(f"Error in main: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main()) 