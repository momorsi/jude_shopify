#!/usr/bin/env python3
"""
Run Items Initialization Script
This script runs the items initialization process for both local and international stores.
"""

import asyncio
import sys
import os

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.sync.items_init import items_init
from app.utils.logging import logger

async def main():
    """
    Main function to run the items initialization process
    """
    logger.info("Starting Shopify items initialization process")
    logger.info("This will process both local and international stores")
    logger.info("SAP item field updates will only be applied to the local store")
    logger.info("Mapping records will be created for both stores")
    
    try:
        await items_init.initialize_all_stores()
        logger.info("Shopify items initialization completed successfully")
    except Exception as e:
        logger.error(f"Items initialization failed: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
