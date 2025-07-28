"""
Customer Management for Sales Module
Handles customer creation and lookup in SAP
"""

import asyncio
from typing import Dict, Any, Optional, List
from app.services.sap.client import sap_client
from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.core.config import config_settings
from app.utils.logging import logger, log_sync_event


class CustomerManager:
    """
    Manages customer operations between Shopify and SAP
    """
    
    def __init__(self):
        self.batch_size = config_settings.orders_batch_size
    
    async def find_customer_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """
        Find customer in SAP by phone number
        """
        try:
            # Clean phone number (remove spaces, dashes, etc.)
            clean_phone = self._clean_phone_number(phone)
            
            # Search in SAP Business Partners
            filter_query = f"Phone1 eq '{clean_phone}' or Phone2 eq '{clean_phone}' or Cellular eq '{clean_phone}'"
            result = await sap_client.get_entities(
                entity_type='BusinessPartners',
                filter_query=filter_query,
                top=1
            )
            
            if result["msg"] == "failure":
                logger.error(f"Failed to search customer by phone: {result.get('error')}")
                return None
            
            customers = result["data"].get("value", [])
            if customers:
                return customers[0]
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding customer by phone: {str(e)}")
            return None
    
    async def create_customer_in_sap(self, customer_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Create new customer in SAP
        """
        try:
            # Prepare customer data for SAP
            sap_customer_data = self._map_shopify_customer_to_sap(customer_data)
            
            # Create customer in SAP
            result = await sap_client._make_request(
                method='POST',
                endpoint='BusinessPartners',
                data=sap_customer_data
            )
            
            if result["msg"] == "failure":
                logger.error(f"Failed to create customer in SAP: {result.get('error')}")
                return None
            
            created_customer = result["data"]
            logger.info(f"Created customer in SAP: {created_customer.get('CardCode', 'Unknown')}")
            
            return created_customer
            
        except Exception as e:
            logger.error(f"Error creating customer in SAP: {str(e)}")
            return None
    
    async def get_or_create_customer(self, shopify_customer: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Get existing customer or create new one in SAP
        """
        try:
            # Extract phone number from customer
            phone = self._extract_phone_from_customer(shopify_customer)
            
            if not phone:
                logger.warning("No phone number found in customer data")
                return None
            
            # Try to find existing customer
            existing_customer = await self.find_customer_by_phone(phone)
            
            if existing_customer:
                logger.info(f"Found existing customer: {existing_customer.get('CardCode', 'Unknown')}")
                return existing_customer
            
            # Create new customer
            logger.info("Creating new customer in SAP")
            new_customer = await self.create_customer_in_sap(shopify_customer)
            
            return new_customer
            
        except Exception as e:
            logger.error(f"Error in get_or_create_customer: {str(e)}")
            return None
    
    def _clean_phone_number(self, phone: str) -> str:
        """
        Clean phone number by removing spaces, dashes, and other characters
        """
        if not phone:
            return ""
        
        # Remove common separators
        cleaned = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        
        # Remove country code if present (assuming +20 for Egypt)
        if cleaned.startswith("+20"):
            cleaned = cleaned[3:]
        elif cleaned.startswith("20"):
            cleaned = cleaned[2:]
        
        return cleaned
    
    def _extract_phone_from_customer(self, customer: Dict[str, Any]) -> Optional[str]:
        """
        Extract phone number from Shopify customer data
        """
        # Try different possible phone fields
        phone_fields = ['phone', 'Phone', 'phoneNumber', 'PhoneNumber']
        
        for field in phone_fields:
            if customer.get(field):
                return customer[field]
        
        # Check in addresses if available
        addresses = customer.get('addresses', [])
        for address in addresses:
            if address.get('phone'):
                return address['phone']
        
        return None
    
    def _map_shopify_customer_to_sap(self, shopify_customer: Dict[str, Any]) -> Dict[str, Any]:
        """
        Map Shopify customer data to SAP Business Partner format
        """
        # Extract basic information
        first_name = shopify_customer.get('firstName', '')
        last_name = shopify_customer.get('lastName', '')
        email = shopify_customer.get('email', '')
        phone = self._extract_phone_from_customer(shopify_customer)
        
        # Generate SAP CardCode (you might want to implement a specific logic)
        card_code = self._generate_card_code(first_name, last_name)
        
        sap_customer = {
            "CardCode": card_code,
            "CardName": f"{first_name} {last_name}".strip(),
            "CardType": "cCustomer",  # Customer type
            "EmailAddress": email,
            "Phone1": phone,
            "Cellular": phone,  # Also store in cellular field
            "Active": "Y",
            "U_ShopifyCustomerID": str(shopify_customer.get('id', '')),
            "U_ShopifyEmail": email
        }
        
        # Add address information if available
        addresses = shopify_customer.get('addresses', [])
        if addresses:
            default_address = addresses[0]  # Use first address as default
            sap_customer.update({
                "Address": default_address.get('address1', ''),
                "Address2": default_address.get('address2', ''),
                "City": default_address.get('city', ''),
                "State": default_address.get('province', ''),
                "ZipCode": default_address.get('zip', ''),
                "Country": default_address.get('country', '')
            })
        
        return sap_customer
    
    def _generate_card_code(self, first_name: str, last_name: str) -> str:
        """
        Generate a unique CardCode for SAP customer
        This is a simple implementation - you might want to enhance it
        """
        import uuid
        
        # Create a base code from name
        base_code = f"{first_name[:3]}{last_name[:3]}".upper()
        
        # Add a unique suffix
        unique_suffix = str(uuid.uuid4())[:8].upper()
        
        return f"{base_code}{unique_suffix}"
    
    async def update_customer_shopify_mapping(self, sap_customer: Dict[str, Any], 
                                            shopify_customer_id: str) -> bool:
        """
        Update SAP customer with Shopify mapping information
        """
        try:
            update_data = {
                "U_ShopifyCustomerID": str(shopify_customer_id),
                "U_ShopifyEmail": sap_customer.get('EmailAddress', '')
            }
            
            result = await sap_client.update_entity(
                entity_type='BusinessPartners',
                entity_id=sap_customer['CardCode'],
                entity_data=update_data
            )
            
            if result["msg"] == "success":
                logger.info(f"Updated customer mapping: {sap_customer['CardCode']}")
                return True
            else:
                logger.error(f"Failed to update customer mapping: {result.get('error')}")
                return False
                
        except Exception as e:
            logger.error(f"Error updating customer mapping: {str(e)}")
            return False 