#!/usr/bin/env python3
"""
Simple script to test Shopify API access with basic endpoints
"""

import asyncio
import sys
import os
import httpx

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.core.config import config_settings

async def test_shopify_api():
    """
    Test Shopify API access with various endpoints
    """
    print("🧪 Testing Shopify API Access...")
    print("=" * 60)
    
    # Get the local store configuration
    store_config = config_settings.shopify_stores.get("local")
    if not store_config:
        print("❌ Local store configuration not found")
        return
    
    print(f"🏪 Store: {store_config.name}")
    print(f"   URL: {store_config.shop_url}")
    print(f"   API Version: {store_config.api_version}")
    print(f"   Token: {store_config.access_token[:20]}...")
    print("-" * 50)
    
    headers = {
        'X-Shopify-Access-Token': store_config.access_token,
        'Content-Type': 'application/json',
    }
    
    # Test 1: Basic shop info (most basic endpoint)
    print("\n1️⃣ Testing /shop.json endpoint...")
    shop_url = f"https://{store_config.shop_url}/admin/api/{store_config.api_version}/shop.json"
    print(f"   URL: {shop_url}")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(shop_url, headers=headers)
            print(f"   Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                shop = data.get('shop', {})
                print(f"   ✅ Success! Shop name: {shop.get('name', 'N/A')}")
                print(f"   ✅ Shop domain: {shop.get('domain', 'N/A')}")
                print(f"   ✅ Shop email: {shop.get('email', 'N/A')}")
            else:
                print(f"   ❌ Error: {response.text}")
                
    except Exception as e:
        print(f"   ❌ Exception: {str(e)}")
    
    # Test 2: Products endpoint (if shop endpoint works)
    print("\n2️⃣ Testing /products.json endpoint...")
    products_url = f"https://{store_config.shop_url}/admin/api/{store_config.api_version}/products.json?limit=1"
    print(f"   URL: {products_url}")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(products_url, headers=headers)
            print(f"   Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                products = data.get('products', [])
                print(f"   ✅ Success! Found {len(products)} product(s)")
                if products:
                    product = products[0]
                    print(f"   ✅ First product: {product.get('title', 'N/A')} (ID: {product.get('id', 'N/A')})")
            else:
                print(f"   ❌ Error: {response.text}")
                
    except Exception as e:
        print(f"   ❌ Exception: {str(e)}")
    
    # Test 3: Locations endpoint (the one that was failing)
    print("\n3️⃣ Testing /locations.json endpoint...")
    locations_url = f"https://{store_config.shop_url}/admin/api/{store_config.api_version}/locations.json"
    print(f"   URL: {locations_url}")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(locations_url, headers=headers)
            print(f"   Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                locations = data.get('locations', [])
                print(f"   ✅ Success! Found {len(locations)} location(s)")
                for i, location in enumerate(locations[:3], 1):  # Show first 3 locations
                    print(f"      {i}. {location.get('name', 'N/A')} (ID: {location.get('id', 'N/A')})")
            else:
                print(f"   ❌ Error: {response.text}")
                
    except Exception as e:
        print(f"   ❌ Exception: {str(e)}")
    
    # Test 4: Check if token has expired by looking at response headers
    print("\n4️⃣ Checking token validity...")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(shop_url, headers=headers)
            
            # Check Shopify-specific headers
            shopify_headers = {k: v for k, v in response.headers.items() if 'shopify' in k.lower()}
            if shopify_headers:
                print("   📋 Shopify response headers:")
                for key, value in shopify_headers.items():
                    print(f"      {key}: {value}")
            else:
                print("   📋 No Shopify-specific headers found")
                
            # Check rate limiting
            if 'X-Shopify-Shop-Api-Call-Limit' in response.headers:
                limit_info = response.headers['X-Shopify-Shop-Api-Call-Limit']
                print(f"   📊 API Call Limit: {limit_info}")
            
    except Exception as e:
        print(f"   ❌ Exception: {str(e)}")
    
    print("\n" + "=" * 60)
    print("✅ API testing completed!")

async def main():
    """
    Main function
    """
    try:
        await test_shopify_api()
    except KeyboardInterrupt:
        print("\n⏹️  Operation cancelled by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
