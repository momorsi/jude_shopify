import asyncio
import json
import os
from datetime import datetime
from typing import Dict, Any
from app.services.sap.freight_prices import sap_freight_prices_service
from app.utils.logging import logger


class FreightSync:
    """Sync freight prices from SAP to configuration file"""
    
    def __init__(self, config_file_path: str = "configurations.json"):
        self.config_file_path = config_file_path
        self.freight_service = sap_freight_prices_service
    
    async def sync_freight_prices(self) -> Dict[str, Any]:
        """
        Main method to sync freight prices from SAP to configuration file
        
        Returns:
            Dict containing sync results
        """
        try:
            logger.info("Starting freight prices sync...")
            
            # Step 1: Fetch freight prices from SAP
            sap_result = await self.freight_service.get_freight_prices()
            
            if sap_result.get("msg") != "success":
                logger.error(f"Failed to fetch freight prices from SAP: {sap_result.get('error')}")
                return {
                    "success": False,
                    "error": f"SAP fetch failed: {sap_result.get('error')}",
                    "timestamp": datetime.now().isoformat()
                }
            
            # Step 2: Parse the freight data
            freight_data = sap_result.get("data", {}).get("value", [])
            if not freight_data:
                logger.warning("No freight data received from SAP")
                return {
                    "success": False,
                    "error": "No freight data received from SAP",
                    "timestamp": datetime.now().isoformat()
                }
            
            parsed_config = self.freight_service.parse_freight_data(freight_data)
            
            # Step 3: Update configuration file
            update_result = await self._update_configuration_file(parsed_config)
            
            if update_result["success"]:
                logger.info("Freight prices sync completed successfully")
                return {
                    "success": True,
                    "message": "Freight prices updated successfully",
                    "local_entries": len(parsed_config.get("local", {})),
                    "international_entries": len(parsed_config.get("international", {})),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                logger.error(f"Failed to update configuration file: {update_result.get('error')}")
                return {
                    "success": False,
                    "error": f"Configuration update failed: {update_result.get('error')}",
                    "timestamp": datetime.now().isoformat()
                }
                
        except Exception as e:
            logger.error(f"Error during freight sync: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    async def _update_configuration_file(self, new_freight_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update the configuration file with new freight data
        
        Args:
            new_freight_config: New freight configuration to write
            
        Returns:
            Dict containing update results
        """
        try:
            # Read current configuration
            if not os.path.exists(self.config_file_path):
                logger.error(f"Configuration file not found: {self.config_file_path}")
                return {"success": False, "error": "Configuration file not found"}
            
            with open(self.config_file_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            # Create backup of current configuration
            backup_path = f"{self.config_file_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            with open(backup_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
            logger.info(f"Configuration backup created: {backup_path}")
            
            # Update freight configuration
            if "shopify" not in config_data:
                config_data["shopify"] = {}
            
            config_data["shopify"]["freight_config"] = new_freight_config
            
            # Write updated configuration
            with open(self.config_file_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
            
            logger.info("Configuration file updated successfully")
            return {"success": True}
            
        except Exception as e:
            logger.error(f"Error updating configuration file: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def validate_freight_config(self, freight_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate the freight configuration structure
        
        Args:
            freight_config: Freight configuration to validate
            
        Returns:
            Dict containing validation results
        """
        try:
            validation_results = {
                "valid": True,
                "errors": [],
                "warnings": []
            }
            
            # Check for required sections
            if "local" not in freight_config:
                validation_results["errors"].append("Missing 'local' section in freight config")
                validation_results["valid"] = False
            
            if "international" not in freight_config:
                validation_results["errors"].append("Missing 'international' section in freight config")
                validation_results["valid"] = False
            
            # Validate local configuration structure
            if "local" in freight_config:
                for amount_key, config in freight_config["local"].items():
                    if "revenue" not in config or "cost" not in config:
                        validation_results["errors"].append(f"Local config for amount {amount_key} missing revenue or cost section")
                        validation_results["valid"] = False
                    else:
                        # Check required fields in revenue and cost
                        for section in ["revenue", "cost"]:
                            if "ExpenseCode" not in config[section] or "LineTotal" not in config[section]:
                                validation_results["errors"].append(f"Local config for amount {amount_key} missing ExpenseCode or LineTotal in {section}")
                                validation_results["valid"] = False
            
            # Validate international configuration structure
            if "international" in freight_config:
                for key, config in freight_config["international"].items():
                    if "ExpenseCode" not in config or "LineTotal" not in config:
                        validation_results["errors"].append(f"International config for {key} missing ExpenseCode or LineTotal")
                        validation_results["valid"] = False
            
            return validation_results
            
        except Exception as e:
            logger.error(f"Error validating freight config: {str(e)}")
            return {
                "valid": False,
                "errors": [str(e)],
                "warnings": []
            }


# Create singleton instance
freight_sync = FreightSync()


async def main():
    """Main function to run freight sync"""
    try:
        result = await freight_sync.sync_freight_prices()
        
        if result["success"]:
            print(f"✅ Freight sync completed successfully")
            print(f"   Local entries: {result.get('local_entries', 0)}")
            print(f"   International entries: {result.get('international_entries', 0)}")
            print(f"   Timestamp: {result.get('timestamp')}")
        else:
            print(f"❌ Freight sync failed: {result.get('error')}")
            print(f"   Timestamp: {result.get('timestamp')}")
            
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")


if __name__ == "__main__":
    asyncio.run(main())
