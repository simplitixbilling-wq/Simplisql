"""
Export Utilities Module

Provides data export functionality:
- Export to CSV with DuckDB optimization
- Filtered vs full dataset export
- Progress tracking for large exports
- PyInstaller-compatible file dialogs

This module separates data export logic from core editor functionality,
providing efficient and user-friendly export capabilities.

Dependencies:
    - self attributes: _model, _proxy, results_table, doc_dir, file_dropdown, conn
    - External methods: apply_progress_dialog_styling, _duckdb_copy_from_parquet
    - PyQt6: File dialogs, progress dialogs
    - pandas: DataFrame CSV export
    - DuckDB: Direct COPY for optimized export
    - MainWindow: Styled message boxes

Author: Refactored from Simplsql.py Phase 12C
"""

import os
import pandas as pd
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog, QApplication
from PyQt6.QtCore import Qt


class ExportUtils:
    """Mixin class providing data export functionality"""
    
    def export_to_csv(self):
        """
        Export current table view to CSV file.
        
        Provides optimized CSV export with multiple strategies:
        - DuckDB COPY: Direct export from parquet (fastest, no memory overhead)
        - Filtered export: Exports visible filtered rows via proxy model
        - Full export: Exports complete DataFrame
        
        Features:
        - Smart detection of export type (full vs filtered)
        - Progress tracking with styled dialog
        - File overwrite confirmation
        - Default save location in ParquetFiles folder
        - Automatic .csv extension handling
        - DuckDB optimization when possible
        
        Export strategies:
        1. If no filter active and single parquet file → Use DuckDB COPY (fastest)
        2. If filter active → Export filtered rows via proxy model
        3. Otherwise → Export full DataFrame
        
        Called by: Excel export button, export menu
        """
        # Import MainWindow here to avoid circular import
        from Simplisql import MainWindow
        
        # Check if we have data to export
        if not hasattr(self, '_model') or self._model is None:
            MainWindow.show_styled_message_box(
                self, "Warning", "No data available to export!",
                icon=QMessageBox.Icon.Warning
            )
            return

        model = self.results_table.model()
        if model is None or model.rowCount() == 0:
            MainWindow.show_styled_message_box(
                self, "Warning", "No data available to export!",
                icon=QMessageBox.Icon.Warning
            )
            return

        # Default save location is the app's ParquetFiles folder for convenience
        default_csv = os.path.join(self.doc_dir, "exported_view.csv")
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save CSV File", default_csv, "CSV files (*.csv)",
        )
        if not file_path:
            return

        # Ensure .csv extension
        if not file_path.lower().endswith('.csv'):
            file_path = file_path + '.csv'

        # If file exists, confirm overwrite
        if os.path.exists(file_path):
            confirm = MainWindow.show_styled_message_box(
                self,
                "Confirm Overwrite",
                f"File {os.path.basename(file_path)} already exists. Overwrite?",
                icon=QMessageBox.Icon.Question,
                buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        try:
            # Show progress dialog for CSV export
            progress = QProgressDialog("Exporting data to CSV...", "Cancel", 0, 100, self)
            progress.setWindowTitle("Export Progress")
            progress.setWindowModality(Qt.WindowModality.ApplicationModal)
            progress.setMinimumDuration(0)
            progress.setValue(0)
            self.apply_progress_dialog_styling(progress, "#E91E63")  # Pink for export operations
            progress.show()
            QApplication.processEvents()

            # Use DuckDB COPY when possible for full, unfiltered exports to avoid
            # materializing large DataFrames in memory. Otherwise fall back to pandas.
            used_duckdb = False
            try:
                # Detect simple case: no proxy filtering (proxy absent) and the model
                # corresponds to a single parquet file currently selected in file_dropdown
                if (not hasattr(self, '_proxy') or self._proxy is None) and hasattr(self, 'file_dropdown'):
                    sel = self.file_dropdown.currentText()
                    if sel:
                        src_path = os.path.join(self.doc_dir, f"{sel}.parquet").replace('\\', '/')
                        if os.path.exists(src_path):
                            # Use DuckDB COPY to export to CSV directly from parquet
                            progress.setValue(30)
                            progress.setLabelText("Exporting using DuckDB...")
                            QApplication.processEvents()
                            self._duckdb_copy_from_parquet(src_path, file_path, format='csv')
                            used_duckdb = True
            except Exception:
                used_duckdb = False

            if not used_duckdb:
                # Use the underlying DataFrame from the model for export
                if hasattr(self, '_proxy') and self._proxy is not None:
                    proxy_model = self._proxy
                    source_model = self._model
                    col_names = list(source_model._df.columns)
                    data = []
                    for row in range(proxy_model.rowCount()):
                        row_data = []
                        for col in range(proxy_model.columnCount()):
                            proxy_idx = proxy_model.index(row, col)
                            value = proxy_model.data(proxy_idx, Qt.ItemDataRole.DisplayRole)
                            row_data.append(value if value is not None else '')
                        data.append(row_data)
                    progress.setValue(70)
                    progress.setLabelText("Creating DataFrame...")
                    QApplication.processEvents()
                    df = pd.DataFrame(data, columns=col_names)
                else:
                    progress.setValue(50)
                    progress.setLabelText("Preparing data...")
                    QApplication.processEvents()
                    df = self._model._df.copy()
                
                progress.setValue(90)
                progress.setLabelText("Writing CSV file...")
                QApplication.processEvents()
                df.to_csv(file_path, index=False)

            progress.setValue(100)
            progress.close()

            MainWindow.show_styled_message_box(
                self, "Success",
                f"Data exported successfully as:\n{os.path.basename(file_path)}",
                icon=QMessageBox.Icon.Information
            )
        except Exception as e:
            progress.close()
            MainWindow.show_styled_message_box(
                self, "Error", f"Failed to save CSV:\n{str(e)}",
                icon=QMessageBox.Icon.Critical
            )
