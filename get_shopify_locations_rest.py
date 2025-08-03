#!/usr/bin/env python3
"""
Script to get all Shopify locations using REST API and display their names and IDs
"""

import asyncio
import sys
import os
import httpx

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.core.config import config_settings
from app.utils.logging import logger

async def get_locations_rest(shop_url: str, access_token: str, api_version: str):
    """
    Get locations using REST API
    """
    url = f"https://{shop_url}/admin/api/{api_version}/locations.json"
    
    headers = {
        'X-Shopify-Access-Token': access_token,
        'Content-Type': 'application/json',
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                return {"msg": "success", "data": data}
            else:
                return {"msg": "failure", "error": f"HTTP {response.status_code}: {response.text}"}
                
    except Exception as e:
        return {"msg": "failure", "error": str(e)}

async def get_all_locations():
    """
    Get locations from all enabled Shopify stores using REST API
    """
    print("🔍 Fetching Shopify locations using REST API...")
    print("=" * 60)
    
    # Get all enabled stores
    enabled_stores = config_settings.get_enabled_stores()
    
    if not enabled_stores:
        print("❌ No enabled stores found in configuration")
        return
    
    for store_key, store_config in enabled_stores.items():
        print(f"\n🏪 Store: {store_config.name} ({store_key})")
        print(f"   URL: {store_config.shop_url}")
        print(f"   API Version: {store_config.api_version}")
        print("-" * 50)
        
        try:
            # Get locations for this store
            result = await get_locations_rest(
                store_config.shop_url,
                store_config.access_token,
                store_config.api_version
            )
            
            if result["msg"] == "success":
                locations = result["data"]["locations"]
                
                if not locations:
                    print("   📍 No locations found")
                else:
                    print(f"   📍 Found {len(locations)} location(s):")
                    print()
                    
                    for i, location in enumerate(locations, 1):
                        location_id = location["id"]
                        name = location["name"]
                        is_active = location.get("active", True)
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
                        
                        # Additional location details
                        if location.get("phone"):
                            print(f"      Phone: {location['phone']}")
                        
                        if location.get("created_at"):
                            print(f"      Created: {location['created_at']}")
                        
                        print()
            else:
                print(f"   ❌ Error: {result.get('error', 'Unknown error')}")
                
        except Exception as e:
            print(f"   ❌ Exception: {str(e)}")
    
    print("=" * 60)
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