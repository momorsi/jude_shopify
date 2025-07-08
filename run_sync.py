#!/usr/bin/env python3
"""
Command-line interface for running sync operations
"""

import asyncio
import sys
from app.sync.new_items_multi_store import multi_store_new_items_sync
from app.sync.gift_cards import gift_cards_sync
from app.utils.logging import logger

async def run_multi_store_new_items_sync():
    """Run multi-store new items sync"""
    print("🔄 Running multi-store new items sync...")
    result = await multi_store_new_items_sync.sync_new_items()
    
    if result["msg"] == "success":
        print("✅ Multi-store new items sync completed successfully!")
        print(f"   Processed: {result.get('processed', 0)} items")
        print(f"   Successful: {result.get('success', 0)} items")
        print(f"   Errors: {result.get('errors', 0)} items")
    else:
        print(f"❌ Multi-store new items sync failed: {result.get('error', 'Unknown error')}")
        sys.exit(1)

async def run_gift_cards_sync():
    """Run gift cards sync"""
    print("🔄 Running gift cards sync...")
    result = await gift_cards_sync.sync_gift_cards()
    
    if result["msg"] == "success":
        print("✅ Gift cards sync completed successfully!")
        print(f"   Processed: {result.get('processed', 0)} gift cards")
        print(f"   Successful: {result.get('success', 0)} gift cards")
        print(f"   Errors: {result.get('errors', 0)} gift cards")
    else:
        print(f"❌ Gift cards sync failed: {result.get('error', 'Unknown error')}")
        sys.exit(1)

async def main():
    """Main function"""
    if len(sys.argv) < 2:
        print("Usage: python run_sync.py <sync_type>")
        print("Available sync types:")
        print("  new-items-multi  - Sync new items from SAP to all Shopify stores (with variants)")
        print("  gift-cards       - Sync gift cards from SAP to all Shopify stores")
        print("  all              - Run all sync operations")
        sys.exit(1)
    
    sync_type = sys.argv[1].lower()
    
    try:
        if sync_type == "new-items-multi":
            await run_multi_store_new_items_sync()
        elif sync_type == "gift-cards":
            await run_gift_cards_sync()
        elif sync_type == "all":
            print("🔄 Running all sync operations...")
            await run_multi_store_new_items_sync()
            await run_gift_cards_sync()
        else:
            print(f"❌ Unknown sync type: {sync_type}")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n⚠️  Sync interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Sync failed with error: {str(e)}")
        logger.error(f"Sync failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    result = asyncio.run(multi_store_new_items_sync.sync_new_items())
    print(result) 