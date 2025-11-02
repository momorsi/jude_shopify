# Shopify-SAP Integration - Continuous Executable

This executable runs all enabled sync processes continuously, with each process running on its own configured interval.

## Features

- **Continuous Operation**: Runs indefinitely until manually stopped
- **Independent Intervals**: Each sync process has its own interval (configured in `configurations.json`)
- **Graceful Shutdown**: Press Ctrl+C to stop all syncs gracefully
- **Runtime Statistics**: Shows total runtime when stopped
- **Automatic Logging**: All API calls are automatically logged to SAP U_API_LOG table

## How to Run

### Option 1: Using the Batch File (Recommended)
1. Double-click `run_continuous_sync.bat`
2. The batch file will show information about the continuous mode
3. Press any key to start the sync processes
4. Press Ctrl+C to stop all syncs gracefully

### Option 2: Direct Executable
1. Double-click `ShopifySAPIntegration.exe`
2. The continuous sync will start immediately
3. Press Ctrl+C to stop all syncs gracefully

## Configuration

The executable uses the `configurations.json` file to determine:
- Which sync processes are enabled
- The interval for each sync process (in minutes)
- All other sync settings

### Sync Process Intervals

Each sync process can be configured with its own interval:

- **New Items**: `new_items_interval` (minutes)
- **Inventory**: `inventory_interval` (minutes)  
- **Item Changes**: `item_changes_interval` (minutes)
- **Price Changes**: `price_changes_interval` (minutes)
- **Sales Orders**: `sales_orders_interval` (minutes)
- **Payment Recovery**: `payment_recovery_interval` (minutes)
- **Returns**: `returns_interval` (minutes)
- **Freight Prices**: Daily at `freight_prices_run_time` in `freight_prices_timezone`

## Example Output

```
============================================================
🔄 Shopify-SAP Integration - Continuous Mode
============================================================
⏰ Started at: 2024-01-15 14:30:00

✅ Enabled Sync Processes:
   📦 New Items: Every 30 minutes
   📊 Inventory: Every 15 minutes
   🛒 Sales Orders: Every 10 minutes
   💳 Payment Recovery: Every 60 minutes

🔄 Starting continuous sync processes...
Press Ctrl+C to stop all syncs gracefully
--------------------------------------------------------------------------------
```

## Stopping the Application

- **Graceful Shutdown**: Press Ctrl+C to stop all syncs gracefully
- The application will show runtime statistics before exiting
- All running sync processes will be stopped cleanly

## Logging

- All sync operations are logged to the console
- Detailed API calls are logged to SAP U_API_LOG table
- Error logs are written to `logs/sync.log`

## Requirements

- Windows 10/11
- SAP system access (configured in `configurations.json`)
- Shopify store access (configured in `configurations.json`)
- Network connectivity to both SAP and Shopify

## Troubleshooting

1. **No syncs enabled**: Check `configurations.json` and enable at least one sync process
2. **Configuration errors**: Verify all required settings in `configurations.json`
3. **Network issues**: Check connectivity to SAP and Shopify systems
4. **Permission issues**: Ensure the executable has necessary permissions

## File Structure

```
dist/
├── ShopifySAPIntegration.exe          # Main executable
├── run_continuous_sync.bat           # Batch file for easy execution
└── configurations.json               # Configuration file
```
