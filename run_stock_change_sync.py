"""
Script to run the stock change sync process using the MASHURA_StockChangeB1SLQuery view
"""

import asyncio
import sys
import os

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.sync.inventory import sync_stock_change_view
from app.utils.logging import logger

async def main():
    print("Running Stock Change Sync (MASHURA_StockChangeB1SLQuery)")
    print("=" * 50)
    try:
        result = await sync_stock_change_view()
        print(f"\nStock change sync completed!")
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
    print("All inventory updates have been automatically logged!")

if __name__ == "__main__":
    asyncio.run(main()) 