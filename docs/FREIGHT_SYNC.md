# Freight Prices Sync Module

This module automatically syncs freight prices from SAP to the configuration file on a daily basis.

## Overview

The freight sync process fetches freight pricing data from SAP's `/FREIGHT_PRICES` endpoint and updates the local configuration file to ensure pricing is always current.

## Components

### 1. SAP Freight Prices Service (`app/services/sap/freight_prices.py`)

- **Purpose**: Fetches freight prices from SAP API
- **Endpoint**: `GET /FREIGHT_PRICES`
- **Features**:
  - Automatic SAP authentication
  - Error handling and retry logic
  - Data parsing and transformation

### 2. Freight Sync Process (`app/sync/freight_sync.py`)

- **Purpose**: Orchestrates the sync process
- **Features**:
  - Fetches data from SAP
  - Parses and validates freight data
  - Updates configuration file
  - Creates automatic backups
  - Comprehensive logging

### 3. Daily Runner (`run_freight_sync.py`)

- **Purpose**: Executable script for daily scheduling
- **Features**:
  - User-friendly output
  - Error handling
  - Exit codes for scheduling systems

## Data Flow

```
SAP /FREIGHT_PRICES → Parse Data → Update configurations.json
```

### SAP Data Structure

The SAP endpoint returns freight data with the following structure:

```json
{
    "value": [
        {
            "U_OnlineStore": "Local",
            "U_Type": "Standard",
            "U_TotalAmount": 100.0,
            "U_FreightCode": "5",
            "U_Amount": 60.0,
            "U_FreightCode2": "4",
            "U_Amount2": 40.0
        }
    ]
}
```

### Configuration Format

The data is transformed into the configuration format:

```json
{
    "shopify": {
        "freight_config": {
            "local": {
                "100": {
                    "revenue": {"ExpenseCode": 5, "LineTotal": 60},
                    "cost": {"ExpenseCode": 4, "LineTotal": 40}
                }
            },
            "international": {
                "dhl": {
                    "ExpenseCode": 1,
                    "LineTotal": 25
                }
            }
        }
    }
}
```

## Usage

### Manual Execution

```bash
# Run the sync process manually
python run_freight_sync.py

# Or using the batch file (Windows)
run_freight_sync.bat
```

### Scheduled Execution

#### Windows Task Scheduler

1. Open Task Scheduler
2. Create Basic Task
3. Set trigger to "Daily" at desired time (e.g., 6:00 AM)
4. Set action to start program: `run_freight_sync.bat`
5. Configure to run whether user is logged on or not

#### Linux Cron

Add to crontab for daily execution at 6 AM:

```bash
# Edit crontab
crontab -e

# Add this line for daily execution at 6 AM
0 6 * * * /path/to/your/project/run_freight_sync.py
```

## Configuration

The sync process uses the existing SAP configuration from `configurations.json`:

```json
{
    "sap": {
        "server": "https://10.0.0.100:50000/b1s/v1",
        "company": "JudeBenHalim_Test",
        "user": "manager",
        "password": "Azmjude$1"
    }
}
```

## Logging

The process logs all activities to the standard log file (`logs/sync.log`) with the following information:

- SAP API calls and responses
- Data parsing results
- Configuration file updates
- Error messages and stack traces

## Error Handling

The sync process includes comprehensive error handling:

1. **SAP Connection Issues**: Automatic retry with exponential backoff
2. **Data Parsing Errors**: Graceful handling with detailed error messages
3. **File System Issues**: Backup creation and rollback capabilities
4. **Configuration Validation**: Data structure validation before updates

## Backup Strategy

Before updating the configuration file, the system:

1. Creates a timestamped backup: `configurations.json.backup.YYYYMMDD_HHMMSS`
2. Updates the main configuration file
3. Logs the backup location for recovery if needed

## Monitoring

### Success Indicators

- ✅ "Freight sync completed successfully" message
- Updated freight configuration in `configurations.json`
- Backup file created with timestamp

### Failure Indicators

- ❌ Error messages in console output
- Non-zero exit code
- Error entries in log files

## Troubleshooting

### Common Issues

1. **SAP Authentication Failed**
   - Check SAP credentials in configuration
   - Verify SAP server connectivity
   - Check SAP session timeout settings

2. **No Data Received**
   - Verify FREIGHT_PRICES endpoint is accessible
   - Check SAP user permissions
   - Review SAP data availability

3. **Configuration Update Failed**
   - Check file permissions
   - Verify disk space availability
   - Review file locking issues

### Debug Mode

For detailed debugging, check the log file:

```bash
tail -f logs/sync.log
```

## Integration with Existing System

The freight sync process integrates seamlessly with the existing system:

- Uses the same SAP client and authentication
- Follows the same logging patterns
- Maintains configuration file structure
- Compatible with existing sync processes

## Future Enhancements

Potential improvements for the freight sync system:

1. **Real-time Updates**: Webhook-based updates instead of daily sync
2. **Multiple Store Support**: Enhanced support for multiple store configurations
3. **Advanced Validation**: More sophisticated data validation rules
4. **Performance Optimization**: Caching and incremental updates
5. **Monitoring Dashboard**: Web-based monitoring interface
