# Shopify-SAP Integration Executable

This document explains how to build and use the executable version of the Shopify-SAP Integration.

## 🏗️ Building the Executable

### Prerequisites
- Python 3.8 or higher
- All dependencies installed (`pip install -r requirements.txt`)

### Build Steps

1. **Install PyInstaller** (if not already installed):
   ```bash
   pip install pyinstaller
   ```

2. **Run the build script**:
   ```bash
   python build_exe.py
   ```

3. **Or build manually**:
   ```bash
   pyinstaller shopify_sap_integration.spec
   ```

### Build Output
The executable will be created in the `dist/` directory:
- `ShopifySAPIntegration.exe` - Main executable
- `run_sync.bat` - Batch file for easy execution
- `configurations.json` - Configuration file

## 🚀 Using the Executable

### Method 1: Double-click the executable
Simply double-click `ShopifySAPIntegration.exe` to run all enabled syncs.

### Method 2: Use the batch file
Double-click `run_sync.bat` for a more user-friendly experience.

### Method 3: Command line
```bash
./ShopifySAPIntegration.exe
```

## ⚙️ Configuration

### Enable/Disable Syncs
Edit `configurations.json` to enable or disable specific sync processes:

```json
{
  "new_items_enabled": true,
  "stock_sync_enabled": true,
  "master_data_enabled": false,
  "orders_enabled": false,
  "gift_cards_enabled": false
}
```

### Available Syncs
- **new_items**: Sync new products from SAP to Shopify
- **stock**: Sync inventory changes from SAP to Shopify
- **master_data**: Sync product data from Shopify to SAP
- **orders**: Sync orders from Shopify to SAP
- **gift_cards**: Sync gift cards from SAP to Shopify

## 📋 What the Executable Does

1. **Reads Configuration**: Checks which syncs are enabled in `configurations.json`
2. **Runs Enabled Syncs**: Executes all enabled sync processes in sequence
3. **Logs Results**: Shows detailed results for each sync
4. **SAP Logging**: All operations are logged to SAP's API log table
5. **Error Handling**: Graceful error handling with detailed error messages

## 🔧 Troubleshooting

### Common Issues

1. **"No sync processes are enabled"**
   - Edit `configurations.json` and enable at least one sync

2. **"Failed to connect to SAP"**
   - Check SAP server connectivity
   - Verify credentials in configuration

3. **"Failed to connect to Shopify"**
   - Check internet connection
   - Verify Shopify API credentials

4. **Executable not found**
   - Run the build script again
   - Check that PyInstaller is installed

### Logs
- Console output shows real-time progress
- SAP API log table contains detailed operation logs
- Check the console for error messages

## 📁 File Structure (After Build)

```
dist/
├── ShopifySAPIntegration.exe    # Main executable
├── run_sync.bat                 # Batch file for easy execution
├── configurations.json          # Configuration file
└── [other PyInstaller files]    # Required runtime files
```

## 🔄 Scheduling

### Windows Task Scheduler
1. Open Task Scheduler
2. Create Basic Task
3. Set trigger (e.g., every 15 minutes)
4. Action: Start a program
5. Program: `C:\path\to\ShopifySAPIntegration.exe`
6. Start in: `C:\path\to\dist\`

### Example Schedule
- **New Items**: Every 30 minutes
- **Stock Changes**: Every 15 minutes
- **Master Data**: Once daily
- **Orders**: Every 5 minutes
- **Gift Cards**: Every hour

## 🛡️ Security Notes

- Keep `configurations.json` secure (contains API credentials)
- Run executable with appropriate permissions
- Consider using Windows service for production deployment
- Monitor logs for any security issues

## 📞 Support

If you encounter issues:
1. Check the console output for error messages
2. Verify configuration settings
3. Check SAP and Shopify connectivity
4. Review the SAP API log table for detailed error information 