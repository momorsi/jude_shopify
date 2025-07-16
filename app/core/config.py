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
        self.location_id = store_data.get('location_id', '')
        self.currency = store_data.get('currency', 'USD')
        self.price_list = store_data.get('price_list', 1)
        self.warehouse_code = store_data.get('warehouse_code', '01')
        self.enabled = store_data.get('enabled', True)

class ConfigSettings(BaseSettings):
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
    
    @property
    def shopify_location_id(self) -> str:
        """Get the first enabled store's location ID for backward compatibility"""
        enabled_stores = self.get_enabled_stores()
        if enabled_stores:
            return list(enabled_stores.values())[0].location_id
        return ""
    
    # Sync Settings
    new_items_enabled: bool = config_data['sync']['new_items']['enabled']
    new_items_interval: int = config_data['sync']['new_items']['interval_minutes']
    new_items_batch_size: int = config_data['sync']['new_items']['batch_size']
    
    inventory_enabled: bool = config_data['sync']['inventory']['enabled']
    inventory_interval: int = config_data['sync']['inventory']['interval_minutes']
    inventory_batch_size: int = config_data['sync']['inventory']['batch_size']
    
    master_data_enabled: bool = config_data['sync']['master_data']['enabled']
    master_data_interval: int = config_data['sync']['master_data']['interval_minutes']
    master_data_batch_size: int = config_data['sync']['master_data']['batch_size']
    
    orders_enabled: bool = config_data['sync']['orders']['enabled']
    orders_interval: int = config_data['sync']['orders']['interval_minutes']
    orders_batch_size: int = config_data['sync']['orders']['batch_size']
    
    # Logging Settings
    log_level: str = config_data['logging']['level']
    log_file: str = config_data['logging']['file']
    log_max_size: int = config_data['logging']['max_size_mb']
    log_backup_count: int = config_data['logging']['backup_count']
    
    # Retry Settings
    retry_max_attempts: int = config_data['retry']['max_attempts']
    retry_delay: int = config_data['retry']['delay_seconds']

config_settings = ConfigSettings() 