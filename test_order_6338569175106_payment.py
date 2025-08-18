"""
Test script to directly test payment creation for order 6338569175106
"""

import asyncio
import sys
import os
from typing import Dict, Any

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.sync.sales.orders_sync import OrdersSalesSync
from app.utils.logging import logger


async def test_order_6338569175106_payment():
    """Test payment creation for specific order 6338569175106"""
    try:
        orders_sync = OrdersSalesSync()
        
        # Create the order data structure that matches what we get from Shopify
        order_data = {
            "node": {
                "id": "gid://shopify/Order/6338569175106",
                "name": "#1533",
                "createdAt": "2025-08-16T18:16:11Z",
                "displayFinancialStatus": "PAID",
                "displayFulfillmentStatus": "FULFILLED",
                "sourceName": "web",
                "sourceIdentifier": None,
                "totalPriceSet": {
                    "shopMoney": {
                        "amount": "12520.0",
                        "currencyCode": "EGP"
                    }
                },
                "subtotalPriceSet": {
                    "shopMoney": {
                        "amount": "12400.0",
                        "currencyCode": "EGP"
                    }
                },
                "totalShippingPriceSet": {
                    "shopMoney": {
                        "amount": "120.0",
                        "currencyCode": "EGP"
                    }
                },
                "customer": {
                    "id": "gid://shopify/Customer/8071840497730",
                    "firstName": "Mai",
                    "lastName": "Saad",
                    "email": "mai_110@hotmail.com",
                    "phone": None,
                    "addresses": [
                        {
                            "address1": "التجمع الخامس الياسمين ٧ فيلا ١٥٥",
                            "address2": "4",
                            "city": "New Cairo",
                            "province": "Cairo",
                            "zip": "11347",
                            "country": "Egypt",
                            "phone": "01005528924"
                        }
                    ]
                },
                "shippingAddress": {
                    "address1": "التجمع الخامس الياسمين ٧ فيلا ١٥٥",
                    "address2": "4",
                    "city": "New Cairo",
                    "province": "Cairo",
                    "zip": "11347",
                    "country": "Egypt",
                    "phone": "01005528924",
                    "firstName": "Mai",
                    "lastName": "Saad",
                    "company": None
                },
                "billingAddress": {
                    "address1": "التجمع الخامس الياسمين ٧ فيلا ١٥٥",
                    "address2": "4",
                    "city": "New Cairo",
                    "province": "Cairo",
                    "zip": "11347",
                    "country": "Egypt",
                    "phone": "01005528924",
                    "firstName": "Mai",
                    "lastName": "Saad",
                    "company": None
                },
                "lineItems": {
                    "edges": [
                        {
                            "node": {
                                "id": "gid://shopify/LineItem/15879663943746",
                                "name": "Nova Earrings - Orange",
                                "quantity": 1,
                                "sku": "FG-0000655",
                                "title": "Nova Earrings",
                                "variant": {
                                    "id": "gid://shopify/ProductVariant/42194953109570",
                                    "sku": "FG-0000655",
                                    "price": "4900.00",
                                    "product": {
                                        "id": "gid://shopify/Product/7490852978754",
                                        "title": "Nova Earrings"
                                    }
                                },
                                "discountedTotalSet": {
                                    "shopMoney": {
                                        "amount": "4900.0",
                                        "currencyCode": "EGP"
                                    }
                                }
                            }
                        },
                        {
                            "node": {
                                "id": "gid://shopify/LineItem/15879663976514",
                                "name": "Eclipse Necklace - Orange",
                                "quantity": 1,
                                "sku": "FG-0000669",
                                "title": "Eclipse Necklace",
                                "variant": {
                                    "id": "gid://shopify/ProductVariant/42194953568322",
                                    "sku": "FG-0000669",
                                    "price": "7500.00",
                                    "product": {
                                        "id": "gid://shopify/Product/7490853175362",
                                        "title": "Eclipse Necklace"
                                    }
                                },
                                "discountedTotalSet": {
                                    "shopMoney": {
                                        "amount": "7500.0",
                                        "currencyCode": "EGP"
                                    }
                                }
                            }
                        }
                    ]
                },
                "transactions": [
                    {
                        "id": "gid://shopify/OrderTransaction/8096376520770",
                        "kind": "SALE",
                        "status": "SUCCESS",
                        "gateway": "Paymob",
                        "amountSet": {
                            "shopMoney": {
                                "amount": "12520.0",
                                "currencyCode": "EGP"
                            }
                        },
                        "processedAt": "2025-08-16T18:14:53Z",
                        "test": False
                    }
                ],
                "note": None
            }
        }
        
        logger.info(f"Testing payment creation for order: #1533 (ID: 6338569175106)")
        logger.info(f"Financial Status: PAID")
        logger.info(f"Payment Gateway: Paymob")
        logger.info(f"Payment ID: gid://shopify/OrderTransaction/8096376520770")
        logger.info(f"Amount: 12520.0 EGP")
        logger.info(f"Shipping Fee: 120.0 EGP")
        
        # Process the order
        result = await orders_sync.process_order("local", order_data)
        
        if result["msg"] == "success":
            logger.info(f"✅ Successfully processed order #1533")
            logger.info(f"   SAP Invoice: {result.get('sap_invoice_number', 'N/A')}")
            logger.info(f"   SAP Payment: {result.get('sap_payment_number', 'N/A')}")
            logger.info(f"   Payment ID: {result.get('payment_id', 'N/A')}")
            logger.info(f"   Gateway: {result.get('payment_gateway', 'N/A')}")
            logger.info(f"   Amount: {result.get('payment_amount', 'N/A')}")
            logger.info(f"   Is Online Payment: {result.get('is_online_payment', 'N/A')}")
        else:
            logger.error(f"❌ Failed to process order #1533: {result.get('error')}")
        
    except Exception as e:
        logger.error(f"Error in order payment test: {str(e)}")


async def main():
    logger.info("Testing payment creation for specific order 6338569175106...")
    await test_order_6338569175106_payment()


if __name__ == "__main__":
    asyncio.run(main())
