import logging
from logging.handlers import RotatingFileHandler
import os
from app.core.config import config_settings

def setup_logging():
    # Create logs directory if it doesn't exist
    log_dir = os.path.dirname(config_settings.log_file)
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Configure logging
    logger = logging.getLogger('sync_service')
    logger.setLevel(getattr(logging, config_settings.log_level))
    
    # Create rotating file handler with UTF-8 encoding
    file_handler = RotatingFileHandler(
        config_settings.log_file,
        maxBytes=config_settings.log_max_size * 1024 * 1024,  # Convert MB to bytes
        backupCount=config_settings.log_backup_count,
        encoding='utf-8'
    )
    
    # Create console handler with UTF-8 encoding
    console_handler = logging.StreamHandler()
    # Set encoding for Windows console
    if hasattr(console_handler.stream, 'reconfigure'):
        console_handler.stream.reconfigure(encoding='utf-8')
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Add formatter to handlers
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# Create logger instance
logger = setup_logging()

def log_api_call(service: str, endpoint: str, request_data: dict = None, response_data: dict = None, status: str = None):
    """Log API calls with request and response data"""
    try:
        log_data = {
            'service': service,
            'endpoint': endpoint,
            'request': request_data,
            'response': response_data,
            'status': status
        }
        logger.info(f"API Call: {log_data}")
    except UnicodeEncodeError:
        # Fallback logging without problematic characters
        logger.info(f"API Call: {service} - {endpoint} - {status}")

def log_sync_event(sync_type: str, items_processed: int, success_count: int, error_count: int, details: dict = None):
    """Log synchronization events"""
    try:
        log_data = {
            'sync_type': sync_type,
            'items_processed': items_processed,
            'success_count': success_count,
            'error_count': error_count,
            'details': details
        }
        logger.info(f"Sync Event: {log_data}")
    except UnicodeEncodeError:
        # Fallback logging without problematic characters
        logger.info(f"Sync Event: {sync_type} - {items_processed} processed, {success_count} success, {error_count} errors")

def log_error(error_type: str, error_message: str, details: dict = None):
    """Log error events"""
    try:
        log_data = {
            'error_type': error_type,
            'error_message': error_message,
            'details': details
        }
        logger.error(f"Error: {log_data}")
    except UnicodeEncodeError:
        # Fallback logging without problematic characters
        logger.error(f"Error: {error_type} - {error_message}") 