"""
Test script to run the enhanced orders sync with payment ID and address logging
"""

import asyncio
import sys
import os

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.sync.sales.orders_sync import OrdersSalesSync
from app.utils.logging import logger


async def test_orders_sync():
    """
    Test the enhanced orders sync with payment ID and address logging
    """
    print("🔄 Testing Enhanced Orders Sync")
    print("="*60)
    
    try:
        # Create orders sync instance
        orders_sync = OrdersSalesSync()
        
        # Run the sync
        print("Starting orders sync...")
        result = await orders_sync.sync_orders()
        
        if result["msg"] == "success":
            print(f"\n✅ Orders sync completed successfully!")
            print(f"   - Processed: {result.get('processed', 0)}")
            print(f"   - Successful: {result.get('success', 0)}")
            print(f"   - Errors: {result.get('errors', 0)}")
        else:
            print(f"\n❌ Orders sync failed: {result.get('error')}")
            
    except Exception as e:
        print(f"\n❌ Exception occurred: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_orders_sync())
