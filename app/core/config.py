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
    
    
    def get_currency_for_store(self, store_key: str) -> str:
        """Get currency for a specific store"""
        return self.shopify_stores[store_key].currency
    
    def get_series_for_location(self, store_key: str, location_mapping: Dict[str, Any], series_type: str) -> int:
        """
        Get series number for a specific location and series type
        
        Args:
            store_key: Store key (local/international)
            location_mapping: Location mapping from OrderLocationMapper
            series_type: Type of series ('invoices', 'credit_notes', 'incoming_payments')
            
        Returns:
            Series number for the location, or default fallback
        """
        try:
            # Get series from location mapping if available
            if location_mapping and 'series' in location_mapping:
                series_config = location_mapping['series']
                if series_type in series_config:
                    return series_config[series_type]
            
            # Fallback to default series for the store
            mapping = self.get_location_warehouse_mapping(store_key)
            if mapping:
                locations = mapping.get('locations', {})
                if 'web' in locations and 'series' in locations['web']:
                    return locations['web']['series'].get(series_type, getattr(self, f'sales_series_{series_type}', 82))
            
            # Final fallback to config defaults
            return getattr(self, f'sales_series_{series_type}', 82)
            
        except Exception as e:
            # Log error and return default
            print(f"Error getting series for location: {str(e)}")
            return getattr(self, f'sales_series_{series_type}', 82)
    
    def get_group_code_for_location(self, location_mapping: Dict[str, Any]) -> int:
        """
        Get group code for customer creation based on location mapping
        
        Args:
            location_mapping: Location mapping from OrderLocationMapper
            
        Returns:
            Group code for the location, or default fallback
        """
        try:
            if location_mapping and 'group_code' in location_mapping:
                return location_mapping['group_code']
            
            # Fallback to default group code (110 for online customers)
            return 110
            
        except Exception as e:
            print(f"Error getting group code for location: {str(e)}")
            return 110
    
    def get_location_type(self, location_mapping: Dict[str, Any]) -> str:
        """
        Get location type (online or store) from location mapping
        
        Args:
            location_mapping: Location mapping from OrderLocationMapper
            
        Returns:
            Location type ('online' or 'store'), defaults to 'online'
        """
        try:
            if location_mapping and 'type' in location_mapping:
                return location_mapping['type']
            
            # Default to online for backward compatibility
            return 'online'
            
        except Exception as e:
            print(f"Error getting location type: {str(e)}")
            return 'online'
    
    def get_cash_account_for_location(self, location_mapping: Dict[str, Any]) -> str:
        """
        Get cash account for store locations
        
        Args:
            location_mapping: Location mapping from OrderLocationMapper
            
        Returns:
            Cash account code, or empty string if not available
        """
        try:
            if location_mapping and 'cash' in location_mapping:
                return location_mapping['cash']
            
            return ""
            
        except Exception as e:
            print(f"Error getting cash account for location: {str(e)}")
            return ""
    
    def get_bank_transfer_for_location(self, store_key: str, location_mapping: Dict[str, Any], payment_gateway: str, courier_name: str = None) -> str:
        """
        Get bank transfer account for a specific location and payment gateway
        
        Args:
            store_key: Store key (local/international)
            location_mapping: Location mapping from OrderLocationMapper
            payment_gateway: Payment gateway name
            courier_name: Courier name for COD payments (optional)
            
        Returns:
            Bank transfer account code, or empty string if not found
        """
        try:
            location_type = self.get_location_type(location_mapping)
            
            # For online locations, check location-specific bank_transfers first
            if location_type == "online" and location_mapping and 'bank_transfers' in location_mapping:
                bank_transfers = location_mapping['bank_transfers']
                
                # Check if it's a COD payment with courier
                if payment_gateway == "Cash on Delivery (COD)" and courier_name:
                    if store_key in bank_transfers:
                        cod_mappings = bank_transfers[store_key]
                        if courier_name in cod_mappings:
                            return cod_mappings[courier_name]
                
                # Check direct gateway mapping
                if store_key in bank_transfers and payment_gateway in bank_transfers[store_key]:
                    return bank_transfers[store_key][payment_gateway]
            
            # For store locations, check location-specific bank_transfers
            elif location_type == "store" and location_mapping and 'bank_transfers' in location_mapping:
                bank_transfers = location_mapping['bank_transfers']
                if payment_gateway in bank_transfers:
                    return bank_transfers[payment_gateway]
            
            # No fallback - return empty string if not found
            return ""
            
        except Exception as e:
            print(f"Error getting bank transfer for location: {str(e)}")
            return ""
        
    def get_bank_transfers_for_location(self, store_key: str, location_mapping: Dict[str, Any]) -> str:
        """
        Get bank transfer account for a specific location and payment gateway
        
        Args:
            store_key: Store key (local/international)
            location_mapping: Location mapping from OrderLocationMapper
            payment_gateway: Payment gateway name (e.g., "Paymob POS", "Geidea POS")
            
        Returns:
            Bank transfer account code, or empty string if not found
        """
        try:
            location_type = self.get_location_type(location_mapping)
            
            # For store locations, check location-specific bank transfers
            if location_type == "store" and location_mapping and 'bank_transfers' in location_mapping:
                bank_transfers = location_mapping['bank_transfers']
                return bank_transfers
                
            # No fallback - return empty string if not found
            return []
            
        except Exception as e:
            print(f"Error getting bank transfers for location: {str(e)}")
            return []
    
    def get_credits_for_location(self, store_key: str, location_mapping: Dict[str, Any]) -> str:
        """
        Get credit account for a specific location and payment gateway
        
        Args:
            store_key: Store key (local/international)
            location_mapping: Location mapping from OrderLocationMapper
            payment_gateway: Payment gateway name (e.g., "Paymob POS", "Geidea POS")
            
        Returns:
            Credit account code, or empty string if not found
        """
        try:
            location_type = self.get_location_type(location_mapping)
            
            # For store locations, check location-specific credit accounts
            if location_type == "store" and location_mapping and 'credit' in location_mapping:
                credit_accounts = location_mapping['credit']
                
                return credit_accounts
            
            # No fallback - return empty string if not found
            return []
            
        except Exception as e:
            print(f"Error getting credits for location: {str(e)}")
            return []
    
    def get_credit_account_for_location(self, store_key: str, location_mapping: Dict[str, Any], payment_gateway: str) -> str:
        """
        Get credit account for a specific location and payment gateway
        
        Args:
            store_key: Store key (local/international)
            location_mapping: Location mapping from OrderLocationMapper
            payment_gateway: Payment gateway name (e.g., "Paymob POS", "Geidea POS")
            
        Returns:
            Credit account code, or empty string if not found
        """
        try:
            location_type = self.get_location_type(location_mapping)
            
            # For store locations, check location-specific credit accounts
            if location_type == "store" and location_mapping and 'credit' in location_mapping:
                credit_accounts = location_mapping['credit']
                if payment_gateway in credit_accounts:
                    return credit_accounts[payment_gateway]
            
            # No fallback - return empty string if not found
            return ""
            
        except Exception as e:
            print(f"Error getting credit account for location: {str(e)}")
            return ""
    
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
    sales_orders_from_date: str = config_data['sync']['sales']['orders']['from_date']
    payment_recovery_enabled: bool = config_data['sync']['sales']['payment_recovery']['enabled']
    payment_recovery_interval: int = config_data['sync']['sales']['payment_recovery']['interval_minutes']
    payment_recovery_batch_size: int = config_data['sync']['sales']['payment_recovery']['batch_size']
    payment_recovery_from_date: str = config_data['sync']['sales']['payment_recovery']['from_date']
    returns_enabled: bool = config_data['sync']['sales']['returns']['enabled']
    returns_interval: int = config_data['sync']['sales']['returns']['interval_minutes']
    returns_batch_size: int = config_data['sync']['sales']['returns']['batch_size']
    returns_from_date: str = config_data['sync']['sales']['returns']['from_date']
    # Series configuration will be determined dynamically based on location mapping
    # Default fallback values (can be overridden by location-specific series)
    sales_series_invoices: int = config_data['shopify']['location_warehouse_mapping']['local']['locations']['web']['series']['invoices']
    sales_series_credit_notes: int = config_data['shopify']['location_warehouse_mapping']['local']['locations']['web']['series']['credit_notes']
    sales_series_incoming_payments: int = config_data['shopify']['location_warehouse_mapping']['local']['locations']['web']['series']['incoming_payments']
    # Logging Settings
    log_level: str = config_data['logging']['level']
    log_file: str = config_data['logging']['file']
    log_max_size: int = config_data['logging']['max_size_mb']
    log_backup_count: int = config_data['logging']['backup_count']
    
    # Retry Settings
    retry_max_attempts: int = config_data['retry']['max_attempts']
    retry_delay: int = config_data['retry']['delay_seconds']

config_settings = ConfigSettings() 