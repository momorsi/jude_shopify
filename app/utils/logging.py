import logging
from logging.handlers import RotatingFileHandler
import os
from app.core.config import config_settings


class SafeRotatingFileHandler(RotatingFileHandler):
    """
    A RotatingFileHandler that gracefully handles Windows file rotation errors.
    
    On Windows, RotatingFileHandler.doRollover() can fail with [Errno 2] or [Errno 13]
    when another handle still has the log file open (e.g., antivirus, editor, indexer).
    When rotation fails, the standard handler's internal state breaks and ALL subsequent
    log writes raise exceptions, causing the entire application to malfunction.
    
    This subclass catches rotation errors and recovers by:
    1. Reopening the current log file so writes can continue
    2. Retrying the rotation on the next emit if the file is still over the size limit
    """

    def doRollover(self):
        """Override doRollover to handle Windows file locking errors."""
        try:
            super().doRollover()
        except (OSError, IOError, FileNotFoundError, PermissionError) as e:
            # Rotation failed (file locked, missing, permission denied, etc.)
            # Recover by reopening the base log file so logging can continue
            try:
                if self.stream:
                    self.stream.close()
                self.stream = self._open()
            except Exception:
                pass  # If even reopening fails, emit() will handle it below

    def emit(self, record):
        """Override emit to catch any residual file errors and recover."""
        try:
            super().emit(record)
        except (OSError, IOError, FileNotFoundError, PermissionError):
            # File handle is broken -- attempt to reopen and retry once
            try:
                if self.stream:
                    self.stream.close()
                self.stream = self._open()
                super().emit(record)
            except Exception:
                # If recovery also fails, silently drop this log line
                # Console handler will still show it
                pass
        except Exception:
            # Catch-all: never let a logging failure crash business logic
            pass


def setup_logging():
    # Create logs directory if it doesn't exist
    log_dir = os.path.dirname(config_settings.log_file)
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Configure logging
    logger = logging.getLogger('sync_service')
    logger.setLevel(getattr(logging, config_settings.log_level))
    
    # Create safe rotating file handler that survives Windows rotation errors
    file_handler = SafeRotatingFileHandler(
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

def safe_log(level: str, message: str, *args, **kwargs):
    """
    Safely log a message, catching any file system errors during logging.
    This prevents logging errors (e.g., during log rotation) from interrupting business logic.
    
    Args:
        level: Log level ('error', 'warning', 'info', 'debug', 'critical')
        message: Log message
        *args, **kwargs: Additional arguments passed to logger method
    """
    try:
        if level == 'error':
            logger.error(message, *args, **kwargs)
        elif level == 'warning':
            logger.warning(message, *args, **kwargs)
        elif level == 'info':
            logger.info(message, *args, **kwargs)
        elif level == 'debug':
            logger.debug(message, *args, **kwargs)
        elif level == 'critical':
            logger.critical(message, *args, **kwargs)
    except (OSError, IOError, FileNotFoundError) as e:
        # If file logging fails (e.g., during rotation), fall back to console print
        # This prevents logging errors from interrupting business logic
        try:
            print(f"[{level.upper()}] {message}")
        except:
            pass  # If even print fails, silently continue
    except Exception as e:
        # For any other logging error, try console print as fallback
        try:
            print(f"[{level.upper()}] {message}")
        except:
            pass  # If even print fails, silently continue

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