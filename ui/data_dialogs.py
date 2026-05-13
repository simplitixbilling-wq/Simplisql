"""
Data Operation Dialogs Module
=============================

This module contains data transformation dialog classes used by SimplSQL.

Extracted dialogs:
 - perform_aggregation(): aggregation dialog with group-by support
 - get_distinct_values(): distinct-values extraction dialog
 - split_file_by_column(): split a file by a column's values
 - pivot_table_dialog(): pivot table creation dialog
 - join_tables(): join two parquet files dialog

These dialogs provide UI for common data operations and integrate with the
DuckDB backend.
"""

import os
import time
import re
import pandas as pd
import csv
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QListWidget, QListWidgetItem, QPushButton, QProgressDialog,
    QMessageBox, QLineEdit, QFrame, QFileDialog, QApplication,
    QCheckBox, QSpinBox
)
from PyQt6.QtCore import Qt


class DataOperationDialogs:
    """
    Mixin class containing all data operation dialog methods.
    
    This class requires the following attributes from the parent class:
    - self.doc_dir: Path to ParquetFiles directory
    - self.conn: DuckDB connection
    - self.populate_treeview(): Method to display results
    - self.apply_dark_dialog_styling(): Dialog styling method
    - self.apply_progress_dialog_styling(): Progress dialog styling
    - self.make_save_checkbox(): Create dashboard save checkbox
    - self.create_input_popup(): Input dialog method
    - self.add_view(): Add dashboard view method
    - self.display_existing_files(): Refresh file list method
    """
    
    def perform_aggregation(self):
        """Show aggregation dialog with group-by and save-as-view options"""
        # Import MainWindow here to avoid circular import
        from Simplisql import MainWindow
        
        # Prepare list of parquet base names in the ParquetFiles folder
        try:
            files = [f for f in os.listdir(self.doc_dir) if f.endswith('.parquet')]
            base_names = [os.path.splitext(f)[0] for f in files]
        except Exception:
            base_names = []

        if not base_names:
            MainWindow.show_styled_message_box(self, "No Files", "No parquet files found in the ParquetFiles folder.", icon=QMessageBox.Icon.Warning)
            return

        dialog = QDialog(self)
        self.apply_dark_dialog_styling(dialog)
        dialog.setWindowTitle("Aggregate from Parquet")
        dlg_layout = QVBoxLayout(dialog)

        file_label = QLabel("Select Parquet (base name):")
        file_label.setStyleSheet("color: #d0d0d0; font-weight: bold;")
        dlg_layout.addWidget(file_label)
        file_combo = QComboBox()
        file_combo.addItems(base_names)
        dlg_layout.addWidget(file_combo)
        # Show group-by selector first (as requested)
        gb_label = QLabel("Select Group-by Field(s) (optional):")
        gb_label.setStyleSheet("color: #d0d0d0; font-weight: bold;")
        dlg_layout.addWidget(gb_label)
        gb_list = QListWidget()
        gb_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        gb_list.setStyleSheet("""
            QListWidget {
                background-color: #3c3f41;
                color: #ffffff;
                border: 2px solid #555555;
                padding: 4px;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 6px;
                border-radius: 3px;
            }
            QListWidget::item:selected {
                background-color: #0d7377;
                color: #ffffff;
                font-weight: bold;
            }
            QListWidget::item:hover {
                background-color: #4a5568;
            }
        """)
        dlg_layout.addWidget(gb_list)

        # Then show numeric field selector
        col_label = QLabel("Select Field(s) to aggregate (multi-select, numeric-only):")
        col_label.setStyleSheet("color: #d0d0d0; font-weight: bold;")
        dlg_layout.addWidget(col_label)
        col_list = QListWidget()
        col_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        col_list.setStyleSheet("""
            QListWidget {
                background-color: #3c3f41;
                color: #ffffff;
                border: 2px solid #555555;
                padding: 4px;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 6px;
                border-radius: 3px;
            }
            QListWidget::item:selected {
                background-color: #0d7377;
                color: #ffffff;
                font-weight: bold;
            }
            QListWidget::item:hover {
                background-color: #4a5568;
            }
        """)
        dlg_layout.addWidget(col_list)

        agg_label = QLabel("Select Aggregator:")
        agg_label.setStyleSheet("color: #d0d0d0; font-weight: bold;")
        dlg_layout.addWidget(agg_label)
        agg_combo = QComboBox()
        agg_combo.addItems(["SUM", "AVG", "MIN", "MAX", "COUNT", "STD", "VAR"])
        dlg_layout.addWidget(agg_combo)

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        dlg_layout.addLayout(btn_layout)

        # Save as dashboard view option (consistent style)
        save_checkbox = self.make_save_checkbox("Save as Dashboard View")
        dlg_layout.insertWidget(dlg_layout.count() - 1, save_checkbox)

        # When file selected, populate columns
        def on_file_change(idx):
            from utils import ParquetSchemaThread
            
            base = file_combo.currentText()
            path = os.path.join(self.doc_dir, f"{base}.parquet")
            # Use background thread to read only parquet schema (much faster)
            progress = QProgressDialog("Loading column information...", "Cancel", 0, 100, self)
            progress.setWindowTitle("Loading Columns")
            progress.setWindowModality(Qt.WindowModality.ApplicationModal)
            progress.setMinimumDuration(100)  # Show quickly for schema reading
            progress.setValue(0)
            self.apply_progress_dialog_styling(progress, "#9C27B0")  # Purple for schema loading
            progress.show()
            QApplication.processEvents()

            def on_finished(schema_info):
                progress.setValue(100)
                progress.setLabelText("Populating column list...")
                QApplication.processEvents()
                progress.close()
                try:
                    all_columns, numeric_cols = schema_info
                except Exception:
                    all_columns = []
                    numeric_cols = []

                col_list.clear()
                gb_list.clear()
                for c in all_columns:
                    item = QListWidgetItem(c)
                    gb_list.addItem(QListWidgetItem(c))
                for c in numeric_cols:
                    col_list.addItem(QListWidgetItem(c))

            def on_error(msg):
                progress.close()
                MainWindow.show_styled_message_box(self, "Error reading parquet schema", msg, icon=QMessageBox.Icon.Critical)

            # Use schema thread instead of full data thread
            progress.setValue(30)
            progress.setLabelText("Reading file schema...")
            QApplication.processEvents()
            
            reader = ParquetSchemaThread(path)
            # keep a reference so thread is not garbage-collected
            self._parquet_schema_reader = reader
            reader.finished.connect(on_finished)
            reader.error.connect(on_error)
            reader.start()

        file_combo.currentIndexChanged.connect(on_file_change)
        # initialize columns for first file
        on_file_change(0)

        def on_ok():
            base = file_combo.currentText()
            selected_items = col_list.selectedItems()
            cols = [it.text() for it in selected_items]
            gb_items = gb_list.selectedItems()
            group_cols = [it.text() for it in gb_items]
            agg = agg_combo.currentText()
            # If user chose to save the view, prompt for name and persist
            if save_checkbox.isChecked():
                name = self.create_input_popup("Save View", "Enter view name:")
                if name:
                    view_spec = {
                        'name': name,
                        'base_parquet': base,
                        'group_by': group_cols,
                        'aggregations': [{'column': c, 'agg': agg} for c in cols],
                        'visualization': 'table',
                        'refresh': {'type': 'on-open'}
                    }
                    try:
                        vid = self.add_view(view_spec)
                        MainWindow.show_styled_message_box(self, "Saved", f"View saved: {name}", icon=QMessageBox.Icon.Information)
                    except Exception as e:
                        MainWindow.show_styled_message_box(self, "Error", f"Failed to save view: {e}", icon=QMessageBox.Icon.Critical)

            dialog.accept()
            # perform aggregation using DuckDB
            try:
                path = os.path.join(self.doc_dir, f"{base}.parquet").replace("\\", "/")
                
                if not cols:
                    MainWindow.show_styled_message_box(self, "Error", "Please select at least one column.", icon=QMessageBox.Icon.Critical)
                    return

                # Build aggregation SQL query using DuckDB
                agg_expressions = []
                
                # Map UI aggregator names to SQL function names
                sql_func_map = {
                    'COUNT': 'COUNT',
                    'SUM': 'SUM', 
                    'AVG': 'AVG',
                    'MIN': 'MIN',
                    'MAX': 'MAX',
                    'STD': 'STDDEV',
                    'VAR': 'VARIANCE'
                }
                
                sql_func = sql_func_map.get(agg)
                if not sql_func:
                    MainWindow.show_styled_message_box(self, "Error", f"Unknown aggregator: {agg}", icon=QMessageBox.Icon.Critical)
                    return
                
                # Build aggregation expressions for each selected column
                for col in cols:
                    if agg == 'COUNT':
                        # COUNT can work on any column
                        agg_expressions.append(f'COUNT("{col}") AS "{agg}_{col}"')
                    else:
                        # Other functions need numeric casting for reliability
                        agg_expressions.append(f'{sql_func}(CAST("{col}" AS DOUBLE)) AS "{agg}_{col}"')
                
                # Build SELECT clause
                select_clause = ", ".join(agg_expressions)
                
                # Build GROUP BY clause if group columns are specified
                if group_cols:
                    group_clause = ", ".join([f'"{gc}"' for gc in group_cols])
                    query = f'''
                    SELECT {group_clause}, {select_clause}
                    FROM read_parquet('{path}')
                    GROUP BY {group_clause}
                    ORDER BY {group_clause}
                    '''
                else:
                    # No grouping - single row result
                    query = f'''
                    SELECT {select_clause}
                    FROM read_parquet('{path}')
                    '''
                
                print(f"\n🔍 Aggregation Query:\n{query}")
                
                # Show progress dialog
                progress = QProgressDialog("Executing aggregation query...", "Cancel", 0, 100, self)
                progress.setWindowTitle("Aggregation Progress")
                progress.setWindowModality(Qt.WindowModality.ApplicationModal)
                progress.setMinimumDuration(0)
                progress.setValue(0)
                self.apply_progress_dialog_styling(progress, "#FF9800")  # Orange for aggregation
                progress.show()
                QApplication.processEvents()
                
                # Execute DuckDB query
                start_time = time.time()
                print(f"🚀 Aggregation started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
                
                # Configure DuckDB for performance
                self.conn.execute("PRAGMA threads=8;")
                self.conn.execute("PRAGMA memory_limit='16GB';")
                
                progress.setValue(30)
                progress.setLabelText("Processing aggregation...")
                QApplication.processEvents()
                
                # Execute the aggregation query
                res = self.conn.execute(query).fetchdf()
                
                progress.setValue(90)
                progress.setLabelText("Preparing results...")
                QApplication.processEvents()
                
                end_time = time.time()
                total_time = end_time - start_time
                print(f"✅ Aggregation completed at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"⏱️ Total execution time: {total_time:.2f} seconds")
                print(f"📊 Result shape: {res.shape}")
                
                progress.setValue(100)
                progress.close()
                
                # Display results in the table
                self.populate_treeview(res, set_full=True)
                
            except Exception as e:
                MainWindow.show_styled_message_box(self, "Aggregation Error", str(e), icon=QMessageBox.Icon.Critical)

        ok_btn.clicked.connect(on_ok)
        cancel_btn.clicked.connect(dialog.reject)

        dialog.exec()

    def get_distinct_values(self):
        """Show a dialog to let the user pick a parquet file and one or more columns,
        then run a DISTINCT query and display the results in the table."""
        # Import MainWindow here to avoid circular import
        from Simplisql import MainWindow
        
        try:
            # List available parquet base names
            try:
                files = [f for f in os.listdir(self.doc_dir) if f.endswith('.parquet')]
                base_names = [os.path.splitext(f)[0] for f in files]
            except Exception:
                base_names = []

            if not base_names:
                MainWindow.show_styled_message_box(self, "No Files", "No parquet files found in the ParquetFiles folder.", icon=QMessageBox.Icon.Warning)
                return

            dlg = QDialog(self)
            self.apply_dark_dialog_styling(dlg)
            dlg.setWindowTitle("Get Distinct Values")
            dlg.setMinimumSize(480, 420)
            layout = QVBoxLayout(dlg)

            file_label = QLabel("Select Parquet (base name):")
            file_label.setStyleSheet("color: #d0d0d0; font-weight: bold;")
            layout.addWidget(file_label)

            file_combo = QComboBox()
            file_combo.addItems(base_names)
            layout.addWidget(file_combo)

            col_label = QLabel("Select Column(s) to DISTINCT:")
            col_label.setStyleSheet("color: #d0d0d0; font-weight: bold;")
            layout.addWidget(col_label)

            cols_list = QListWidget()
            cols_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
            cols_list.setStyleSheet("""
                QListWidget {
                    background-color: #3c3f41;
                    color: #ffffff;
                    border: 2px solid #555555;
                    padding: 4px;
                    font-size: 12px;
                }
                QListWidget::item {
                    padding: 6px;
                    border-radius: 3px;
                }
                QListWidget::item:selected {
                    background-color: #0d7377;
                    color: #ffffff;
                    font-weight: bold;
                }
                QListWidget::item:hover {
                    background-color: #4a5568;
                }
            """)
            layout.addWidget(cols_list)

            btn_row = QHBoxLayout()
            ok_btn = QPushButton("OK")
            cancel_btn = QPushButton("Cancel")
            btn_row.addStretch()
            btn_row.addWidget(ok_btn)
            btn_row.addWidget(cancel_btn)
            layout.addLayout(btn_row)

            # Save as dashboard view option (consistent style)
            save_distinct_checkbox = self.make_save_checkbox("Save as Dashboard View (store SQL)")
            layout.addWidget(save_distinct_checkbox)

            def load_columns_for_current_file():
                cols_list.clear()
                base = file_combo.currentText()
                if not base:
                    return
                path = os.path.join(self.doc_dir, f"{base}.parquet")
                try:
                    import pyarrow.parquet as pq
                    pf = pq.ParquetFile(path)
                    columns = pf.schema.names
                except Exception:
                    try:
                        df_tmp = pd.read_parquet(path, engine='pyarrow')
                        columns = list(df_tmp.columns)
                    except Exception:
                        columns = []

                for c in columns:
                    item = QListWidgetItem(c)
                    cols_list.addItem(item)

            file_combo.currentIndexChanged.connect(lambda _idx: load_columns_for_current_file())
            load_columns_for_current_file()

            def on_ok():
                selected_items = cols_list.selectedItems()
                if not selected_items:
                    MainWindow.show_styled_message_box(self, "Select Column", "Please select at least one column.", icon=QMessageBox.Icon.Warning)
                    return
                cols = [it.text() for it in selected_items]
                base = file_combo.currentText()
                path = os.path.join(self.doc_dir, f"{base}.parquet").replace('\\', '/')
                # Build DISTINCT query
                cols_sql = ', '.join([f'"{c}"' for c in cols])
                query = f"SELECT DISTINCT {cols_sql} FROM read_parquet('{path}')"
                try:
                    df = self.conn.execute(query).fetchdf()
                    self.populate_treeview(df, set_full=True)
                    # if user wants to save as view, persist SQL view
                    if save_distinct_checkbox.isChecked():
                        # Ask for dashboard name & description using the consistent dialog used elsewhere
                        name_dialog = QDialog(self)
                        self.apply_dark_dialog_styling(name_dialog)
                        name_dialog.setWindowTitle("Save View")
                        name_dialog.setMinimumWidth(400)
                        name_layout = QVBoxLayout(name_dialog)

                        name_label = QLabel("View Name:")
                        name_label.setStyleSheet("color: #d0d0d0; font-weight: bold;")
                        name_layout.addWidget(name_label)

                        name_input = QLineEdit()
                        name_input.setText(f"{base}_distinct")
                        name_layout.addWidget(name_input)

                        desc_label = QLabel("Description (optional):")
                        desc_label.setStyleSheet("color: #d0d0d0; font-weight: bold;")
                        name_layout.addWidget(desc_label)

                        desc_input = QLineEdit()
                        name_layout.addWidget(desc_input)

                        name_btn_layout = QHBoxLayout()
                        save_btn = QPushButton("Save")
                        cancel_name_btn = QPushButton("Cancel")
                        save_btn.setStyleSheet("background-color: #2e7d32; color: white; padding: 6px 12px;")
                        for btn in [save_btn, cancel_name_btn]:
                            btn.setMinimumHeight(32)
                            btn.setStyleSheet("background-color: #454545; color: #d0d0d0; padding: 6px 12px;")
                        name_btn_layout.addStretch()
                        name_btn_layout.addWidget(save_btn)
                        name_btn_layout.addWidget(cancel_name_btn)
                        name_layout.addLayout(name_btn_layout)

                        def on_save_name():
                            dashboard_name = name_input.text().strip()
                            if not dashboard_name:
                                MainWindow.show_styled_message_box(self, "Name Required", "Please enter a name for the view.", icon=QMessageBox.Icon.Warning)
                                return
                            view_spec = {
                                'name': dashboard_name,
                                'description': desc_input.text().strip(),
                                'type': 'sql',
                                'sql': query,
                                'visualization': 'table',
                                'refresh': {'type': 'on-open'},
                                'created_from': 'get_distinct_values'
                            }
                            try:
                                self.add_view(view_spec)
                                MainWindow.show_styled_message_box(self, "Saved", f"View '{dashboard_name}' saved.", icon=QMessageBox.Icon.Information)
                            except Exception as e:
                                MainWindow.show_styled_message_box(self, "Error", f"Failed to save view: {e}", icon=QMessageBox.Icon.Critical)
                            name_dialog.accept()

                        def on_cancel_name():
                            name_dialog.reject()

                        save_btn.clicked.connect(on_save_name)
                        cancel_name_btn.clicked.connect(on_cancel_name)
                        name_dialog.exec()
                    dlg.accept()
                except Exception as e:
                    MainWindow.show_styled_message_box(self, "Error", f"Failed to fetch distinct values:\n{e}", icon=QMessageBox.Icon.Critical)

            def on_cancel():
                dlg.reject()

            ok_btn.clicked.connect(on_ok)
            cancel_btn.clicked.connect(on_cancel)
            dlg.exec()

        except Exception as e:
            MainWindow.show_styled_message_box(self, "Error", f"Unexpected error: {e}", icon=QMessageBox.Icon.Critical)

    def split_file_by_column(self):
        """Prompt the user to select a parquet file and a column, then split the file into
        separate parquet files for each distinct value of that column. Files are written to
        ParquetFiles/<base>_splits/<sanitized_key>.parquet
        """
        # Import MainWindow here to avoid circular import
        from Simplisql import MainWindow
        
        try:
            try:
                files = [f for f in os.listdir(self.doc_dir) if f.endswith('.parquet')]
                base_names = [os.path.splitext(f)[0] for f in files]
            except Exception:
                base_names = []

            if not base_names:
                MainWindow.show_styled_message_box(self, "No Files", "No parquet files found in the ParquetFiles folder.", icon=QMessageBox.Icon.Warning)
                return

            dlg = QDialog(self)
            self.apply_dark_dialog_styling(dlg)
            dlg.setWindowTitle("Split by Column")
            dlg.setMinimumSize(420, 340)
            v = QVBoxLayout(dlg)
            v.setSpacing(8)
            v.setContentsMargins(12, 12, 12, 12)

            file_label = QLabel("Select Parquet (base name):")
            file_label.setStyleSheet("color: #d0d0d0; font-weight: bold; font-size: 14px;")
            v.addWidget(file_label)

            file_combo = QComboBox()
            file_combo.addItems(base_names)
            v.addWidget(file_combo)

            col_label = QLabel("Select Column to split by:")
            col_label.setStyleSheet("color: #d0d0d0; font-weight: bold; font-size: 14px;")
            v.addWidget(col_label)

            col_combo = QComboBox()
            v.addWidget(col_combo)

            opts_row = QHBoxLayout()
            opts_row.setSpacing(6)
            limit_label = QLabel("Max keys (0 = all):")
            limit_label.setStyleSheet("color:#d0d0d0; font-size: 14px;")
            opts_row.addWidget(limit_label)
            limit_input = QLineEdit()
            limit_input.setText("")
            limit_input.setPlaceholderText("Leave blank...")
            limit_input.setMaximumWidth(120)
            opts_row.addWidget(limit_input)
            opts_row.addStretch()
            v.addLayout(opts_row)

            out_row = QHBoxLayout()
            out_row.setSpacing(6)
            out_label = QLabel("Output folder (optional):")
            out_label.setStyleSheet("color:#d0d0d0; font-size: 14px;")
            out_row.addWidget(out_label)
            out_input = QLineEdit()
            out_input.setPlaceholderText("defaults to <base>_splits")
            out_row.addWidget(out_input)
            v.addLayout(out_row)

            # Optionally create dashboard views for each key instead of writing files
            create_views_checkbox = self.make_save_checkbox("Create Dashboard Views per key (do not write files)")
            v.addWidget(create_views_checkbox)

            btn_row = QHBoxLayout()
            start_btn = QPushButton("Start Split")
            cancel_btn = QPushButton("Cancel")
            btn_row.addStretch()
            btn_row.addWidget(start_btn)
            btn_row.addWidget(cancel_btn)
            v.addLayout(btn_row)

            def load_columns():
                col_combo.clear()
                base = file_combo.currentText()
                if not base:
                    return
                path = os.path.join(self.doc_dir, f"{base}.parquet")
                try:
                    import pyarrow.parquet as pq
                    pf = pq.ParquetFile(path)
                    cols = pf.schema.names
                except Exception:
                    try:
                        df_tmp = pd.read_parquet(path, engine='pyarrow')
                        cols = list(df_tmp.columns)
                    except Exception:
                        cols = []
                col_combo.addItems(cols)

            file_combo.currentIndexChanged.connect(lambda _i: load_columns())
            load_columns()

            def sanitize_filename(s: str) -> str:
                s = str(s)
                s = s.strip()
                # replace path-unfriendly chars
                return re.sub(r"[^A-Za-z0-9_.-]", "_", s)

            def on_start():
                base = file_combo.currentText()
                col = col_combo.currentText()
                if not base or not col:
                    MainWindow.show_styled_message_box(self, "Missing", "Please select a file and a column.", icon=QMessageBox.Icon.Warning)
                    return
                path = os.path.join(self.doc_dir, f"{base}.parquet").replace('\\', '/')

                try:
                    # get distinct keys count
                    q = f"SELECT DISTINCT \"{col}\" as key FROM read_parquet('{path}')"
                    keys_df = self.conn.execute(q).fetchdf()
                except Exception as e:
                    MainWindow.show_styled_message_box(self, "Error", f"Failed to retrieve distinct keys: {e}", icon=QMessageBox.Icon.Critical)
                    return

                keys = keys_df['key'].tolist()
                total = len(keys)

                try:
                    max_keys = int(limit_input.text().strip() or 0)
                except Exception:
                    max_keys = 0

                if max_keys > 0 and total > max_keys:
                    keys = keys[:max_keys]
                    total = len(keys)

                if total == 0:
                    MainWindow.show_styled_message_box(self, "No Keys", "No distinct keys found.", icon=QMessageBox.Icon.Information)
                    return

                # Confirm with user if many keys
                if total > 200:
                    confirm = MainWindow.show_styled_message_box(self, "Many Keys", f"There are {total} distinct keys. This will create {total} files and may take a while. Proceed?", icon=QMessageBox.Icon.Question, buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                    if confirm != QMessageBox.StandardButton.Yes:
                        return

                # Ask user for output folder to save CSV splits
                out_folder = QFileDialog.getExistingDirectory(self, "Select output folder", self.doc_dir)
                if not out_folder:
                    # user cancelled
                    return

                progress = QProgressDialog(f"Splitting into {total} files...", "Cancel", 0, total, self)
                progress.setWindowTitle("Splitting Files")
                progress.setWindowModality(Qt.WindowModality.ApplicationModal)
                progress.setMinimumDuration(0)
                progress.setValue(0)
                self.apply_progress_dialog_styling(progress, "#795548")  # Brown for file operations
                progress.show()
                QApplication.processEvents()

                written = 0
                for i, key in enumerate(keys, start=1):
                    if progress.wasCanceled():
                        break
                    # safe SQL literal
                    if key is None:
                        literal = 'NULL'
                        where_clause = f"\"{col}\" IS NULL"
                    elif isinstance(key, str):
                        esc = key.replace("'", "''")
                        literal = f"'{esc}'"
                        where_clause = f"\"{col}\" = {literal}"
                    else:
                        literal = str(key)
                        where_clause = f"\"{col}\" = {literal}"

                    if create_views_checkbox.isChecked():
                        # Create an advanced_load view for this key
                        try:
                            view_name = f"{base}_{sanitize_filename(str(key))}"
                            view_spec = {
                                'name': view_name,
                                'description': f'Split of {base} where {col} = {str(key)}',
                                'type': 'advanced_load',
                                'file': base,
                                'columns': [],
                                'where_clause': where_clause,
                                'preview_size': ''
                            }
                            self.add_view(view_spec)
                            written += 1
                        except Exception as e:
                            print(f"Failed to create view for key={key}: {e}")
                    else:
                        out_file = os.path.join(out_folder, f"{sanitize_filename(str(key))}.csv").replace('\\', '/')
                        try:
                            # Use DuckDB COPY to write parquet chunk for this key
                            self.conn.execute("PRAGMA threads=4;")
                            # write CSV with header
                            self.conn.execute(f"COPY (SELECT * FROM read_parquet('{path}') WHERE {where_clause}) TO '{out_file}' (FORMAT 'csv', HEADER true);")
                            written += 1
                        except Exception as e:
                            print(f"Failed to write split for key={key}: {e}")

                    progress.setValue(i)
                    QApplication.processEvents()

                progress.close()
                MainWindow.show_styled_message_box(self, "Done", f"Completed splitting. {written} files written to {os.path.basename(out_folder)}", icon=QMessageBox.Icon.Information)
                dlg.accept()

            start_btn.clicked.connect(on_start)
            cancel_btn.clicked.connect(dlg.reject)

            dlg.exec()

        except Exception as e:
            MainWindow.show_styled_message_box(self, "Error", f"Unexpected error: {e}", icon=QMessageBox.Icon.Critical)

    def pivot_table_dialog(self):
        """Create a pivot table preview and optionally save the pivot spec as a dashboard view (no file write)."""
        # Import MainWindow here to avoid circular import
        from Simplisql import MainWindow
        
        try:
            try:
                files = [f for f in os.listdir(self.doc_dir) if f.endswith('.parquet')]
                base_names = [os.path.splitext(f)[0] for f in files]
            except Exception:
                base_names = []

            if not base_names:
                MainWindow.show_styled_message_box(self, "No Files", "No parquet files found in the ParquetFiles folder.", icon=QMessageBox.Icon.Warning)
                return

            dlg = QDialog(self)
            self.apply_dark_dialog_styling(dlg)
            dlg.setWindowTitle("Pivot Table")
            dlg.setMinimumSize(560, 480)
            layout = QVBoxLayout(dlg)

            file_combo = QComboBox()
            file_combo.addItems(base_names)
            layout.addWidget(QLabel("Select Parquet (base name):"))
            layout.addWidget(file_combo)

            idx_list = QListWidget()
            idx_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
            idx_list.setStyleSheet("""
                QListWidget {
                    background-color: #3c3f41;
                    color: #ffffff;
                    border: 2px solid #555555;
                    padding: 4px;
                    font-size: 12px;
                }
                QListWidget::item {
                    padding: 6px;
                    border-radius: 3px;
                }
                QListWidget::item:selected {
                    background-color: #0d7377;
                    color: #ffffff;
                    font-weight: bold;
                }
                QListWidget::item:hover {
                    background-color: #4a5568;
                }
            """)
            layout.addWidget(QLabel("Index (rows) - multi-select:"))
            layout.addWidget(idx_list)

            col_list = QListWidget()
            col_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
            col_list.setStyleSheet("""
                QListWidget {
                    background-color: #3c3f41;
                    color: #ffffff;
                    border: 2px solid #555555;
                    padding: 4px;
                    font-size: 12px;
                }
                QListWidget::item {
                    padding: 6px;
                    border-radius: 3px;
                }
                QListWidget::item:selected {
                    background-color: #0d7377;
                    color: #ffffff;
                    font-weight: bold;
                }
                QListWidget::item:hover {
                    background-color: #4a5568;
                }
            """)
            layout.addWidget(QLabel("Columns (optional):"))
            layout.addWidget(col_list)

            val_list = QListWidget()
            val_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
            val_list.setStyleSheet("""
                QListWidget {
                    background-color: #3c3f41;
                    color: #ffffff;
                    border: 2px solid #555555;
                    padding: 4px;
                    font-size: 12px;
                }
                QListWidget::item {
                    padding: 6px;
                    border-radius: 3px;
                }
                QListWidget::item:selected {
                    background-color: #0d7377;
                    color: #ffffff;
                    font-weight: bold;
                }
                QListWidget::item:hover {
                    background-color: #4a5568;
                }
            """)
            layout.addWidget(QLabel("Values (one or more):"))
            layout.addWidget(val_list)

            agg_combo = QComboBox()
            agg_combo.addItems(["sum", "mean", "min", "max", "count", "std", "var"])
            row = QHBoxLayout()
            row.addWidget(QLabel("Aggregator:"))
            row.addWidget(agg_combo)
            row.addStretch()
            layout.addLayout(row)

            # Save-as checkbox (consistent style)
            save_checkbox_for_pivot = self.make_save_checkbox("Save as Dashboard View")
            layout.addWidget(save_checkbox_for_pivot)

            btn_row = QHBoxLayout()
            preview_btn = QPushButton("Preview")
            save_view_btn = QPushButton("Save")
            cancel_btn = QPushButton("Cancel")
            btn_row.addStretch()
            btn_row.addWidget(preview_btn)
            btn_row.addWidget(save_view_btn)
            btn_row.addWidget(cancel_btn)
            layout.addLayout(btn_row)

            def load_columns():
                idx_list.clear(); col_list.clear(); val_list.clear()
                base = file_combo.currentText()
                path = os.path.join(self.doc_dir, f"{base}.parquet")
                try:
                    import pyarrow.parquet as pq
                    pf = pq.ParquetFile(path)
                    cols = pf.schema.names
                except Exception:
                    try:
                        df_tmp = pd.read_parquet(path, engine='pyarrow')
                        cols = list(df_tmp.columns)
                    except Exception:
                        cols = []
                for c in cols:
                    idx_list.addItem(QListWidgetItem(c))
                    col_list.addItem(QListWidgetItem(c))
                    val_list.addItem(QListWidgetItem(c))

            file_combo.currentIndexChanged.connect(lambda _i: load_columns())
            load_columns()

            def compute_pivot():
                base = file_combo.currentText()
                idx = [it.text() for it in idx_list.selectedItems()]
                cols = [it.text() for it in col_list.selectedItems()]
                vals = [it.text() for it in val_list.selectedItems()]
                agg = agg_combo.currentText()
                if not idx or not vals:
                    MainWindow.show_styled_message_box(self, "Missing", "Select at least one index and one value.", icon=QMessageBox.Icon.Warning)
                    return None
                
                # Show loading indicator
                progress = QProgressDialog("Computing pivot table...", None, 0, 0, self)
                progress.setWindowTitle("Processing")
                progress.setWindowModality(Qt.WindowModality.WindowModal)
                self.apply_progress_dialog_styling(progress)
                progress.show()
                QApplication.processEvents()
                
                path = os.path.join(self.doc_dir, f"{base}.parquet").replace('\\', '/')
                try:
                    cols_needed = set(idx + cols + vals)
                    cols_sql = ', '.join([f'"{c}"' for c in cols_needed])
                    # Try to cast value columns to DECIMAL for proper aggregation
                    cast_sql = cols_sql
                    for val in vals:
                        cast_sql = cast_sql.replace(f'"{val}"', f'TRY_CAST("{val}" AS DECIMAL) AS "{val}"')
                    df = self.conn.execute(f"SELECT {cast_sql} FROM read_parquet('{path}')").fetchdf()
                except Exception:
                    try:
                        df = pd.read_parquet(path, engine='pyarrow')
                        # Try to convert value columns to numeric
                        for val in vals:
                            if val in df.columns:
                                df[val] = pd.to_numeric(df[val], errors='coerce')
                    except Exception:
                        progress.close()
                        raise
                
                pivot = pd.pivot_table(df, index=idx, columns=cols if cols else None, values=vals, aggfunc=agg)
                if isinstance(pivot.columns, pd.MultiIndex):
                    pivot.columns = ["_".join([str(x) for x in col]).strip() for col in pivot.columns]
                pivot = pivot.reset_index()
                progress.close()
                return pivot

            def on_preview():
                p = compute_pivot()
                if p is not None:
                    self.populate_treeview(p, set_full=True)

            def on_save_view():
                # If checkbox checked, save the pivot spec as a dashboard view; otherwise preview
                if save_checkbox_for_pivot.isChecked():
                    # Save as dashboard view
                    name = self.create_input_popup("Save Pivot View", "Enter view name:")
                    if not name:
                        return
                    desc = self.create_input_popup("Description", "Optional description:")
                    spec = {
                        'name': name,
                        'description': desc or '',
                        'type': 'pivot',
                        'base_parquet': file_combo.currentText(),
                        'index': [it.text() for it in idx_list.selectedItems()],
                        'columns': [it.text() for it in col_list.selectedItems()],
                        'values': [it.text() for it in val_list.selectedItems()],
                        'agg': agg_combo.currentText(),
                        'visualization': 'pivot',
                        'refresh': {'type': 'on-open'},
                        'created_from': 'pivot_table_dialog'
                    }
                    try:
                        self.add_view(spec)
                        MainWindow.show_styled_message_box(self, "Saved", f"Pivot view '{name}' saved.", icon=QMessageBox.Icon.Information)
                    except Exception as e:
                        MainWindow.show_styled_message_box(self, "Error", f"Failed to save pivot view: {e}", icon=QMessageBox.Icon.Critical)
                else:
                    # behave like preview when checkbox is not checked
                    p = compute_pivot()
                    if p is not None:
                        self.populate_treeview(p, set_full=True)

            preview_btn.clicked.connect(on_preview)
            save_view_btn.clicked.connect(on_save_view)
            cancel_btn.clicked.connect(dlg.reject)

            dlg.exec()

        except Exception as e:
            MainWindow.show_styled_message_box(self, "Error", f"Unexpected error: {e}", icon=QMessageBox.Icon.Critical)

    def join_tables(self):
        """Dialog to join two parquet files on selected columns and show/save the result."""
        # Import MainWindow here to avoid circular import
        from Simplisql import MainWindow
        
        try:
            try:
                files = [f for f in os.listdir(self.doc_dir) if f.endswith('.parquet')]
                base_names = [os.path.splitext(f)[0] for f in files]
            except Exception:
                base_names = []

            if len(base_names) < 2:
                MainWindow.show_styled_message_box(self, "Not enough files", "Need at least two parquet files in ParquetFiles to join.", icon=QMessageBox.Icon.Warning)
                return

            dlg = QDialog(self)
            self.apply_dark_dialog_styling(dlg)
            dlg.setWindowTitle("Join Tables")
            dlg.setMinimumSize(640, 480)
            layout = QVBoxLayout(dlg)

            row1 = QHBoxLayout()
            left_label = QLabel("Left table:")
            left_label.setStyleSheet("color:#d0d0d0;")
            row1.addWidget(left_label)
            left_combo = QComboBox()
            left_combo.addItems(base_names)
            row1.addWidget(left_combo)

            right_label = QLabel("Right table:")
            right_label.setStyleSheet("color:#d0d0d0;")
            row1.addWidget(right_label)
            right_combo = QComboBox()
            right_combo.addItems(base_names)
            # default to second file
            if len(base_names) > 1:
                right_combo.setCurrentIndex(1)
            row1.addWidget(right_combo)
            layout.addLayout(row1)

            # columns selection area
            cols_row = QHBoxLayout()
            left_cols = QListWidget()
            left_cols.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
            left_cols.setMaximumWidth(250)
            left_cols.setStyleSheet("""
                QListWidget {
                    background-color: #3c3f41;
                    color: #ffffff;
                    border: 2px solid #555555;
                    padding: 4px;
                    font-size: 12px;
                }
                QListWidget::item {
                    padding: 6px;
                    border-radius: 3px;
                }
                QListWidget::item:selected {
                    background-color: #0d7377;
                    color: #ffffff;
                    font-weight: bold;
                }
                QListWidget::item:hover {
                    background-color: #4a5568;
                }
            """)
            right_cols = QListWidget()
            right_cols.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
            right_cols.setMaximumWidth(250)
            right_cols.setStyleSheet("""
                QListWidget {
                    background-color: #3c3f41;
                    color: #ffffff;
                    border: 2px solid #555555;
                    padding: 4px;
                    font-size: 12px;
                }
                QListWidget::item {
                    padding: 6px;
                    border-radius: 3px;
                }
                QListWidget::item:selected {
                    background-color: #0d7377;
                    color: #ffffff;
                    font-weight: bold;
                }
                QListWidget::item:hover {
                    background-color: #4a5568;
                }
            """)

            cols_row.addWidget(QLabel("Left column:"))
            cols_row.addWidget(left_cols)
            cols_row.addWidget(QLabel("Right column:"))
            cols_row.addWidget(right_cols)
            layout.addLayout(cols_row)

            # join type selector
            jt_row = QHBoxLayout()
            jt_label = QLabel("Join type:")
            jt_label.setStyleSheet("color:#d0d0d0;")
            jt_row.addWidget(jt_label)
            jt_combo = QComboBox()
            jt_combo.addItems(["INNER", "LEFT", "RIGHT", "FULL OUTER"])
            jt_row.addWidget(jt_combo)
            jt_row.addStretch()
            layout.addLayout(jt_row)

            # preview limit and buttons
            bottom_row = QHBoxLayout()
            preview_limit = QLineEdit()
            preview_limit.setPlaceholderText("Leave blank or 0 to preview all rows")
            preview_limit.setMaximumWidth(140)
            bottom_row.addWidget(preview_limit)
            preview_btn = QPushButton("Preview")
            save_btn = QPushButton("Save File")
            cancel_btn = QPushButton("Cancel")
            bottom_row.addStretch()
            bottom_row.addWidget(preview_btn)
            bottom_row.addWidget(save_btn)
            bottom_row.addWidget(cancel_btn)
            layout.addLayout(bottom_row)

            # Option: Save the join as a dashboard view (store SQL, do not write file)
            save_view_checkbox = self.make_save_checkbox("Save as Dashboard View (store SQL)")
            layout.addWidget(save_view_checkbox)
            def load_columns_for(combo_widget, list_widget):
                list_widget.clear()
                base = combo_widget.currentText()
                if not base:
                    return
                path = os.path.join(self.doc_dir, f"{base}.parquet")
                try:
                    import pyarrow.parquet as pq
                    pf = pq.ParquetFile(path)
                    cols = pf.schema.names
                except Exception:
                    try:
                        df_tmp = pd.read_parquet(path, engine='pyarrow')
                        cols = list(df_tmp.columns)
                    except Exception:
                        cols = []
                for c in cols:
                    list_widget.addItem(QListWidgetItem(c))

            left_combo.currentIndexChanged.connect(lambda _i: load_columns_for(left_combo, left_cols))
            right_combo.currentIndexChanged.connect(lambda _i: load_columns_for(right_combo, right_cols))
            load_columns_for(left_combo, left_cols)
            load_columns_for(right_combo, right_cols)

            def build_and_run(join_save=False):
                left_base = left_combo.currentText()
                right_base = right_combo.currentText()
                if left_base == right_base:
                    MainWindow.show_styled_message_box(self, "Invalid", "Please select two different files to join.", icon=QMessageBox.Icon.Warning)
                    return
                left_col_item = left_cols.currentItem()
                right_col_item = right_cols.currentItem()
                if not left_col_item or not right_col_item:
                    MainWindow.show_styled_message_box(self, "Select Columns", "Please pick join columns on both tables.", icon=QMessageBox.Icon.Warning)
                    return

                left_col = left_col_item.text()
                right_col = right_col_item.text()
                jt = jt_combo.currentText()
                left_path = os.path.join(self.doc_dir, f"{left_base}.parquet").replace('\\', '/')
                right_path = os.path.join(self.doc_dir, f"{right_base}.parquet").replace('\\', '/')

                limit = 0
                try:
                    limit = int(preview_limit.text().strip() or 0)
                except Exception:
                    limit = 0

                join_map = {
                    'INNER': 'INNER JOIN',
                    'LEFT': 'LEFT JOIN',
                    'RIGHT': 'RIGHT JOIN',
                    'FULL OUTER': 'FULL OUTER JOIN'
                }
                join_clause = join_map.get(jt, 'INNER JOIN')

                sql = f"SELECT * FROM read_parquet('{left_path}') AS L {join_clause} read_parquet('{right_path}') AS R ON L.\"{left_col}\" = R.\"{right_col}\""
                if limit > 0:
                    sql_preview = sql + f" LIMIT {limit}"
                else:
                    sql_preview = sql

                try:
                    df = self.conn.execute(sql_preview).fetchdf()
                    self.populate_treeview(df, set_full=True)
                    # If user opted to save as a dashboard view (store SQL), do that here
                    if save_view_checkbox.isChecked():
                        try:
                            # Prompt for name/description using consistent dialog
                            name = self.create_input_popup("Save View", "Enter view name:")
                            if name:
                                desc = self.create_input_popup("Description", "Enter an optional description (leave blank to skip):")
                                view_spec = {
                                    'name': name,
                                    'description': desc or '',
                                    'type': 'sql',
                                    'sql': sql,  # store the join SQL for execution later
                                    'visualization': 'table',
                                    'refresh': {'type': 'on-open'},
                                    'created_from': 'join_tables'
                                }
                                self.add_view(view_spec)
                                MainWindow.show_styled_message_box(self, "Saved", f"Dashboard view '{name}' saved.", icon=QMessageBox.Icon.Information)
                        except Exception as e:
                            MainWindow.show_styled_message_box(self, "Save Error", f"Failed to save dashboard view: {e}", icon=QMessageBox.Icon.Critical)
                        # Ask user where to save the joined parquet (default to ParquetFiles/<left>_<right>_join.parquet)
                        suggested = f"{left_base}_{right_base}_join.parquet"
                        default_path = os.path.join(self.doc_dir, suggested)
                        save_path, _ = QFileDialog.getSaveFileName(self, "Save Join As", default_path, "Parquet Files (*.parquet)")
                        if not save_path:
                            # user cancelled save
                            return
                        if not save_path.lower().endswith('.parquet'):
                            save_path = save_path + '.parquet'
                        save_path = save_path.replace('\\', '/')
                        try:
                            # Use DuckDB to write the join directly to parquet (avoids building a pandas DF)
                            try:
                                self.conn.execute("PRAGMA threads=4;")
                            except Exception:
                                pass
                            copy_sql = f"COPY ({sql}) TO '{save_path}' (FORMAT 'parquet')"
                            self.conn.execute(copy_sql)
                            # Refresh file list (re-scan ParquetFiles folder)
                            try:
                                # If saved inside the ParquetFiles folder, refresh listing from disk
                                self.display_existing_files()
                            except Exception:
                                pass
                            MainWindow.show_styled_message_box(self, "Saved", f"Join saved to {os.path.basename(save_path)}", icon=QMessageBox.Icon.Information)
                        except Exception as e:
                            MainWindow.show_styled_message_box(self, "Save Error", f"Failed to save parquet using DuckDB: {e}", icon=QMessageBox.Icon.Critical)
                except Exception as e:
                    MainWindow.show_styled_message_box(self, "Join Error", f"Failed to run join: {e}", icon=QMessageBox.Icon.Critical)

            preview_btn.clicked.connect(lambda: build_and_run(join_save=False))
            save_btn.clicked.connect(lambda: build_and_run(join_save=True))
            cancel_btn.clicked.connect(dlg.reject)

            dlg.exec()

        except Exception as e:
            MainWindow.show_styled_message_box(self, "Error", f"Unexpected error: {e}", icon=QMessageBox.Icon.Critical)

    def fix_csv_columns(self):
        """Show dialog to fix CSV columns by selecting file and specifying column fixes"""
        try:
            # Import MainWindow here to avoid circular import
            from Simplisql import MainWindow
            
            # Create dialog
            dialog = QDialog(self)
            self.apply_dark_dialog_styling(dialog)
            dialog.setWindowTitle("Fix CSV Columns")
            dialog.setMinimumWidth(500)

            layout = QVBoxLayout(dialog)

            # Header
            header_label = QLabel("Fix CSV Columns")
            header_label.setStyleSheet("color: #00bcd4; font-weight: bold; font-size: 16px;")
            layout.addWidget(header_label)

            # File selection
            file_label = QLabel("Select CSV file:")
            file_label.setStyleSheet("color: #d0d0d0; font-size: 13px; margin-top: 10px;")
            layout.addWidget(file_label)

            file_layout = QHBoxLayout()
            file_path_edit = QLineEdit()
            file_path_edit.setPlaceholderText("Click Browse to select CSV file...")
            file_path_edit.setStyleSheet("""
                QLineEdit {
                    background-color: #3c3f41;
                    color: #ffffff;
                    border: 2px solid #555555;
                    padding: 6px;
                    border-radius: 4px;
                    font-size: 13px;
                }
            """)
            browse_btn = QPushButton("Browse")
            browse_btn.setStyleSheet("""
                QPushButton {
                    background-color: #0d7377;
                    color: white;
                    padding: 6px 12px;
                    border-radius: 4px;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background-color: #14919b;
                }
            """)

            def browse_file():
                file_path, _ = QFileDialog.getOpenFileName(
                    self, "Select CSV File", "", "CSV Files (*.csv);;All Files (*.*)"
                )
                if file_path:
                    file_path_edit.setText(file_path)

            browse_btn.clicked.connect(browse_file)
            file_layout.addWidget(file_path_edit)
            file_layout.addWidget(browse_btn)
            layout.addLayout(file_layout)

            # Fix options
            options_label = QLabel("Column Fix Options:")
            options_label.setStyleSheet("color: #d0d0d0; font-size: 13px; margin-top: 15px;")
            layout.addWidget(options_label)

            # Option 1: Keep first N columns
            keep_layout = QHBoxLayout()
            keep_checkbox = QCheckBox("Keep only first")
            keep_checkbox.setStyleSheet("color: #d0d0d0; font-size: 13px;")
            keep_spin = QSpinBox()
            keep_spin.setMinimum(1)
            keep_spin.setMaximum(1000)
            keep_spin.setValue(22)  # Default from the script
            keep_spin.setStyleSheet("""
                QSpinBox {
                    background-color: #3c3f41;
                    color: #ffffff;
                    border: 2px solid #555555;
                    padding: 4px;
                    border-radius: 4px;
                    font-size: 13px;
                }
            """)
            keep_label = QLabel("columns (when checked: truncate rows > N cols including header, when unchecked: skip rows = N cols)")
            keep_label.setStyleSheet("color: #d0d0d0; font-size: 11px;")
            keep_layout.addWidget(keep_checkbox)
            keep_layout.addWidget(keep_spin)
            keep_layout.addWidget(keep_label)
            keep_layout.addStretch()
            layout.addLayout(keep_layout)

            # Connect checkbox to enable/disable spinbox
            keep_spin.setEnabled(True)  # Always enabled since it's used for both truncate and filter logic
            # keep_checkbox.stateChanged.connect(lambda: keep_spin.setEnabled(keep_checkbox.isChecked()))

            # Buttons
            button_layout = QHBoxLayout()
            ok_btn = QPushButton("Fix CSV")
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

            def fix_csv():
                csv_path = file_path_edit.text().strip()
                if not csv_path:
                    MainWindow.show_styled_message_box(
                        self, "Error", "Please select a CSV file.", icon=QMessageBox.Icon.Critical
                    )
                    return

                if not os.path.exists(csv_path):
                    MainWindow.show_styled_message_box(
                        self, "Error", "Selected file does not exist.", icon=QMessageBox.Icon.Critical
                    )
                    return

                try:
                    # Show progress
                    progress = QProgressDialog("Creating fixed CSV file...", "Cancel", 0, 100, self)
                    progress.setWindowTitle("CSV Fix Progress")
                    progress.setWindowModality(Qt.WindowModality.ApplicationModal)
                    progress.setMinimumDuration(0)
                    progress.setValue(10)
                    self.apply_progress_dialog_styling(progress, "#FF9800")
                    progress.show()
                    QApplication.processEvents()

                    # Create new filename with "_fixed" suffix
                    file_dir = os.path.dirname(csv_path)
                    file_name = os.path.basename(csv_path)
                    name_parts = os.path.splitext(file_name)
                    fixed_filename = f"{name_parts[0]}_fixed{name_parts[1]}"
                    fixed_path = os.path.join(file_dir, fixed_filename)

                    # Read and fix the CSV, write to new file
                    fixed_rows = 0

                    with open(csv_path, "r", newline='', encoding="utf-8") as infile, \
                         open(fixed_path, "w", newline='', encoding="utf-8") as outfile:
                        reader = csv.reader(infile, delimiter=',')
                        writer = csv.writer(outfile, delimiter=',')

                        # Read header
                        try:
                            header = next(reader)
                            if keep_checkbox.isChecked():
                                n_cols = keep_spin.value()
                                if len(header) > n_cols:
                                    header = header[:n_cols]
                            writer.writerow(header)
                        except StopIteration:
                            MainWindow.show_styled_message_box(
                                self, "Error", "CSV file appears to be empty.", icon=QMessageBox.Icon.Critical
                            )
                            progress.close()
                            return

                        progress.setValue(30)

                        # Process rows
                        for i, row in enumerate(reader, start=2):
                            n_cols = keep_spin.value()
                            
                            if keep_checkbox.isChecked():
                                # Truncate only if row has more than N columns
                                if len(row) > n_cols:
                                    row = row[:n_cols]
                                # Keep as-is if row has N or fewer columns
                                writer.writerow(row)
                                fixed_rows += 1
                            else:
                                # Skip rows with exactly N columns, keep others
                                if len(row) != n_cols:
                                    writer.writerow(row)
                                    fixed_rows += 1
                                # Skip rows with exactly N columns

                            # Update progress occasionally
                            if i % 1000 == 0:
                                progress.setValue(min(80, 30 + (i // 100)))

                    progress.setValue(90)

                    progress.setValue(100)
                    progress.close()

                    # Show result
                    msg = f"CSV fixed successfully!\n\nProcessed {fixed_rows} rows."
                    if keep_checkbox.isChecked():
                        msg += f"\nRows with > {keep_spin.value()} columns were truncated to {keep_spin.value()} columns."
                    else:
                        msg += f"\nRows with exactly {keep_spin.value()} columns were skipped."
                    msg += f"\n\nNew file created: {fixed_filename}"

                    MainWindow.show_styled_message_box(
                        self, "Success", msg, icon=QMessageBox.Icon.Information
                    )

                    dialog.accept()

                except Exception as e:
                    if 'progress' in locals():
                        progress.close()
                    MainWindow.show_styled_message_box(
                        self, "Error", f"Failed to fix CSV: {str(e)}", icon=QMessageBox.Icon.Critical
                    )

            ok_btn.clicked.connect(fix_csv)
            cancel_btn.clicked.connect(dialog.reject)

            dialog.exec()

        except Exception as e:
            MainWindow.show_styled_message_box(self, "Error", f"Unexpected error: {e}", icon=QMessageBox.Icon.Critical)