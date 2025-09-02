#!/usr/bin/env python3
"""
Script to get order details using REST API
"""

import asyncio
import json
import sys
import httpx
from app.core.config import config_settings
from order_location_mapper import OrderLocationMapper, print_order_analysis

async def get_order_rest(order_id: str):
    """
    Get order details using REST API
    """
    print(f"Searching for order: {order_id}")
    
    # Get all enabled stores
    enabled_stores = config_settings.get_enabled_stores()
    
    for store_key, store_config in enabled_stores.items():
        print(f"\nChecking store: {store_config.name} ({store_key})")
        
        try:
            # Build REST API URL
            url = f"https://{store_config.shop_url}/admin/api/{store_config.api_version}/orders/{order_id}.json"
            
            # Prepare headers
            headers = {
                'X-Shopify-Access-Token': store_config.access_token,
                'Content-Type': 'application/json',
            }
            
            async with httpx.AsyncClient(timeout=store_config.timeout) as client:
                response = await client.get(url, headers=headers)
                
                if response.status_code == 200:
                    order_data = response.json().get('order')
                    if order_data:
                        print(f"✅ Order found in {store_config.name}!")
                        print_rest_order_details(order_data, store_key)
                        

                        
                        # Analyze order source and location mapping
                        analysis = OrderLocationMapper.analyze_order_source(order_data, store_key)
                        print_order_analysis(analysis)
                        
                        return order_data
                    else:
                        print(f"❌ Order not found in {store_config.name}")
                elif response.status_code == 404:
                    print(f"❌ Order not found in {store_config.name}")
                else:
                    print(f"❌ Error querying {store_config.name}: HTTP {response.status_code}: {response.text}")
                    
        except Exception as e:
            print(f"❌ Error querying {store_config.name}: {str(e)}")
    
    print(f"\n❌ Order {order_id} not found in any store")
    return None

def print_rest_order_details(order_data, store_key):
    """
    Print order details from REST API response
    """
    print("\n" + "="*60)
    print("ORDER DETAILS")
    print("="*60)
    
    # Basic order info
    print(f"Order ID: {order_data.get('id', 'N/A')}")
    print(f"Order Name: {order_data.get('name', 'N/A')}")
    print(f"Created: {order_data.get('created_at', 'N/A')}")
    
    # Financial info
    print(f"Total: {order_data.get('total_price', 'N/A')} {order_data.get('currency', 'N/A')}")
    print(f"Financial Status: {order_data.get('financial_status', 'N/A')}")
    print(f"Fulfillment Status: {order_data.get('fulfillment_status', 'N/A')}")
    
    # SOURCE INFORMATION (what you specifically asked for)
    print("\n" + "-"*40)
    print("SOURCE INFORMATION")
    print("-"*40)
    print(f"Source Name: {order_data.get('source_name', 'N/A')}")
    print(f"Source Identifier: {order_data.get('source_identifier', 'N/A')}")
    
    # LOCATION INFORMATION (what you specifically asked for)
    print("\n" + "-"*40)
    print("LOCATION INFORMATION")
    print("-"*40)
    fulfillments = order_data.get('fulfillments', [])
    if fulfillments:
        for i, fulfillment in enumerate(fulfillments, 1):
            print(f"Fulfillment {i}:")
            print(f"  Status: {fulfillment.get('status', 'N/A')}")
            print(f"  Fulfillment ID: {fulfillment.get('id', 'N/A')}")
            
            # Try to get location from fulfillment
            location_id = fulfillment.get('location_id')
            if location_id:
                print(f"  Location ID: {location_id}")
                # We can map this to the location name from our configuration
                store_config = config_settings.get_store_by_name(store_key)
                if store_config and hasattr(store_config, 'location_warehouse_mapping'):
                    location_mapping = store_config.location_warehouse_mapping
                    if store_key in location_mapping:
                        locations = location_mapping[store_key].get('locations', {})
                        if str(location_id) in locations:
                            location_info = locations[str(location_id)]
                            print(f"  Warehouse: {location_info.get('warehouse', 'N/A')}")
                            print(f"  Location CC: {location_info.get('location_cc', 'N/A')}")
                            print(f"  Department CC: {location_info.get('department_cc', 'N/A')}")
                            print(f"  Activity CC: {location_info.get('activity_cc', 'N/A')}")
            print()
    else:
        print("No fulfillment information available")
    
    # Customer info
    print("\n" + "-"*40)
    print("CUSTOMER INFORMATION")
    print("-"*40)
    customer = order_data.get('customer')
    if customer:
        print(f"Customer Email: {customer.get('email', 'N/A')}")
        print(f"Customer Name: {customer.get('first_name', '')} {customer.get('last_name', '')}")
    else:
        print("No customer information available")
    
    # Line items
    print("\n" + "-"*40)
    print("LINE ITEMS")
    print("-"*40)
    line_items = order_data.get('line_items', [])
    for i, item in enumerate(line_items, 1):
        print(f"{i}. {item.get('name', 'N/A')}")
        print(f"   SKU: {item.get('sku', 'N/A')}")
        print(f"   Quantity: {item.get('quantity', 'N/A')}")
        variant = item.get('variant')
        if variant:
            print(f"   Variant ID: {variant.get('id', 'N/A')}")
            print(f"   Variant SKU: {variant.get('sku', 'N/A')}")
        print()
    
    print("\n" + "="*60)

async def main():
    """
    Main function
    """
    if len(sys.argv) != 2:
        print("Usage: python get_order_rest.py <order_id>")
        print("Example: python get_order_rest.py 6347058708546")
        sys.exit(1)
    
    order_id = sys.argv[1]
    
    try:
        order_data = await get_order_rest(order_id)
        if order_data:
            print(f"\n✅ Successfully retrieved order {order_id}")
        else:
            print(f"\n❌ Failed to retrieve order {order_id}")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
