"""
Path utility functions for SimplSQL application.

This module provides helper functions for resolving paths in both
development and PyInstaller compiled environments.
"""

import sys
import os


def get_resource_path(relative_path):
    """
    Get absolute path to resource, works for dev and PyInstaller.
    
    Parameters
    ----------
    relative_path : str
        The relative path to the resource file
        
    Returns
    -------
    str
        The absolute path to the resource
        
    Notes
    -----
    PyInstaller creates a temp folder and stores path in _MEIPASS.
    In development, uses the project root directory (where sql.png is located).
    """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        # Running in normal Python environment
        # Get the project root (go up from utils/ to project root)
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    return os.path.join(base_path, relative_path)


def get_app_dir():
    """
    Get the directory where the app should store user data.
    
    Returns
    -------
    str
        The application directory path
        
    Notes
    -----
    When running as compiled executable, uses the directory containing the .exe.
    When running as script, uses the script's directory.
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        # Use the directory containing the .exe for user data
        return os.path.dirname(sys.executable)
    else:
        # Running as script
        return os.path.dirname(os.path.abspath(__file__))
