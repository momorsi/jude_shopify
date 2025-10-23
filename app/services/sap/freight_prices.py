import asyncio
from typing import Dict, Any, List, Optional
from app.services.sap.client import sap_client
from app.utils.logging import logger


class SAPFreightPricesService:
    """Service to fetch freight prices from SAP FREIGHT_PRICES endpoint"""
    
    def __init__(self):
        self.sap_client = sap_client
    
    async def get_freight_prices(self) -> Dict[str, Any]:
        """
        Fetch freight prices from SAP FREIGHT_PRICES endpoint
        
        Returns:
            Dict containing the response from SAP API
        """
        try:
            logger.info("Fetching freight prices from SAP...")
            
            # Make request to FREIGHT_PRICES endpoint
            result = await self.sap_client._make_request(
                method='GET',
                endpoint='FREIGHT_PRICES',
                login_required=True
            )
            
            if result.get("msg") == "success":
                logger.info(f"Successfully fetched freight prices from SAP")
                return result
            else:
                logger.error(f"Failed to fetch freight prices: {result.get('error', 'Unknown error')}")
                return result
                
        except Exception as e:
            logger.error(f"Error fetching freight prices: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    def parse_freight_data(self, freight_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Parse SAP freight data and convert to configuration format
        
        Args:
            freight_data: List of freight price records from SAP
            
        Returns:
            Dict containing parsed freight configuration
        """
        try:
            parsed_config = {
                "local": {},
                "international": {}
            }
            
            for record in freight_data:
                online_store = record.get("U_OnlineStore", "").lower()
                freight_type = record.get("U_Type", "").lower()
                total_amount = record.get("U_TotalAmount", 0)
                freight_code = record.get("U_FreightCode", "")
                amount = record.get("U_Amount", 0)
                freight_code2 = record.get("U_FreightCode2")
                amount2 = record.get("U_Amount2", 0)
                
                # Skip if no total amount
                if not total_amount:
                    continue
                
                # Convert total amount to string for key matching
                total_amount_str = str(int(total_amount))
                
                if online_store == "local":
                    # For local store, create structure with revenue and cost
                    parsed_config["local"][total_amount_str] = {
                        "revenue": {
                            "ExpenseCode": int(freight_code) if freight_code else 4,
                            "LineTotal": int(amount) if amount else 0
                        },
                        "cost": {
                            "ExpenseCode": int(freight_code2) if freight_code2 else 6,
                            "LineTotal": int(amount2) if amount2 else 0
                        }
                    }
                    
                elif online_store == "international":
                    # For international store, create simpler structure
                    if freight_type == "standard":
                        parsed_config["international"]["dhl"] = {
                            "ExpenseCode": int(freight_code) if freight_code else 1,
                            "LineTotal": int(amount) if amount else 0
                        }
                    else:
                        # Handle other international types
                        key = freight_type if freight_type else "dhl"
                        parsed_config["international"][key] = {
                            "ExpenseCode": int(freight_code) if freight_code else 1,
                            "LineTotal": int(amount) if amount else 0
                        }
            
            logger.info(f"Parsed freight configuration: {len(parsed_config['local'])} local entries, {len(parsed_config['international'])} international entries")
            return parsed_config
            
        except Exception as e:
            logger.error(f"Error parsing freight data: {str(e)}")
            return {"local": {}, "international": {}}


# Create singleton instance
sap_freight_prices_service = SAPFreightPricesService()
