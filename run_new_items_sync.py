"""
Simple script to run the new items sync process
Uses the automatic logging version
"""

import asyncio
import sys
import os

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.sync.new_items_multi_store import multi_store_new_items_sync
from app.utils.logging import logger

async def main():
    """Run the new items sync process"""
    print("Running New Items Multi-Store Sync")
    print("=" * 50)
    print("Using automatic logging version")
    print("=" * 50)
    
    try:
        # Run the sync process
        print("Starting sync...")
        result = await multi_store_new_items_sync.sync_new_items()
        
        print(f"\nSync completed!")
        print(f"Result: {result}")
        
        if result["msg"] == "success":
            print(f"✅ Success!")
            print(f"   - Processed: {result.get('processed', 0)}")
            print(f"   - Successful: {result.get('success', 0)}")
            print(f"   - Errors: {result.get('errors', 0)}")
        else:
            print(f"❌ Failed: {result.get('error', 'Unknown error')}")
            
    except Exception as e:
        print(f"❌ Exception occurred: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 50)
    print("Check your SAP U_API_LOG table for detailed logging information.")
    print("All API calls have been automatically logged!")

if __name__ == "__main__":
    asyncio.run(main()) 