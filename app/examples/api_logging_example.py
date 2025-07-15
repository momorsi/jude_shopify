"""
Example usage of the SAP API logging system

This file demonstrates how to use the new SAP API logging functionality
that mimics the reference project's log_crud.py functionality.
"""

import asyncio
from app.services.sap.api_logger import sap_api_logger, sl_add_log, sl_add_sync
from app.utils.logging import log_api_call

async def example_integrated_logging():
    """Example using the integrated logging system (recommended)"""
    print("=== Integrated Logging Example ===")
    
    # This will log to both file and SAP table automatically
    await log_api_call(
        service="shopify",
        endpoint="/admin/api/2024-01/products.json",
        request_data={"title": "Test Product", "body_html": "Test description"},
        response_data={"product": {"id": 12345, "title": "Test Product"}},
        status="success"
    )

async def example_direct_sap_logging():
    """Example using direct SAP logging (similar to reference project)"""
    print("=== Direct SAP Logging Example ===")
    
    # Direct SAP logging with all parameters (similar to sl_add_log)
    await sl_add_log(
        server="shopify",
        endpoint="/admin/api/2024-01/products.json",
        request_data={"title": "Test Product", "body_html": "Test description"},
        response_data={"product": {"id": 12345, "title": "Test Product"}},
        status="success",
        reference="PROD_12345",
        action="create_product",
        value="Product created successfully"
    )

async def example_sync_logging():
    """Example of sync event logging"""
    print("=== Sync Logging Example ===")
    
    # Log sync event (similar to sl_add_sync)
    await sl_add_sync(
        sync_code=1,  # Sync type identifier
        sync_date="2024-01-15",
        sync_time="1430"  # 2:30 PM
    )

async def example_error_logging():
    """Example of error logging"""
    print("=== Error Logging Example ===")
    
    # Log API error
    await sl_add_log(
        server="shopify",
        endpoint="/admin/api/2024-01/products.json",
        request_data={"title": "Test Product"},
        response_data={"errors": "Invalid product data"},
        status="failure",
        reference="PROD_12345",
        action="create_product",
        value="Validation failed"
    )

async def example_using_logger_instance():
    """Example using the logger instance directly"""
    print("=== Logger Instance Example ===")
    
    # Using the logger instance directly
    await sap_api_logger.log_api_call(
        server="sap",
        endpoint="/Items",
        request_data={"filter": "U_ShopifyID eq '12345'"},
        response_data={"Items": [{"ItemCode": "ITEM001", "ItemName": "Test Item"}]},
        status="success",
        reference="ITEM001",
        action="get_item",
        value="Item retrieved successfully"
    )

async def main():
    """Run all examples"""
    print("SAP API Logging Examples")
    print("=" * 50)
    
    try:
        await example_integrated_logging()
        await example_direct_sap_logging()
        await example_sync_logging()
        await example_error_logging()
        await example_using_logger_instance()
        
        print("\nAll examples completed successfully!")
        
    except Exception as e:
        print(f"Error running examples: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main()) 