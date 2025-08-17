import httpx
import datetime
import asyncio
from typing import Dict, Any, Optional, List
from tenacity import retry, stop_after_attempt, wait_exponential
from app.core.config import config_settings
from app.utils.logging import logger, log_api_call


class SAPClient:
    def __init__(self):
        self.session_token: str = ""
        self.session_time: datetime.datetime = datetime.datetime.now()
        self.timeout = httpx.Timeout(config_settings.sap_timeout, read=None)
        self.base_url = config_settings.sap_server.rstrip('/')
        
    async def _login(self) -> bool:
        """Login to SAP and get session token"""
        try:
            payload = {
                'CompanyDB': config_settings.sap_company,
                'Password': config_settings.sap_password,
                'UserName': config_settings.sap_user
            }
            headers = {'Content-Type': 'application/json', 'Accept': '*/*'}
            url = f"{self.base_url}/Login"
            
            log_api_call(
                service="sap",
                endpoint="login",
                request_data={"company": config_settings.sap_company, "user": config_settings.sap_user}
            )
            
            async with httpx.AsyncClient(verify=False) as client:
                response = await client.post(url=url, json=payload, headers=headers, timeout=self.timeout)
                
                if response.status_code == httpx.codes.OK:
                    self.session_token = response.cookies.get('B1SESSION', '')
                    self.session_time = datetime.datetime.now()
                    
                    log_api_call(
                        service="sap",
                        endpoint="login",
                        response_data={"status": "success"},
                        status="success"
                    )
                    
                    logger.info("SAP login successful")
                    return True
                else:
                    log_api_call(
                        service="sap",
                        endpoint="login",
                        response_data={"status": "failed", "status_code": response.status_code},
                        status="failure"
                    )
                    
                    logger.error(f"SAP login failed: {response.status_code} - {response.text}")
                    return False
                    
        except Exception as e:
            logger.error(f"SAP login error: {str(e)}")
            return False
    
    def _is_session_valid(self) -> bool:
        """Check if current session is still valid (less than 30 minutes old)"""
        if not self.session_token:
            return False
        
        # SAP sessions typically expire after 30 minutes
        session_age = datetime.datetime.now() - self.session_time
        return session_age.total_seconds() < 1800  # 30 minutes
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def _make_request(self, method: str, endpoint: str, data: Dict = None, 
                           params: Dict = None, login_required: bool = True) -> Dict[str, Any]:
        """Make HTTP request to SAP with automatic session management"""
        
        # Ensure we have a valid session
        if login_required and not self._is_session_valid():
            if not await self._login():
                return {"msg": "failure", "error": "Failed to login to SAP"}
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': '*/*'
        }
        
        if self.session_token:
            headers['Cookie'] = f'B1SESSION={self.session_token}'
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        try:
            # Skip logging for U_SHOPIFY_MAPPING_2 endpoint as requested by user
            if endpoint != 'U_SHOPIFY_MAPPING_2':
                log_api_call(
                    service="sap",
                    endpoint=endpoint,
                    request_data={"method": method, "url": url, "data": data, "params": params}
                )
            
            async with httpx.AsyncClient(verify=False) as client:
                if method.upper() == 'GET':
                    response = await client.get(url=url, headers=headers, params=params, timeout=self.timeout)
                elif method.upper() == 'POST':
                    response = await client.post(url=url, json=data, headers=headers, timeout=self.timeout)
                elif method.upper() == 'PATCH':
                    response = await client.patch(url=url, json=data, headers=headers, timeout=self.timeout)
                elif method.upper() == 'PUT':
                    response = await client.put(url=url, json=data, headers=headers, timeout=self.timeout)
                elif method.upper() == 'DELETE':
                    response = await client.delete(url=url, headers=headers, timeout=self.timeout)
                else:
                    return {"msg": "failure", "error": f"Unsupported HTTP method: {method}"}
                
                # Handle session expiration
                if response.status_code == 401 and login_required:
                    logger.info("SAP session expired, attempting to re-login")
                    if await self._login():
                        # Retry the request with new session
                        return await self._make_request(method, endpoint, data, params, login_required=False)
                    else:
                        return {"msg": "failure", "error": "Session expired and re-login failed"}
                
                # Handle successful responses
                if response.status_code in [200, 201, 204]:
                    response_data = None
                    if response.status_code != 204:  # No content
                        try:
                            response_data = response.json()
                        except:
                            response_data = response.text
                    
                    # Skip logging for U_SHOPIFY_MAPPING_2 endpoint as requested by user
                    if endpoint != 'U_SHOPIFY_MAPPING_2':
                        log_api_call(
                            service="sap",
                            endpoint=endpoint,
                            response_data=response_data,
                            status="success"
                        )
                    
                    return {"msg": "success", "data": response_data}
                else:
                    # Skip logging for U_SHOPIFY_MAPPING_2 endpoint as requested by user
                    if endpoint != 'U_SHOPIFY_MAPPING_2':
                        log_api_call(
                            service="sap",
                            endpoint=endpoint,
                            response_data={"status_code": response.status_code, "text": response.text},
                            status="failure"
                        )
                    
                    return {"msg": "failure", "error": f"HTTP {response.status_code}: {response.text}"}
                    
        except Exception as e:
            error_msg = f"SAP request error: {str(e)}"
            logger.error(error_msg)
            

                
            return {"msg": "failure", "error": error_msg}
    
    # Generic CRUD Methods (for flexibility)
    async def get_entities(self, entity_type: str, filter_query: str = None, 
                          orderby: str = None, top: int = 50, 
                          entity_id: str = None) -> Dict[str, Any]:
        """Generic method to get entities from SAP
        
        Args:
            entity_type: The entity type (e.g., 'Items', 'Orders', 'BusinessPartners')
            filter_query: OData filter query
            orderby: OData orderby clause
            top: Number of records to return
            entity_id: Specific entity ID for single record retrieval
        """
        params = {}
        if filter_query:
            params['$filter'] = filter_query
        if orderby:
            params['$orderby'] = orderby
        if top:
            params['$top'] = top
        
        endpoint = f"{entity_type}('{entity_id}')" if entity_id else entity_type
        return await self._make_request('GET', endpoint, params=params)
    
    async def update_entity(self, entity_type: str, entity_id: str, 
                          entity_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generic method to update entities in SAP"""
        endpoint = f"{entity_type}('{entity_id}')"
        return await self._make_request('PATCH', endpoint, data=entity_data)

    # Product/Item Methods
    async def get_items(self, filter_query: str = None, orderby: str = None, 
                       top: int = 50) -> Dict[str, Any]:
        """Get items from SAP"""
        params = {}
        if filter_query:
            params['$filter'] = filter_query
        if orderby:
            params['$orderby'] = orderby
        if top:
            params['$top'] = top
        
        return await self._make_request('GET', 'Items', params=params)
    
    async def update_item(self, item_code: str, item_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update existing item in SAP"""
        return await self._make_request('PATCH', f"Items('{item_code}')", data=item_data)
    
    # Inventory Methods
    async def get_inventory_changes(self, filter_query: str = None) -> Dict[str, Any]:
        """Get inventory changes from SAP"""
        params = {}
        if filter_query:
            params['$filter'] = filter_query
        
        return await self._make_request('GET', 'sml.svc/QTY_CHANGE', params=params)
    
    # Custom Query Methods (for your specific endpoints)
    async def get_new_items(self, store_key: str = None) -> Dict[str, Any]:
        """Get new items from the new SAP view endpoint, with optional store filter"""
        endpoint = 'view.svc/MASHURA_New_ItemsB1SLQuery'
        # Get all items first, then filter in application code to avoid SQL Server OData issues
        result = await self._make_request('GET', endpoint)
        
        if result["msg"] == "success" and store_key:
            # Filter the results in application code
            items = result["data"].get("value", [])
            filtered_items = [item for item in items if item.get("Shopify_Store") == store_key]
            result["data"]["value"] = filtered_items
            
        return result

    async def add_shopify_mapping(self, mapping_data: dict) -> dict:
        """Add a mapping row to the SAP Shopify mapping table."""
        return await self._make_request('POST', 'U_SHOPIFY_MAPPING_2', data=mapping_data)

# Create singleton instance
sap_client = SAPClient() 

# Usage Examples:
# 
# Specific Named Methods (Recommended for common operations):
# - await sap_client.get_items(filter_query="ItemCode eq 'ITEM001'")
# - await sap_client.get_orders(top=100, orderby="DocDate desc")
# - await sap_client.create_business_partner(bp_data={...})
#
# Generic Methods (For flexibility and new endpoints):
# - await sap_client.get_entities('Invoices', filter_query="DocDate gt datetime'2024-01-01'")
# - await sap_client.get_entities('Items', entity_id='ITEM001')  # Get single item
# - await sap_client.create_entity('Invoices', invoice_data={...})
# - await sap_client.update_entity('Orders', '12345', order_data={...})
# - await sap_client.delete_entity('Items', 'ITEM001') 