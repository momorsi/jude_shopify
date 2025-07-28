#!/usr/bin/env python3
"""
Test script for Sales Module
Verifies the structure and basic functionality of the Sales module
"""

import asyncio
import sys
import os

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from app.sync.sales import GiftCardsSalesSync, OrdersSalesSync, CustomerManager
from app.core.config import config_settings
from app.utils.logging import logger


async def test_sales_module_structure():
    """
    Test the Sales module structure and basic initialization
    """
    print("🧪 Testing Sales Module Structure...")
    
    try:
        # Test configuration
        print(f"✅ Configuration loaded successfully")
        print(f"   - Sales Gift Cards Enabled: {config_settings.sales_gift_cards_enabled}")
        print(f"   - Sales Orders Enabled: {config_settings.sales_orders_enabled}")
        print(f"   - Gift Cards Interval: {config_settings.sales_gift_cards_interval} minutes")
        print(f"   - Orders Interval: {config_settings.sales_orders_interval} minutes")
        
        # Test class initialization
        print("\n🔧 Testing class initialization...")
        
        gift_cards_sync = GiftCardsSalesSync()
        print(f"✅ GiftCardsSalesSync initialized")
        print(f"   - Batch size: {gift_cards_sync.batch_size}")
        
        orders_sync = OrdersSalesSync()
        print(f"✅ OrdersSalesSync initialized")
        print(f"   - Batch size: {orders_sync.batch_size}")
        print(f"   - Customer manager: {type(orders_sync.customer_manager).__name__}")
        
        customer_manager = CustomerManager()
        print(f"✅ CustomerManager initialized")
        print(f"   - Batch size: {customer_manager.batch_size}")
        
        # Test enabled stores
        enabled_stores = config_settings.get_enabled_stores()
        print(f"\n🏪 Enabled stores: {len(enabled_stores)}")
        for store_key, store_config in enabled_stores.items():
            print(f"   - {store_key}: {store_config.name} ({store_config.currency})")
        
        print("\n✅ Sales Module structure test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error testing Sales Module structure: {str(e)}")
        logger.error(f"Sales Module structure test failed: {str(e)}")
        return False


async def test_customer_manager_methods():
    """
    Test CustomerManager methods (without making actual API calls)
    """
    print("\n👥 Testing CustomerManager methods...")
    
    try:
        customer_manager = CustomerManager()
        
        # Test phone number cleaning
        test_phones = [
            "+20 123 456 7890",
            "01234567890",
            "+201234567890",
            "123-456-7890"
        ]
        
        for phone in test_phones:
            cleaned = customer_manager._clean_phone_number(phone)
            print(f"   - {phone} -> {cleaned}")
        
        # Test customer data mapping
        test_customer = {
            "id": "gid://shopify/Customer/123456789",
            "firstName": "John",
            "lastName": "Doe",
            "email": "john.doe@example.com",
            "phone": "+201234567890",
            "addresses": [{
                "address1": "123 Main St",
                "city": "Cairo",
                "province": "Cairo",
                "zip": "12345",
                "country": "Egypt"
            }]
        }
        
        sap_customer = customer_manager._map_shopify_customer_to_sap(test_customer)
        print(f"\n📋 Customer mapping test:")
        print(f"   - CardCode: {sap_customer.get('CardCode', 'N/A')}")
        print(f"   - CardName: {sap_customer.get('CardName', 'N/A')}")
        print(f"   - Email: {sap_customer.get('EmailAddress', 'N/A')}")
        print(f"   - Phone: {sap_customer.get('Phone1', 'N/A')}")
        
        print("✅ CustomerManager methods test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error testing CustomerManager methods: {str(e)}")
        logger.error(f"CustomerManager methods test failed: {str(e)}")
        return False


async def test_gift_cards_mapping():
    """
    Test gift cards mapping functionality
    """
    print("\n🎁 Testing Gift Cards mapping...")
    
    try:
        gift_cards_sync = GiftCardsSalesSync()
        
        # Test SAP gift card data
        test_sap_gift_card = {
            "ItemCode": "GC001",
            "ItemName": "Birthday Gift Card",
            "U_GiftCardDescription": "Perfect for birthdays",
            "U_Category": "Birthday",
            "U_Occasion": "Birthday",
            "U_Theme": "Celebration",
            "U_Value": "50",
            "U_Design": "Classic",
            "Active": "Y",
            "Price": 50.0
        }
        
        # Mock store config
        class MockStoreConfig:
            def __init__(self):
                self.price_list = 1
                self.location_id = "gid://shopify/Location/123456"
        
        store_config = MockStoreConfig()
        
        # Test mapping
        shopify_data = gift_cards_sync.map_sap_gift_card_to_shopify(test_sap_gift_card, store_config)
        
        print(f"📋 Gift card mapping test:")
        print(f"   - Title: {shopify_data.get('title', 'N/A')}")
        print(f"   - Product Type: {shopify_data.get('productType', 'N/A')}")
        print(f"   - Status: {shopify_data.get('status', 'N/A')}")
        print(f"   - Tags: {shopify_data.get('tags', [])}")
        print(f"   - Variant SKU: {shopify_data.get('variants', [{}])[0].get('sku', 'N/A')}")
        print(f"   - Variant Price: {shopify_data.get('variants', [{}])[0].get('price', 'N/A')}")
        
        print("✅ Gift Cards mapping test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error testing Gift Cards mapping: {str(e)}")
        logger.error(f"Gift Cards mapping test failed: {str(e)}")
        return False


async def test_orders_mapping():
    """
    Test orders mapping functionality
    """
    print("\n📦 Testing Orders mapping...")
    
    try:
        orders_sync = OrdersSalesSync()
        
        # Test Shopify order data
        test_shopify_order = {
            "node": {
                "id": "gid://shopify/Order/123456789",
                "name": "#1001",
                "createdAt": "2024-01-15T10:30:00Z",
                "totalPriceSet": {
                    "shopMoney": {
                        "amount": "150.00",
                        "currencyCode": "EGP"
                    }
                },
                "subtotalPriceSet": {
                    "shopMoney": {
                        "amount": "140.00",
                        "currencyCode": "EGP"
                    }
                },
                "totalTaxSet": {
                    "shopMoney": {
                        "amount": "10.00",
                        "currencyCode": "EGP"
                    }
                },
                "totalShippingPriceSet": {
                    "shopMoney": {
                        "amount": "20.00",
                        "currencyCode": "EGP"
                    }
                },
                "lineItems": {
                    "edges": [{
                        "node": {
                            "id": "gid://shopify/LineItem/123",
                            "quantity": 2,
                            "sku": "PROD001",
                            "title": "Test Product",
                            "variant": {
                                "id": "gid://shopify/ProductVariant/123",
                                "sku": "PROD001",
                                "price": "70.00"
                            },
                            "discountedTotalSet": {
                                "shopMoney": {
                                    "amount": "140.00",
                                    "currencyCode": "EGP"
                                }
                            }
                        }
                    }]
                },
                "discountApplications": {
                    "edges": []
                }
            }
        }
        
        # Test mapping
        sap_invoice_data = orders_sync.map_shopify_order_to_sap(test_shopify_order, "CUST001")
        
        print(f"📋 Order mapping test:")
        print(f"   - CardCode: {sap_invoice_data.get('CardCode', 'N/A')}")
        print(f"   - DocDate: {sap_invoice_data.get('DocDate', 'N/A')}")
        print(f"   - Shopify Order ID: {sap_invoice_data.get('U_ShopifyOrderID', 'N/A')}")
        print(f"   - Total: {sap_invoice_data.get('U_ShopifyTotal', 'N/A')}")
        print(f"   - Line Items: {len(sap_invoice_data.get('DocumentLines', []))}")
        
        print("✅ Orders mapping test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error testing Orders mapping: {str(e)}")
        logger.error(f"Orders mapping test failed: {str(e)}")
        return False


async def main():
    """
    Main test function
    """
    print("🚀 Starting Sales Module Tests...\n")
    
    tests = [
        test_sales_module_structure,
        test_customer_manager_methods,
        test_gift_cards_mapping,
        test_orders_mapping
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            result = await test()
            if result:
                passed += 1
        except Exception as e:
            print(f"❌ Test failed with exception: {str(e)}")
    
    print(f"\n📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Sales Module is ready for use.")
        return 0
    else:
        print("⚠️  Some tests failed. Please check the errors above.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code) 