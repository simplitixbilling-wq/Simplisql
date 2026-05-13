"""
Logging Configuration for SimpliSQL

Provides structured logging throughout the application with file and console output.
Replaces ad-hoc print() statements with proper logging framework.

Usage:
    from utils.logging_config import get_logger
    
    logger = get_logger(__name__)
    logger.info("Starting application")
    logger.error("Failed to load file: %s", filename)
"""

import logging
import logging.handlers
import os
from pathlib import Path
from datetime import datetime


def setup_logging(app_dir=None, log_level=logging.INFO):
    """
    Configure logging for SimpliSQL application.
    
    Args:
        app_dir: Application directory for log files
        log_level: Logging level (logging.DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Create logs directory
    if app_dir is None:
        from utils.paths import get_app_dir
        app_dir = get_app_dir()
    
    logs_dir = os.path.join(app_dir, "Logs")
    os.makedirs(logs_dir, exist_ok=True)
    
    # Log file path with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(logs_dir, f"simplisql_{timestamp}.log")
    
    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    simple_formatter = logging.Formatter(
        '%(levelname)s - %(message)s'
    )
    
    # File handler - detailed logging
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(file_handler)
    
    # Console handler - simplified logging
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(simple_formatter)
    root_logger.addHandler(console_handler)
    
    # Log startup
    logger = logging.getLogger('SimpliSQL')
    logger.info("=" * 60)
    logger.info("SimpliSQL Application Started")
    logger.info("=" * 60)
    logger.info(f"Log file: {log_file}")
    logger.info(f"App directory: {app_dir}")
    
    return logger


def get_logger(name):
    """
    Get a logger instance for a specific module.
    
    Args:
        name: Module name (typically __name__)
    
    Returns:
        logging.Logger instance
    """
    return logging.getLogger(name)


# Migration helpers to replace print() statements
class LoggingMixin:
    """
    Mixin to provide logging to any class.
    
    Usage:
        class MyClass(LoggingMixin, QWidget):
            def __init__(self):
                self.logger = self.setup_logger(__name__)
                self.logger.info("MyClass initialized")
    """
    
    def setup_logger(self, name):
        """Setup and return a logger for this class."""
        return get_logger(name)


# Common logging messages
class LogMessages:
    """Standard log messages for consistency."""
    
    # File operations
    FILE_UPLOAD_START = "Starting file upload: %s"
    FILE_UPLOAD_SUCCESS = "Successfully imported file: %s (%d rows)"
    FILE_UPLOAD_ERROR = "Failed to import file: %s - %s"
    FILE_DELETE = "Deleted file: %s"
    
    # Query operations
    QUERY_EXECUTE = "Executing query: %s..."
    QUERY_SUCCESS = "Query executed successfully (%d rows, %.2f seconds)"
    QUERY_ERROR = "Query execution failed: %s"
    QUERY_VALIDATE = "Validating SQL syntax..."
    
    # Workflow operations
    WORKFLOW_CREATE = "Created workflow: %s"
    WORKFLOW_EXECUTE = "Executing workflow: %s"
    WORKFLOW_COMPLETE = "Workflow completed: %s (steps: %d)"
    WORKFLOW_ERROR = "Workflow execution failed: %s"
    
    # AI operations
    AI_REQUEST = "Sending request to AI: %s"
    AI_RESPONSE = "Received AI response (%d tokens)"
    AI_ERROR = "AI request failed: %s"
    
    # UI operations
    UI_THEME_APPLY = "Applied theme: %s"
    UI_DIALOG_OPEN = "Opened dialog: %s"
    UI_DIALOG_CLOSE = "Closed dialog: %s"
    
    # Configuration
    CONFIG_LOAD = "Loading configuration from: %s"
    CONFIG_SAVE = "Saving configuration to: %s"
    CONFIG_ERROR = "Configuration error: %s"
    
    # Database operations
    DB_CONNECT = "Connecting to database"
    DB_CLOSE = "Closing database connection"
    DB_ERROR = "Database error: %s"
    
    # Application lifecycle
    APP_START = "Application started"
    APP_SHUTDOWN = "Application shutting down"
    APP_ERROR = "Application error: %s"


if __name__ == "__main__":
    # Test logging configuration
    logger = setup_logging()
    logger.debug("Debug message")
    logger.info("Info message")
    logger.warning("Warning message")
    logger.error("Error message")
    logger.critical("Critical message")
