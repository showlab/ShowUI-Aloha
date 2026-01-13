import os
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Union


class LoggerUtils:
    """
    Centralized logging utility for all components.
    Provides consistent logging across components with support for different formats and logging levels.
    """
    
    def __init__(self, component_name: str = None, timezone: timezone = None):
        """
        Initialize the logger utility.
        
        Args:
            log_dir: Directory to store log files
            component_name: Name of the component using the logger (e.g., 'planner')
        """
        self.component_name = component_name or "general"
        self.timezone = timezone

        # Setup Python logger
        self._setup_python_logger()
        
    def _setup_python_logger(self):
        """Configure the Python logger for console output."""
        self.logger = logging.getLogger(f"aloha.{self.component_name}")
        
        # Only set up handler if it doesn't already exist
        if not self.logger.handlers:
            self.logger.setLevel(logging.INFO)
            
            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            
            # Formatter
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            if self.timezone:
                formatter.converter = lambda *args: datetime.now(self.timezone).timetuple()

            console_handler.setFormatter(formatter)
            
            self.logger.addHandler(console_handler)
    
    def ensure_log_directory(self, target_dir: str = None) -> str:
        """
        Ensure the log directory exists, optionally with a target_directory.
        Args:
            target_dir: Optional target_dir to create
        Returns:
            Full path to the log directory
        """
        target_dir = target_dir or "./logs"
        os.makedirs(target_dir, exist_ok=True)
        return target_dir
    
    def get_timestamped_path(self, file_name: str, target_dir: str = None) -> str:
        """
        Get a timestamped path for a log file.
        Args:
            file_name: Base file name
            target_dir: target directory
        Returns:
            Full path with timestamp
        """
        log_dir = self.ensure_log_directory(target_dir)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        
        # If file has an extension, insert timestamp before extension
        if "." in file_name:
            base_name, ext = file_name.rsplit(".", 1)
            file_path = os.path.join(log_dir, f"{base_name}_{timestamp}.{ext}")
        else:
            file_path = os.path.join(log_dir, f"{file_name}_{timestamp}")
            
        return file_path
    
    def log_json(self, 
                data: Union[Dict, List], 
                file_name: str, 
                target_dir: str = None, 
                ensure_ascii: bool = False,
                indent: int = 4,
                timestamped: bool = False) -> str:
        """
        Log JSON data to a file.
        
        Args:
            data: JSON-serializable data to log
            file_name: Output file name
            target_dir: target directory
            ensure_ascii: JSON encoding parameter
            indent: JSON formatting indent
            timestamped: Whether to add timestamp to filename
            
        Returns:
            Path to the created log file
        """
        try:
            # Get file path
            if timestamped:
                file_path = self.get_timestamped_path(file_name, target_dir)
            else:
                log_dir = self.ensure_log_directory(target_dir)
                file_path = os.path.join(log_dir, file_name)
            
            # Write JSON data
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=ensure_ascii, indent=indent)
                
            self.logger.info(f"Logged JSON data to {file_path}")
            return file_path
            
        except Exception as e:
            self.logger.error(f"Error logging JSON data: {e}")
            return None
    
    def log_text(self, 
                text: str, 
                file_name: str, 
                target_dir: str = None,
                timestamped: bool = False) -> str:
        """
        Log text data to a file.
        
        Args:
            text: Text content to log
            file_name: Output file name
            target_dir: target directory
            timestamped: Whether to add timestamp to filename
            
        Returns:
            Path to the created log file
        """
        try:
            # Get file path
            if timestamped:
                file_path = self.get_timestamped_path(file_name, target_dir)
            else:
                log_dir = self.ensure_log_directory(target_dir)
                file_path = os.path.join(log_dir, file_name)
            
            # Write text data
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(text)
                
            self.logger.info(f"Logged text data to {file_path}")
            return file_path
            
        except Exception as e:
            self.logger.error(f"Error logging text data: {e}")
            return None
    
    
    def log_performance(self, 
                       operation_name: str, 
                       start_time: float, 
                       file_name: str = "performance.json",
                       target_dir: str = "./logs/server_logs",
                       additional_data: Dict = None) -> Dict:
        """
        Log performance metrics for an operation.
        
        Args:
            operation_name: Name of the operation being timed
            start_time: Start time of the operation (from time.time())
            file_name: Output file name
            target_dir: target directory
            additional_data: Additional data to include in the log
            
        Returns:
            Performance data that was logged
        """
        end_time = time.time()
        duration = end_time - start_time
        
        performance_data = {
            "operation": operation_name,
            "start_time": start_time,
            "end_time": end_time,
            "duration_seconds": duration
        }
        
        # Add additional data if provided
        if additional_data:
            performance_data.update(additional_data)
        
        try:
            log_dir = self.ensure_log_directory(target_dir)
            file_path = os.path.join(log_dir, file_name)
            
            # Read existing data if file exists
            existing_data = []
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)
                except:
                    self.logger.warning(f"Could not read existing performance log: {file_path}")
            
            # Append new data
            if isinstance(existing_data, list):
                existing_data.append(performance_data)
            else:
                existing_data = [performance_data]
                
            # Write updated data
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, indent=2)
                
            self.logger.info(f"Operation '{operation_name}' completed in {duration:.2f} seconds")
            return performance_data
            
        except Exception as e:
            self.logger.error(f"Error logging performance data: {e}")
            return performance_data
    
    
    def log_error(self, 
                 error: Exception,
                 context: Dict = None,
                 file_name: str = "errors.log",
                 target_dir: str = None) -> str:
        """
        Log an error with context information.
        
        Args:
            error: The exception to log
            context: Additional context information
            file_name: Output file name
            target_dir: target directory
            
        Returns:
            Path to the created log file
        """
        log_dir = self.ensure_log_directory(target_dir)
        file_path = os.path.join(log_dir, file_name)
        
        error_data = {
            "timestamp": datetime.now().isoformat(),
            "error_type": type(error).__name__,
            "error_message": str(error)
        }
        
        if context:
            error_data["context"] = context
            
        try:
            # Add to existing log file if it exists
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(error_data, indent=2) + "\n\n")
                
            self.logger.error(f"Error logged to {file_path}: {error}")
            return file_path
            
        except Exception as e:
            self.logger.error(f"Failed to log error: {e}")
            return None




# Set timezone offset for UTC+8
class UTC8Formatter(logging.Formatter):
    converter = staticmethod(lambda *args: datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).timetuple())
