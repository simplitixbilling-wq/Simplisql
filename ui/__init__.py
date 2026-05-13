"""
UI Module
---------
User interface components for SimplSQL.

Components:
- MainWindow: Main application window
- Dialogs: WorkflowWizard, StepEditorDialog
- Widgets: Custom UI widgets (SearchDialog, CustomPlainTextEdit)
- DataOperationDialogs: Data transformation dialogs (aggregation, pivot, join, distinct, split)
- ViewManager: Dashboard and view management
- UIBuilder: Main UI construction and theming
"""

from .widgets import SearchDialog, CustomPlainTextEdit
from .dialogs import WorkflowWizard, StepEditorDialog
from .data_dialogs import DataOperationDialogs
from .view_manager import ViewManager
from .ui_builder import UIBuilder

__all__ = [
    'SearchDialog', 
    'CustomPlainTextEdit', 
    'WorkflowWizard', 
    'StepEditorDialog',
    'DataOperationDialogs',
    'ViewManager',
    'UIBuilder'
]
