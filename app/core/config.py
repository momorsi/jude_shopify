from pydantic_settings import BaseSettings
import json
import os
import sys
from typing import Dict, Any
from pathlib import Path

class AdvancedSettings:
    configuration_data: Dict[str, Any] = {}
    
    def load_config(self):
        # Try to find config file in multiple locations
        config_paths = [
            # 1. Same directory as executable (for external config)
            Path(sys.executable).parent / "configurations.json" if getattr(sys, 'frozen', False) else None,
            # 2. Current working directory
            Path.cwd() / "configurations.json",
            # 3. Original project directory (fallback)
            Path(__file__).parent.parent.parent / "configurations.json"
        ]
        
        config_file = None
        for path in config_paths:
            if path and path.exists():
                config_file = path
                break
        
        if not config_file:
            raise FileNotFoundError("configurations.json not found in any of the expected locations")
        
        print(f"📋 Loading configuration from: {config_file}")
        
        with open(config_file) as json_file:
            self.configuration_data = json.load(json_file)

configs = AdvancedSettings()
configs.load_config()
config_data = configs.configuration_data

class ShopifyStoreConfig:
    """Configuration for a single Shopify store"""
    def __init__(self, store_data: Dict[str, Any]):
        self.name = store_data.get('name', '')
        self.shop_url = store_data.get('shop_url', '')
        self.access_token = store_data.get('access_token', '')
        self.api_version = store_data.get('api_version', '2024-01')
        self.timeout = store_data.get('timeout', 30)
        self.currency = store_data.get('currency', 'USD')
        self.price_list = store_data.get('price_list', 1)
        self.enabled = store_data.get('enabled', True)
        # Add location warehouse mapping
        self.location_warehouse_mapping = config_data['shopify'].get('location_warehouse_mapping', {})

class ConfigSettings(BaseSettings):
    # Test Mode
    test_mode: bool = config_data.get('test_mode', True)
    
    # SAP Settings
    sap_server: str = config_data['sap']['server']
    sap_company: str = config_data['sap']['company']
    sap_user: str = config_data['sap']['user']
    sap_password: str = config_data['sap']['password']
    sap_language: str = config_data['sap']['language']
    sap_timeout: int = config_data['sap']['timeout']
    
    # Shopify Settings - Multi-store support
    shopify_stores: Dict[str, ShopifyStoreConfig] = {}
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Initialize Shopify stores
        stores_data = config_data['shopify'].get('stores', {})
        for store_key, store_data in stores_data.items():
            self.shopify_stores[store_key] = ShopifyStoreConfig(store_data)
    
    def get_enabled_stores(self) -> Dict[str, ShopifyStoreConfig]:
        """Get only enabled stores"""
        return {key: store for key, store in self.shopify_stores.items() if store.enabled}
    
    def get_store_by_name(self, store_name: str) -> ShopifyStoreConfig:
        """Get store configuration by name"""
        return self.shopify_stores.get(store_name)
    
    def get_location_warehouse_mapping(self, store_key: str) -> Dict[str, Any]:
        """Get location-warehouse mapping for a specific store"""
        mapping_data = config_data['shopify'].get('location_warehouse_mapping', {})
        return mapping_data.get(store_key, {})
    
    def get_warehouse_code_for_location(self, store_key: str, location_id: str) -> str:
        """Get warehouse code for a specific location in a store"""
        mapping = self.get_location_warehouse_mapping(store_key)
        if not mapping:
            return "SW"  # Default warehouse
        
        # Check if location has specific mapping
        locations = mapping.get('locations', {})
        if location_id in locations:
            location_info = locations[location_id]
            # Handle both old format (direct warehouse code) and new format (with warehouse field)
            if isinstance(location_info, str):
                return location_info  # Old format
            elif isinstance(location_info, dict):
                return location_info.get('warehouse', 'SW')  # New format
        
        # Return default warehouse for the store
        return mapping.get('default', 'SW')
    
    def get_location_mapping_for_location(self, store_key: str, location_id: str) -> Dict[str, str]:
        """Get complete location mapping (warehouse + costing codes) for a specific location"""
        mapping = self.get_location_warehouse_mapping(store_key)
        if not mapping:
            return {"warehouse": "SW"}  # Default warehouse
        
        locations = mapping.get('locations', {})
        if location_id in locations:
            location_info = locations[location_id]
            if isinstance(location_info, dict):
                return location_info  # New format with costing codes
            elif isinstance(location_info, str):
                return {"warehouse": location_info}  # Old format, convert to new format
        
        # Return default mapping
        return {"warehouse": mapping.get('default', 'SW')}
    
    def get_warehouse_code_for_order(self, store_key: str, order_data: Dict[str, Any]) -> str:
        """Get warehouse code for an order based on its location"""
        # Extract location from order GraphQL response
        location = order_data.get('location')
        if location and location.get('id'):
            # Extract the numeric ID from the GID format (e.g., "gid://shopify/Location/70074892354" -> "70074892354")
            location_gid = location['id']
            if 'gid://shopify/Location/' in location_gid:
                location_id = location_gid.replace('gid://shopify/Location/', '')
                return self.get_warehouse_code_for_location(store_key, location_id)
        
        # If no location found, use default
        mapping = self.get_location_warehouse_mapping(store_key)
        return mapping.get('default', 'SW') if mapping else 'SW'
    
    def get_bank_transfer_mapping(self, store_key: str) -> Dict[str, str]:
        """Get bank transfer account mappings for a specific store"""
        bank_transfers = config_data['shopify'].get('bank_transfers', {})
        return bank_transfers.get(store_key, {})
    
    def get_bank_transfer_account(self, store_key: str, payment_type: str) -> str:
        """Get bank transfer account for a specific payment type in a store"""
        mapping = self.get_bank_transfer_mapping(store_key)
        return mapping.get(payment_type, "")
    
    def get_currency_for_store(self, store_key: str) -> str:
        """Get currency for a specific store"""
        return self.shopify_stores[store_key].currency
    
    # Legacy support for backward compatibility
    @property
    def shopify_shop_url(self) -> str:
        """Get the first enabled store's URL for backward compatibility"""
        enabled_stores = self.get_enabled_stores()
        if enabled_stores:
            return list(enabled_stores.values())[0].shop_url
        return ""
    
    @property
    def shopify_access_token(self) -> str:
        """Get the first enabled store's access token for backward compatibility"""
        enabled_stores = self.get_enabled_stores()
        if enabled_stores:
            return list(enabled_stores.values())[0].access_token
        return ""
    
    @property
    def shopify_api_version(self) -> str:
        """Get the first enabled store's API version for backward compatibility"""
        enabled_stores = self.get_enabled_stores()
        if enabled_stores:
            return list(enabled_stores.values())[0].api_version
        return "2024-01"
    
    @property
    def shopify_timeout(self) -> int:
        """Get the first enabled store's timeout for backward compatibility"""
        enabled_stores = self.get_enabled_stores()
        if enabled_stores:
            return list(enabled_stores.values())[0].timeout
        return 30
    

    
    # Sync Settings
    new_items_enabled: bool = config_data['sync']['new_items']['enabled']
    new_items_interval: int = config_data['sync']['new_items']['interval_minutes']
    new_items_batch_size: int = config_data['sync']['new_items']['batch_size']
    
    inventory_enabled: bool = config_data['sync']['inventory']['enabled']
    inventory_interval: int = config_data['sync']['inventory']['interval_minutes']
    inventory_batch_size: int = config_data['sync']['inventory']['batch_size']
    
    item_changes_enabled: bool = config_data['sync']['item_changes']['enabled']
    item_changes_interval: int = config_data['sync']['item_changes']['interval_minutes']
    item_changes_batch_size: int = config_data['sync']['item_changes']['batch_size']
    
    price_changes_enabled: bool = config_data['sync']['price_changes']['enabled']
    price_changes_interval: int = config_data['sync']['price_changes']['interval_minutes']
    price_changes_batch_size: int = config_data['sync']['price_changes']['batch_size']
    

    
    # Sales Module Settings
    
    
    sales_orders_enabled: bool = config_data['sync']['sales']['orders']['enabled']
    sales_orders_interval: int = config_data['sync']['sales']['orders']['interval_minutes']
    sales_orders_batch_size: int = config_data['sync']['sales']['orders']['batch_size']
    
    payment_recovery_enabled: bool = config_data['sync']['sales']['payment_recovery']['enabled']
    payment_recovery_interval: int = config_data['sync']['sales']['payment_recovery']['interval_minutes']
    payment_recovery_batch_size: int = config_data['sync']['sales']['payment_recovery']['batch_size']
    
    # Logging Settings
    log_level: str = config_data['logging']['level']
    log_file: str = config_data['logging']['file']
    log_max_size: int = config_data['logging']['max_size_mb']
    log_backup_count: int = config_data['logging']['backup_count']
    
    # Retry Settings
    retry_max_attempts: int = config_data['retry']['max_attempts']
    retry_delay: int = config_data['retry']['delay_seconds']

config_settings = ConfigSettings() 