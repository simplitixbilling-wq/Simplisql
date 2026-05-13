"""
File Management Utilities Module

Provides file management functionality for the DuckDB Query Editor:
- Parquet file listing and refresh
- File dropdown UI updates
- File deletion with confirmations
- ZIP file selection dialog

This module handles all file-related operations except for the core
upload_files and process_zip_file methods (reserved for Phase 10B).

Dependencies:
    - self.doc_dir: Path to ParquetFiles directory
    - self.uploaded_files: List of uploaded file paths
    - self.uploaded_display_names: List of display names for UI
    - self.file_dropdown: QComboBox widget for file selection
    - MainWindow.show_styled_message_box(): Styled message box method

Author: Refactored from Simplsql.py Phase 10A
"""

import os
from PyQt6.QtWidgets import (
    QDialog, QLabel, QListWidget, QListWidgetItem,
    QVBoxLayout, QHBoxLayout, QPushButton, QMessageBox
)
from PyQt6.QtCore import Qt


class FileUtilities:
    """Mixin class providing file management utilities"""
    
    def load_existing_parquet_files(self):
        """
        Load existing Parquet files from the document directory.
        
        Scans the doc_dir for .parquet files and populates:
        - self.uploaded_files: Full paths to parquet files
        - self.uploaded_display_names: Display names (filenames without extension)
        
        Called by: display_existing_files, refresh_parquet_files
        """
        if os.path.exists(self.doc_dir):
            self.uploaded_files = [
                os.path.join(self.doc_dir, f)
                for f in os.listdir(self.doc_dir)
                if f.endswith(".parquet")
            ]
            self.uploaded_display_names = [
                os.path.splitext(os.path.basename(f))[0] for f in self.uploaded_files
            ]

    def display_existing_files(self, selected=None):
        """
        Update the file dropdown with existing Parquet files.

        Refreshes the file list from disk and updates the UI dropdown.

        Args:
            selected: optional display name (filename without extension) to select after refresh.

        Called by: __init__, delete_parquet, refresh_parquet_files, upload_files
        """
        # Refresh list from disk
        self.load_existing_parquet_files()

        # Preserve previous selection where possible so UI doesn't unexpectedly jump to the first file
        prev = None
        try:
            if hasattr(self, 'file_dropdown') and isinstance(self.file_dropdown, type(self.file_dropdown)):
                prev = self.file_dropdown.currentText()
        except Exception:
            prev = None

        # Re-populate dropdown
        self.file_dropdown.clear()
        self.file_dropdown.addItems(self.uploaded_display_names)

        # If a specific file was requested, try to select it
        try:
            if selected and selected in self.uploaded_display_names:
                self.file_dropdown.setCurrentText(selected)
                return
        except Exception:
            pass

        # Otherwise try to restore previous selection if it still exists
        try:
            if prev and prev in self.uploaded_display_names:
                self.file_dropdown.setCurrentText(prev)
        except Exception:
            pass

    def delete_parquet(self):
        """
        Delete selected Parquet file with user confirmation.
        
        Shows confirmation dialog, deletes the file from disk, updates
        the file list, and displays success/error message.
        
        Connected to: Delete button in main UI
        """
        selected_text = self.file_dropdown.currentText()
        if not selected_text:
            # Import MainWindow to access static method
            from Simplisql import MainWindow
            MainWindow.show_styled_message_box(
                self, "Warning", "Please select a file to delete!", 
                icon=QMessageBox.Icon.Warning
            )
            return

        from Simplisql import MainWindow
        confirm = MainWindow.show_styled_message_box(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete '{selected_text}'?",
            icon=QMessageBox.Icon.Question,
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if confirm != QMessageBox.StandardButton.Yes:
            return

        # Find full path from display name
        full_path = next(
            (
                f
                for f in self.uploaded_files
                if os.path.splitext(os.path.basename(f))[0] == selected_text
            ),
            None,
        )

        if full_path and os.path.exists(full_path):
            try:
                os.remove(full_path)
                self.uploaded_files.remove(full_path)
                self.display_existing_files()
                MainWindow.show_styled_message_box(
                    self, "Deleted", f"File '{selected_text}' deleted successfully!", 
                    icon=QMessageBox.Icon.Information
                )
            except Exception as e:
                MainWindow.show_styled_message_box(
                    self, "Error", f"Failed to delete the file: {str(e)}",
                    icon=QMessageBox.Icon.Critical
                )
        else:
            MainWindow.show_styled_message_box(
                self, "Error", "File not found!", 
                icon=QMessageBox.Icon.Critical
            )

    def refresh_parquet_files(self):
        """
        Manually refresh the Parquet file list from disk.
        
        Rescans the doc_dir, updates the dropdown, and shows success message.
        
        Connected to: Refresh button in main UI
        """
        if os.path.exists(self.doc_dir):
            self.uploaded_files = [
                os.path.join(self.doc_dir, f)
                for f in os.listdir(self.doc_dir)
                if f.endswith(".parquet")
            ]

        self.display_existing_files()

        from Simplisql import MainWindow
        MainWindow.show_styled_message_box(
            self, "Refreshed", "File list updated successfully!",
            icon=QMessageBox.Icon.Information
        )

    def show_zip_file_selection(self, supported_files):
        """
        Show dialog to select specific files from a ZIP archive.
        
        Creates a dialog with a multi-selection list of files from the ZIP.
        All files are selected by default. User can select/deselect and confirm.
        
        Args:
            supported_files: List of file info objects with .filename and .file_size attributes
            
        Returns:
            List of selected file info objects, or empty list if cancelled
            
        Called by: upload_files when processing ZIP files
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Files from ZIP")
        dialog.setModal(True)
        dialog.resize(400, 300)
        
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Select files to process:"))
        
        file_list = QListWidget()
        file_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        
        # Add all files to list
        for file_info in supported_files:
            item = QListWidgetItem(f"{file_info.filename} ({file_info.file_size} bytes)")
            item.setData(Qt.ItemDataRole.UserRole, file_info)
            file_list.addItem(item)
            item.setSelected(True)  # Select all by default
        
        layout.addWidget(file_list)
        
        # Create buttons
        button_layout = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_none_btn = QPushButton("Select None")
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        
        # Connect button actions
        select_all_btn.clicked.connect(lambda: file_list.selectAll())
        select_none_btn.clicked.connect(lambda: file_list.clearSelection())
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        
        button_layout.addWidget(select_all_btn)
        button_layout.addWidget(select_none_btn)
        button_layout.addStretch()
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        
        # Return selected files if OK clicked
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return [item.data(Qt.ItemDataRole.UserRole) for item in file_list.selectedItems()]
        return []
