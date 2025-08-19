import datetime
import json
from typing import Dict, Any, Optional
from app.services.sap.logging_client import sap_logging_client
from app.utils.logging import logger

class SAPAPILogger:
    """SAP API Logger for logging API calls to SAP tables similar to reference project"""
    
    def __init__(self):
        self.sap_client = sap_logging_client
    
    async def log_api_call(self, 
                          server: str,
                          endpoint: str, 
                          request_data: Dict[str, Any] = None,
                          response_data: Dict[str, Any] = None,
                          status: str = "success",
                          reference: str = "",
                          action: str = "",
                          value: str = "",
                          order_id: str = "") -> bool:
        """
        Log API call to SAP table similar to sl_add_log function from reference project
        
        Args:
            server: Server name (e.g., 'shopify', 'sap')
            endpoint: API endpoint
            request_data: Request data (will be converted to JSON string)
            response_data: Response data (will be converted to JSON string)
            status: Status of the API call ('success', 'failure', 'error')
            reference: Reference information
            action: Action being performed
            value: Additional value information
        """
        try:
            # Truncate fields according to SAP API_LOG table limits
            # Server: Alphanumeric (50), EndPoint: Alphanumeric (100), Action: Alphanumeric (20), Value: Alphanumeric (250)
            truncated_server = str(server)[:50] if server else ""
            truncated_endpoint = str(endpoint)[:100] if endpoint else ""
            truncated_action = str(action)[:20] if action else ""
            truncated_value = str(value)[:250] if value else ""
            truncated_reference = str(reference)[:60] if reference else ""
            truncated_status = str(status)[:20] if status else ""
            
            # Add order ID to reference if provided
            final_reference = truncated_reference
            if order_id:
                if final_reference:
                    final_reference = f"{final_reference} | Order: {order_id}"
                else:
                    final_reference = f"Order: {order_id}"
            
            # Prepare the log data with truncated fields
            log_data = {
                'U_Server': truncated_server,
                'U_EndPoint': truncated_endpoint,
                'U_Request': json.dumps(request_data) if request_data else "",
                'U_Response': json.dumps(response_data) if response_data else "",
                'U_Status': truncated_status,
                'U_Reference': final_reference[:60],  # Truncate to 60 chars
                'U_LogDate': datetime.datetime.now().strftime('%Y-%m-%d'),
                'U_LogTime': datetime.datetime.now().strftime('%H%M'),
                'U_Action': truncated_action,
                'U_Value': truncated_value
            }
            
            # Add to SAP table using the service layer approach
            result = await self.sap_client.create_entity('U_API_LOG', log_data)
            
            if result.get('msg') == 'success':
                logger.info(f"API log added to SAP: {server} - {endpoint} - {status}")
                return True
            else:
                logger.error(f"Failed to add API log to SAP: {result.get('error', 'Unknown error')}")
                return False
                
        except Exception as e:
            logger.error(f"Error logging API call to SAP: {str(e)}")
            return False
    
    async def log_sync_event(self, 
                           sync_code: int,
                           sync_date: str = None,
                           sync_time: str = None) -> bool:
        """
        Log sync event to SAP table similar to sl_add_sync function from reference project
        
        Args:
            sync_code: Sync code identifier
            sync_date: Sync date (YYYY-MM-DD format)
            sync_time: Sync time (HHMM format)
        """
        try:
            if not sync_date:
                sync_date = datetime.datetime.now().strftime('%Y-%m-%d')
            if not sync_time:
                sync_time = datetime.datetime.now().strftime('%H%M')
            
            # Prepare the sync log data
            sync_data = {
                'U_SyncDate': sync_date,
                'U_SyncTime': sync_time
            }
            
            # Update sync log in SAP
            result = await self.sap_client.update_entity('U_SYNC_LOG', str(sync_code), sync_data)
            
            if result.get('msg') == 'success':
                logger.info(f"Sync log updated in SAP: Code {sync_code} - {sync_date} {sync_time}")
                return True
            else:
                logger.error(f"Failed to update sync log in SAP: {result.get('error', 'Unknown error')}")
                return False
                
        except Exception as e:
            logger.error(f"Error logging sync event to SAP: {str(e)}")
            return False

# Global instance for easy access
sap_api_logger = SAPAPILogger()

# Convenience functions for backward compatibility with reference project style
async def sl_add_log(server: str, endpoint: str, request_data: Dict[str, Any] = None,
                    response_data: Dict[str, Any] = None, status: str = "success",
                    reference: str = "", action: str = "", value: str = "", order_id: str = "") -> bool:
    """Convenience function that matches the reference project's sl_add_log signature"""
    return await sap_api_logger.log_api_call(
        server=server,
        endpoint=endpoint,
        request_data=request_data,
        response_data=response_data,
        status=status,
        reference=reference,
        action=action,
        value=value,
        order_id=order_id
    )

async def sl_add_sync(sync_code: int, sync_date: str = None, sync_time: str = None) -> bool:
    """Convenience function that matches the reference project's sl_add_sync signature"""
    return await sap_api_logger.log_sync_event(
        sync_code=sync_code,
        sync_date=sync_date,
        sync_time=sync_time
    ) 