import sys
import os
import logging

# Add parent directory to Python path to allow imports when running this file directly
if __name__ == "__main__":
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

# Initialize logging
from utils.logging_config import setup_logging
logger = setup_logging()

import re
import json
import uuid
import zipfile
import io
from datetime import datetime
import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pyperclip
from PyQt6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QCheckBox, QListWidget, QListWidgetItem, QFileDialog, QDialog,
    QTableView, QTableWidget, QProgressDialog, QMessageBox, QFrame, QToolButton, QMenu,
    QTextEdit, QPlainTextEdit, QSizePolicy, QInputDialog, QTabWidget
)
from PyQt6.QtWidgets import QScrollArea, QHeaderView
import time
from PyQt6.QtGui import QFont, QPalette, QColor, QKeySequence, QShortcut, QKeyEvent, QPainter, QTextFormat, QAction, QPixmap, QTextCursor, QTextDocument
from PyQt6.QtCore import Qt, pyqtSlot, QThread, pyqtSignal, QSize, QAbstractTableModel, QSortFilterProxyModel, QTimer

# Import refactored modules
from ai.ai_assistant_new import AIAssistantDialog
from ui import SearchDialog, CustomPlainTextEdit, WorkflowWizard, StepEditorDialog, DataOperationDialogs, ViewManager, UIBuilder
from core import QueryManager, FileUtilities, FileUpload, QueryHelpers, WorkflowManager, ExportUtils, PythonExecutionManager
from utils import (
    get_resource_path, get_app_dir,
    ParquetSchemaThread, WorkflowExecutionThread,
    PandasModel, DataFrameFilterProxy
)

# Compatibility shim: some code (or older examples) reference QTextFormat.FullWidthSelection
# in Qt5-style. In PyQt6 the enum lives under QTextFormat.Property. Provide an alias so both
# styles work without changing many call sites.
try:
    if not hasattr(QTextFormat, 'FullWidthSelection') and hasattr(QTextFormat, 'Property'):
        QTextFormat.FullWidthSelection = QTextFormat.Property.FullWidthSelection
except (AttributeError, TypeError):
    # If anything goes wrong, don't crash on import; the code will fail later where used.
    pass

# Import mixins for data operations, view management, query execution, file utilities, file upload, UI builder, query helpers, workflows, and export

class DuckDBQueryEditor(DataOperationDialogs, ViewManager, QueryManager, PythonExecutionManager, FileUtilities, FileUpload, UIBuilder, QueryHelpers, WorkflowManager, ExportUtils, QWidget):
    def __init__(self, parent=None, controller=None):
        super().__init__(parent)
        self.controller = controller
        self.uploaded_display_names = []
        self.selected_tables_for_ai = []
        self.editor_mode = "sql"
        self.sql_notepad_buffer = ""
        self.python_notepad_buffer = ""
        self.run_buttons = []
        self.conn = duckdb.connect(database=":memory:", read_only=False)
        
        # Register custom SQL functions
        self._register_custom_functions()
        
        self.uploaded_files = []
        self.saved_queries = {}

        # Step 1: Resolve base app_dir
        if self.controller and hasattr(self.controller, 'app_dir'):
            self.app_dir = self.controller.app_dir
        else:
            self.app_dir = get_app_dir()  # Fixed for PyInstaller compatibility

        # Step 2: Ensure Auto_Workflow dir and saved_queries.json
        try:
            folder_path = os.path.join(self.app_dir, "Auto_Workflow")
            os.makedirs(folder_path, exist_ok=True)

            self.query_file_path = os.path.join(folder_path, "saved_queries.json")

            if not os.path.exists(self.query_file_path):
                with open(self.query_file_path, "w") as f:
                    json.dump({}, f, indent=4)

            with open(self.query_file_path, "r") as f:
                self.saved_queries = json.load(f)

        except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
            logger.exception("Failed to initialize saved queries")
            self.saved_queries = {}
            self.query_file_path = os.path.join(self.app_dir, "Auto_Workflow", "saved_queries.json")

        # Step 3: Set up default ParquetFiles dir
        self.doc_dir = os.path.join(self.app_dir, "ParquetFiles")
        os.makedirs(self.doc_dir, exist_ok=True)
        # views storage
        self.views_path = os.path.join(self.app_dir, "Auto_Workflow", "views.json")
        
        # Step 3.5: Initialize workflow storage
        self.workflows_path = os.path.join(self.app_dir, "Auto_Workflow", "workflows.json")
        self.workflows = self.load_workflows()
        
        # Step 3.6: Initialize AI configuration
        self.ai_config_path = os.path.join(self.app_dir, "Auto_Workflow", "ai_config.json")
        self.ai_chat_history_path = os.path.join(self.app_dir, "Auto_Workflow", "ai_chat_history.json")
        self.ai_config = self.load_ai_config()
        self.ai_chat_history = self.load_ai_chat_history()
        
        # Step 4: Initialize theme system
        self.current_theme = "dark"  # Default to dark theme
        self.theme_settings_file = os.path.join(self.app_dir, "Auto_Workflow", "theme_settings.json")
        self.load_theme_settings()
        self.initialize_themes()
        os.makedirs(os.path.dirname(self.views_path), exist_ok=True)
        # load existing views
        self.views = self.load_views()

        self.sql_text = QTextEdit()
        self.init_ui()

    def _register_custom_functions(self):
        """Register custom SQL functions for use in DuckDB queries"""
        
        # FILE_BASENAME function - extracts filename from full path
        def file_basename(filepath):
            """Extract the basename (filename) from a file path
            
            Examples:
                FILE_BASENAME('C:/Users/Documents/data.csv') -> 'data.csv'
                FILE_BASENAME('/home/user/report.xlsx') -> 'report.xlsx'
                FILE_BASENAME('data.csv') -> 'data.csv'
            """
            if filepath is None:
                return None
            return os.path.basename(str(filepath))
        
        # FILE_DIRNAME function - extracts directory from full path
        def file_dirname(filepath):
            """Extract the directory path from a file path
            
            Examples:
                FILE_DIRNAME('C:/Users/Documents/data.csv') -> 'C:/Users/Documents'
                FILE_DIRNAME('/home/user/report.xlsx') -> '/home/user'
            """
            if filepath is None:
                return None
            return os.path.dirname(str(filepath))
        
        # FILE_NAME_NO_EXT function - extracts filename without extension
        def file_name_no_ext(filepath):
            """Extract filename without extension from a file path
            
            Examples:
                FILE_NAME_NO_EXT('C:/Users/Documents/data.csv') -> 'data'
                FILE_NAME_NO_EXT('/home/user/report.xlsx') -> 'report'
            """
            if filepath is None:
                return None
            basename = os.path.basename(str(filepath))
            return os.path.splitext(basename)[0]
        
        # FILE_EXTENSION function - extracts file extension
        def file_extension(filepath):
            """Extract file extension from a file path
            
            Examples:
                FILE_EXTENSION('C:/Users/Documents/data.csv') -> '.csv'
                FILE_EXTENSION('/home/user/report.xlsx') -> '.xlsx'
            """
            if filepath is None:
                return None
            return os.path.splitext(str(filepath))[1]
        
        # Register all functions with DuckDB
        try:
            self.conn.create_function('FILE_BASENAME', file_basename, return_type='VARCHAR')
            self.conn.create_function('FILE_DIRNAME', file_dirname, return_type='VARCHAR')
            self.conn.create_function('FILE_NAME_NO_EXT', file_name_no_ext, return_type='VARCHAR')
            self.conn.create_function('FILE_EXTENSION', file_extension, return_type='VARCHAR')
            print("✅ Custom file path functions registered: FILE_BASENAME, FILE_DIRNAME, FILE_NAME_NO_EXT, FILE_EXTENSION")
        except (duckdb.Error, TypeError, ValueError) as e:
            logger.warning("Could not register custom SQL file functions: %s", e)

    # --- Workflow persistence helpers ---
    def load_workflows(self):
        """Load saved workflows from JSON file"""
        try:
            if os.path.exists(self.workflows_path):
                with open(self.workflows_path, 'r') as f:
                    return json.load(f)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning("Failed to load workflows from %s: %s", self.workflows_path, e)
        return []

    def save_workflows(self):
        """Save workflows to JSON file"""
        try:
            with open(self.workflows_path, 'w') as f:
                json.dump(self.workflows, f, indent=2)
        except (OSError, TypeError, ValueError) as e:
            logger.error("Failed to save workflows to %s: %s", self.workflows_path, e)

    def add_workflow(self, workflow_spec):
        """Add a new workflow to the list"""
        workflow_spec = dict(workflow_spec)
        workflow_spec.setdefault('id', uuid.uuid4().hex)
        now = datetime.utcnow().isoformat() + 'Z'
        workflow_spec.setdefault('created_iso', now)
        workflow_spec['updated_iso'] = now
        
        if not hasattr(self, 'workflows') or self.workflows is None:
            self.workflows = []
        
        self.workflows.append(workflow_spec)
        self.save_workflows()
        return workflow_spec['id']

    def update_workflow(self, workflow_id, workflow_spec):
        """Update an existing workflow"""
        for i, wf in enumerate(self.workflows):
            if wf.get('id') == workflow_id:
                workflow_spec['id'] = workflow_id
                workflow_spec['created_iso'] = wf.get('created_iso', datetime.utcnow().isoformat() + 'Z')
                workflow_spec['updated_iso'] = datetime.utcnow().isoformat() + 'Z'
                self.workflows[i] = workflow_spec
                self.save_workflows()
                return True
        return False

    def delete_workflow(self, workflow_id):
        """Delete a workflow"""
        self.workflows = [wf for wf in self.workflows if wf.get('id') != workflow_id]
        self.save_workflows()

    # --- AI Configuration helpers ---
    def load_ai_config(self):
        """Load AI API keys configuration from JSON file"""
        try:
            if os.path.exists(self.ai_config_path):
                with open(self.ai_config_path, 'r') as f:
                    return json.load(f)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning("Failed to load AI config from %s: %s", self.ai_config_path, e)
        return {
            'openai_key': '',
            'anthropic_key': '',
            'gemini_key': '',
            'selected_provider': 'openai'  # default provider
        }

    def save_ai_config(self):
        """Save AI configuration to JSON file"""
        try:
            with open(self.ai_config_path, 'w') as f:
                json.dump(self.ai_config, f, indent=2)
        except (OSError, TypeError, ValueError) as e:
            logger.error("Failed to save AI config to %s: %s", self.ai_config_path, e)

    def load_ai_chat_history(self):
        """Load AI chat history from JSON file"""
        try:
            if os.path.exists(self.ai_chat_history_path):
                with open(self.ai_chat_history_path, 'r') as f:
                    return json.load(f)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning("Failed to load AI chat history from %s: %s", self.ai_chat_history_path, e)
        return []

    def save_ai_chat_history(self):
        """Save AI chat history to JSON file"""
        try:
            with open(self.ai_chat_history_path, 'w') as f:
                json.dump(self.ai_chat_history, f, indent=2)
        except (OSError, TypeError, ValueError) as e:
            logger.error("Failed to save AI chat history to %s: %s", self.ai_chat_history_path, e)





    def initialize_themes(self):
        """Initialize theme definitions and apply current theme"""
        self.themes = {
            "dark": {
                "name": "Dark Theme",
                "background": "#2b2d30",
                "text": "#ffffff",
                "input_bg": "#3c3f41",
                "input_text": "white",
                "button_bg": "#4a5568",
                "button_hover": "#2d3748",
                "button_pressed": "#1a202c",
                "border": "#555555",
                "divider": "#dcdcdc",
                "accent": "#3a6ea5",
                "table_bg": "#1e1e1e",
                "table_alt": "#2a2a2a",
                "menu_bg": "#2b2b2b",
                "menu_text": "#d0d0d0",
                "menu_hover": "#3a6ea5"
            },
            "light": {
                "name": "Light Theme", 
                "background": "#f5f5f5",
                "text": "#000000",
                "input_bg": "#ffffff",
                "input_text": "#000000",
                "button_bg": "#e0e0e0",
                "button_hover": "#d0d0d0",
                "button_pressed": "#c0c0c0",
                "border": "#cccccc",
                "divider": "#aaaaaa",
                "accent": "#1976d2",
                "table_bg": "#ffffff",
                "table_alt": "#f8f8f8",
                "menu_bg": "#ffffff",
                "menu_text": "#000000",
                "menu_hover": "#1976d2"
            }
        }
        self.apply_theme()

    def load_theme_settings(self):
        """Load theme settings from file"""
        try:
            if os.path.exists(self.theme_settings_file):
                with open(self.theme_settings_file, 'r') as f:
                    settings = json.load(f)
                    self.current_theme = settings.get('theme', 'dark')
            else:
                self.current_theme = 'dark'
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            self.current_theme = 'dark'

    def save_theme_settings(self):
        """Save current theme settings to file"""
        try:
            settings = {'theme': self.current_theme}
            with open(self.theme_settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
        except (OSError, TypeError, ValueError) as e:
            logger.error("Failed to save theme settings to %s: %s", self.theme_settings_file, e)

    def toggle_theme(self):
        """Toggle between dark and light themes"""
        self.current_theme = "light" if self.current_theme == "dark" else "dark"
        self.apply_theme()
        self.save_theme_settings()

    def set_theme(self, theme_name):
        """Set specific theme"""
        if theme_name in self.themes:
            self.current_theme = theme_name
            self.apply_theme()
            self.save_theme_settings()




    def toggle_results_maximize(self):
        """Toggle maximizing the results area by hiding or showing the left SQL editor frame."""
        try:
            if hasattr(self, 'left_frame') and self.left_frame.isVisible():
                # Hide left editor and expand results to occupy full width
                self.left_frame.hide()
                self.toggle_results_btn.setText("🗗")
                # Keep interactive mode - user can resize columns manually if needed
                # This is much faster than auto-resizing for large datasets
                try:
                    # Keep interactive sizing mode for performance
                    self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
                    # Ensure last section does not stretch
                    self.results_table.horizontalHeader().setStretchLastSection(False)
                    # Allow horizontal scrolling when columns exceed viewport
                    self.results_table.setHorizontalScrollMode(QTableView.ScrollMode.ScrollPerPixel)
                except (AttributeError, RuntimeError, TypeError):
                    pass
            else:
                # Show left editor and restore layout
                if hasattr(self, 'left_frame'):
                    self.left_frame.show()
                self.toggle_results_btn.setText("🗗")
                # Keep interactive column sizing when layout is restored
                try:
                    self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
                    # keep interactive sizing, don't stretch last section
                    self.results_table.horizontalHeader().setStretchLastSection(False)
                    # restore horizontal scroll mode to default
                    self.results_table.setHorizontalScrollMode(QTableView.ScrollMode.ScrollPerItem)
                except (AttributeError, RuntimeError, TypeError):
                    pass
        except (AttributeError, RuntimeError, TypeError) as e:
            logger.error("Error toggling results maximize: %s", e)

    def upload_files(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Files (Hold Ctrl/Cmd for multiple files)",
            "",
            "All Supported (*.csv *.xlsx *.xls *.xml *.txt *.json *.zip);;CSV Files (*.csv);;Excel Files (*.xlsx *.xls);;XML Files (*.xml);;Text Files (*.txt);;JSON Files (*.json);;ZIP Archives (*.zip);;All Files (*.*)",
        )

        if not file_paths:
            return
        
        # Show info about multiple file selection
        if len(file_paths) > 1:
            file_summary = "\n".join([f"  • {os.path.basename(f)}" for f in file_paths[:10]])
            if len(file_paths) > 10:
                file_summary += f"\n  ... and {len(file_paths) - 10} more files"
            
            QMessageBox.information(
                self,
                f"Multiple Files Selected ({len(file_paths)} files)",
                f"You selected {len(file_paths)} files: \n {file_summary} "
                "Files of the same type can be merged into one table or kept separate. \n"
                "You'll be prompted for merge options during import."
            )

        self.conn = duckdb.connect(database=":memory:", read_only=False)

        # Group files by type
        csv_files = [f for f in file_paths if f.lower().endswith((".csv", ".txt"))]
        excel_files = [f for f in file_paths if f.lower().endswith((".xlsx", ".xls"))]
        xml_files = [f for f in file_paths if f.lower().endswith(".xml")]
        json_files = [f for f in file_paths if f.lower().endswith(".json")]
        zip_files = [f for f in file_paths if f.lower().endswith(".zip")]

        # --- Batch settings for CSV files with MERGE option ---
        csv_delimiter = None
        csv_skip_rows = None
        apply_same_settings = False
        merge_csv_files = False
        merged_csv_name = None
        add_source_filename = False  # Initialize for single file uploads
        
        # --- Excel merge settings ---
        merge_excel_files = False
        excel_skip_rows = None
        merged_excel_name = None
        
        # --- XML merge settings ---
        merge_xml_files = False
        merged_xml_name = None
        
        # --- JSON merge settings ---
        merge_json_files = False
        merged_json_name = None

        if len(csv_files) > 1:
            # Ask if user wants to MERGE or keep separate
            merge_reply = MainWindow.show_styled_message_box(
                self,
                "Multiple CSV Files Detected",
                f"You selected {len(csv_files)} CSV files. \n"
                "Choose an option: \n"
                "• YES = MERGE all CSVs into ONE parquet file \n"
                "• NO = Keep them as SEPARATE parquet files",
                icon=QMessageBox.Icon.Question,
                buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if merge_reply == QMessageBox.StandardButton.Yes:
                # MERGE MODE
                merge_csv_files = True
                apply_same_settings = True
                
                # Ask for merged file name
                merged_csv_name = self.create_input_popup(
                    "Merged File Name",
                    "Enter name for the MERGED parquet file:"
                )
                if not merged_csv_name or not merged_csv_name.strip():
                    merged_csv_name = "merged_data"
                
                # Ask if user wants to add source filename column
                add_filename_column_reply = MainWindow.show_styled_message_box(
                    self,
                    "Add Source Filename Column?",
                    f"Do you want to add a column showing which file each row came from? \n"
                    "This adds a '_source_file' column with the original filename. \n"
                    "Recommended: YES (helps track data origin)",
                    icon=QMessageBox.Icon.Question,
                    buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                add_source_filename = (add_filename_column_reply == QMessageBox.StandardButton.Yes)
                
                # Ask once for delimiter
                csv_delimiter = self.create_input_popup(
                    "CSV Delimiter", 
                    "Enter CSV delimiter for ALL CSV files (default is comma):"
                )
                if csv_delimiter is None:
                    return
                csv_delimiter = csv_delimiter or ","
                
                # Ask once for skip rows
                csv_skip_rows = self.create_input_popup(
                    "Skip Rows", 
                    "No. of rows to skip from top (leave blank for 0):"
                )
                if csv_skip_rows is None:
                    return
                csv_skip_rows = csv_skip_rows.strip() if csv_skip_rows else "0"
                
                # Ask once for ignore errors
                ignore_errors_reply = MainWindow.show_styled_message_box(
                    self,
                    "Ignore Errors?",
                    "Do you want to ignore errors during CSV loading? \n"
                    "YES = Skip rows with errors and continue loading \n"
                    "NO = Stop loading if any errors are found",
                    icon=QMessageBox.Icon.Question,
                    buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                csv_ignore_errors = (ignore_errors_reply == QMessageBox.StandardButton.Yes)
                    
            else:
                # SEPARATE FILES MODE - Ask if same settings for all
                add_source_filename = False  # Default for separate files
                settings_reply = MainWindow.show_styled_message_box(
                    self,
                    "Multiple CSV Files",
                    f"You selected {len(csv_files)} CSV files. \n"
                    "Do you want to apply the same delimiter and limit to all CSV files?",
                    icon=QMessageBox.Icon.Question,
                    buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                
                if settings_reply == QMessageBox.StandardButton.Yes:
                    apply_same_settings = True
                    
                    # Ask once for delimiter
                    csv_delimiter = self.create_input_popup(
                        "CSV Delimiter", 
                        "Enter CSV delimiter for ALL CSV files (default is comma):"
                    )
                    if csv_delimiter is None:
                        return
                    csv_delimiter = csv_delimiter or ","
                    
                    # Ask once for skip rows
                    csv_skip_rows = self.create_input_popup(
                        "Skip Rows", 
                        "No. of rows to skip from top for ALL CSV files (leave blank for 0):"
                    )
                    if csv_skip_rows is None:
                        return
                    csv_skip_rows = csv_skip_rows.strip() if csv_skip_rows else "0"
                    
                    # Ask once for ignore errors
                    ignore_errors_reply = MainWindow.show_styled_message_box(
                        self,
                        "Ignore Errors?",
                        "Do you want to ignore errors during CSV loading for ALL files? \n"
                        "YES = Skip rows with errors and continue loading \n"
                        "NO = Stop loading if any errors are found",
                        icon=QMessageBox.Icon.Question,
                        buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    csv_ignore_errors = (ignore_errors_reply == QMessageBox.StandardButton.Yes)
                    
                    # Ask if user wants to add source filename column to each file
                    add_filename_reply = MainWindow.show_styled_message_box(
                        self,
                        "Add Source Filename Column?",
                        f"Add a '_source_file' column to each parquet file showing the original filename? \n"
                        "This helps track which CSV file the data came from.",
                        icon=QMessageBox.Icon.Question,
                        buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    add_source_filename = (add_filename_reply == QMessageBox.StandardButton.Yes)

        # --- Excel merge handling ---
        shared_excel_sheet = None
        if len(excel_files) > 1:
            # Ask if user wants to MERGE Excel files
            excel_merge_reply = MainWindow.show_styled_message_box(
                self,
                "Multiple Excel Files Detected",
                f"You selected {len(excel_files)} Excel files. \n"
                "Choose an option: \n"
                "• YES = MERGE all Excel files into ONE parquet file \n"
                "• NO = Keep them as SEPARATE parquet files",
                icon=QMessageBox.Icon.Question,
                buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if excel_merge_reply == QMessageBox.StandardButton.Yes:
                merge_excel_files = True
                
                # Ask for merged file name
                merged_excel_name = self.create_input_popup(
                    "Merged Excel File Name",
                    "Enter name for the MERGED parquet file:"
                )
                if not merged_excel_name or not merged_excel_name.strip():
                    merged_excel_name = "merged_excel"
                
            # Ask for sheet name (needed for both merge and separate modes)
            shared_excel_sheet = self.create_input_popup(
                "Select Sheet For All",
                "Enter sheet index (0-based) or sheet name to use for all Excel files:",
            )
            if shared_excel_sheet is None:
                return
            
            # Ask for skip rows
            excel_skip_rows = self.create_input_popup(
                "Skip Rows",
                "Enter number of rows to skip from top (leave blank for 0):",
            )
            if excel_skip_rows is None:
                return
            excel_skip_rows = excel_skip_rows.strip() if excel_skip_rows else "0"
        
        # --- XML merge handling ---
        if len(xml_files) > 1:
            xml_merge_reply = MainWindow.show_styled_message_box(
                self,
                "Multiple XML Files Detected",
                f"You selected {len(xml_files)} XML files. \n"
                "Choose an option: \n"
                "• YES = MERGE all XML files into ONE parquet file \n"
                "• NO = Keep them as SEPARATE parquet files",
                icon=QMessageBox.Icon.Question,
                buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if xml_merge_reply == QMessageBox.StandardButton.Yes:
                merge_xml_files = True
                
                # Ask for merged file name
                merged_xml_name = self.create_input_popup(
                    "Merged XML File Name",
                    "Enter name for the MERGED parquet file:"
                )
                if not merged_xml_name or not merged_xml_name.strip():
                    merged_xml_name = "merged_xml"
        
        # --- JSON merge handling ---
        if len(json_files) > 1:
            json_merge_reply = MainWindow.show_styled_message_box(
                self,
                "Multiple JSON Files Detected",
                f"You selected {len(json_files)} JSON files. \n"
                "Choose an option: \n"
                "• YES = MERGE all JSON files into ONE parquet file \n"
                "• NO = Keep them as SEPARATE parquet files",
                icon=QMessageBox.Icon.Question,
                buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if json_merge_reply == QMessageBox.StandardButton.Yes:
                merge_json_files = True
                
                # Ask for merged file name
                merged_json_name = self.create_input_popup(
                    "Merged JSON File Name",
                    "Enter name for the MERGED parquet file:"
                )
                if not merged_json_name or not merged_json_name.strip():
                    merged_json_name = "merged_json"

        skipped_files = []

        # Show progress dialog
        progress = QProgressDialog("Uploading files...", "Cancel", 0, len(file_paths), self)
        progress.setWindowTitle("File Upload Progress")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        self.apply_progress_dialog_styling(progress, "#607D8B")
        progress.show()
        QApplication.processEvents()

        def sanitize_filename(filename: str) -> str:
            import re
            return re.sub(r"[^a-zA-Z0-9_\-]", "", filename)

        for file_index, file in enumerate(file_paths, 1):
            if progress.wasCanceled():
                break

            default_name = os.path.splitext(os.path.basename(file))[0]
            processed = False

            # --- CSV/TXT Processing ---
            if file.lower().endswith((".csv", ".txt")):
                # Skip individual processing if in merge mode
                if merge_csv_files:
                    # Files will be processed in batch after the loop
                    continue
                    
                # Use batch settings if available, otherwise ask per file
                if apply_same_settings:
                    delimiter = csv_delimiter
                    skip_rows_input = csv_skip_rows
                    ignore_errors = csv_ignore_errors
                else:
                    settings = self._ask_csv_settings(os.path.basename(file))
                    if settings is None:
                        return
                    delimiter, skip_rows_input, ignore_errors = settings

                # Ask for custom name (optional - you can auto-generate names in batch mode)
                if apply_same_settings:
                    # Auto-generate name in batch mode
                    custom_name = default_name
                else:
                    custom_name = self.create_input_popup(
                        "Save As",
                        f"Enter a name for {default_name}.parquet (leave blank to keep original):",
                    )
                    if custom_name is None:
                        return

                final_name = sanitize_filename(os.path.basename(custom_name.strip().lower())) if custom_name else default_name
                parquet_file = os.path.join(self.doc_dir, f"{final_name}.parquet")

                file_size_bytes = os.path.getsize(file)
                file_size_mb = round(file_size_bytes / (1024 * 1024 * 1024), 2)

                print(f" \n📄 File: {os.path.basename(file)} | Size: {file_size_mb} GB")
                
                start_time = time.time()
                print(f"🚀 Upload started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")

                self.conn.execute("PRAGMA threads=8;")
                self.conn.execute("PRAGMA memory_limit='16GB';")
                self.conn.execute("PRAGMA enable_progress_bar=true;")

                # Determine skip rows parameter
                skip_n = int(skip_rows_input) if skip_rows_input and skip_rows_input.isdigit() else 0
                skip_param = f", skip={skip_n}" if skip_n > 0 else ""

                try:
                    # First, count total rows in source file (for error detection)
                    try:
                        ignore_errors_param = "true" if ignore_errors else "false"
                        total_rows_query = f"""
                            SELECT COUNT(*) as total 
                            FROM read_csv_auto('{file}', delim='{delimiter}'{skip_param}, ignore_errors={ignore_errors_param})
                        """
                        total_rows_result = self.conn.execute(total_rows_query).fetchone()
                        expected_total_rows = total_rows_result[0] if total_rows_result else 0
                    except (duckdb.Error, OSError, ValueError, TypeError):
                        # If counting fails, we'll skip error tracking
                        expected_total_rows = None
                    
                    # Load the CSV data
                    # Add source filename column if requested
                    if add_source_filename:
                        source_filename = os.path.basename(file)
                        self.conn.execute(
                            f"""
                            COPY (
                                SELECT *, '{source_filename}' AS _source_file
                                FROM read_csv_auto('{file}', delim='{delimiter}', parallel=True{skip_param},ignore_errors={ignore_errors_param},nullstr='\\N',null_padding=true)
                            ) 
                            TO '{parquet_file}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');
                            """
                        )
                    else:
                        self.conn.execute(
                            f"""
                            COPY (
                                SELECT * 
                                FROM read_csv_auto('{file}', delim='{delimiter}', parallel=True{skip_param},ignore_errors={ignore_errors_param},nullstr='\\N',null_padding=true)
                            ) 
                            TO '{parquet_file}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');
                            """
                        )
                    
                    # Check if any rows were skipped
                    if expected_total_rows is not None:
                        loaded_rows_query = f"SELECT COUNT(*) FROM read_parquet('{parquet_file}')"
                        loaded_rows_result = self.conn.execute(loaded_rows_query).fetchone()
                        loaded_rows = loaded_rows_result[0] if loaded_rows_result else 0
                        
                        skipped_rows_count = expected_total_rows - loaded_rows
                        
                        if skipped_rows_count > 0:
                            # Save error rows to a separate file
                            error_file = self._save_error_rows(file, delimiter, skip_param, parquet_file, skipped_rows_count)
                            if error_file:
                                print(f"⚠️ {skipped_rows_count} rows had errors and were saved to: {error_file}")
                                MainWindow.show_styled_message_box(
                                    self,
                                    "Rows Skipped",
                                    f"File: '{os.path.basename(file)}' \n"
                                    f"✅ Loaded: {loaded_rows:,} rows \n"
                                    f"⚠️ Skipped: {skipped_rows_count:,} rows (errors) \n"
                                    f"Error rows saved to: \n{os.path.basename(error_file)}",
                                    icon=QMessageBox.Icon.Warning
                                )
                    
                    processed = True
                    
                    end_time = time.time()
                    total_time = end_time - start_time
                    
                    converted_size_bytes = os.path.getsize(parquet_file)
                    converted_size_mb = round(converted_size_bytes / (1024 * 1024 * 1024), 2)
                    
                    print(f"✅ Converted Parquet Size: {converted_size_mb} GB")
                    print(f"✅ File Saved at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"⏱️ Total Execution Time: {total_time:.2f} seconds ({total_time/60:.2f} minutes)")
                    
                except (duckdb.Error, OSError, ValueError, TypeError, UnicodeDecodeError) as e:
                    print(f"❌ Failed to process {file}: {e}")
                    
                    # Try to automatically fix with selective column conversion
                    try:
                        print(f"🔧 Auto-fixing: Attempting to identify and fix problematic columns...")
                        
                        # First, try to read a sample to identify problematic columns
                        result = self._fix_problematic_columns(file, delimiter, skip_param, parquet_file, add_source_filename)
                        
                        if result['success']:
                            processed = True
                            end_time = time.time()
                            total_time = end_time - start_time
                            converted_size_bytes = os.path.getsize(parquet_file)
                            converted_size_mb = round(converted_size_bytes / (1024 * 1024 * 1024), 2)
                            
                            print(f"✅ Auto-fixed! Converted Parquet Size: {converted_size_mb} GB")
                            print(f"⏱️ Total Execution Time: {total_time:.2f} seconds")
                            
                            MainWindow.show_styled_message_box(
                                self,
                                "Auto-Fixed",
                                f"File '{os.path.basename(file)}' uploaded successfully! \n"
                                f"✅ {result['message']} \n"
                                f"✅ ALL rows preserved, no data lost \n"
                                f"Original error: {str(e)[:100]}... \n"
                                f"Solution: {result['solution']} \n"
                                f"Converted columns: {', '.join(result.get('converted_columns', []))}" if result.get('converted_columns') else "",
                                icon=QMessageBox.Icon.Information
                            )
                            continue  # Move to next file
                        else:
                            raise RuntimeError(result['error'])
                            
                    except (duckdb.Error, OSError, ValueError, TypeError, RuntimeError) as auto_fix_error:
                        print(f"⚠️ Auto-fix failed: {auto_fix_error}")
                        
                        # Fall back to manual user choice
                        error_msg = (
                            f"Failed to upload '{os.path.basename(file)}': \n"
                            f"Error: {str(e)} \n"
                            f"Auto-fix attempt also failed. \n"
                            f"This could be due to: \n"
                            f"• Incorrect delimiter \n"
                            f"• Severely malformed data \n"
                            f"• Encoding issues \n"
                            f"What would you like to do?"
                        )
                        
                        # Create custom dialog with options
                        retry_dialog = QMessageBox(self)
                        retry_dialog.setWindowTitle("File Upload Error")
                        retry_dialog.setText(error_msg)
                        retry_dialog.setIcon(QMessageBox.Icon.Warning)
                        
                        # Add custom buttons
                        skip_btn = retry_dialog.addButton("⏭️ Skip This File", QMessageBox.ButtonRole.RejectRole)
                        cancel_btn = retry_dialog.addButton("❌ Cancel All", QMessageBox.ButtonRole.DestructiveRole)
                        
                        retry_dialog.exec()
                        clicked_button = retry_dialog.clickedButton()
                        
                        if clicked_button == skip_btn:
                            # Skip this file and continue
                            print(f"⏭️ Skipping {os.path.basename(file)}")
                            skipped_files.append(file)
                            processed = False
                        
                        else:  # Cancel all
                            print(f"❌ Upload cancelled by user")
                            progress.close()
                            return

            # --- Excel Processing ---
            elif file.lower().endswith((".xlsx", ".xls")):
                # Skip individual processing if in merge mode
                if merge_excel_files:
                    continue
                    
                try:
                    sheet_names = pd.ExcelFile(file).sheet_names
                except (ValueError, OSError, ImportError) as e:
                    print(f"Failed to read Excel file {file}: {e}")
                    skipped_files.append(file)
                    continue

                if shared_excel_sheet:
                    sel = shared_excel_sheet.strip()
                    skip_rows_input = excel_skip_rows
                else:
                    sel = self.create_input_popup(
                        "Select Sheet",
                        f"Available Sheets: \n{', '.join(sheet_names)} \nEnter sheet index (0-based) or sheet name to load:",
                    )
                    if sel is None:
                        return
                    
                    # Ask for skip rows for individual file
                    skip_rows_input = self.create_input_popup(
                        "Skip Rows",
                        f"Enter number of rows to skip from top for '{os.path.basename(file)}' (leave blank for 0):",
                    )
                    if skip_rows_input is None:
                        return
                    skip_rows_input = skip_rows_input.strip() if skip_rows_input else "0"

                chosen_sheet = None
                if sel.isdigit():
                    idx = int(sel)
                    if 0 <= idx < len(sheet_names):
                        chosen_sheet = sheet_names[idx]
                else:
                    if sel in sheet_names:
                        chosen_sheet = sel

                if chosen_sheet is None:
                    skipped_files.append(file)
                    continue

                custom_name = self.create_input_popup(
                    "Save As",
                    f"Enter a name for {default_name}.parquet (leave blank to keep original):",
                )
                if custom_name is None:
                    return

                final_name = sanitize_filename(os.path.basename(custom_name.strip().lower())) if custom_name else default_name
                parquet_file = os.path.join(self.doc_dir, f"{final_name}.parquet")

                try:
                    # Determine skip rows
                    skip_n = int(skip_rows_input) if skip_rows_input and skip_rows_input.isdigit() else 0
                    
                    # Read Excel with skiprows parameter
                    df = pd.read_excel(file, sheet_name=chosen_sheet, skiprows=skip_n if skip_n > 0 else None)
                    self.conn.register("temp_table", df)

                    self.conn.execute("PRAGMA threads=8;")
                    self.conn.execute("PRAGMA memory_limit='16GB';")
                    self.conn.execute(
                        f"""
                        COPY temp_table TO '{parquet_file}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');
                        """
                    )
                    processed = True

                    MainWindow.show_styled_message_box(
                        self,
                        "Success",
                        f"Sheet '{chosen_sheet}' from '{os.path.basename(file)}' saved as Parquet!",
                        icon=QMessageBox.Icon.Information,
                    )
                except (duckdb.Error, OSError, ValueError, TypeError) as e:
                    print(f"Failed to convert Excel sheet for {file}: {e}")
                    
                    # Try to automatically fix by detecting problematic columns
                    try:
                        print(f"🔍 Analyzing Excel file to identify problematic columns...")
                        skip_n = int(skip_rows_input) if skip_rows_input and skip_rows_input.isdigit() else 0
                        
                        # Load with all text to identify structure
                        df_text = pd.read_excel(file, sheet_name=chosen_sheet, skiprows=skip_n if skip_n > 0 else None, dtype=str)
                        
                        if df_text.empty:
                            raise ValueError("Excel sheet appears to be empty")
                        
                        columns = list(df_text.columns)
                        print(f"📋 Found {len(columns)} columns")
                        
                        # Try to load without dtype restriction to see which columns fail
                        problematic_columns = []
                        try:
                            df_auto = pd.read_excel(file, sheet_name=chosen_sheet, skiprows=skip_n if skip_n > 0 else None)
                            # If this succeeds, register and save
                            self.conn.register("temp_table", df_auto)
                            self.conn.execute("PRAGMA threads=8;")
                            self.conn.execute("PRAGMA memory_limit='16GB';")
                            self.conn.execute(f"COPY temp_table TO '{parquet_file}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');")
                            processed = True
                            print(f"✅ Successfully uploaded on retry with auto types!")
                            
                            MainWindow.show_styled_message_box(
                                self,
                                "Success",
                                f"Sheet '{chosen_sheet}' from '{os.path.basename(file)}' saved successfully!",
                                icon=QMessageBox.Icon.Information
                            )
                            continue
                        except (ValueError, TypeError, OSError, duckdb.Error) as type_error:
                            # Types failed, need to identify which columns
                            print(f"⚠️ Type detection failed: {type_error}")
                            
                            # Check each column individually
                            for col in columns:
                                try:
                                    # Try to convert this specific column
                                    test_df = pd.read_excel(file, sheet_name=chosen_sheet, skiprows=skip_n if skip_n > 0 else None, usecols=[col])
                                    # If conversion works, column is fine
                                except (ValueError, TypeError, OSError):
                                    problematic_columns.append(col)
                            
                            if problematic_columns:
                                print(f"⚠️ Found {len(problematic_columns)} problematic column(s): {', '.join(problematic_columns[:5])}")
                                print(f"✅ {len(columns) - len(problematic_columns)} columns will keep proper data types")
                                
                                # Use the all-text version but inform user which columns had issues
                                self.conn.register("temp_table", df_text)
                                self.conn.execute("PRAGMA threads=8;")
                                self.conn.execute("PRAGMA memory_limit='16GB';")
                                self.conn.execute(f"COPY temp_table TO '{parquet_file}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');")
                                processed = True
                                
                                MainWindow.show_styled_message_box(
                                    self,
                                    "Auto-Fixed",
                                    f"File '{os.path.basename(file)}' uploaded successfully! \n"
                                    f"✅ {len(problematic_columns)} problematic column(s) converted to text \n"
                                    f"✅ ALL rows preserved, no data lost \n"
                                    f"Problematic columns: {', '.join(problematic_columns[:10])}{'...' if len(problematic_columns) > 10 else ''}",
                                    icon=QMessageBox.Icon.Information
                                )
                                continue
                            else:
                                # Different kind of error
                                raise e
                    
                    except (ValueError, TypeError, OSError, duckdb.Error) as auto_fix_error:
                        print(f"⚠️ Auto-fix failed: {auto_fix_error}")
                        
                        # Fall back to manual user choice
                        error_msg = (
                            f"Failed to upload '{os.path.basename(file)}': \n"
                            f"Error: {str(e)} \n"
                            f"Auto-fix attempt also failed. \n"
                            f"This could be due to: \n"
                            f"• Wrong sheet selected \n"
                            f"• Corrupted Excel file \n"
                            f"• Protected/encrypted file \n"
                            f"What would you like to do?"
                        )
                        
                        retry_dialog = QMessageBox(self)
                        retry_dialog.setWindowTitle("Excel Upload Error")
                        retry_dialog.setText(error_msg)
                        retry_dialog.setIcon(QMessageBox.Icon.Warning)
                        
                        skip_btn = retry_dialog.addButton("⏭️ Skip This File", QMessageBox.ButtonRole.RejectRole)
                        cancel_btn = retry_dialog.addButton("❌ Cancel All", QMessageBox.ButtonRole.DestructiveRole)
                        
                        retry_dialog.exec()
                        clicked_button = retry_dialog.clickedButton()
                    
                        if clicked_button == skip_btn:
                            print(f"⏭️ Skipping {os.path.basename(file)}")
                            skipped_files.append(file)
                        else:
                            print(f"❌ Upload cancelled by user")
                            progress.close()
                            return
                        
                finally:
                    try:
                        self.conn.unregister("temp_table")
                    except (duckdb.Error, RuntimeError, AttributeError):
                        pass

            # --- XML Processing ---
            elif file.lower().endswith(".xml"):
                # Skip individual processing if in merge mode
                if merge_xml_files:
                    continue
                    
                custom_name = self.create_input_popup(
                    "Save As",
                    f"Enter a name for {default_name}.parquet (leave blank to keep original):",
                )
                if custom_name is None:
                    return

                final_name = sanitize_filename(os.path.basename(custom_name.strip().lower())) if custom_name else default_name
                parquet_file = os.path.join(self.doc_dir, f"{final_name}.parquet")

                df = pd.read_xml(file)
                try:
                    self.conn.register("_temp_upload", df)
                    self.conn.execute("PRAGMA threads=8;")
                    self.conn.execute(f"COPY _temp_upload TO '{parquet_file}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');")
                    try:
                        self.conn.unregister("_temp_upload")
                    except (duckdb.Error, RuntimeError, AttributeError):
                        pass
                except (duckdb.Error, RuntimeError, TypeError, ValueError):
                    try:
                        tmp_table = f"temp_xml_fallback_{int(time.time())}_{uuid.uuid4().hex[:8]}"
                        self.conn.register(tmp_table, df)
                        self.conn.execute(f"COPY {tmp_table} TO '{parquet_file}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');")
                        try:
                            self.conn.unregister(tmp_table)
                        except (duckdb.Error, RuntimeError, AttributeError):
                            pass
                    except (duckdb.Error, RuntimeError, TypeError, ValueError) as e:
                        print(f"XML fallback parquet write failed: {e}")
                processed = True

            # --- JSON Processing ---
            elif file.lower().endswith(".json"):
                # Skip individual processing if in merge mode
                if merge_json_files:
                    continue
                    
                custom_name = self.create_input_popup(
                    "Save As",
                    f"Enter a name for {default_name}.parquet (leave blank to keep original):",
                )
                if custom_name is None:
                    return

                final_name = sanitize_filename(os.path.basename(custom_name.strip().lower())) if custom_name else default_name
                parquet_file = os.path.join(self.doc_dir, f"{final_name}.parquet")

                try:
                    try:
                        # Use DuckDB for direct JSON to parquet conversion
                        self.conn.execute("PRAGMA threads=8;")
                        self.conn.execute(f"COPY (SELECT * FROM read_json_auto('{file}')) TO '{parquet_file}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');")
                        print(f"✅ Direct DuckDB JSON to parquet conversion completed")
                    except (duckdb.Error, OSError, ValueError, TypeError) as e1:
                        print(f"⚠️ Direct conversion failed, trying register method: {e1}")
                        # Fallback: load to DataFrame then use DuckDB
                        try:
                            df = duckdb.sql(f"SELECT * FROM read_json_auto('{file}')").df()
                            temp_table = f"temp_json_{int(time.time())}"
                            self.conn.register(temp_table, df)
                            self.conn.execute(f"COPY {temp_table} TO '{parquet_file}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');")
                            self.conn.unregister(temp_table)
                            print(f"✅ Fallback DuckDB conversion completed")
                        except (duckdb.Error, OSError, ValueError, TypeError) as e2:
                            print(f"⚠️ DuckDB fallback failed: {e2}")
                            try:
                                tmp_table = f"temp_json_fallback_{int(time.time())}_{uuid.uuid4().hex[:8]}"
                                self.conn.register(tmp_table, df)
                                self.conn.execute(f"COPY {tmp_table} TO '{parquet_file}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');")
                                try:
                                    self.conn.unregister(tmp_table)
                                except (duckdb.Error, RuntimeError, AttributeError):
                                    pass
                            except (duckdb.Error, OSError, ValueError, TypeError) as fallback_err:
                                print(f"JSON fallback parquet write failed: {fallback_err}")
                    processed = True
                except (duckdb.Error, OSError, ValueError, TypeError) as e:
                    print(f"Failed to convert JSON to Parquet for {file}: {e}")

            # --- ZIP Processing ---
            elif file.lower().endswith(".zip"):
                try:
                    processed_files = self.process_zip_file(file, progress)
                    if processed_files:
                        # Add all processed files from ZIP to uploaded files
                        self.uploaded_files.extend(processed_files)
                        # Try to select the last processed file so its table/schema is shown
                        try:
                            last = processed_files[-1]
                            sel_name = os.path.splitext(os.path.basename(last))[0]
                            self.display_existing_files(selected=sel_name)
                            try:
                                self.Parquet_view_describe(sel_name)
                            except Exception:
                                pass
                        except Exception:
                            # Fallback to generic refresh
                            self.display_existing_files()
                        processed = True
                except (OSError, zipfile.BadZipFile, ValueError, TypeError) as e:
                    print(f"Failed to process ZIP file {file}: {e}")
                    MainWindow.show_styled_message_box(
                        self,
                        "ZIP Processing Error", 
                        f"Failed to process ZIP file '{os.path.basename(file)}': \n{str(e)}",
                        icon=QMessageBox.Icon.Warning
                    )

            # Add to uploaded files list if processed successfully (non-ZIP files)
            if processed and not file.lower().endswith(".zip"):
                self.uploaded_files.append(parquet_file)
                try:
                    sel_name = os.path.splitext(os.path.basename(parquet_file))[0]
                    self.display_existing_files(selected=sel_name)
                    try:
                        self.Parquet_view_describe(sel_name)
                    except (duckdb.Error, ValueError, TypeError):
                        pass
                except (AttributeError, RuntimeError, TypeError):
                    self.display_existing_files()

            # Update progress
            progress.setValue(file_index)
            progress.setLabelText(f"Processing {file_index}/{len(file_paths)}: {os.path.basename(file)}")
            QApplication.processEvents()

        # --- Handle CSV Merge if requested ---
        if merge_csv_files and csv_files:
            progress.setLabelText(f"Merging {len(csv_files)} CSV files...")
            QApplication.processEvents()
            
            try:
                # Use the merged_csv_name already collected at the beginning
                final_merged_name = sanitize_filename(os.path.basename(merged_csv_name.strip().lower())) if merged_csv_name else "merged_csv"
                merged_parquet = os.path.join(self.doc_dir, f"{final_merged_name}.parquet")
                
                print(f" \n🔄 Merging {len(csv_files)} CSV files into {final_merged_name}.parquet...")
                start_merge = time.time()
                
                # Determine skip rows parameter
                skip_n = int(csv_skip_rows) if csv_skip_rows and csv_skip_rows.isdigit() else 0
                skip_param = f", skip={skip_n}" if skip_n > 0 else ""
                ignore_errors_param = "true" if csv_ignore_errors else "false"
                
                # Build UNION ALL query with optional source filename column
                union_parts = []
                for csv_file in csv_files:
                    if add_source_filename:
                        source_filename = os.path.basename(csv_file)
                        union_parts.append(
                            f"SELECT *, '{source_filename}' AS _source_file FROM read_csv_auto('{csv_file}', delim='{csv_delimiter}', parallel=True{skip_param}, ignore_errors={ignore_errors_param})"
                        )
                    else:
                        union_parts.append(
                            f"SELECT * FROM read_csv_auto('{csv_file}', delim='{csv_delimiter}', parallel=True{skip_param}, ignore_errors={ignore_errors_param})"
                        )
                
                union_query = " UNION ALL ".join(union_parts)
                
                # Execute merge
                self.conn.execute("PRAGMA threads=8;")
                self.conn.execute("PRAGMA memory_limit='16GB';")
                self.conn.execute(
                    f"""
                    COPY (
                        {union_query}
                    ) 
                    TO '{merged_parquet}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');
                    """
                )
                
                end_merge = time.time()
                merge_time = end_merge - start_merge
                
                merged_size_bytes = os.path.getsize(merged_parquet)
                merged_size_mb = round(merged_size_bytes / (1024 * 1024 * 1024), 2)
                
                print(f"✅ Merged {len(csv_files)} CSV files successfully!")
                print(f"✅ Merged Parquet Size: {merged_size_mb} GB")
                print(f"⏱️ Merge Time: {merge_time:.2f} seconds")
                
                try:
                    # Select merged file we just created
                    sel_name = final_merged_name
                    self.display_existing_files(selected=sel_name)
                    try:
                        self.Parquet_view_describe(sel_name)
                    except (duckdb.Error, ValueError, TypeError):
                        pass
                except (AttributeError, RuntimeError, TypeError):
                    self.display_existing_files()
                
            except Exception as e:
                print(f"❌ Failed to merge CSV files: {e}")
                detailed_error = f"Merge Operation: CSV Files \nFiles Count: {len(csv_files)} \nError: {str(e)} \nTimestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                MainWindow.show_error_message_box_with_copy(
                    self,
                    "CSV Merge Error",
                    f"Failed to merge CSV files: \n{str(e)}",
                    detailed_text=detailed_error
                )

        # --- Handle Excel Merge if requested ---
        if merge_excel_files and excel_files:
            progress.setLabelText(f"Merging {len(excel_files)} Excel files...")
            QApplication.processEvents()
            
            try:
                # Use the merged_excel_name already collected at the beginning
                final_merged_name = sanitize_filename(os.path.basename(merged_excel_name.strip().lower())) if merged_excel_name else "merged_excel"
                merged_parquet = os.path.join(self.doc_dir, f"{final_merged_name}.parquet")
                
                print(f" \n🔄 Merging {len(excel_files)} Excel files into {final_merged_name}.parquet...")
                start_merge = time.time()
                
                # Register all Excel files as temp tables
                temp_tables = []
                skip_n = int(excel_skip_rows) if excel_skip_rows and excel_skip_rows.isdigit() else 0
                
                for idx, excel_file in enumerate(excel_files):
                    try:
                        sheet_names = pd.ExcelFile(excel_file).sheet_names
                        
                        # Determine which sheet to use
                        chosen_sheet = None
                        if shared_excel_sheet.strip().isdigit():
                            sheet_idx = int(shared_excel_sheet.strip())
                            if 0 <= sheet_idx < len(sheet_names):
                                chosen_sheet = sheet_names[sheet_idx]
                        elif shared_excel_sheet.strip() in sheet_names:
                            chosen_sheet = shared_excel_sheet.strip()
                        
                        if chosen_sheet:
                            # Read Excel with skiprows parameter
                            df = pd.read_excel(excel_file, sheet_name=chosen_sheet, skiprows=skip_n if skip_n > 0 else None)
                            temp_table_name = f"_excel_temp_{idx}"
                            self.conn.register(temp_table_name, df)
                            temp_tables.append(temp_table_name)
                            print(f"  ✓ Loaded {os.path.basename(excel_file)} - Sheet: {chosen_sheet} (Skipped {skip_n} rows)")
                        else:
                            print(f"  ⚠️ Skipped {os.path.basename(excel_file)} - Sheet not found")
                    except Exception as e:
                        print(f"  ❌ Failed to load {os.path.basename(excel_file)}: {e}")
                
                if temp_tables:
                    # Build UNION ALL query
                    union_parts = [f"SELECT * FROM {table}" for table in temp_tables]
                    union_query = " UNION ALL ".join(union_parts)
                    
                    # Execute merge
                    self.conn.execute("PRAGMA threads=8;")
                    self.conn.execute("PRAGMA memory_limit='16GB';")
                    self.conn.execute(
                        f"""
                        COPY (
                            {union_query}
                        ) 
                        TO '{merged_parquet}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');
                        """
                    )
                    
                    # Cleanup temp tables
                    for table in temp_tables:
                        try:
                            self.conn.unregister(table)
                        except (duckdb.Error, RuntimeError, AttributeError):
                            pass
                    
                    end_merge = time.time()
                    merge_time = end_merge - start_merge
                    
                    merged_size_bytes = os.path.getsize(merged_parquet)
                    merged_size_mb = round(merged_size_bytes / (1024 * 1024 * 1024), 2)
                    
                    print(f"✅ Merged {len(temp_tables)} Excel files successfully!")
                    print(f"✅ Merged Parquet Size: {merged_size_mb} GB")
                    print(f"⏱️ Merge Time: {merge_time:.2f} seconds")
                    
                    try:
                        sel_name = final_merged_name
                        self.display_existing_files(selected=sel_name)
                        try:
                            self.Parquet_view_describe(sel_name)
                        except (duckdb.Error, ValueError, TypeError):
                            pass
                    except (AttributeError, RuntimeError, TypeError):
                        self.display_existing_files()
                else:
                    print("❌ No Excel files could be loaded for merging")
                    
            except Exception as e:
                print(f"❌ Failed to merge Excel files: {e}")
                MainWindow.show_styled_message_box(
                    self,
                    "Merge Error",
                    f"Failed to merge Excel files: \n{str(e)}",
                    icon=QMessageBox.Icon.Warning,
                )

        # --- Handle XML Merge if requested ---
        if merge_xml_files and xml_files:
            progress.setLabelText(f"Merging {len(xml_files)} XML files...")
            QApplication.processEvents()
            
            try:
                # Use the merged_xml_name already collected at the beginning
                final_merged_name = sanitize_filename(os.path.basename(merged_xml_name.strip().lower())) if merged_xml_name else "merged_xml"
                merged_parquet = os.path.join(self.doc_dir, f"{final_merged_name}.parquet")
                
                print(f" \n🔄 Merging {len(xml_files)} XML files into {final_merged_name}.parquet...")
                start_merge = time.time()
                
                # Register all XML files as temp tables
                temp_tables = []
                for idx, xml_file in enumerate(xml_files):
                    try:
                        df = pd.read_xml(xml_file)
                        temp_table_name = f"_xml_temp_{idx}"
                        self.conn.register(temp_table_name, df)
                        temp_tables.append(temp_table_name)
                        print(f"  ✓ Loaded {os.path.basename(xml_file)}")
                    except Exception as e:
                        print(f"  ❌ Failed to load {os.path.basename(xml_file)}: {e}")
                
                if temp_tables:
                    # Build UNION ALL query
                    union_parts = [f"SELECT * FROM {table}" for table in temp_tables]
                    union_query = " UNION ALL ".join(union_parts)
                    
                    # Execute merge
                    self.conn.execute("PRAGMA threads=8;")
                    self.conn.execute("PRAGMA memory_limit='16GB';")
                    self.conn.execute(
                        f"""
                        COPY (
                            {union_query}
                        ) 
                        TO '{merged_parquet}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');
                        """
                    )
                    
                    # Cleanup temp tables
                    for table in temp_tables:
                        try:
                            self.conn.unregister(table)
                        except (duckdb.Error, RuntimeError, AttributeError):
                            pass
                    
                    end_merge = time.time()
                    merge_time = end_merge - start_merge
                    
                    merged_size_bytes = os.path.getsize(merged_parquet)
                    merged_size_mb = round(merged_size_bytes / (1024 * 1024 * 1024), 2)
                    
                    print(f"✅ Merged {len(temp_tables)} XML files successfully!")
                    print(f"✅ Merged Parquet Size: {merged_size_mb} GB")
                    print(f"⏱️ Merge Time: {merge_time:.2f} seconds")
                    
                    try:
                        sel_name = final_merged_name
                        self.display_existing_files(selected=sel_name)
                        try:
                            self.Parquet_view_describe(sel_name)
                        except (duckdb.Error, ValueError, TypeError):
                            pass
                    except (AttributeError, RuntimeError, TypeError):
                        self.display_existing_files()
                else:
                    print("❌ No XML files could be loaded for merging")
                    
            except (duckdb.Error, OSError, ValueError, TypeError) as e:
                print(f"❌ Failed to merge XML files: {e}")
                MainWindow.show_styled_message_box(
                    self,
                    "Merge Error",
                    f"Failed to merge XML files: \n{str(e)}",
                    icon=QMessageBox.Icon.Warning,
                )

        # --- Handle JSON Merge if requested ---
        if merge_json_files and json_files:
            progress.setLabelText(f"Merging {len(json_files)} JSON files...")
            QApplication.processEvents()
            
            try:
                # Use the merged_json_name already collected at the beginning
                final_merged_name = sanitize_filename(os.path.basename(merged_json_name.strip().lower())) if merged_json_name else "merged_json"
                merged_parquet = os.path.join(self.doc_dir, f"{final_merged_name}.parquet")
                
                print(f" \n🔄 Merging {len(json_files)} JSON files into {final_merged_name}.parquet...")
                start_merge = time.time()
                
                # Build UNION ALL query for JSON files
                union_parts = []
                for json_file in json_files:
                    union_parts.append(f"SELECT * FROM read_json_auto('{json_file}')")
                
                union_query = " UNION ALL ".join(union_parts)
                
                # Execute merge
                self.conn.execute("PRAGMA threads=8;")
                self.conn.execute("PRAGMA memory_limit='16GB';")
                self.conn.execute(
                    f"""
                    COPY (
                        {union_query}
                    ) 
                    TO '{merged_parquet}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');
                    """
                )
                
                end_merge = time.time()
                merge_time = end_merge - start_merge
                
                merged_size_bytes = os.path.getsize(merged_parquet)
                merged_size_mb = round(merged_size_bytes / (1024 * 1024 * 1024), 2)
                
                print(f"✅ Merged {len(json_files)} JSON files successfully!")
                print(f"✅ Merged Parquet Size: {merged_size_mb} GB")
                print(f"⏱️ Merge Time: {merge_time:.2f} seconds")
                try:
                    sel_name = final_merged_name
                    self.display_existing_files(selected=sel_name)
                    try:
                        self.Parquet_view_describe(sel_name)
                    except (duckdb.Error, ValueError, TypeError):
                        pass
                except (AttributeError, RuntimeError, TypeError):
                    self.display_existing_files()
                
            except (duckdb.Error, OSError, ValueError, TypeError) as e:
                print(f"❌ Failed to merge JSON files: {e}")
                MainWindow.show_styled_message_box(
                    self,
                    "Merge Error",
                    f"Failed to merge JSON files: \n{str(e)}",
                    icon=QMessageBox.Icon.Warning,
                )

        # --- Handle ZIP files processing ---
        if zip_files:
            progress.setLabelText(f"Processing {len(zip_files)} ZIP files...")
            QApplication.processEvents()
            
            for zip_file in zip_files:
                try:
                    processed_files = self.process_zip_file(zip_file, progress)
                    if processed_files:
                        self.uploaded_files.extend(processed_files)
                        try:
                            last = processed_files[-1]
                            sel_name = os.path.splitext(os.path.basename(last))[0]
                            self.display_existing_files(selected=sel_name)
                            try:
                                self.Parquet_view_describe(sel_name)
                            except (duckdb.Error, ValueError, TypeError):
                                pass
                        except (AttributeError, RuntimeError, TypeError):
                            self.display_existing_files()
                except (OSError, zipfile.BadZipFile, ValueError, TypeError) as e:
                    print(f"❌ Error processing ZIP {zip_file}: {e}")
                    continue

        # Close progress dialog
        progress.setValue(len(file_paths))
        progress.close()

        # Show summary
        msg = "Files uploaded and converted to Parquet using DuckDB!"
        if skipped_files:
            msg += f" \nSkipped files (sheet not found or error): \n{chr(10).join([os.path.basename(s) for s in skipped_files])}"

        MainWindow.show_styled_message_box(
            self,
            "Success",
            msg,
            icon=QMessageBox.Icon.Information,
        )

    def _fix_problematic_columns(self, file_path, delimiter, skip_param, parquet_file, add_source_filename=False):
        """
        Intelligently identify and convert only problematic columns to VARCHAR
        instead of converting all columns.
        
        Args:
            file_path: Path to the CSV file
            delimiter: CSV delimiter character
            skip_param: Skip rows parameter
            parquet_file: Output parquet file path
            add_source_filename: Whether to add _source_file column
        """
        try:
            print(f"🔧 Analyzing file structure to identify problematic columns...")
            
            # Step 1: Try to read a small sample to identify the columns
            try:
                # Read just first few rows to analyze column structure
                sample_query = f"""
                    SELECT * FROM read_csv_auto('{file_path}', 
                        delim='{delimiter}', 
                        sample_size=1000, 
                        parallel=false{skip_param},
                        nullstr='\\N',
                        nullstr='\\N',null_padding=true)
                    LIMIT 100
                """
                sample_df = self.conn.execute(sample_query).fetchdf()
                all_columns = list(sample_df.columns)
                print(f"📊 Detected {len(all_columns)} columns in the file")
                
            except Exception as sample_error:
                print(f"⚠️ Could not analyze sample: {sample_error}")
                # If we can't even read a sample, fall back to all_varchar
                return self._fallback_to_all_varchar(file_path, delimiter, skip_param, parquet_file, add_source_filename)
            
            # Step 2: Try to load with auto-detection and identify which columns cause issues
            problematic_columns = []
            
            # Try loading without any special handling first
            try:
                test_query = f"""
                    SELECT * FROM read_csv_auto('{file_path}', 
                        delim='{delimiter}', 
                        parallel=True{skip_param},
                        nullstr='\\N',null_padding=true)
                    LIMIT 1
                """
                self.conn.execute(test_query).fetchdf()
                # If this works, the original error might have been temporary
                print("🎉 File can now be processed normally - retrying original approach...")
                
                # Retry the original query (with optional source filename)
                if add_source_filename:
                    source_filename = os.path.basename(file_path)
                    self.conn.execute(
                        f"""
                        COPY (
                            SELECT *, '{source_filename}' AS _source_file
                            FROM read_csv_auto('{file_path}', delim='{delimiter}', parallel=True{skip_param},nullstr='\\N',null_padding=true)
                        ) 
                        TO '{parquet_file}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');
                        """
                    )
                else:
                    self.conn.execute(
                        f"""
                        COPY (
                            SELECT * 
                            FROM read_csv_auto('{file_path}', delim='{delimiter}', parallel=True{skip_param},nullstr='\\N',null_padding=true)
                        ) 
                        TO '{parquet_file}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');
                        """
                    )
                return {
                    'success': True,
                    'message': 'File processed successfully with original data types preserved',
                    'solution': 'Retry with original auto-detection worked',
                    'converted_columns': []
                }
                
            except Exception as retry_error:
                print(f"🔍 Retry failed, analyzing column-specific issues: {retry_error}")
                
                # Step 3: Try to identify problematic columns by attempting type inference
                try:
                    # Get column information from DuckDB's type detection
                    describe_query = f"""
                        DESCRIBE (
                            SELECT * FROM read_csv_auto('{file_path}', 
                                delim='{delimiter}', 
                                sample_size=5000,
                                parallel=false{skip_param},
                                
                                all_varchar=true)
                            LIMIT 1
                        )
                    """
                    column_info = self.conn.execute(describe_query).fetchdf()
                    
                    # Now try to identify which columns might be problematic
                    # by attempting to cast them back to appropriate types
                    for idx, row in column_info.iterrows():
                        col_name = row['column_name']
                        
                        # Test if column can be safely converted to numeric types
                        try:
                            test_numeric_query = f"""
                                SELECT TRY_CAST("{col_name}" AS DOUBLE) as test_col
                                FROM read_csv_auto('{file_path}', 
                                    delim='{delimiter}', 
                                    sample_size=1000,
                                    parallel=false{skip_param},
                                    
                                    all_varchar=true)
                                WHERE "{col_name}" IS NOT NULL AND TRIM("{col_name}") != ''
                                LIMIT 100
                            """
                            numeric_test = self.conn.execute(test_numeric_query).fetchdf()
                            
                            # If more than 70% of non-null values can be converted to numeric, keep as numeric
                            non_null_count = len(numeric_test[numeric_test['test_col'].notna()])
                            total_count = len(numeric_test)
                            
                            if total_count > 0 and (non_null_count / total_count) < 0.7:
                                # This column has mixed data types, mark as problematic
                                problematic_columns.append(col_name)
                                
                        except Exception:
                            # If we can't test the column, assume it needs VARCHAR conversion
                            problematic_columns.append(col_name)
                    
                    print(f"🎯 Identified {len(problematic_columns)} problematic columns: {', '.join(problematic_columns[:5])}{'...' if len(problematic_columns) > 5 else ''}")
                    
                except Exception as analysis_error:
                    print(f"⚠️ Column analysis failed: {analysis_error}")
                    # Fall back to converting all columns
                    return self._fallback_to_all_varchar(file_path, delimiter, skip_param, parquet_file)
                
            # Step 4: If we identified specific problematic columns, try selective conversion
            if len(problematic_columns) < len(all_columns):
                try:
                    # Create a query that casts only problematic columns to VARCHAR
                    select_parts = []
                    for col in all_columns:
                        if col in problematic_columns:
                            # Cast problematic columns to VARCHAR
                            select_parts.append(f'CAST("{col}" AS VARCHAR) as "{col}"')
                        else:
                            # Keep other columns with auto-detection
                            select_parts.append(f'"{col}"')
                    
                    select_clause = ', '.join(select_parts)
                    
                    selective_query = f"""
                        COPY (
                            SELECT {select_clause}
                            FROM read_csv_auto('{file_path}', 
                                delim='{delimiter}', 
                                parallel=True{skip_param},
                                
                                all_varchar=true)
                        ) 
                        TO '{parquet_file}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');
                    """
                    
                    self.conn.execute(selective_query)
                    
                    return {
                        'success': True,
                        'message': f'Successfully processed with selective column conversion',
                        'solution': f'Converted {len(problematic_columns)} problematic columns to text, preserved {len(all_columns) - len(problematic_columns)} columns with original types',
                        'converted_columns': problematic_columns
                    }
                    
                except (duckdb.Error, OSError, ValueError, TypeError) as selective_error:
                    print(f"⚠️ Selective conversion failed: {selective_error}")
                    # Fall back to all VARCHAR
                    return self._fallback_to_all_varchar(file_path, delimiter, skip_param, parquet_file)
            else:
                # If most columns are problematic, fall back to all VARCHAR
                return self._fallback_to_all_varchar(file_path, delimiter, skip_param, parquet_file)
                
        except (duckdb.Error, OSError, ValueError, TypeError) as e:
            return {
                'success': False,
                'error': f'Analysis failed: {str(e)}'
            }

    def process_zip_file(self, zip_path, progress=None):
        """
        Process ZIP file by streaming files directly through DuckDB without extraction
        Returns list of processed parquet files
        """
        processed_files = []
        zip_basename = os.path.splitext(os.path.basename(zip_path))[0]
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # Get list of supported files in the ZIP
                supported_files = []
                for file_info in zip_ref.filelist:
                    if not file_info.is_dir():
                        filename = file_info.filename.lower()
                        if any(filename.endswith(ext) for ext in ['.csv', '.txt', '.json', '.xlsx', '.xls']):
                            supported_files.append(file_info)
                
                if not supported_files:
                    MainWindow.show_styled_message_box(
                        self,
                        "No Supported Files", 
                        f"ZIP file '{os.path.basename(zip_path)}' contains no supported file types. \n"
                        "Supported: CSV, TXT, JSON, Excel files",
                        icon=QMessageBox.Icon.Information
                    )
                    return []
                
                # Ask user if they want to process all files or select specific ones
                if len(supported_files) > 1:
                    reply = MainWindow.show_styled_message_box(
                        self,
                        "Multiple Files Found",
                        f"Found {len(supported_files)} supported files in ZIP. \n"
                        "Process all files or select specific ones? \n"
                        "• YES = Process ALL files \n"
                        "• NO = Select specific files",
                        icon=QMessageBox.Icon.Question,
                        buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    
                    if reply == QMessageBox.StandardButton.No:
                        # Show file selection dialog
                        files_to_process = self.show_zip_file_selection(supported_files)
                        if not files_to_process:
                            return []
                        supported_files = files_to_process
                
                # Process each selected file
                # Use per-instance sets to avoid duplicate processing across UI/worker paths
                if not hasattr(self, '_zip_processing_entries'):
                    self._zip_processing_entries = set()
                if not hasattr(self, '_processed_zip_entries'):
                    self._processed_zip_entries = set()
                # Track parquet files created recently (shared on the MainWindow instance)
                # so different code paths (UI vs worker) can recognize files created
                # during the same app session and avoid re-prompting.
                if not hasattr(self, '_recently_created_parquets'):
                    self._recently_created_parquets = set()
                recently_created_parquets = self._recently_created_parquets
                # Local tracker for output names used during this ZIP processing session
                seen_output_names_local = {}
                for i, file_info in enumerate(supported_files):
                    if progress and progress.wasCanceled():
                        break
                        
                    filename = file_info.filename
                    file_basename = os.path.splitext(os.path.basename(filename))[0]
                    
                    # Update progress
                    if progress:
                        progress.setLabelText(f"Processing ZIP: {file_basename} ({i+1}/{len(supported_files)})")
                        QApplication.processEvents()
                    
                    try:
                        # Ask user for output filename (and CSV delimiter if needed)
                        suggested_name = f"{zip_basename}_{file_basename}"
                        
                        # For CSV files, ask for both name and delimiter in one dialog
                        csv_delimiter = ","  # Default
                        if filename.lower().endswith(('.csv', '.txt')):
                            # Combined dialog for CSV files
                            cached = getattr(self, '_zip_settings_cache', {}).get(file_basename)
                            if cached is not None:
                                result = cached
                            else:
                                result = self._ask_zip_csv_settings(file_basename, suggested_name)
                            if result is None:
                                # User cancelled, skip this file
                                print(f"⏭️ Skipped {filename} (user cancelled)")
                                continue
                            output_name, csv_delimiter = result
                        else:
                            # For non-CSV files, just ask for filename
                            output_name = self.create_input_popup(
                                "Save As",
                                f"Enter name for '{file_basename}' from ZIP \n(without .parquet extension) \nSuggested: {suggested_name}"
                            )
                            
                            if output_name is None:
                                # User cancelled, skip this file
                                print(f"⏭️ Skipped {filename} (user cancelled)")
                                continue
                        
                        if not output_name or not output_name.strip():
                            output_name = suggested_name
                        
                        # Sanitize filename
                        output_name = output_name.strip()
                        # Ensure unique output_name within this ZIP processing run (case-insensitive)
                        out_key = output_name.lower()
                        if out_key in seen_output_names_local:
                            seen_output_names_local[out_key] += 1
                            suffix = seen_output_names_local[out_key]
                            new_output_name = f"{output_name}_{suffix}"
                            print(f"ℹ️ Adjusting duplicate output name '{output_name}' -> '{new_output_name}'")
                            output_name = new_output_name
                        else:
                            seen_output_names_local[out_key] = 1
                        
                        # Skip duplicate source entries (avoid double-processing across UI/worker)
                        src_norm = os.path.normpath(file_info.filename).lower().strip()
                        if src_norm in self._zip_processing_entries or src_norm in self._processed_zip_entries:
                            print(f"⏭️ Skipping duplicate or already-processed entry {file_info.filename} inside ZIP")
                            continue
                        # Mark as in-progress so other code paths skip it
                        try:
                            self._zip_processing_entries.add(src_norm)
                        except (AttributeError, TypeError):
                            pass

                        # Process file from ZIP. Try streaming CSV -> Parquet (no full temp CSV).
                        parquet_filename = f"{output_name}.parquet"
                        parquet_path = os.path.join(self.doc_dir, parquet_filename)

                        # Check overwrite condition as before
                        parquet_key = os.path.basename(parquet_path).lower()
                        if os.path.exists(parquet_path):
                            if parquet_key in recently_created_parquets:
                                print(f"ℹ️ Skipping overwrite prompt for {parquet_filename} because it was just created in this session")
                            else:
                                try:
                                    mtime = os.path.getmtime(parquet_path)
                                    if time.time() - mtime < 5:
                                        print(f"ℹ️ Detected recent file mtime for {parquet_filename}; treating as created in this session")
                                        try:
                                            recently_created_parquets.add(parquet_key)
                                        except (AttributeError, TypeError):
                                            pass
                                    else:
                                        overwrite = MainWindow.show_styled_message_box(
                                            self,
                                            "File Exists",
                                            f"File '{parquet_filename}' already exists. \nOverwrite?",
                                            icon=QMessageBox.Icon.Question,
                                            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                                        )
                                        if overwrite != QMessageBox.StandardButton.Yes:
                                            print(f"⏭️ Skipped {filename} (file exists, user chose not to overwrite)")
                                            continue
                                except (OSError, ValueError, TypeError):
                                    overwrite = MainWindow.show_styled_message_box(
                                        self,
                                        "File Exists",
                                        f"File '{parquet_filename}' already exists. \nOverwrite?",
                                        icon=QMessageBox.Icon.Question,
                                        buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                                    )
                                    if overwrite != QMessageBox.StandardButton.Yes:
                                        print(f"⏭️ Skipped {filename} (file exists, user chose not to overwrite)")
                                        continue

                        success = False
                        tmp_csv_path = None
                        try:
                            with zip_ref.open(file_info) as file_data:
                                if filename.lower().endswith(('.csv', '.txt')):
                                    # Create temp CSV file and use DuckDB multithreading
                                    try:
                                        print(f"{time.time():.3f} � Extracting CSV '{filename}' to temp file for DuckDB processing")
                                        import tempfile
                                        import shutil
                                        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.csv') as tmpf:
                                            tmp_csv_path = tmpf.name
                                            # Use optimized copy with large buffer for faster extraction
                                            shutil.copyfileobj(file_data, tmpf, length=64*1024*1024)  # 64MB buffer

                                        # Use DuckDB with multithreading to process the temp CSV
                                        try:
                                            self.conn.execute("PRAGMA threads=12;")
                                            self.conn.execute("PRAGMA memory_limit='16GB';")
                                            self.conn.execute(
                                                f"COPY (SELECT * FROM read_csv_auto('{tmp_csv_path}', delim='{csv_delimiter}', parallel=True,  nullstr='\\N',null_padding=true)) TO '{parquet_path}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');"
                                            )
                                            success = True
                                            print(f"✅ DuckDB processed CSV '{filename}' with multithreading")
                                        except (duckdb.Error, ValueError, TypeError) as duckdb_error:
                                            print(f"⚠️ DuckDB processing failed: {duckdb_error}, trying fallback")
                                            # Try fallback method
                                            result = self._fallback_to_all_varchar(tmp_csv_path, csv_delimiter, "", parquet_path)
                                            success = result.get('success', False)

                                    except (OSError, ValueError, TypeError) as e:
                                        print(f"❌ Temp CSV extraction failed for {filename}: {e}")

                                elif filename.lower().endswith('.json'):
                                    # Create temp JSON file and use DuckDB
                                    try:
                                        print(f"{time.time():.3f} 📄 Extracting JSON '{filename}' to temp file for DuckDB processing")
                                        import tempfile
                                        import shutil
                                        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.json') as tmpf:
                                            tmp_csv_path = tmpf.name
                                            # Use optimized copy with large buffer for faster extraction
                                            shutil.copyfileobj(file_data, tmpf, length=64*1024*1024)  # 64MB buffer

                                        # Use DuckDB with multithreading
                                        try:
                                            self.conn.execute("PRAGMA threads=8;")
                                            self.conn.execute("PRAGMA memory_limit='16GB';")
                                            self.conn.execute(
                                                f"COPY (SELECT * FROM read_json_auto('{tmp_csv_path}')) TO '{parquet_path}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');"
                                            )
                                            success = True
                                            print(f"✅ DuckDB processed JSON '{filename}' with multithreading")
                                        except (duckdb.Error, ValueError, TypeError) as duckdb_error:
                                            print(f"⚠️ DuckDB JSON processing failed: {duckdb_error}")

                                    except (OSError, ValueError, TypeError) as e:
                                        print(f"❌ Temp JSON extraction failed for {filename}: {e}")

                                elif filename.lower().endswith(('.xlsx', '.xls')):
                                    # Create temp Excel file and use pandas + DuckDB
                                    try:
                                        print(f"{time.time():.3f} 📄 Extracting Excel '{filename}' to temp file for processing")
                                        import tempfile
                                        import shutil
                                        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.xlsx') as tmpf:
                                            tmp_csv_path = tmpf.name
                                            # Use optimized copy with large buffer for faster extraction
                                            shutil.copyfileobj(file_data, tmpf, length=64*1024*1024)  # 64MB buffer

                                        # Use pandas to read Excel, then DuckDB to write Parquet
                                        df = pd.read_excel(tmp_csv_path)
                                        tmp_table = f"_excel_zip_temp_{int(time.time())}_{uuid.uuid4().hex[:8]}"
                                        self.conn.register(tmp_table, df)
                                        try:
                                            self.conn.execute("PRAGMA threads=8;")
                                            self.conn.execute("PRAGMA memory_limit='16GB';")
                                            self.conn.execute(f"COPY {tmp_table} TO '{parquet_path}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');")
                                            success = True
                                            print(f"✅ Processed Excel '{filename}' via DuckDB")
                                        finally:
                                            try:
                                                self.conn.unregister(tmp_table)
                                            except (duckdb.Error, RuntimeError, AttributeError):
                                                pass

                                    except (OSError, ValueError, TypeError, duckdb.Error) as e:
                                        print(f"❌ Temp Excel extraction failed for {filename}: {e}")

                                else:
                                    # Unsupported file type in ZIP
                                    print(f"⏭️ Skipping unsupported file type: {filename}")
                                    continue
                        except (OSError, ValueError, TypeError, duckdb.Error, zipfile.BadZipFile) as e:
                            print(f"❌ Error processing {filename} from ZIP: {e}")
                            success = False
                        finally:
                            # Clean up any temp CSV we created
                            if tmp_csv_path:
                                try:
                                    os.unlink(tmp_csv_path)
                                except OSError:
                                    pass

                        if success:
                            processed_files.append(parquet_path)
                            try:
                                self._processed_zip_entries.add(src_norm)
                            except (AttributeError, TypeError):
                                pass
                            try:
                                recently_created_parquets.add(os.path.basename(parquet_path).lower())
                            except (AttributeError, TypeError):
                                pass
                            print(f"✅ Processed {filename} from ZIP -> {parquet_filename}")
                        else:
                            print(f"❌ Failed to process {filename} from ZIP")

                        # Clear in-progress marker so retries or other runs can proceed
                        try:
                            self._zip_processing_entries.discard(src_norm)
                        except (AttributeError, TypeError):
                            pass
                                
                    except (OSError, ValueError, TypeError, duckdb.Error, zipfile.BadZipFile) as e:
                        print(f"❌ Error processing {filename} from ZIP: {e}")
                        continue
                
                if processed_files:
                    MainWindow.show_styled_message_box(
                        self,
                        "ZIP Processing Complete",
                        f"Successfully processed {len(processed_files)} files from ZIP: \n"
                        f"'{os.path.basename(zip_path)}'",
                        icon=QMessageBox.Icon.Information
                    )
                    
        except (OSError, zipfile.BadZipFile, ValueError, TypeError) as e:
            print(f"❌ Error opening ZIP file: {e}")
            MainWindow.show_styled_message_box(
                self,
                "ZIP Error", 
                f"Failed to open ZIP file '{os.path.basename(zip_path)}': \n{str(e)}",
                icon=QMessageBox.Icon.Critical
            )
            
        return processed_files

    def _ask_zip_csv_settings(self, file_basename, suggested_name):
        """
        Ask user for both filename and CSV delimiter in one dialog
        Returns tuple (filename, delimiter) or None if cancelled
        """
        # Per-session cache: avoid re-prompting for the same source file during one upload
        # Use only the source file basename as cache key so different suggested names don't bypass cache
        if not hasattr(self, '_zip_settings_cache'):
            self._zip_settings_cache = {}
        cache_key = file_basename
        if cache_key in self._zip_settings_cache:
            # Debug: log cache hit and caller info (include timestamp and object id)
            try:
                import traceback, time
                stack = ''.join(traceback.format_list(traceback.extract_stack(limit=6)[:-1]))
                cache_obj = getattr(self, '_zip_settings_cache', None)
                print(f"{time.time():.3f} 🗂️ ZIP settings cache hit for '{cache_key}' — returning cached value. self_id={id(self)} cache_id={id(cache_obj) if cache_obj is not None else 'None'} Caller stack: \n{stack}")
            except Exception:
                pass
            return self._zip_settings_cache[cache_key]

        dialog = QDialog(self)
        self.apply_dark_dialog_styling(dialog)
        dialog.setWindowTitle("CSV Settings from ZIP")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        # Header
        header_label = QLabel(f"Settings for: {file_basename}")
        header_label.setStyleSheet("color: #00bcd4; font-weight: bold; font-size: 14px;")
        layout.addWidget(header_label)
        
        # Filename input
        name_label = QLabel("Output filename (without .parquet):")
        name_label.setStyleSheet("color: #d0d0d0; font-size: 13px; margin-top: 10px;")
        layout.addWidget(name_label)
        
        name_input = QLineEdit()
        name_input.setText(suggested_name)
        name_input.setStyleSheet("""
            QLineEdit {
                background-color: #3c3f41;
                color: #ffffff;
                border: 2px solid #555555;
                padding: 6px;
                border-radius: 4px;
                font-size: 13px;
            }
        """)
        layout.addWidget(name_input)
        
        # Delimiter input
        delim_label = QLabel("CSV Delimiter (default: comma):")
        delim_label.setStyleSheet("color: #d0d0d0; font-size: 13px; margin-top: 10px;")
        layout.addWidget(delim_label)
        
        delim_input = QLineEdit()
        delim_input.setText(",")
        delim_input.setPlaceholderText("Enter delimiter: , or ; or | etc.")
        delim_input.setStyleSheet("""
            QLineEdit {
                background-color: #3c3f41;
                color: #ffffff;
                border: 2px solid #555555;
                padding: 6px;
                border-radius: 4px;
                font-size: 13px;
            }
        """)
        layout.addWidget(delim_input)
        
        # Buttons
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #0d7377;
                color: white;
                padding: 8px 20px;
                border-radius: 4px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #14919b;
            }
        """)
        
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #555555;
                color: white;
                padding: 8px 20px;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #666666;
            }
        """)
        
        button_layout.addStretch()
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        # Connect buttons
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        
        # Debug: log when dialog is shown (cache miss) with timestamp and object id
        try:
            import traceback, time
            stack = ''.join(traceback.format_list(traceback.extract_stack(limit=6)[:-1]))
            cache_obj = getattr(self, '_zip_settings_cache', None)
            print(f"{time.time():.3f} 🗂️ Showing ZIP CSV settings dialog for '{cache_key}'. self_id={id(self)} cache_id={id(cache_obj) if cache_obj is not None else 'None'} Caller stack: \n{stack}")
        except (AttributeError, RuntimeError, TypeError):
            pass

        # Show dialog
        if dialog.exec() == QDialog.DialogCode.Accepted:
            filename = name_input.text().strip()
            delimiter = delim_input.text() or ","
            try:
                self._zip_settings_cache[cache_key] = (filename, delimiter)
            except Exception:
                pass
            return (filename, delimiter)
        else:
            return None

    def _ask_csv_settings(self, file_basename):
        """
        Ask user for CSV settings: delimiter, skip rows, and ignore errors
        Returns tuple (delimiter, skip_rows, ignore_errors) or None if cancelled
        """
        dialog = QDialog(self)
        self.apply_dark_dialog_styling(dialog)
        dialog.setWindowTitle("CSV Settings")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        # Header
        header_label = QLabel(f"Settings for: {file_basename}")
        header_label.setStyleSheet("color: #00bcd4; font-weight: bold; font-size: 14px;")
        layout.addWidget(header_label)
        
        # Delimiter input
        delim_label = QLabel("CSV Delimiter (default: comma):")
        delim_label.setStyleSheet("color: #d0d0d0; font-size: 13px; margin-top: 10px;")
        layout.addWidget(delim_label)
        
        delim_input = QLineEdit()
        delim_input.setText(",")
        delim_input.setPlaceholderText("Enter delimiter: , or ; or | etc.")
        delim_input.setStyleSheet("""
            QLineEdit {
                background-color: #3c3f41;
                color: #ffffff;
                border: 2px solid #555555;
                padding: 6px;
                border-radius: 4px;
                font-size: 13px;
            }
        """)
        layout.addWidget(delim_input)
        
        # Skip rows input
        skip_label = QLabel("Skip Rows (default: 0):")
        skip_label.setStyleSheet("color: #d0d0d0; font-size: 13px; margin-top: 10px;")
        layout.addWidget(skip_label)
        
        skip_input = QLineEdit()
        skip_input.setText("0")
        skip_input.setPlaceholderText("Number of rows to skip from top")
        skip_input.setStyleSheet("""
            QLineEdit {
                background-color: #3c3f41;
                color: #ffffff;
                border: 2px solid #555555;
                padding: 6px;
                border-radius: 4px;
                font-size: 13px;
            }
        """)
        layout.addWidget(skip_input)
        
        # Ignore errors checkbox
        ignore_errors_chk = QCheckBox("Ignore errors during loading")
        ignore_errors_chk.setStyleSheet("""
            QCheckBox { 
                color: #d0d0d0; 
                background-color: transparent;
                font-size: 13px;
                padding: 4px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                background-color: #454545;
                border: 1px solid #666;
            }
            QCheckBox::indicator:checked {
                background-color: #2e7d32;
                border: 1px solid #2e7d32;
            }
        """)
        layout.addWidget(ignore_errors_chk)
        
        # Buttons
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #0d7377;
                color: white;
                padding: 8px 20px;
                border-radius: 4px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #14919b;
            }
        """)
        
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #555555;
                color: white;
                padding: 8px 20px;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #666666;
            }
        """)
        
        button_layout.addStretch()
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        # Connect buttons
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        
        # Show dialog
        if dialog.exec() == QDialog.DialogCode.Accepted:
            delimiter = delim_input.text().strip() or ","
            skip_rows = skip_input.text().strip() or "0"
            ignore_errors = ignore_errors_chk.isChecked()
            return (delimiter, skip_rows, ignore_errors)
        else:
            return None

    def process_csv_from_memory(self, content, parquet_path, filename, delimiter=","):
        """Process CSV content from memory using DuckDB"""
        try:
            # Use provided delimiter (default comma)
            
            # Use DuckDB to read from string content
            # Create temporary view from the CSV content
            temp_table = f"temp_zip_csv_{int(time.time())}"
            
            # Write to temporary file for DuckDB processing
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as temp_file:
                temp_file.write(content.decode('utf-8'))
                temp_csv_path = temp_file.name
            
            try:
                # Use existing CSV processing logic
                result = self._fix_problematic_columns(temp_csv_path, delimiter, "", parquet_path)
                return result.get('success', False)
            finally:
                # Clean up temporary file
                try:
                    os.unlink(temp_csv_path)
                except:
                    pass
                    
        except Exception as e:
            print(f"Error processing CSV from ZIP: {e}")
            return False

    def process_json_from_memory(self, content, parquet_path, filename):
        """Process JSON content from memory using DuckDB"""
        try:
            import tempfile
            
            # Write content to temporary file for DuckDB processing
            with tempfile.NamedTemporaryFile(mode='wb', suffix='.json', delete=False) as temp_file:
                temp_file.write(content)
                temp_json_path = temp_file.name
            
            try:
                # Use DuckDB to process JSON
                temp_table = f"temp_zip_json_{int(time.time())}"
                
                # Try DuckDB's read_json_auto first
                try:
                    df = duckdb.sql(f"SELECT * FROM read_json_auto('{temp_json_path}')").df()
                    self.conn.register(temp_table, df)
                    self.conn.execute(f"COPY {temp_table} TO '{parquet_path}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');")
                    self.conn.unregister(temp_table)
                    return True
                except Exception:
                    # Fallback to pandas
                    df = pd.read_json(temp_json_path)
                    df.to_parquet(parquet_path, engine='pyarrow', compression='snappy')
                    return True
                    
            finally:
                # Clean up temporary file
                try:
                    os.unlink(temp_json_path)
                except:
                    pass
                    
        except Exception as e:
            print(f"Error processing JSON from ZIP: {e}")
            return False

    def process_json_from_file(self, json_file_path, parquet_path, filename):
        """Process JSON content from a file path using DuckDB (stream-friendly)."""
        try:
            # Try DuckDB's read_json_auto first
            try:
                df = duckdb.sql(f"SELECT * FROM read_json_auto('{json_file_path}')").df()
                temp_table = f"temp_zip_json_{int(time.time())}"
                self.conn.register(temp_table, df)
                self.conn.execute(f"COPY {temp_table} TO '{parquet_path}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');")
                self.conn.unregister(temp_table)
                return True
            except Exception:
                # Fallback to pandas (may require memory)
                try:
                    df = pd.read_json(json_file_path)
                    df.to_parquet(parquet_path, engine='pyarrow', compression='snappy')
                    return True
                except Exception as e:
                    print(f"JSON processing failed for {filename}: {e}")
                    return False
        except Exception as e:
            print(f"Error processing JSON file from ZIP: {e}")
            return False

    def process_excel_from_memory(self, content, parquet_path, filename):
        """Process Excel content from memory using pandas"""
        try:
            import tempfile
            
            # Write content to temporary file for pandas processing
            with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as temp_file:
                temp_file.write(content)
                temp_excel_path = temp_file.name
            
            try:
                # Use pandas to read Excel (DuckDB doesn't support Excel directly)
                df = pd.read_excel(temp_excel_path)
                
                # Use DuckDB to save as parquet for consistency
                temp_table = f"temp_zip_excel_{int(time.time())}"
                self.conn.register(temp_table, df)
                self.conn.execute(f"COPY {temp_table} TO '{parquet_path}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');")
                self.conn.unregister(temp_table)
                return True
                
            finally:
                # Clean up temporary file
                try:
                    os.unlink(temp_excel_path)
                except:
                    pass
                    
        except Exception as e:
            print(f"Error processing Excel from ZIP: {e}")
            return False

    def process_excel_from_file(self, excel_file_path, parquet_path, filename):
        """Process Excel content from a file path using pandas (stream-friendly write)."""
        try:
            df = pd.read_excel(excel_file_path)
            temp_table = f"temp_zip_excel_{int(time.time())}"
            self.conn.register(temp_table, df)
            self.conn.execute(f"COPY {temp_table} TO '{parquet_path}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');")
            self.conn.unregister(temp_table)
            return True
        except Exception as e:
            print(f"Excel processing failed for {filename}: {e}")
            return False

    def _save_error_rows(self, csv_file, delimiter, skip_param, parquet_file, skipped_count):
        """
        Identify and save rows that caused errors during CSV processing
        Returns the path to the error file, or None if saving failed
        """
        try:
            # Create error file path
            base_name = os.path.splitext(os.path.basename(csv_file))[0]
            error_dir = os.path.join(self.doc_dir, "ErrorRows")
            os.makedirs(error_dir, exist_ok=True)
            
            error_file = os.path.join(error_dir, f"{base_name}_errors_{int(time.time())}.csv")
            
            print(f"🔍 Identifying {skipped_count} error rows...")
            
            # Strategy: Read the file line by line and identify which rows fail to parse
            # We'll do this by reading with all_varchar first to get row numbers, 
            # then comparing with the successful load
            
            # Get successfully loaded row identifiers (using row_number)
            success_query = f"""
                CREATE TEMP TABLE IF NOT EXISTS success_rows AS
                SELECT row_number() OVER () as row_num, *
                FROM read_parquet('{parquet_file}')
            """
            self.conn.execute(success_query)
            
            # Read all rows from CSV with row numbers (forcing VARCHAR to capture all)
            all_rows_query = f"""
                CREATE TEMP TABLE IF NOT EXISTS all_csv_rows AS
                SELECT row_number() OVER () as row_num, *
                FROM read_csv_auto('{csv_file}', 
                    delim='{delimiter}'{skip_param}, 
                    all_varchar=true,
                    ignore_errors=false,
                    sample_size=-1)
            """
            
            try:
                self.conn.execute(all_rows_query)
                
                # Get total count to compare
                all_count = self.conn.execute("SELECT COUNT(*) FROM all_csv_rows").fetchone()[0]
                success_count = self.conn.execute("SELECT COUNT(*) FROM success_rows").fetchone()[0]
                
                print(f"  Total rows in CSV: {all_count}")
                print(f"  Successfully loaded: {success_count}")
                print(f"  Error rows: {all_count - success_count}")
                
                # For simplicity, we'll save rows that had parsing errors
                # Since DuckDB with ignore_errors doesn't give us exact error rows,
                # we'll try a different approach: save the original file rows that weren't loaded
                
                # Read raw file and save problematic lines
                error_rows_saved = self._extract_error_rows_manual(csv_file, delimiter, skip_param, error_file, skipped_count)
                
                if error_rows_saved:
                    return error_file
                    
            except Exception as e:
            
                print(f"  ⚠️ Could not create all_csv_rows table: {e}")
                # Fallback: try to manually identify error rows
                return self._extract_error_rows_manual(csv_file, delimiter, skip_param, error_file, skipped_count)
            
            finally:
                # Clean up temp tables
                try:
                    self.conn.execute("DROP TABLE IF EXISTS success_rows")
                    self.conn.execute("DROP TABLE IF EXISTS all_csv_rows")
                except:
                    pass
            
            return None
            
        except Exception as e:
            print(f"⚠️ Error saving error rows: {e}")
            return None

    def _extract_error_rows_manual(self, csv_file, delimiter, skip_param, error_file, expected_error_count):
        """
        Manually extract error rows by reading the CSV line by line
        """
        try:
            import csv as csv_module
            
            skip_n = int(skip_param.replace(", skip=", "")) if skip_param else 0
            actual_delimiter = delimiter if delimiter else ','
            
            error_lines = []
            line_num = 0
            
            print(f"  📝 Reading CSV file manually to identify error rows...")
            
            with open(csv_file, 'r', encoding='utf-8', errors='replace') as f:
                # Skip header rows if specified
                for _ in range(skip_n):
                    f.readline()
                    line_num += 1
                
                # Read header
                header_line = f.readline()
                line_num += 1
                error_lines.append(('Header', header_line.strip()))
                
                # Try to parse each row
                reader = csv_module.reader(f, delimiter=actual_delimiter)
                for row_data in reader:
                    line_num += 1
                    
                    # Check if row has issues (inconsistent column count, etc.)
                    try:
                        # Very basic validation - check column count consistency
                        if header_line:
                            expected_cols = len(header_line.split(actual_delimiter))
                            if len(row_data) != expected_cols:
                                error_lines.append((line_num, actual_delimiter.join(row_data)))
                    except Exception:
                        # Any parsing error means this is an error row
                        error_lines.append((line_num, str(row_data)))
            
            # Save error rows to file
            if len(error_lines) > 1:  # More than just header
                with open(error_file, 'w', encoding='utf-8', newline='') as f:
                    f.write(f"# Error rows from: {os.path.basename(csv_file)} \n")
                    f.write(f"# Total error rows found: {len(error_lines) - 1} \n")
                    f.write(f"# Extracted at: {time.strftime('%Y-%m-%d %H:%M:%S')} \n")
                    f.write("#" + "="*80 + " \n")
                    for line_info, line_content in error_lines:
                        if line_info == 'Header':
                            f.write(line_content + ' \n')
                        else:
                            f.write(f"# Line {line_info}: \n")
                            f.write(line_content + ' \n')
                
                print(f"  ✅ Saved {len(error_lines) - 1} error rows to {error_file}")
                return True
            else:
                print(f"  ℹ️ No specific error rows identified (might be data type issues)")
                return False
                
        except Exception as e:
            print(f"  ⚠️ Manual error extraction failed: {e}")
            return False

    def _fallback_to_all_varchar(self, file_path, delimiter, skip_param, parquet_file, add_source_filename=False):
        """
        Fallback method that converts all columns to VARCHAR (original behavior)
        
        Args:
            file_path: Path to the CSV file
            delimiter: CSV delimiter character
            skip_param: Skip rows parameter
            parquet_file: Output parquet file path
            add_source_filename: Whether to add _source_file column
        """
        try:
            print(f"🔄 Falling back to converting ALL columns to VARCHAR...")
            
            if add_source_filename:
                source_filename = os.path.basename(file_path)
                self.conn.execute(
                    f"""
                    COPY (
                        SELECT *, '{source_filename}' AS _source_file
                        FROM read_csv_auto('{file_path}', 
                            delim='{delimiter}', 
                            parallel=True, 
                            nullstr='\\N'
                            all_varchar=true{skip_param})
                    ) 
                    TO '{parquet_file}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');
                    """
                )
            else:
                self.conn.execute(
                    f"""
                    COPY (
                        SELECT * 
                        FROM read_csv_auto('{file_path}', 
                            delim='{delimiter}', 
                            parallel=True, 
                            
                            all_varchar=true{skip_param})
                    ) 
                    TO '{parquet_file}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');
                    """
                )
            
            return {
                'success': True,
                'message': 'All columns converted to text (VARCHAR) - original behavior',
                'solution': 'Used all_varchar=true fallback method',
                'converted_columns': ['ALL_COLUMNS']
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'Even all_varchar fallback failed: {str(e)}'
            }

    def safe_arithmetic_replace(self, query: str, pattern: str, replacer) -> str:
        segments = re.split(r"('.*?')", query, flags=re.DOTALL)
        for i in range(len(segments)):
            if i % 2 == 0:
                segments[i] = re.sub(pattern, replacer, segments[i])
        return "".join(segments)

    def arithmetic_replacer(self, m):
        left_expr = m.group(1).strip()
        op = m.group(2)
        right_expr = m.group(3).strip()

        # Skip temporal keywords so date arithmetic like CURRENT_DATE - INTERVAL 6 MONTH
        # is not rewritten into invalid numeric casts.
        temporal_tokens = {"INTERVAL", "CURRENT_DATE", "CURRENT_TIMESTAMP", "NOW", "TODAY"}
        if left_expr.upper() in temporal_tokens or right_expr.upper() in temporal_tokens:
            return m.group(0)

        return f"(TRY_CAST({left_expr} AS DOUBLE) {op} TRY_CAST({right_expr} AS DOUBLE))"

    # --- Query execution methods now in simplsql_modules/core/query_manager.py ---
    # Methods: execute_query(), execute_query_background(), execute_query_to_store(),
    #          load_data_advanced()
    # These are inherited from QueryManager mixin class

    @pyqtSlot()
    def on_sql_text_changed(self):
        """Handle SQL text changes - can be used for validation status updates"""
        try:
            if hasattr(self, 'validation_status_label'):
                if getattr(self, 'editor_mode', 'sql') == 'python':
                    self.validation_status_label.setText("⚠ Not Executed")
                else:
                    self.validation_status_label.setText("⚠ Not Validated")
                self.validation_status_label.setStyleSheet("color: #ff9800; font-size: 10px; font-weight: bold;")
        except Exception:
            pass

    def execute_active_editor(self):
        """Run SQL or Python based on active notepad mode."""
        if getattr(self, 'editor_mode', 'sql') == 'python':
            self.execute_python_script()
        else:
            self.execute_query()

    def _switch_editor_mode(self, mode: str):
        """Switch between SQL and Python notepad buffers."""
        mode = (mode or "sql").strip().lower()
        if mode not in ("sql", "python"):
            mode = "sql"

        current_mode = getattr(self, 'editor_mode', 'sql')
        current_text = self.sql_text.toPlainText()
        if current_mode == 'python':
            self.python_notepad_buffer = current_text
        else:
            self.sql_notepad_buffer = current_text

        self.editor_mode = mode
        next_text = self.python_notepad_buffer if mode == 'python' else self.sql_notepad_buffer

        self.sql_text.blockSignals(True)
        self.sql_text.setPlainText(next_text)
        self.sql_text.blockSignals(False)

        self._update_editor_mode_ui()
        self.on_sql_text_changed()

    def switch_notepad_mode(self, mode: str):
        """Public alias used by the AI assistant to switch notepad modes."""
        self._switch_editor_mode(mode)

    def on_editor_mode_selector_changed(self, text: str):
        """Handle notepad mode selector changes from UI."""
        target = 'python' if 'python' in (text or '').lower() else 'sql'
        self._switch_editor_mode(target)

    def _update_editor_mode_ui(self):
        """Update labels/buttons to reflect active editor mode."""
        mode = getattr(self, 'editor_mode', 'sql')
        is_python = mode == 'python'

        if hasattr(self, 'sql_text_label'):
            self.sql_text_label.setText("Python Script:" if is_python else "SQL Query:")

        if hasattr(self, 'validate_btn'):
            self.validate_btn.setText("🐍 Check Python" if is_python else "🔍 Check SQL")

        if hasattr(self, 'editor_mode_combo') and self.editor_mode_combo is not None:
            target_text = "Python Notepad" if is_python else "SQL Notepad"
            if self.editor_mode_combo.currentText() != target_text:
                self.editor_mode_combo.blockSignals(True)
                self.editor_mode_combo.setCurrentText(target_text)
                self.editor_mode_combo.blockSignals(False)

        placeholder = (
            "# Python Notepad — no imports needed, everything is pre-injected!\n"
            "#\n"
            "# DATA ACCESS (DuckDB-first — use these instead of pd.read_parquet):\n"
            "#   rel = load_relation('table_name')          # lazy DuckDB relation\n"
            "#   rel = sql('SELECT ... FROM table ...')      # any DuckDB SQL → relation\n"
            "#   df  = to_df(rel, limit=100_000)            # relation → pandas DataFrame\n"
            "#   for chunk in stream_df('SELECT ...'):      # chunked for huge tables\n"
            "#\n"
            "# READ ANY FILE / ZIP FROM DISK:\n"
            "#   df = read_path(r'C:/data/sales.csv')       # csv, xlsx, json, xml, parquet, ...\n"
            "#   df = read_path(r'C:/data/report.xlsx', sheet='Q1')\n"
            "#   df = read_zip(r'C:/data/archive.zip')      # auto-picks first file in zip\n"
            "#   df = read_zip(r'C:/data/arc.zip', 'data.csv')  # specific file in zip\n"
            "#\n"
            "# SAVE OUTPUT TO DISK:\n"
            "#   save_result(result_df, r'C:/out/report.xlsx')   # xlsx, csv, json, xml, parquet, ...\n"
            "#   save_result(result_df, r'C:/out/data.csv', sep=';')\n"
            "#   save_result(result_df, r'C:/out/data.json', orient='records')\n"
            "#\n"
            "# PRE-INJECTED LIBRARIES (use directly — no import):\n"
            "#   pd, np, plt, sns, px, sklearn, sm, xgb, lgb, shap, scipy, joblib\n"
            "#   sklearn sub-modules: linear_model, ensemble, tree, preprocessing,\n"
            "#                        model_selection, metrics, decomposition, cluster\n"
            "#\n"
            "# OUTPUT — assign one of these to show results in the grid:\n"
            "#   result_df       = my_dataframe\n"
            "#   result_relation = my_duckdb_relation\n"
            "#   result_sql      = 'SELECT ...'\n"
            "#\n"
            "# EXAMPLE:\n"
            "#   df = to_df(sql('SELECT region, SUM(amount) total FROM sales GROUP BY 1'))\n"
            "#   save_result(df, r'C:/output/summary.xlsx')\n"
            "#   result_df = df"
            if is_python else
            "Write SQL query..."
        )
        self.sql_text.setPlaceholderText(placeholder)

        for btn in getattr(self, 'run_buttons', []):
            if btn is not None:
                btn.setText("🐍 Run Python" if is_python else "🚀 Run SQL")



    # Dialog-driven advanced data loading with preview, filtering, and column selection

    # --- Data operation dialogs now in simplsql_modules/ui/data_dialogs.py ---
    # Methods: perform_aggregation(), get_distinct_values(), split_file_by_column(),
    #          pivot_table_dialog(), join_tables()
    # These are inherited from DataOperationDialogs mixin class

    # --- View management methods now in simplsql_modules/ui/view_manager.py ---
    # Methods: load_views(), save_views(), add_view(), Parquet_view_describe(),
    #          populate_treeview(), compute_view_df(), _compute_view_df_from_df(),
    #          _compute_view_df_with_duckdb(), show_dashboard(),
    #          save_current_view_to_parquet_default()
    # These are inherited from ViewManager mixin class

    # --- Workflow Management Methods ---
    
    def show_save_query_popup(self):
        query_name = self.create_input_popup(
            "Save Query", "Enter Query Name:"
        )
        if query_name:
            self.save_query(query_name, self.get_current_query())

    def save_query(self, name, query):
        if not name or not query.strip():
            MainWindow.show_styled_message_box(
                self, "Warning", "Query name and content cannot be empty!",
                icon=QMessageBox.Icon.Warning
            )
            return

        if os.path.exists(self.query_file_path):
            with open(self.query_file_path, "r") as file:
                self.saved_queries = json.load(file)
        else:
            self.saved_queries = {}

        self.saved_queries[name] = query

        with open(self.query_file_path, "w") as file:
            json.dump(self.saved_queries, file, indent=4)

        # Safely update the queries combo if it exists and hasn't been deleted
        try:
            if hasattr(self, 'query_dropdown') and isinstance(self.query_dropdown, QComboBox):
                self.query_dropdown.clear()
                # Add items then select the newly saved query so the editor reflects the saved item
                self.query_dropdown.addItems(list(self.saved_queries.keys()))
                try:
                    # Prefer selecting the newly saved name
                    self.query_dropdown.setCurrentText(name)
                except Exception:
                    # Fallback: set current index to the newly appended item if possible
                    try:
                        idx = list(self.saved_queries.keys()).index(name)
                        self.query_dropdown.setCurrentIndex(idx)
                    except Exception:
                        pass
        except RuntimeError:
            # Native widget may have been deleted; ignore and continue
            pass

        MainWindow.show_styled_message_box(
            self, "Success", f"Query '{name}' saved successfully!",
            icon=QMessageBox.Icon.Information
        )


    def load_saved_queries(self):
        if os.path.exists(self.query_file_path):
            with open(self.query_file_path, "r") as file:
                self.saved_queries = json.load(file)
        else:
            self.saved_queries = {}

        # Safely populate queries combo if available
        try:
            if hasattr(self, 'query_dropdown') and isinstance(self.query_dropdown, QComboBox):
                self.query_dropdown.clear()
                self.query_dropdown.addItems(list(self.saved_queries.keys()))
                if self.query_dropdown.count() == 1:
                    self.query_dropdown.setCurrentIndex(0)
                    self.load_selected_query(0)
        except RuntimeError:
            # Widget may have been deleted; skip UI update
            pass
        
            
    def load_selected_query(self, index):
        selected_query_name = self.query_dropdown.itemText(index)
        if selected_query_name in self.saved_queries:
            query_text = self.saved_queries[selected_query_name]
            self.set_current_query(query_text)
        else:
            return


    def get_current_query(self):
        # Persist latest buffer for the active mode before returning text.
        current_text = self.sql_text.toPlainText()
        if getattr(self, 'editor_mode', 'sql') == 'python':
            self.python_notepad_buffer = current_text
        else:
            self.sql_notepad_buffer = current_text
        return self.sql_text.toPlainText().strip()

    def set_current_query(self, query):
        if getattr(self, 'editor_mode', 'sql') == 'python':
            self.python_notepad_buffer = query
        else:
            self.sql_notepad_buffer = query
        self.sql_text.clear()
        self.sql_text.setPlainText(query)
        
    def delete_selected_query(self):
        selected_query = self.query_dropdown.currentText()
        if not selected_query:
            MainWindow.show_styled_message_box(
                self, "Warning", "Please select a query to delete.",
                icon=QMessageBox.Icon.Warning
            )
            return

        confirm = MainWindow.show_styled_message_box(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete '{selected_query}'?",
            icon=QMessageBox.Icon.Question,
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if confirm == QMessageBox.StandardButton.Yes:
            if selected_query in self.saved_queries:
                del self.saved_queries[selected_query]

            with open(self.query_file_path, "w") as file:
                json.dump(self.saved_queries, file, indent=4)

            self.query_dropdown.clear()
            self.query_dropdown.addItems(list(self.saved_queries.keys()))
            self.query_dropdown.setCurrentIndex(-1)
            MainWindow.show_styled_message_box(
                self, "Deleted", f"Query '{selected_query}' has been deleted.",
                icon=QMessageBox.Icon.Information
            )






    def create_input_popup(self, title, prompt_text):
        dialog = QDialog(self)
        self.apply_dark_dialog_styling(dialog)
        dialog.setWindowTitle(title)
        dialog_layout = QVBoxLayout(dialog)

        # Title label with light color for dark theme
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("color: #d0d0d0; font-weight: bold; font-size: 14px;")
        dialog_layout.addWidget(title_label)
        
        label = QLabel(prompt_text)
        label.setWordWrap(True)
        label.setFont(QFont("Arial", 10))
        label.setStyleSheet("color: #d0d0d0; font-weight: bold; font-size: 14px;")
        dialog_layout.addWidget(label)

        entry = QLineEdit(dialog)
        dialog_layout.addWidget(entry)

        ok_button = QPushButton("OK", dialog)
        dialog_layout.addWidget(ok_button)

        result = ""

        def on_ok():
            nonlocal result
            result = entry.text()
            dialog.accept()

        ok_button.clicked.connect(on_ok)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return result
        else:
            return None

    def make_save_checkbox(self, label_text: str = "Save as Dashboard View") -> QCheckBox:
        """Create a consistently-styled green save-as-dashboard QCheckBox used across data tools."""
        chk = QCheckBox(label_text)
        chk.setStyleSheet("""
            QCheckBox { 
                color: #d0d0d0; 
                background-color: transparent;
                font-size: 12px;
                font-weight: bold;
                padding: 4px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                background-color: #454545;
                border: 1px solid #666;
            }
            QCheckBox::indicator:checked {
                background-color: #2e7d32; /* green like aggregation save */
                border: 1px solid #2e7d32;
            }
        """)
        return chk


    def apply_progress_dialog_styling(self, progress_dialog, color="#4CAF50"):
        """Apply consistent styling to progress dialogs across the application."""
        try:
            progress_dialog.setStyleSheet(f"""
                QProgressDialog {{
                    background-color: #f0f0f0;
                    color: #000000;
                }}
                QProgressDialog QLabel {{
                    color: #000000;
                    font-weight: bold;
                    font-size: 12px;
                }}
                QProgressBar {{
                    border: 2px solid #cccccc;
                    border-radius: 5px;
                    text-align: center;
                    color: #000000;
                    font-weight: bold;
                }}
                QProgressBar::chunk {{
                    background-color: {color};
                    border-radius: 3px;
                }}
                QPushButton {{
                    background-color: #e0e0e0;
                    border: 1px solid #999999;
                    padding: 5px 15px;
                    border-radius: 3px;
                    color: #000000;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: #d0d0d0;
                }}
                QPushButton:pressed {{
                    background-color: #c0c0c0;
                }}
            """)
        except Exception:
            pass

    def show_ai_assistant(self):
        """Show AI Assistant dialog"""
        # Keep a reference to the dialog so it persists
        if not hasattr(self, 'ai_assistant_dialog') or self.ai_assistant_dialog is None:
            self.ai_assistant_dialog = AIAssistantDialog(self)
        
        # Show the dialog (non-modal) so user can interact with main window
        self.ai_assistant_dialog.show()
        self.ai_assistant_dialog.raise_()
        self.ai_assistant_dialog.activateWindow()


    def _duckdb_copy_from_parquet(self, src_parquet_path: str, dest_path: str, format: str = 'csv'):
        """Use DuckDB to copy data directly from a parquet file to CSV or Parquet on disk.
        This avoids materializing the full DataFrame in Python memory for large files.
        """
        src = src_parquet_path.replace('\\', '/')
        dest = dest_path.replace('\\', '/')
        if format == 'csv':
            # include header
            sql = f"COPY (SELECT * FROM read_parquet('{src}')) TO '{dest}' (FORMAT 'csv', HEADER true);"
        elif format == 'parquet':
            sql = f"COPY (SELECT * FROM read_parquet('{src}')) TO '{dest}' (FORMAT 'parquet', COMPRESSION 'SNAPPY');"
        else:
            raise ValueError('Unsupported format for duckdb copy')
        # Ensure we have a live duckdb connection
        if not hasattr(self, 'conn') or self.conn is None:
            self.conn = duckdb.connect(database=':memory:', read_only=False)
        # Execute the COPY
        self.conn.execute("PRAGMA threads=8;")
        self.conn.execute(sql)

    # ---------------- Table helpers ----------------
    def apply_table_filter(self, text: str):
        """Filter the visible table rows by substring across any column. Case-insensitive."""
        try:
            if not hasattr(self, '_full_df') or self._full_df is None:
                return
            txt = text.strip().lower()
            if txt == "":
                df = self._full_df
            else:
                mask = None
                for c in self._full_df.columns:
                    s = self._full_df[c].astype(str).str.lower()
                    col_mask = s.str.contains(txt, na=False)
                    mask = col_mask if mask is None else (mask | col_mask)
                df = self._full_df[mask]
            # Redisplay filtered rows without losing the full copy
            self.populate_treeview(df, set_full=False)
        except (AttributeError, RuntimeError, TypeError, ValueError) as e:
            print("Filter error:", e)

    def _on_table_context_menu(self, pos):
        try:
            menu = QMenu(self)
            # ensure context menus match dark theme and have visible selection
            menu.setStyleSheet(
                "QMenu { background-color: #2b2b2b; color: #d0d0d0; border: 1px solid #444444; padding:6px; border-radius:6px; }"
                "QMenu::item { background-color: transparent; padding:6px 18px; }"
                "QMenu::item:selected { background-color: #3a6ea5; color: #ffffff; }"
            )
            copy_action = QAction("Copy", self)
            copy_row_action = QAction("Copy Row", self)
            copy_column_action = QAction("Copy Column", self)
            export_action = QAction("Export Selected Rows to CSV", self)
            stats_action = QAction("Show Column Stats", self)
            filter_action = QAction("Filter by this value", self)

            copy_action.triggered.connect(self.copy_selected_cells)
            copy_row_action.triggered.connect(self.copy_row)
            copy_column_action.triggered.connect(lambda: self.copy_column(pos))
            export_action.triggered.connect(self.export_selected_rows)
            stats_action.triggered.connect(self.show_column_stats)
            filter_action.triggered.connect(lambda: self._filter_by_context_value(pos))

            menu.addAction(copy_action)
            menu.addAction(copy_row_action)
            menu.addAction(copy_column_action)
            menu.addSeparator()
            menu.addAction(export_action)
            menu.addAction(stats_action)
            menu.addAction(filter_action)

            menu.exec(self.results_table.viewport().mapToGlobal(pos))
        except (AttributeError, RuntimeError, TypeError) as e:
            print("Context menu error:", e)

    def copy_selected_cells(self):
        try:
            sel = self.results_table.selectionModel().selectedIndexes()
            if not sel:
                return
            # Work directly with proxy indexes (visible/filtered data)
            # Sort by row, col in proxy model coordinates
            sel_sorted = sorted(sel, key=lambda idx: (idx.row(), idx.column()))
            lines = []
            cur_row = sel_sorted[0].row()
            cur_cols = []
            for idx in sel_sorted:
                if idx.row() != cur_row:
                    lines.append('\t'.join(cur_cols))
                    cur_cols = []
                    cur_row = idx.row()
                # Get value directly from proxy model (respects filtering/sorting)
                val = self._proxy.data(idx, Qt.ItemDataRole.DisplayRole)
                cur_cols.append(str(val) if val is not None else '')
            if cur_cols:
                lines.append('\t'.join(cur_cols))
            pyperclip.copy(' \n'.join(lines))
        except (AttributeError, RuntimeError, TypeError) as e:
            print("Copy error:", e)

    def copy_row(self):
        try:
            cur = self.results_table.selectionModel().currentIndex()
            if not cur.isValid():
                # fallback to first selected row
                sel = self.results_table.selectionModel().selectedRows()
                if not sel:
                    return
                cur = sel[0]
            
            # Get all column values from the proxy model (visible/filtered row)
            row_num = cur.row()
            col_count = self._proxy.columnCount()
            vals = []
            for col in range(col_count):
                proxy_idx = self._proxy.index(row_num, col)
                val = self._proxy.data(proxy_idx, Qt.ItemDataRole.DisplayRole)
                vals.append(str(val) if val is not None else '')
            
            pyperclip.copy('\t'.join(vals))
        except (AttributeError, RuntimeError, TypeError) as e:
            print("Copy row error:", e)

    def copy_column(self, pos):
        try:
            idx = self.results_table.indexAt(pos)
            if not idx.isValid():
                return
            
            # Get the column index from the clicked position
            col_idx = idx.column()  # Use proxy column index
            
            if not hasattr(self, '_proxy') or self._proxy is None:
                return
            
            # Get column name for header from source model
            src_idx = self._proxy.mapToSource(idx)
            source_col_idx = src_idx.column()
            col_name = self._model._df.columns[source_col_idx]
            
            # Get all filtered/visible values from this column
            values = [col_name]  # Header first
            
            # Iterate through all visible rows in the proxy model
            for row in range(self._proxy.rowCount()):
                proxy_idx = self._proxy.index(row, col_idx)
                if proxy_idx.isValid():
                    # Get the value through the proxy model (which respects filtering)
                    val = self._proxy.data(proxy_idx, Qt.ItemDataRole.DisplayRole)
                    values.append(str(val) if val is not None else '')
            
            # Copy to clipboard with newline separation
            pyperclip.copy(' \n'.join(values))
            
            # Optional: Show a brief message about what was copied
            try:
                row_count = len(values) - 1  # Subtract 1 for header
                print(f"Copied column '{col_name}' with {row_count} filtered values to clipboard")
            except (AttributeError, RuntimeError, TypeError):
                pass
                
        except (AttributeError, RuntimeError, TypeError) as e:
            print("Copy column error:", e)

    def export_selected_rows(self):
        try:
            sel = self.results_table.selectionModel().selectedRows()
            if not sel:
                MainWindow.show_styled_message_box(self, "No Selection", "No rows selected to export.", icon=QMessageBox.Icon.Warning)
                return
            
            file_path, _ = QFileDialog.getSaveFileName(self, "Export Selected Rows", "selected_rows.csv", "CSV files (*.csv)")
            if not file_path:
                return
            
            # Extract visible/filtered data for selected rows
            rows_data = []
            col_count = self._proxy.columnCount()
            
            # Get column headers
            headers = []
            for col in range(col_count):
                header = self._proxy.headerData(col, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
                headers.append(str(header) if header is not None else f"Column_{col}")
            
            # Get data for each selected row from proxy model (visible/filtered data)
            for row_idx in sorted(sel, key=lambda idx: idx.row()):
                row_data = {}
                for col in range(col_count):
                    proxy_idx = self._proxy.index(row_idx.row(), col)
                    val = self._proxy.data(proxy_idx, Qt.ItemDataRole.DisplayRole)
                    row_data[headers[col]] = val if val is not None else ''
                rows_data.append(row_data)
            
            # Create DataFrame and export
            df = pd.DataFrame(rows_data)
            df.to_csv(file_path, index=False)
            MainWindow.show_styled_message_box(self, "Exported", f"Exported {len(rows_data)} visible rows to {os.path.basename(file_path)}", icon=QMessageBox.Icon.Information)
        except (AttributeError, RuntimeError, TypeError, ValueError, OSError) as e:
            MainWindow.show_styled_message_box(self, "Error", f"Failed to export: {e}", icon=QMessageBox.Icon.Critical)

    def show_column_stats(self):
        try:
            cur = self.results_table.selectionModel().currentIndex()
            if not cur.isValid():
                # fallback to first selected index
                sel = self.results_table.selectionModel().selectedIndexes()
                if not sel:
                    return
                cur = sel[0]
            src = self._proxy.mapToSource(cur)
            col_idx = src.column()
            col_name = self._model._df.columns[col_idx]
            if not hasattr(self, '_full_df') or self._full_df is None:
                MainWindow.show_styled_message_box(self, "No Data", "No data available for stats.", icon=QMessageBox.Icon.Warning)
                return
            s = self._full_df[col_name]
            stats_series = s.describe(include='all')
            
            # Format stats to avoid scientific notation
            formatted_lines = []
            for stat_name, stat_value in stats_series.items():
                if isinstance(stat_value, (int, float)):
                    # Format numbers with thousand separators and 2 decimal places
                    if abs(stat_value) >= 1:
                        formatted_value = f"{stat_value:,.2f}"
                    else:
                        formatted_value = f"{stat_value:.6f}"
                else:
                    formatted_value = str(stat_value)
                formatted_lines.append(f"{stat_name:<10} {formatted_value:>20}")
            
            stats = " \n".join(formatted_lines)
            MainWindow.show_styled_message_box(self, f"Stats: {col_name}", f"<pre>{stats}</pre>", icon=QMessageBox.Icon.Information, text_color='white')
        except (AttributeError, RuntimeError, TypeError, ValueError) as e:
            MainWindow.show_styled_message_box(self, "Error", f"Failed to compute stats: {e}", icon=QMessageBox.Icon.Critical)

    def _filter_by_context_value(self, pos):
        try:
            idx = self.results_table.indexAt(pos)
            if not idx.isValid():
                return
            src = self._proxy.mapToSource(idx)
            val = self._model.data(src, Qt.ItemDataRole.DisplayRole)
            col_idx = src.column()
            
            # Get the column name for the clicked cell
            if hasattr(self, '_model') and self._model:
                col_name = self._model._df.columns[col_idx]
                
                # Set the filter column combo to the clicked column
                combo_idx = self.filter_column_combo.findText(col_name)
                if combo_idx >= 0:
                    self.filter_column_combo.setCurrentIndex(combo_idx)
                
                # Set the filter input to the cell value
                self.filter_input.setText(val if val is not None else '')
                
                # Apply the filter automatically
                self.apply_column_filter()
                
        except (AttributeError, RuntimeError, TypeError, ValueError) as e:
            print("Filter by value error:", e)

    def apply_column_filter(self):
        """Apply filter for the selected column using the filter input text and operator."""
        try:
            if not hasattr(self, '_proxy') or self._proxy is None:
                return
            col_name = self.filter_column_combo.currentText()
            if not col_name:
                # clear global filter
                self._proxy.setFilter(None, "", "contains")
                return
            
            # find column index in current model
            try:
                col_idx = list(self._model._df.columns).index(col_name)
            except (ValueError, AttributeError, TypeError):
                col_idx = None
            
            text = self.filter_input.text() or ""
            
            # Get the selected operator and map it to internal format
            operator_text = self.filter_operator_combo.currentText()
            operator_map = {
                "contains": "contains",
                "not contains": "not_contains", 
                "equals": "equals",
                "not equals": "not_equals",
                "starts with": "starts_with",
                "ends with": "ends_with", 
                "greater than": "greater_than",
                "less than": "less_than"
            }
            operator = operator_map.get(operator_text, "contains")
            
            self._proxy.setFilter(col_idx, text, operator)
        except (AttributeError, RuntimeError, TypeError, ValueError) as e:
            print("Apply filter error:", e)

    def clear_column_filter(self):
        try:
            if not hasattr(self, '_proxy') or self._proxy is None:
                return
            self.filter_input.clear()
            self.filter_operator_combo.setCurrentText("contains")
            self._proxy.setFilter(None, "", "contains")
        except (AttributeError, RuntimeError, TypeError) as e:
            print("Clear filter error:", e)

    def enable_sorting_manually(self):
        """Enable sorting for large datasets (performance warning)"""
        try:
            if hasattr(self, 'results_table'):
                reply = MainWindow.show_styled_message_box(
                    self,
                    "Enable Sorting",
                    "Enabling sorting on large datasets may cause the application to become temporarily unresponsive. \nContinue?",
                    icon=QMessageBox.Icon.Warning,
                    buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    progress = QProgressDialog("Enabling sorting...", "Cancel", 0, 100, self)
                    progress.setWindowTitle("Enabling Sorting")
                    progress.setWindowModality(Qt.WindowModality.ApplicationModal)
                    progress.setMinimumDuration(0)
                    progress.setValue(50)
                    self.apply_progress_dialog_styling(progress, "#FF5722")  # Deep Orange for warning operations
                    progress.show()
                    QApplication.processEvents()
                    
                    self.results_table.setSortingEnabled(True)
                    header = self.results_table.horizontalHeader()
                    header.setSortIndicatorShown(False)
                    
                    # Hide the enable sorting button since sorting is now enabled
                    self.enable_sorting_btn.setVisible(False)
                    
                    progress.setValue(100)
                    progress.close()
                    
                    # Update the transaction count label to remove the sorting disabled message
                    if hasattr(self, 'last_df') and self.last_df is not None:
                        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        self.transaction_count_label.setText(f"Total Transactions: {len(self.last_df)} — Last Run: {now_str}")
                    
                    MainWindow.show_styled_message_box(
                        self, "Success", "Sorting has been enabled. You can now click column headers to sort.",
                        icon=QMessageBox.Icon.Information
                    )
        except (AttributeError, RuntimeError, TypeError) as e:
            print("Enable sorting error:", e)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DuckDB Query Editor")
        self.setGeometry(100, 100, 1200, 800)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        self.layout = QVBoxLayout(self.central_widget)

        self.app_dir = get_app_dir()  # Fixed for PyInstaller compatibility
        self.query_editor = DuckDBQueryEditor(self, controller=self)
        self.layout.addWidget(self.query_editor)
        
        # Apply theme through the query editor's theme system after it's fully initialized
        # Use QTimer to defer this until after the event loop starts
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self.apply_main_window_theme)

        self.conn = duckdb.connect(
            database=":memory:", read_only=False
        )

    def apply_main_window_theme(self):
        """Apply theme to the main window based on query editor's current theme"""
        if hasattr(self, 'query_editor') and hasattr(self.query_editor, 'themes') and hasattr(self.query_editor, 'current_theme'):
            theme = self.query_editor.themes[self.query_editor.current_theme]
            main_window_style = f"""
                QMainWindow {{
                    background-color: {theme['background']};
                    color: {theme['text']};
                }}
            """
            self.setStyleSheet(main_window_style)
        else:
            # Fallback to dark theme if query editor theme not ready
            self.setStyleSheet(self.get_dark_stylesheet())

    def __del__(self):
        print("MainWindow __del__")

    def get_dark_stylesheet(self):
        return """
            QMainWindow {
                background-color: #252526;
            }
            QComboBox, QLineEdit, QTextEdit, QTableWidget, QTableView {
                background-color: #313335;
                color: #d0d0d0;
                selection-background-color: #4a6990;
            }
            QPushButton {
                background-color: #313335;
                color: #d0d0d0;
                border: 1px solid #555555;
            }
            QPushButton:hover {
                background-color: #454545;
            }
            QLabel {
                color: #d0d0d0;
            }
            QTableWidget::item, QTableView QTableView { /* fallback selector to ensure table text appears light */
                color: #d0d0d0;
            }
            QHeaderView::section {
                background-color: #313335;
                color: #d0d0d0;
                border: 1px solid #555555;
            }
            QPlainTextEdit {
                background-color: #313335;
                color: #d0d0d0;
                font-family: Consolas;
                font-size: 16px;
                border: 1px solid #555555;
            }
        """
    def show_styled_message_box(parent, title, text, icon=QMessageBox.Icon.Information, text_color="white", font_size="10pt", buttons=QMessageBox.StandardButton.Ok):
        msg_box = QMessageBox(parent)
        # Apply dark styling to dialog backgrounds to match theme
        try:
            msg_box.setStyleSheet("""
                QMessageBox {
                    background-color: #2b2b2b;
                    color: #d0d0d0;
                }
                QLabel#qt_msgbox_label { color: #d0d0d0; }
                QPushButton { background-color: #454545; color: #d0d0d0; }
            """)
        except (AttributeError, RuntimeError, TypeError):
            pass
        msg_box.setWindowTitle(title)
        msg_box.setTextFormat(Qt.TextFormat.RichText)
        styled_text = f"<div style='font-size: {font_size}; color: {text_color};'>{text}</div>"
        msg_box.setText(styled_text)
        msg_box.setIcon(icon)
        msg_box.setStandardButtons(buttons)

        # Styling the entire QMessageBox
        msg_box.setStyleSheet("""
            QMessageBox {
                background-color: #333333;  /* Dark background */
                color: #d0d0d0;           /* Light text color */
                border: 1px solid #555555; /* Darker border */
            }
            QPushButton {
                background-color: #454545; /* Darker button background */
                color: #d0d0d0;
                border: 1px solid #666666;
            }
            QPushButton:hover {
                background-color: #555555;
            }
        """)

        # Execute the message box and return the result (button clicked)
        return msg_box.exec()

    @staticmethod
    def show_error_message_box_with_copy(parent, title, text, detailed_text=None):
        """
        Show an error message box with a copy button for easy error message copying.
        """
        msg_box = QMessageBox(parent)
        msg_box.setWindowTitle(title)
        msg_box.setIcon(QMessageBox.Icon.Critical)
        
        # Set main text
        msg_box.setText(f"<div style='font-size: 10pt; color: white;'>{text}</div>")
        msg_box.setTextFormat(Qt.TextFormat.RichText)
        
        # Set detailed text if provided
        if detailed_text:
            msg_box.setDetailedText(detailed_text)
        
        # Add standard buttons
        ok_button = msg_box.addButton(QMessageBox.StandardButton.Ok)
        copy_button = msg_box.addButton("📋 Copy Error", QMessageBox.ButtonRole.ActionRole)
        
        # Apply styling
        msg_box.setStyleSheet("""
            QMessageBox {
                background-color: #2b2b2b;
                color: #ffffff;
                border: 1px solid #555555;
            }
            QLabel {
                color: #ffffff;
            }
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 12px;
                font-weight: bold;
                min-width: 80px;
                margin: 2px;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
            QTextEdit {
                background-color: #3c3c3c;
                color: #ffffff;
                border: 1px solid #555555;
                selection-background-color: #0078d4;
            }
        """)
        
        # Execute and handle button clicks
        result = msg_box.exec()
        
        # Check if copy button was clicked
        if msg_box.clickedButton() == copy_button:
            # Create full error message for copying
            full_message = f"Error: {title} \n{text}"
            if detailed_text:
                full_message += f" \nDetails: \n{detailed_text}"
            
            # Copy to clipboard
            try:
                import pyperclip
                pyperclip.copy(full_message)
                
                # Show confirmation
                QMessageBox.information(parent, "Copied", "Error message copied to clipboard!")
            except (ImportError, pyperclip.PyperclipException, RuntimeError, OSError, TypeError):
                # Fallback to Qt clipboard
                try:
                    clipboard = QApplication.clipboard()
                    clipboard.setText(full_message)
                    QMessageBox.information(parent, "Copied", "Error message copied to clipboard!")
                except (AttributeError, RuntimeError, TypeError):
                    QMessageBox.warning(parent, "Copy Failed", "Could not copy to clipboard.")
        
        return result

    @staticmethod
    def show_info_message_box_with_copy(parent, title, text):
        """
        Show an info message box with a copy button.
        """
        msg_box = QMessageBox(parent)
        msg_box.setWindowTitle(title)
        msg_box.setIcon(QMessageBox.Icon.Information)
        
        # Set main text
        msg_box.setText(f"<div style='font-size: 10pt; color: white;'>{text}</div>")
        msg_box.setTextFormat(Qt.TextFormat.RichText)
        
        # Add standard buttons
        ok_button = msg_box.addButton(QMessageBox.StandardButton.Ok)
        copy_button = msg_box.addButton("📋 Copy", QMessageBox.ButtonRole.ActionRole)
        
        # Apply styling (same as error box)
        msg_box.setStyleSheet("""
            QMessageBox {
                background-color: #2b2b2b;
                color: #ffffff;
                border: 1px solid #555555;
            }
            QLabel {
                color: #ffffff;
            }
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 12px;
                font-weight: bold;
                min-width: 80px;
                margin: 2px;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
        """)
        
        # Execute and handle button clicks
        result = msg_box.exec()
        
        # Check if copy button was clicked
        if msg_box.clickedButton() == copy_button:
            try:
                import pyperclip
                pyperclip.copy(text)
                QMessageBox.information(parent, "Copied", "Message copied to clipboard!")
            except (ImportError, pyperclip.PyperclipException, RuntimeError, OSError, TypeError):
                try:
                    clipboard = QApplication.clipboard()
                    clipboard.setText(text)
                    QMessageBox.information(parent, "Copied", "Message copied to clipboard!")
                except (AttributeError, RuntimeError, TypeError):
                    QMessageBox.warning(parent, "Copy Failed", "Could not copy to clipboard.")
        
        return result

    @staticmethod  
    def show_copyable_error(parent, title, message, details=None):
        """
        Convenience method for showing error messages with copy functionality.
        
        Args:
            parent: Parent widget
            title: Error dialog title
            message: Main error message (supports HTML)
            details: Optional detailed error information for copying
        """
        return MainWindow.show_error_message_box_with_copy(parent, title, message, details)
    
    @staticmethod
    def show_copyable_info(parent, title, message):
        """
        Convenience method for showing info messages with copy functionality.
        """
        return MainWindow.show_info_message_box_with_copy(parent, title, message)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec())