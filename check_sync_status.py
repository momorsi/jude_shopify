#!/usr/bin/env python3
"""
Check Sync Status Script
This script checks the current sync status of products in both stores
"""

import asyncio
import sys
import os

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.sync.items_init import items_init
from app.utils.logging import logger

async def check_sync_status():
    """
    Check the sync status of products in both stores
    """
    logger.info("Checking sync status of products in both stores")
    
    try:
        # Check local store
        logger.info("=== LOCAL STORE ===")
        local_synced = await items_init.get_products_by_sync_status("local", "synced")
        local_failed = await items_init.get_products_by_sync_status("local", "failed")
        local_unsynced = await items_init.get_products_by_sync_status("local", None)
        
        logger.info(f"Local Store - Synced to Production: {len(local_synced)}, Failed: {len(local_failed)}, Unsynced: {len(local_unsynced)}")
        
        # Check international store
        logger.info("=== INTERNATIONAL STORE ===")
        intl_synced = await items_init.get_products_by_sync_status("international", "synced")
        intl_failed = await items_init.get_products_by_sync_status("international", "failed")
        intl_unsynced = await items_init.get_products_by_sync_status("international", None)
        
        logger.info(f"International Store - Synced to Production: {len(intl_synced)}, Failed: {len(intl_failed)}, Unsynced: {len(intl_unsynced)}")
        
        # Show some examples of failed products
        if local_failed:
            logger.info(f"Local Store Failed Products (first 5):")
            for i, product in enumerate(local_failed[:5]):
                logger.info(f"  {i+1}. {product.get('title')} (ID: {product.get('id')})")
        
        if intl_failed:
            logger.info(f"International Store Failed Products (first 5):")
            for i, product in enumerate(intl_failed[:5]):
                logger.info(f"  {i+1}. {product.get('title')} (ID: {product.get('id')})")
                
    except Exception as e:
        logger.error(f"Error checking sync status: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(check_sync_status())
