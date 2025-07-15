import httpx
import datetime
import asyncio
from typing import Dict, Any, Optional
from tenacity import retry, stop_after_attempt, wait_exponential
from app.core.config import config_settings
from app.utils.logging import logger

class SAPLoggingClient:
    """SAP Client specifically for logging operations - no automatic logging to prevent recursion"""
    
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
            
            async with httpx.AsyncClient(verify=False) as client:
                response = await client.post(url=url, json=payload, headers=headers, timeout=self.timeout)
                
                if response.status_code == httpx.codes.OK:
                    self.session_token = response.cookies.get('B1SESSION', '')
                    self.session_time = datetime.datetime.now()
                    logger.info("SAP logging client login successful")
                    return True
                else:
                    logger.error(f"SAP logging client login failed: {response.status_code} - {response.text}")
                    return False
                    
        except Exception as e:
            logger.error(f"SAP logging client login error: {str(e)}")
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
        """Make HTTP request to SAP without automatic logging to prevent recursion"""
        
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
                    logger.info("SAP logging client session expired, attempting to re-login")
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
                    
                    return {"msg": "success", "data": response_data}
                else:
                    return {"msg": "failure", "error": f"HTTP {response.status_code}: {response.text}"}
                    
        except Exception as e:
            error_msg = f"SAP logging client request error: {str(e)}"
            logger.error(error_msg)
            return {"msg": "failure", "error": error_msg}
    
    async def create_entity(self, entity_type: str, entity_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create entity in SAP without logging"""
        return await self._make_request('POST', entity_type, data=entity_data)
    
    async def update_entity(self, entity_type: str, entity_id: str, 
                          entity_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update entity in SAP without logging"""
        endpoint = f"{entity_type}('{entity_id}')"
        return await self._make_request('PATCH', endpoint, data=entity_data)

# Create singleton instance
sap_logging_client = SAPLoggingClient() 