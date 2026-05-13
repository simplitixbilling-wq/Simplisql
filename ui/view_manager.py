"""
View Management Module
======================
This module contains dashboard and view management functionality for SimplSQL.

Extracted methods:
- View persistence: load_views(), save_views(), add_view()
- Dashboard management: show_dashboard()
- View computation: compute_view_df(), _compute_view_df_from_df(), _compute_view_df_with_duckdb()
- Data display: populate_treeview(), Parquet_view_describe()
- File export: save_current_view_to_parquet_default()

These methods handle all dashboard/view operations and data display in the application.
"""

import os
import json
import uuid
import time
import logging
from datetime import datetime
import pandas as pd
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton,
    QLabel, QProgressDialog, QMessageBox, QFileDialog, QApplication,
    QMenu, QInputDialog
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor


logger = logging.getLogger(__name__)


class ViewManager:
    """
    Mixin class containing view and dashboard management methods.
    
    This class requires the following attributes from the parent class:
    - self.views_path: Path to views JSON file
    - self.views: List of dashboard views
    - self.doc_dir: Path to ParquetFiles directory
    - self.conn: DuckDB connection
    - self.current_full_df: Current full dataframe
    - self.results_table: QTableView for results
    - self.transaction_count_label: QLabel for status
    - self.apply_dark_dialog_styling(): Dialog styling method
    - self.apply_progress_dialog_styling(): Progress dialog styling
    - self.show_styled_message_box(): Message box method (via MainWindow)
    """
    
    def load_views(self):
        """Load dashboard views from JSON file"""
        try:
            if os.path.exists(self.views_path):
                with open(self.views_path, 'r') as f:
                    return json.load(f)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning("Failed to load views from %s: %s", self.views_path, e)
        return []

    def save_views(self):
        """Save dashboard views to JSON file"""
        try:
            with open(self.views_path, 'w') as f:
                json.dump(self.views, f, indent=2)
        except (OSError, TypeError, ValueError) as e:
            logger.error("Failed to save views to %s: %s", self.views_path, e)

    def add_view(self, view_spec):
        """Add a new dashboard view"""
        view_spec = dict(view_spec)
        view_spec.setdefault('id', uuid.uuid4().hex)
        now = datetime.utcnow().isoformat() + 'Z'
        view_spec.setdefault('created_iso', now)
        view_spec['updated_iso'] = now
        # ensure self.views exists
        if not hasattr(self, 'views') or self.views is None:
            self.views = []
        self.views.append(view_spec)
        self.save_views()
        return view_spec['id']

    def Parquet_view_describe(self, filename):
        """Describe a Parquet file schema"""
        import duckdb
        try:
            query = f"DESCRIBE SELECT * FROM read_parquet('{self.doc_dir}/{filename}.parquet')"
            query.replace("\\", "/")
            df = duckdb.query(query).to_df()
            self.populate_treeview(df)
            return df
        except (duckdb.Error, OSError, ValueError) as e:
            logger.warning("Failed to describe parquet view for %s: %s", filename, e)
            return None

    def populate_treeview(self, df, set_full=True, skip_large_prompt=False):
        """Populate the results table with a DataFrame"""
        from utils import PandasModel, DataFrameFilterProxy
        
        # Reset model/view state first
        empty_model = PandasModel(pd.DataFrame())
        empty_proxy = DataFrameFilterProxy(self)
        empty_proxy.setSourceModel(empty_model)
        self.results_table.setModel(empty_proxy)

        if df.empty:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.transaction_count_label.setText(f"No Results — Last Run: {now_str}")
            # keep empty model displayed
            return

        # If dataset is large, ask user before loading the full DataFrame
        try:
            total_rows = int(getattr(df, 'shape', (0, 0))[0])
        except (AttributeError, TypeError, ValueError):
            total_rows = 0

        LARGE_THRESHOLD = 100_000
        PREVIEW_N = 1000
        # If the caller passes in a sliced/preview df we still proceed; only prompt when count exceeds threshold
        if not skip_large_prompt and total_rows > LARGE_THRESHOLD:
            # Use a custom dialog so we can apply dark styling and ensure readable buttons
            dlg = QDialog(self)
            dlg.setWindowTitle("Large result set")
            self.apply_dark_dialog_styling(dlg)
            v = QVBoxLayout(dlg)
            label = QLabel(f"Query returned {total_rows:,} rows. Loading all rows may be slow. What do you want to do?")
            label.setWordWrap(True)
            label.setStyleSheet("font-size:14px; color:#d0d0d0;")
            v.addWidget(label)
            btn_row = QHBoxLayout()
            load_btn = QPushButton("Load All")
            preview_btn = QPushButton(f"Preview {PREVIEW_N}")
            cancel_btn = QPushButton("Cancel")
            # Slightly larger buttons for readability
            for b in (load_btn, preview_btn, cancel_btn):
                b.setMinimumHeight(32)
                b.setStyleSheet("background-color:#454545; color:#d0d0d0; padding:6px 12px;")
            btn_row.addStretch()
            btn_row.addWidget(load_btn)
            btn_row.addWidget(preview_btn)
            btn_row.addWidget(cancel_btn)
            v.addLayout(btn_row)

            # Exec and wait for response
            result = None

            def on_load():
                nonlocal result
                result = 'load'
                dlg.accept()

            def on_preview():
                nonlocal result
                result = 'preview'
                dlg.accept()

            def on_cancel():
                nonlocal result
                result = 'cancel'
                dlg.reject()

            load_btn.clicked.connect(on_load)
            preview_btn.clicked.connect(on_preview)
            cancel_btn.clicked.connect(on_cancel)

            if dlg.exec() != QDialog.DialogCode.Accepted:
                return

            if result == 'cancel' or result is None:
                return
            if result == 'preview':
                df = df.head(PREVIEW_N)
                # update status to show it's a preview
                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                self.transaction_count_label.setText(f"Preview ({PREVIEW_N:,} of {total_rows:,} rows) — Last Run: {now_str}")

        # Store the full DF if requested
        if set_full:
            self.current_full_df = df

        # Diagnostic: print the incoming column names (repr) so we can see hidden/control chars
        try:
            print("populate_treeview: incoming df.columns repr:", [repr(c) for c in df.columns])
        except (AttributeError, TypeError):
            pass

        # Sanitize column names to remove trailing control characters that can confuse the UI
        try:
            sanitized_cols = [str(c).strip().rstrip('\r\n\x00') for c in df.columns]
            if sanitized_cols != list(df.columns):
                df = df.copy()
                df.columns = sanitized_cols
                # If we stored full DF earlier, keep it consistent
                if set_full:
                    self.current_full_df = df
        except (AttributeError, TypeError, ValueError):
            pass

        # Create model and proxy
        model = PandasModel(df)
        proxy = DataFrameFilterProxy(self)
        proxy.setSourceModel(model)

        # Apply proxy to the table
        self.results_table.setModel(proxy)

        # Save model/proxy references on self so filtering methods can access them
        try:
            self._model = model
            self._proxy = proxy
            self.last_df = df
        except AttributeError:
            pass

        # Populate the filter column combo with column names for quick selection
        try:
            cols = [str(c) for c in model._df.columns]
            if hasattr(self, 'filter_column_combo'):
                self.filter_column_combo.clear()
                self.filter_column_combo.addItems(cols)
        except (AttributeError, RuntimeError, TypeError):
            pass

        # Force columns to resize
        for i in range(model.columnCount()):
            self.results_table.resizeColumnToContents(i)

        # Update the status label
        try:
            row_count = model.rowCount()
        except (AttributeError, TypeError):
            row_count = 0
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # If not already shown as preview, show full row count
        if 'Preview' not in self.transaction_count_label.text():
            self.transaction_count_label.setText(f"{row_count:,} rows — Last Run: {now_str}")

        # If this was a large dataset, show the manual "Enable Sorting" button so the user
        # can turn on sorting for large tables (may be disabled by default to avoid slowdowns).
        try:
            if hasattr(self, 'enable_sorting_btn'):
                # If the dataset is large, disable sorting by default and show the manual button
                if total_rows > LARGE_THRESHOLD:
                    try:
                        self.results_table.setSortingEnabled(False)
                        self.results_table.horizontalHeader().setSortIndicatorShown(False)
                    except (AttributeError, RuntimeError):
                        pass
                    # Show the enable-sorting button so the user can opt-in
                    self.enable_sorting_btn.setVisible(True)
                else:
                    # For smaller datasets keep sorting enabled and hide manual button
                    try:
                        self.results_table.setSortingEnabled(True)
                        self.results_table.horizontalHeader().setSortIndicatorShown(True)
                    except (AttributeError, RuntimeError):
                        pass
                    self.enable_sorting_btn.setVisible(False)
        except (AttributeError, RuntimeError, TypeError):
            logger.debug("Unable to update sorting controls", exc_info=True)

    def _compute_view_df_from_df(self, view_spec, df_file):
        """Compute dashboard view from DataFrame using pandas"""
        # Given an already-loaded DataFrame, compute aggregation per view_spec
        group_by = view_spec.get('group_by', []) or []
        aggs = view_spec.get('aggregations', [])
        # build agg map: column -> func
        func_map = {}
        for a in aggs:
            col = a.get('column')
            agg = a.get('agg', '').upper()
            if agg == 'SUM':
                func_map[col] = 'sum'
            elif agg == 'AVG':
                func_map[col] = 'mean'
            elif agg == 'MIN':
                func_map[col] = 'min'
            elif agg == 'MAX':
                func_map[col] = 'max'
            elif agg == 'COUNT':
                func_map[col] = 'count'
            elif agg == 'STD':
                func_map[col] = 'std'
            elif agg == 'VAR':
                func_map[col] = 'var'
            else:
                func_map[col] = agg.lower()

        if group_by:
            res = df_file.groupby(group_by).agg(func_map).reset_index()
            # rename columns to include agg prefix
            rename_map = {}
            for a in aggs:
                c = a.get('column')
                rename_map[c] = f"{a.get('agg')}_{c}"
            res = res.rename(columns=rename_map)
            return res
        else:
            # scalar aggregates -> single-row DataFrame
            out = {}
            for a in aggs:
                c = a.get('column')
                agg = a.get('agg', '').upper()
                if agg == 'SUM':
                    val = df_file[c].sum()
                elif agg == 'AVG':
                    val = df_file[c].mean()
                elif agg == 'MIN':
                    val = df_file[c].min()
                elif agg == 'MAX':
                    val = df_file[c].max()
                elif agg == 'COUNT':
                    val = df_file[c].count()
                elif agg == 'STD':
                    val = df_file[c].std()
                elif agg == 'VAR':
                    val = df_file[c].var()
                else:
                    val = None
                out[f"{agg}_{c}"] = [val]
            return pd.DataFrame(out)

    def _compute_view_df_with_duckdb(self, view_spec, parquet_path):
        """Compute dashboard view using DuckDB for better performance"""
        import time
        
    def on_results_header_clicked(self, logicalIndex):
        """Handle clicks on the results table header to provide quick filter options.

        Shows a small menu with: Filter by value..., Clear filter, and Top values submenu.
        """
        try:
            # Determine column name from current proxy/model
            model = getattr(self, '_model', None)
            # If we have a proxy set on the view, try to get source model and column names
            col_name = None
            try:
                proxy = self.results_table.model()
                if proxy is not None and hasattr(proxy, 'sourceModel'):
                    src = proxy.sourceModel()
                    if src and hasattr(src, 'headerData'):
                        col_name = src.headerData(logicalIndex, Qt.Orientation.Horizontal)
            except Exception:
                pass

            if not col_name:
                # fallback: use filter combo current index mapping
                try:
                    col_name = self.filter_column_combo.itemText(logicalIndex)
                except Exception:
                    col_name = None

            if not col_name:
                return

            menu = QMenu(self)
            act_filter = menu.addAction("Filter by value...")
            act_clear = menu.addAction("Clear filter")

            # Top values submenu
            top_menu = menu.addMenu("Top values")
            top_values = []
            try:
                if hasattr(self, 'current_full_df') and self.current_full_df is not None:
                    ser = self.current_full_df.iloc[:, logicalIndex]
                    top_values = list(ser.dropna().value_counts().head(10).index.astype(str))
            except Exception:
                top_values = []

            if top_values:
                for v in top_values:
                    a = top_menu.addAction(v)
                    # closure to capture value
                    a.triggered.connect(lambda checked, val=v: self._apply_header_filter(col_name, val))
            else:
                top_menu.addAction("No values")

            action = menu.exec(QCursor.pos())
            if action == act_filter:
                # ask user for text
                text, ok = QInputDialog.getText(self, f"Filter {col_name}", "Enter filter text (use commas for multiple values):")
                if ok and text is not None:
                    # Set filter controls and apply
                    try:
                        self.filter_column_combo.setCurrentText(col_name)
                    except Exception:
                        pass
                    self.filter_input.setText(text)
                    self.apply_column_filter()
            elif action == act_clear:
                self.clear_column_filter()

        except Exception as e:
            print("Header click filter error:", e)

    def _apply_header_filter(self, col_name, value):
        try:
            # set filter to exact match
            try:
                self.filter_column_combo.setCurrentText(col_name)
            except Exception:
                pass
            self.filter_operator_combo.setCurrentText("equals")
            self.filter_input.setText(value)
            self.apply_column_filter()
        except Exception as e:
            print("Apply header filter error:", e)
        
        group_by = view_spec.get('group_by', []) or []
        aggs = view_spec.get('aggregations', [])
        
        if not aggs:
            raise ValueError('No aggregations specified in view')
        
        # Build aggregation expressions
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
        
        for a in aggs:
            col = a.get('column')
            agg = a.get('agg', '').upper()
            
            if not col:
                continue
                
            sql_func = sql_func_map.get(agg)
            if not sql_func:
                continue
                
            if agg == 'COUNT':
                # COUNT can work on any column
                agg_expressions.append(f'COUNT("{col}") AS "{agg}_{col}"')
            else:
                # Other functions need numeric casting for reliability
                agg_expressions.append(f'{sql_func}(CAST("{col}" AS DOUBLE)) AS "{agg}_{col}"')
        
        if not agg_expressions:
            raise ValueError('No valid aggregations found')
        
        # Build SELECT clause
        select_clause = ", ".join(agg_expressions)
        
        # Build GROUP BY clause if group columns are specified
        if group_by:
            group_clause = ", ".join([f'"{gc}"' for gc in group_by])
            query = f'''
            SELECT {group_clause}, {select_clause}
            FROM read_parquet('{parquet_path}')
            GROUP BY {group_clause}
            ORDER BY {group_clause}
            '''
        else:
            # No grouping - single row result
            query = f'''
            SELECT {select_clause}
            FROM read_parquet('{parquet_path}')
            '''
        
        print(f"\n🔍 Dashboard Aggregation Query:\n{query}")
        
        # Execute DuckDB query
        start_time = time.time()
        print(f"🚀 Dashboard aggregation started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Configure DuckDB for performance
        self.conn.execute("PRAGMA threads=8;")
        self.conn.execute("PRAGMA memory_limit='16GB';")
        
        # Execute the aggregation query
        res = self.conn.execute(query).fetchdf()
        
        end_time = time.time()
        total_time = end_time - start_time
        print(f"✅ Dashboard aggregation completed at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"⏱️ Total execution time: {total_time:.2f} seconds")
        print(f"📊 Result shape: {res.shape}")
        
        return res

    def compute_view_df(self, view_spec):
        """Compute a dashboard view DataFrame based on view specification"""
        import re
        
        # Handle different types of dashboard views
        view_type = view_spec.get('type', 'aggregation')  # default to old aggregation type
        # Support 'sql' view_spec which stores an SQL string to execute
        if view_type == 'sql':
            sql = view_spec.get('sql')
            if not sql:
                raise ValueError('No SQL found in view_spec')
            # Execute SQL using existing connection (ensure parquet table mappings are handled by execute_query machinery)
            try:
                # When SQL references read_parquet explicitly it's fine; otherwise allow read_parquet substitution
                return self.conn.execute(sql).fetchdf()
            except Exception as e:
                # Try to replace simple table names with read_parquet path where needed (reuse earlier logic)
                try:
                    modified = sql
                    table_pattern = r"(?si)\b(FROM|JOIN)\s+(\w+)"
                    def table_replacer(m):
                        keyword = m.group(1)
                        table_name = m.group(2)
                        parquet_file = os.path.join(self.doc_dir, f"{table_name}.parquet").replace('\\', '/')
                        # Quote the table name to handle names starting with numbers or containing special characters
                        quoted_table_name = f'"{table_name}"'
                        return f"{keyword} (SELECT * FROM read_parquet('{parquet_file}')) AS {quoted_table_name}"
                    modified = re.sub(table_pattern, table_replacer, sql)
                    return self.conn.execute(modified).fetchdf()
                except Exception:
                    raise
        
        if view_type == 'advanced_load':
            # Handle advanced load dashboard
            file_name = view_spec.get('file')
            if not file_name:
                raise ValueError('No file specified for advanced load view')
            
            # Build SQL query similar to load_data_advanced
            file_path = os.path.join(self.doc_dir, f"{file_name}.parquet").replace("\\", "/")
            
            # Get selected columns
            selected_cols = view_spec.get('columns', [])
            if selected_cols:
                cols_str = ", ".join([f'"{col}"' for col in selected_cols])
            else:
                cols_str = "*"
            
            # Build query
            query = f"SELECT {cols_str} FROM read_parquet('{file_path}')"
            
            # Add WHERE clause if provided
            where_clause = view_spec.get('where_clause', '').strip()
            if where_clause:
                query += f" WHERE {where_clause}"
            
            # Add LIMIT if preview size specified
            preview_size = view_spec.get('preview_size', '').strip()
            if preview_size and preview_size != "0":
                try:
                    limit_val = int(preview_size)
                    query += f" LIMIT {limit_val}"
                except ValueError:
                    pass  # Ignore invalid preview size
            
            # Execute query using DuckDB
            return self.conn.execute(query).fetchdf()
        # Support pivot-type view_spec (recompute pivot on demand)
        if view_type == 'pivot':
            # pivot view should include 'base_parquet', 'index', 'columns', 'values', 'agg'
            base = view_spec.get('base_parquet') or view_spec.get('file')
            if not base:
                raise ValueError('No base_parquet specified for pivot view')
            path = os.path.join(self.doc_dir, f"{base}.parquet").replace('\\', '/')
            idx = view_spec.get('index', [])
            cols = view_spec.get('columns', [])
            vals = view_spec.get('values', [])
            agg = view_spec.get('agg', 'sum')
            if not idx or not vals:
                raise ValueError('Pivot view must include index and values')
            try:
                cols_needed = set(idx + cols + vals)
                cols_sql = ', '.join([f'"{c}"' for c in cols_needed])
                df = self.conn.execute(f"SELECT {cols_sql} FROM read_parquet('{path}')").fetchdf()
            except Exception:
                df = pd.read_parquet(path)
            pivot = pd.pivot_table(df, index=idx, columns=cols if cols else None, values=vals, aggfunc=agg)
            if isinstance(pivot.columns, pd.MultiIndex):
                pivot.columns = ["_".join([str(x) for x in col]).strip() for col in pivot.columns]
            return pivot.reset_index()
            
        else:
            # Handle legacy aggregation dashboard using DuckDB
            base_parquet = view_spec.get('base_parquet') or view_spec.get('file')
            if not base_parquet:
                raise ValueError('No base_parquet or file found in view_spec')
            parquet_path = os.path.join(self.doc_dir, f"{base_parquet}.parquet").replace('\\', '/')
            return self._compute_view_df_with_duckdb(view_spec, parquet_path)

    def show_dashboard(self):
        """Show dashboard dialog with list of saved views"""
        # Import here to avoid circular imports
        from PyQt6.QtWidgets import QMessageBox as MainWindowMessageBox
        
        if not self.views:
            from Simplisql import MainWindow
            MainWindow.show_styled_message_box(self, "No Views", "No dashboard views saved.", icon=QMessageBox.Icon.Information)
            return

        dlg = QDialog(self)
        self.apply_dark_dialog_styling(dlg)
        dlg.setWindowTitle("Dashboard") 
        layout = QVBoxLayout(dlg)

        list_widget = QListWidget()
        for v in self.views:
            name = v.get('name') or v.get('id')
            desc = v.get('description', '')
            list_widget.addItem(f"{name} {('- ' + desc) if desc else ''}")
        layout.addWidget(list_widget)

        btn_layout = QHBoxLayout()
        open_btn = QPushButton("Open")
        delete_btn = QPushButton("Delete")
        close_btn = QPushButton("Close")
        btn_layout.addWidget(open_btn)
        btn_layout.addWidget(delete_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        def on_open():
            from Simplisql import MainWindow
            idx = list_widget.currentRow()
            if idx < 0:
                MainWindow.show_styled_message_box(self, "Select", "Please select a view.", icon=QMessageBox.Icon.Warning)
                return
            view = self.views[idx]
            
            # Handle different types of dashboard views
            view_type = view.get('type', 'aggregation')  # default to old aggregation type

            # Modern view types that can be computed directly
            if view_type in ('advanced_load', 'sql', 'pivot'):
                progress = QProgressDialog("Loading dashboard...", "Cancel", 0, 100, self)
                progress.setWindowTitle("Dashboard Loading")
                progress.setWindowModality(Qt.WindowModality.ApplicationModal)
                progress.setMinimumDuration(0)
                progress.setValue(0)
                self.apply_progress_dialog_styling(progress, "#673AB7")  # Deep purple for dashboard
                progress.show()
                QApplication.processEvents()

                try:
                    progress.setValue(30)
                    progress.setLabelText("Computing dashboard data...")
                    QApplication.processEvents()

                    df = self.compute_view_df(view)

                    progress.setValue(80)
                    progress.setLabelText("Loading into table...")
                    QApplication.processEvents()

                    progress.close()
                    self.populate_treeview(df, set_full=True, skip_large_prompt=True)
                    dlg.accept()
                except Exception as e:
                    progress.close()
                    MainWindow.show_styled_message_box(self, "Error", f"Failed to load dashboard: {str(e)}", icon=QMessageBox.Icon.Critical)
            else:
                # Handle legacy aggregation dashboard using DuckDB
                progress = QProgressDialog("Loading dashboard...", "Cancel", 0, 100, self)
                progress.setWindowTitle("Dashboard Loading")
                progress.setWindowModality(Qt.WindowModality.ApplicationModal)
                progress.setMinimumDuration(0)
                progress.setValue(0)
                self.apply_progress_dialog_styling(progress, "#673AB7")  # Deep purple for dashboard
                progress.show()
                QApplication.processEvents()

                try:
                    progress.setValue(30)
                    progress.setLabelText("Computing dashboard data...")
                    QApplication.processEvents()

                    df = self.compute_view_df(view)

                    progress.setValue(80)
                    progress.setLabelText("Loading into table...")
                    QApplication.processEvents()

                    progress.close()
                    self.populate_treeview(df, set_full=True, skip_large_prompt=True)
                    dlg.accept()
                except Exception as e:
                    progress.close()
                    MainWindow.show_styled_message_box(self, "Error", f"Failed to load dashboard: {str(e)}", icon=QMessageBox.Icon.Critical)

        def on_delete():
            idx = list_widget.currentRow()
            if idx < 0:
                return
            v = self.views.pop(idx)
            self.save_views()
            list_widget.takeItem(idx)

        open_btn.clicked.connect(on_open)
        delete_btn.clicked.connect(on_delete)
        close_btn.clicked.connect(dlg.reject)

        dlg.exec()

    def _extract_column_name(self, label):
        """Return a simplified column name for display.

        This strips common SQL/cast/function wrappers so UI labels show
        the underlying column name instead of the full expression.
        Examples handled:
        - '"col"' -> col
        - 'TRY_CAST("col" AS DOUBLE)' -> col
        - 'SUM(col) AS SUM_col' -> SUM_col -> col (if possible)
        - 'SUM(TRY_CAST(col AS DOUBLE))' -> col
        - 'col' -> col (unchanged)
        """
        try:
            import re
            if not isinstance(label, str):
                return str(label)

            # 1) Quoted identifier ("col")
            m = re.search(r'"([^"]+)"', label)
            if m:
                return m.group(1)

            # 2) backtick quoted `col`
            m = re.search(r'`([^`]+)`', label)
            if m:
                return m.group(1)

            # 3) pattern like '...name AS alias' -> prefer alias if it's a simple identifier
            m = re.search(r'\bAS\s+"?([A-Za-z0-9_]+)"?$', label, flags=re.IGNORECASE)
            if m:
                return m.group(1)

            # 4) pattern inside CAST/TRY_CAST like 'TRY_CAST(col AS DOUBLE)'
            m = re.search(r'([A-Za-z0-9_]+)\s+AS\s+[A-Za-z0-9_]+', label, flags=re.IGNORECASE)
            if m:
                return m.group(1)

            # 5) nested functions: grab the innermost identifier-like token
            m = re.findall(r'([A-Za-z0-9_]+)', label)
            if m:
                return m[-1]

            return label
        except Exception:
            return label

    def save_current_view_to_parquet_default(self):
        """Save current view/result DataFrame to a Parquet file"""
        from Simplisql import MainWindow
        
        if not hasattr(self, 'current_full_df') or self.current_full_df is None or self.current_full_df.empty:
            MainWindow.show_styled_message_box(self, "No Data", "No data to save. Run a query or load a file first.", icon=QMessageBox.Icon.Warning)
            return

        # Ask user for file name
        suggested = "output.parquet"
        default_path = os.path.join(self.doc_dir, suggested)
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Parquet As",
            default_path,
            "Parquet Files (*.parquet)"
        )
        if not save_path:
            return

        if not save_path.lower().endswith('.parquet'):
            save_path = save_path + '.parquet'

        save_path = save_path.replace('\\', '/')

        # Show progress dialog
        progress = QProgressDialog("Saving to Parquet...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Saving File")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        self.apply_progress_dialog_styling(progress, "#4CAF50")  # Green for save operations
        progress.show()
        QApplication.processEvents()

        try:
            progress.setValue(20)
            progress.setLabelText("Preparing data...")
            QApplication.processEvents()

            # Use DuckDB to write parquet (faster for large datasets)
            try:
                # Register the DataFrame as a temporary table
                self.conn.register("_temp_save", self.current_full_df)
                
                progress.setValue(50)
                progress.setLabelText("Writing Parquet file...")
                QApplication.processEvents()

                # Configure DuckDB for optimal write performance
                self.conn.execute("PRAGMA threads=8;")
                self.conn.execute("PRAGMA memory_limit='16GB';")
                
                # Write to parquet using COPY command
                copy_sql = f"COPY _temp_save TO '{save_path}' (FORMAT 'parquet', COMPRESSION 'SNAPPY')"
                self.conn.execute(copy_sql)
                
                progress.setValue(90)
                progress.setLabelText("Cleaning up...")
                QApplication.processEvents()

                # Unregister temp table
                try:
                    self.conn.unregister("_temp_save")
                except Exception:
                    pass

            except Exception as duckdb_err:
                # Fallback to pandas if DuckDB fails
                print(f"DuckDB save failed: {duckdb_err}, falling back to pandas")
                
                progress.setValue(50)
                progress.setLabelText("Writing Parquet file (pandas)...")
                QApplication.processEvents()

                self.current_full_df.to_parquet(
                    save_path,
                    compression='snappy',
                    index=False
                )

            progress.setValue(100)
            progress.close()

            # If saved inside the ParquetFiles folder, refresh the file list
            try:
                if os.path.dirname(save_path) == self.doc_dir:
                    # Select the newly saved file in the dropdown so its schema is shown
                    sel_name = os.path.splitext(os.path.basename(save_path))[0]
                    try:
                        self.display_existing_files(selected=sel_name)
                    except TypeError:
                        # Older callers may expect the old signature; fallback to no-arg call
                        self.display_existing_files()
            except Exception:
                pass

            MainWindow.show_styled_message_box(
                self,
                "Success",
                f"Saved to:\n{os.path.basename(save_path)}",
                icon=QMessageBox.Icon.Information
            )

        except Exception as e:
            progress.close()
            MainWindow.show_styled_message_box(
                self,
                "Save Error",
                f"Failed to save Parquet file:\n{str(e)}",
                icon=QMessageBox.Icon.Critical
            )

    def show_charts(self):
        """Show charts dialog for data visualization"""
        try:
            # Import required libraries
            import matplotlib
            matplotlib.use('Qt5Agg')  # Use Qt5Agg backend for PyQt6 compatibility
            import matplotlib.pyplot as plt
            from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
            from matplotlib.figure import Figure
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
        except ImportError as e:
            # Non-blocking handling: log and update status label instead of showing a popup
            msg = f"Chart libraries not installed. Please install matplotlib and plotly: {e}"
            try:
                print(msg)
            except Exception:
                pass
            try:
                if hasattr(self, 'transaction_count_label'):
                    self.transaction_count_label.setText("Chart libs missing — see console")
            except Exception:
                pass
            return

        # Create charts dialog
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox, QGroupBox, QScrollArea, QWidget, QCheckBox, QSpinBox, QDoubleSpinBox, QSizePolicy, QStyle, QLineEdit, QListWidget, QListWidgetItem, QDialogButtonBox
        from PyQt6.QtCore import Qt

        # If there's no data available for charts, bail out gracefully
        if (not hasattr(self, 'current_full_df')) or (self.current_full_df is None) or getattr(self.current_full_df, 'empty', True):
            try:
                print("Charts aborted: no data available (current_full_df is missing or empty)")
            except Exception:
                pass
            try:
                if hasattr(self, 'transaction_count_label'):
                    self.transaction_count_label.setText("No data available for charts")
            except Exception:
                pass
            return

        dlg = QDialog(self)
        self.apply_dark_dialog_styling(dlg)
        dlg.setWindowTitle("Data Visualization")
        dlg.resize(1000, 800)
        # Make this dialog a top-level window so maximize/restore behave correctly
        try:
            dlg.setWindowFlag(Qt.WindowType.Window, True)
            dlg.setSizeGripEnabled(True)
            dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        except Exception:
            pass

        # Apply a fixed dark dialog style with teal labels and high-contrast
        # dashed placeholder to match the supplied example image. This ensures
        # labels are visible in Dark mode per the user's request.
        bg = "#2b2b2b"
        text_color = "#00B2B2"   # teal-like label color from example
        input_bg = "#3a3a3a"
        border_color = "#FFFFFF"  # white dashed border for placeholder
        try:
            dlg.setStyleSheet(
                f"QDialog {{ background-color: {bg}; }} "
                f"QWidget {{ background-color: transparent; color: {text_color}; }} "
                f"QGroupBox {{ background-color: transparent; color: {text_color}; border: 1px solid #444; border-radius:4px; margin-top: 18px; }} "
                f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 3px; }} "
                f"QLabel {{ color: {text_color}; }} "
                f"QLineEdit, QComboBox {{ background-color: {input_bg}; color: {text_color}; border: 1px solid #555; }} "
            )
        except Exception:
            # don't block the dialog if styling fails
            pass

        layout = QVBoxLayout(dlg)

        # Header (title + top-right controls)
        header_layout = QHBoxLayout()
        title = QLabel("Data Visualization")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 10px;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        # Top-right maximize button (full expand)
        try:
            top_max_btn = QPushButton()
            top_max_btn.setFixedSize(28, 28)
            # use native maximize icon where available
            try:
                top_max_btn.setIcon(dlg.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarMaxButton))
            except Exception:
                top_max_btn.setText("⤢")
            top_max_btn.setToolTip("Maximize")
            top_max_btn.setFlat(True)
            header_layout.addWidget(top_max_btn)
        except Exception:
            top_max_btn = None

        layout.addLayout(header_layout)

        # Create scroll area for charts
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        # Allow the scroll area to expand when the dialog is resized
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Widget that will hold only the chart display; controls live above and are not scrollable
        chart_display_widget = QWidget()
        # Make the chart display expand so the embedded canvas can grow/shrink
        chart_display_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        chart_display_layout = QVBoxLayout(chart_display_widget)

        # Quick Charts section
        quick_charts_group = QGroupBox("Quick Charts")
        quick_layout = QVBoxLayout(quick_charts_group)

        # Chart type selection
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Chart Type:"))
        chart_type_combo = QComboBox()
        chart_type_combo.addItems(["Bar Chart", "Line Chart", "Pie Chart", "Bar + Line"])
        type_layout.addWidget(chart_type_combo)
        # Inline small Save PNG button (replaces separate Export box)
        save_png_btn = QPushButton("Save PNG")
        save_png_btn.setFixedHeight(28)
        save_png_btn.setStyleSheet("QPushButton { background-color: #FF9800; color: white; padding: 4px 8px; }")
        type_layout.addWidget(save_png_btn)
        
        # Add the chart type selector row into the quick layout so it's visible
        quick_layout.addLayout(type_layout)

        # Column selection for X and Y axes
        axes_layout = QHBoxLayout()

        # X-axis (categories)
        x_layout = QVBoxLayout()
        x_layout.addWidget(QLabel("X-Axis (Categories):"))
        x_column_combo = QComboBox()
        x_column_combo.addItems(self.current_full_df.columns.tolist())
        x_layout.addWidget(x_column_combo)
        axes_layout.addLayout(x_layout)

        # Y-axis (values)
        y_layout = QVBoxLayout()
        y_layout.addWidget(QLabel("Y-Axis (Values):"))
        y_column_combo = QComboBox()
        numeric_columns = self.current_full_df.select_dtypes(include=['number']).columns.tolist()
        y_column_combo.addItems(numeric_columns if numeric_columns else self.current_full_df.columns.tolist())
        y_layout.addWidget(y_column_combo)
        axes_layout.addLayout(y_layout)

        quick_layout.addLayout(axes_layout)

        # Advanced options: create separate widgets for Bar/Line/Pie so only relevant
        # options are visible based on chart type selection.
        # Common/general options (shown for all chart types where applicable)
        general_layout = QHBoxLayout()
        show_labels_chk = QCheckBox("Show Data Labels")
        general_layout.addWidget(show_labels_chk)

        palette_label = QLabel("Palette:")
        palette_combo = QComboBox()
        palette_combo.addItems(["Default", "Viridis", "Pastel1", "Set2"]) 
        general_layout.addWidget(palette_label)
        general_layout.addWidget(palette_combo)

        # Log scale applies to Bar and Line only; we'll show/hide it dynamically
        log_scale_chk = QCheckBox("Log scale (Y)")
        general_layout.addWidget(log_scale_chk)

        # Line-specific options container
        line_widget = QWidget()
        line_layout = QHBoxLayout(line_widget)
        line_layout.setContentsMargins(0, 0, 0, 0)
    # smoothing (rolling window) - existing
        line_layout.addWidget(QLabel("Smoothing (line):"))
        smoothing_spin = QSpinBox()
        smoothing_spin.setRange(0, 100)
        smoothing_spin.setValue(0)
        smoothing_spin.setFixedWidth(70)
        line_layout.addWidget(smoothing_spin)

        # Line width
        line_layout.addWidget(QLabel("Line width:"))
        line_width_spin = QDoubleSpinBox()
        line_width_spin.setRange(0.5, 10.0)
        line_width_spin.setSingleStep(0.5)
        line_width_spin.setValue(1.5)
        line_width_spin.setFixedWidth(90)
        line_layout.addWidget(line_width_spin)

        # Line color
        line_layout.addWidget(QLabel("Color:"))
        line_color_combo = QComboBox()
        line_color_combo.addItems(["Default", "Blue", "Red", "Green", "Orange", "Purple", "Black"]) 
        line_layout.addWidget(line_color_combo)

        # Markers
        marker_chk = QCheckBox("Show markers")
        line_layout.addWidget(marker_chk)
        marker_type_combo = QComboBox()
        marker_type_combo.addItems(["Circle (o)", "Square (s)", "Triangle (^)", "Diamond (D)", "Plus (+)", "None"]) 
        marker_type_combo.setCurrentText("Circle (o)")
        marker_type_combo.setFixedWidth(120)
        line_layout.addWidget(marker_type_combo)
        line_layout.addWidget(QLabel("Size:"))
        marker_size_spin = QSpinBox()
        marker_size_spin.setRange(2, 20)
        marker_size_spin.setValue(6)
        marker_size_spin.setFixedWidth(70)
        line_layout.addWidget(marker_size_spin)

        # Emphasize a specific x value (string matching x labels)
        line_layout.addWidget(QLabel("Emphasize X:"))
        emphasize_le = QLineEdit()
        emphasize_le.setPlaceholderText("enter x value to highlight")
        emphasize_le.setMaximumWidth(180)
        line_layout.addWidget(emphasize_le)

        # Trendline options
        trend_chk = QCheckBox("Add trendline")
        line_layout.addWidget(trend_chk)
        trend_type_combo = QComboBox()
        trend_type_combo.addItems(["Linear", "Moving Average"])
        trend_type_combo.setFixedWidth(130)
        line_layout.addWidget(trend_type_combo)

        # Target/Average line
        target_chk = QCheckBox("Show target")
        line_layout.addWidget(target_chk)
        target_le = QLineEdit()
        target_le.setPlaceholderText("target value")
        target_le.setMaximumWidth(120)
        line_layout.addWidget(target_le)

    # Option to plot the line on a secondary Y axis (useful when combos have different scales)
        sec_y_chk = QCheckBox("Plot line on secondary Y axis")
        sec_y_chk.setChecked(False)
        line_layout.addWidget(sec_y_chk)

        # Dropdown to choose which numeric column to use for the line (when using secondary axis)
        line_y_combo = QComboBox()
        # numeric_columns is defined earlier when building Y-axis combo
        try:
            line_y_combo.addItems(numeric_columns if numeric_columns else [])
        except Exception:
            try:
                line_y_combo.addItems(self.current_full_df.select_dtypes(include=['number']).columns.tolist())
            except Exception:
                pass
        line_y_combo.setMaximumWidth(160)
        line_y_combo.setEnabled(False)
        # default the line column to the same Y column
        try:
            line_y_combo.setCurrentText(y_column_combo.currentText())
        except Exception:
            pass
        line_layout.addWidget(QLabel("Line Y:"))
        line_layout.addWidget(line_y_combo)
        # toggle enabling the dropdown when sec_y_chk is toggled
        try:
            sec_y_chk.toggled.connect(lambda checked: line_y_combo.setEnabled(checked))
        except Exception:
            pass

        # Pie-specific options container
        pie_widget = QWidget()
        pie_layout = QHBoxLayout(pie_widget)
        pie_layout.setContentsMargins(0, 0, 0, 0)
        pie_layout.addWidget(QLabel("Pie min%:"))
        pie_thresh_spin = QDoubleSpinBox()
        pie_thresh_spin.setRange(0.0, 50.0)
        pie_thresh_spin.setSingleStep(0.5)
        pie_thresh_spin.setValue(2.0)
        pie_thresh_spin.setSuffix(" %")
        pie_layout.addWidget(pie_thresh_spin)

        # Pie-specific options
        pie_labels_chk = QCheckBox("Show slice labels (Category + %)")
        pie_labels_chk.setChecked(True)
        pie_layout.addWidget(pie_labels_chk)

        # Rotate angle for first slice
        rotate_grp = QWidget()
        rotate_grp.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        rotate_lay = QHBoxLayout(rotate_grp)
        rotate_lay.setContentsMargins(0, 0, 0, 0)
        rotate_lay.addWidget(QLabel("Rotate°:"))
        pie_rotate_spin = QSpinBox()
        pie_rotate_spin.setRange(0, 360)
        pie_rotate_spin.setValue(90)
        pie_rotate_spin.setFixedWidth(80)
        rotate_lay.addWidget(pie_rotate_spin)
        pie_layout.addWidget(rotate_grp)

        # Explode target (category name). If empty, no explode applied.
        explode_grp = QWidget()
        explode_grp.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        explode_lay = QHBoxLayout(explode_grp)
        explode_lay.setContentsMargins(0, 0, 0, 0)
        explode_lay.addWidget(QLabel("Explode category:"))
        explode_le = QLineEdit()
        explode_le.setPlaceholderText("category name (optional)")
        explode_le.setMaximumWidth(160)
        explode_lay.addWidget(explode_le)
        pie_layout.addWidget(explode_grp)

        # Per-slice color override: target category + color
        color_target_grp = QWidget()
        color_target_grp.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        color_target_lay = QHBoxLayout(color_target_grp)
        color_target_lay.setContentsMargins(0, 0, 0, 0)
        color_target_lay.addWidget(QLabel("Color for:"))
        pie_color_target_le = QLineEdit()
        pie_color_target_le.setPlaceholderText("category (optional)")
        pie_color_target_le.setMaximumWidth(120)
        color_target_lay.addWidget(pie_color_target_le)
        pie_color_combo = QComboBox()
        pie_color_combo.addItems(["Default", "Red", "Orange", "Green", "Blue", "Gray", "Purple"]) 
        pie_color_combo.setFixedWidth(90)
        color_target_lay.addWidget(pie_color_combo)
        pie_layout.addWidget(color_target_grp)

        # Bar-specific options container
        bar_widget = QWidget()
        bar_layout = QHBoxLayout(bar_widget)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        grid_chk = QCheckBox("Show Gridlines")
        grid_chk.setChecked(True)
        # keep grid checkbox separate at the start
        bar_layout.addWidget(grid_chk)

        # group gap width label + spinbox so they stay together
        gap_grp = QWidget()
        gap_grp.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        gap_grp_lay = QHBoxLayout(gap_grp)
        gap_grp_lay.setContentsMargins(0, 0, 0, 0)
        gap_grp_lay.addWidget(QLabel("Gap Width %:"))
        gap_spin = QSpinBox()
        gap_spin.setRange(0, 90)
        gap_spin.setValue(50)
        gap_spin.setFixedWidth(70)
        gap_grp_lay.addWidget(gap_spin)
        bar_layout.addWidget(gap_grp)

        # highlight group (label + spin)
        highlight_grp = QWidget()
        highlight_grp.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        highlight_grp_lay = QHBoxLayout(highlight_grp)
        highlight_grp_lay.setContentsMargins(0, 0, 0, 0)
        highlight_grp_lay.addWidget(QLabel("Highlight top N:"))
        highlight_spin = QSpinBox()
        highlight_spin.setRange(0, 20)
        highlight_spin.setValue(0)
        highlight_spin.setFixedWidth(70)
        highlight_grp_lay.addWidget(highlight_spin)
        bar_layout.addWidget(highlight_grp)

        # highlight color next to the highlight spin
        color_grp = QWidget()
        color_grp.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        color_grp_lay = QHBoxLayout(color_grp)
        color_grp_lay.setContentsMargins(0, 0, 0, 0)
        highlight_color_combo = QComboBox()
        highlight_color_combo.addItems(["Default", "Red", "Orange", "Green", "Blue"]) 
        color_grp_lay.addWidget(highlight_color_combo)
        bar_layout.addWidget(color_grp)

        # Aggregate / Raw toggle (Bar charts only)
        agg_mode_grp = QWidget()
        agg_mode_grp.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        agg_mode_lay = QHBoxLayout(agg_mode_grp)
        agg_mode_lay.setContentsMargins(0, 0, 0, 0)
        agg_mode_lay.addWidget(QLabel("Mode:"))
        agg_mode_combo = QComboBox()
        agg_mode_combo.addItems(["Aggregate (sum)", "Raw"]) 
        agg_mode_combo.setCurrentIndex(0)
        agg_mode_lay.addWidget(agg_mode_combo)
        bar_layout.addWidget(agg_mode_grp)

        # reverse checkbox
        reverse_grp = QWidget()
        reverse_grp.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        reverse_grp_lay = QHBoxLayout(reverse_grp)
        reverse_grp_lay.setContentsMargins(0, 0, 0, 0)
        reverse_chk = QCheckBox("Reverse categories")
        reverse_grp_lay.addWidget(reverse_chk)
        bar_layout.addWidget(reverse_grp)

        # Y axis bounds grouped so min/max/unit stay with their labels
        ymin_grp = QWidget()
        ymin_grp.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        ymin_lay = QHBoxLayout(ymin_grp)
        ymin_lay.setContentsMargins(0, 0, 0, 0)
        ymin_lay.addWidget(QLabel("Y min:"))
        axis_min_le = QLineEdit()
        axis_min_le.setPlaceholderText("min (auto)")
        axis_min_le.setMaximumWidth(80)
        ymin_lay.addWidget(axis_min_le)
        bar_layout.addWidget(ymin_grp)

        ymax_grp = QWidget()
        ymax_grp.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        ymax_lay = QHBoxLayout(ymax_grp)
        ymax_lay.setContentsMargins(0, 0, 0, 0)
        ymax_lay.addWidget(QLabel("max:"))
        axis_max_le = QLineEdit()
        axis_max_le.setPlaceholderText("max (auto)")
        axis_max_le.setMaximumWidth(80)
        ymax_lay.addWidget(axis_max_le)
        bar_layout.addWidget(ymax_grp)

        yunit_grp = QWidget()
        yunit_grp.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        yunit_lay = QHBoxLayout(yunit_grp)
        yunit_lay.setContentsMargins(0, 0, 0, 0)
        yunit_lay.addWidget(QLabel("unit:"))
        axis_unit_le = QLineEdit()
        axis_unit_le.setPlaceholderText("major unit (auto)")
        axis_unit_le.setMaximumWidth(100)
        yunit_lay.addWidget(axis_unit_le)
        bar_layout.addWidget(yunit_grp)

        filter_btn = QPushButton("Filter categories...")
        bar_layout.addWidget(filter_btn)

        # Add general + specific widgets to quick layout. Their visibility will be
        # toggled by _update_adv_visibility() based on chart type selection.
        quick_layout.addLayout(general_layout)
        quick_layout.addWidget(line_widget)
        quick_layout.addWidget(pie_widget)
        quick_layout.addWidget(bar_widget)

        # Generate chart button
        generate_btn = QPushButton("Generate Chart")
        generate_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; padding: 8px 16px; }")
        quick_layout.addWidget(generate_btn)

        # Place the controls (quick_charts_group) above the scrollable chart area so only
        # the chart itself becomes scrollable.
        quick_charts_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(quick_charts_group)

        # Chart title label (fixed above the scrollable chart area) so long titles
        # are always visible and won't be clipped by the canvas.
        chart_title_label = QLabel("")
        chart_title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chart_title_label.setStyleSheet("font-size:14px; font-weight:600; margin:6px 0;")
        layout.addWidget(chart_title_label)

        # Update advanced control visibility based on chart type
        def _update_adv_visibility():
            try:
                ct = chart_type_combo.currentText()
                # Line-specific container (also visible for combo charts)
                line_widget.setVisible(ct in ('Line Chart', 'Bar + Line'))
                # Pie-specific container
                pie_widget.setVisible(ct == 'Pie Chart')
                # Bar-specific container (also visible for combo charts)
                bar_widget.setVisible(ct in ('Bar Chart', 'Bar + Line'))

                # Log scale applies to Bar and Line
                log_scale_chk.setVisible(ct in ('Bar Chart', 'Line Chart'))

                # Show labels applicable for Bar, Pie, Line
                show_labels_chk.setVisible(ct in ('Bar Chart', 'Line Chart', 'Pie Chart'))

                # Palette visible for all chart types (keep available)
                palette_combo.setVisible(True)

            except Exception:
                pass

        chart_type_combo.currentTextChanged.connect(lambda _: _update_adv_visibility())
        # initialize visibility
        _update_adv_visibility()

    # (Trend Analysis removed) - simplified UI with inline export button

    # Removed separate export box; added inline Save PNG button in the chart type row

        # Placeholder for chart display
        self.chart_canvas = None
        chart_placeholder = QLabel("Chart will appear here after generation")
        chart_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Use dialog colors (teal text + white dashed border) so the placeholder
        # is visible in Dark mode and matches the requested design.
        try:
            chart_placeholder.setStyleSheet(f"border: 2px dashed {border_color}; padding: 50px; color: {text_color};")
        except Exception:
            # Fallback to safe hard-coded colors
            chart_placeholder.setStyleSheet("border: 2px dashed #fff; padding: 50px; color: #00B2B2;")
        chart_placeholder.setMinimumHeight(600)
        chart_display_layout.addWidget(chart_placeholder)

        scroll.setWidget(chart_display_widget)
        layout.addWidget(scroll)

        # Dialog buttons
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dlg.reject)
        cancel_btn.setStyleSheet("QPushButton { background-color: #f44336; color: white; padding: 8px 16px; }")
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        close_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; padding: 8px 16px; }")
        
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        # state used by filter dialog
        selected_categories = None

        # Open a small dialog to choose which categories to include
        def open_filter_dialog():
            nonlocal selected_categories
            try:
                col = x_column_combo.currentText()
            except Exception:
                col = None
            dlgf = QDialog(dlg)
            self.apply_dark_dialog_styling(dlgf)
            dlgf.setWindowTitle("Filter categories")
            vlay = QVBoxLayout(dlgf)
            listw = QListWidget()
            listw.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
            # populate with unique values
            try:
                if col and hasattr(self, 'current_full_df') and self.current_full_df is not None:
                    vals = list(self.current_full_df[col].dropna().astype(str).unique())
                else:
                    vals = []
            except Exception:
                vals = []
            for val in vals:
                item = QListWidgetItem(val)
                item.setSelected(True)
                listw.addItem(item)
            vlay.addWidget(listw)
            bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            vlay.addWidget(bb)

            def _ok():
                nonlocal selected_categories
                selected_categories = [it.text() for it in listw.selectedItems()]
                dlgf.accept()

            def _cancel():
                dlgf.reject()

            bb.accepted.connect(_ok)
            bb.rejected.connect(_cancel)
            dlgf.exec()

        filter_btn.clicked.connect(open_filter_dialog)

        # Connect signals
        def generate_chart():
            try:
                # Check if we have data to visualize
                if not hasattr(self, 'current_full_df') or self.current_full_df is None or self.current_full_df.empty:
                    from Simplisql import MainWindow
                    MainWindow.show_styled_message_box(
                        dlg,
                        "No Data",
                        "Please run a query first to generate data for visualization.",
                        icon=QMessageBox.Icon.Warning
                    )
                    return

                chart_type = chart_type_combo.currentText()
                x_col = x_column_combo.currentText()
                y_col = y_column_combo.currentText()

                # Simplify column labels for display (remove CAST/TRY_CAST/SUM/etc)
                x_label = self._extract_column_name(x_col)
                y_label = self._extract_column_name(y_col)

                # Advanced options
                try:
                    show_labels = show_labels_chk.isChecked()
                    log_scale = log_scale_chk.isChecked()
                    palette = palette_combo.currentText()
                    colormap = None if palette == 'Default' else palette
                    # Normalize friendly palette names to matplotlib colormap names
                    try:
                        if colormap:
                            norm_map = {
                                'Viridis': 'viridis',
                                'viridis': 'viridis',
                                'Pastel1': 'Pastel1',
                                'pastel1': 'Pastel1',
                                'Set2': 'Set2',
                                'set2': 'Set2'
                            }
                            colormap = norm_map.get(colormap, colormap)
                    except Exception:
                        pass
                    smoothing = int(smoothing_spin.value())
                    pie_threshold = float(pie_thresh_spin.value()) / 100.0
                except Exception:
                    show_labels = False
                    log_scale = False
                    colormap = None
                    smoothing = 0
                    pie_threshold = 0.02

                if not x_col or not y_col:
                    from Simplisql import MainWindow
                    MainWindow.show_styled_message_box(
                        dlg,
                        "Selection Required",
                        "Please select both X and Y axis columns.",
                        icon=QMessageBox.Icon.Warning
                    )
                    return

                # Create matplotlib figure
                fig = Figure(figsize=(10, 6))
                ax = fig.add_subplot(111)

                if chart_type == "Bar Chart":
                    # Build data series depending on Aggregate/Raw mode
                    try:
                        df_plot = self.current_full_df[[x_col, y_col]].copy()
                        df_plot = df_plot.dropna(subset=[x_col, y_col])
                        try:
                            df_plot[y_col] = pd.to_numeric(df_plot[y_col], errors='coerce')
                        except Exception:
                            pass

                        agg_mode = agg_mode_combo.currentText() if 'agg_mode_combo' in locals() else 'Aggregate (sum)'
                        # Aggregate mode: group by category and sum
                        if agg_mode and agg_mode.startswith('Aggregate'):
                            try:
                                agg = df_plot.groupby(x_col)[y_col].sum()
                            except Exception:
                                agg = pd.Series(dtype=float)
                            # Apply category filter from dialog if set
                            try:
                                if selected_categories:
                                    agg = agg[agg.index.astype(str).isin(selected_categories)]
                            except Exception:
                                pass

                            # Prepare x/y values from aggregated series
                            x_vals = list(agg.index.astype(str))
                            y_vals = list(agg.values)
                        else:
                            # Raw mode: use each row as its own bar
                            try:
                                if selected_categories:
                                    df_plot = df_plot[df_plot[x_col].astype(str).isin(selected_categories)]
                            except Exception:
                                pass
                            x_vals = list(df_plot[x_col].astype(str))
                            try:
                                y_vals = list(df_plot[y_col].astype(float))
                            except Exception:
                                y_vals = list(df_plot[y_col].tolist())
                    except Exception:
                        x_vals = []
                        y_vals = []

                    # Reverse order if requested
                    if reverse_chk.isChecked():
                        x_vals = x_vals[::-1]
                        y_vals = y_vals[::-1]

                    # Determine bar width from gap percentage
                    try:
                        gap = max(0, min(90, int(gap_spin.value())))
                        bar_width = max(0.1, min(0.95, 1.0 - gap / 100.0))
                    except Exception:
                        bar_width = 0.5

                    # Colors
                    colors = None
                    if colormap:
                        try:
                            cmap = plt.get_cmap(colormap)
                            colors = [cmap(i / max(len(y_vals), 1)) for i in range(len(y_vals))]
                        except Exception:
                            colors = None

                    # Highlight top N
                    try:
                        top_n = int(highlight_spin.value())
                    except Exception:
                        top_n = 0
                    if top_n and top_n > 0 and len(y_vals) > 0:
                        # indices of top values
                        idxs = sorted(range(len(y_vals)), key=lambda i: (y_vals[i] if y_vals[i] is not None else -float('inf')), reverse=True)[:top_n]
                        color_map = {'Red': 'red', 'Orange': 'orange', 'Green': 'green', 'Blue': 'blue'}
                        hcol = color_map.get(highlight_color_combo.currentText(), 'red') if highlight_color_combo.currentText() != 'Default' else 'red'
                        if colors is None:
                            colors = ['#4CAF50'] * len(y_vals)
                        for i in range(len(colors)):
                            if i in idxs:
                                colors[i] = hcol

                    # Draw bars
                    try:
                        x_pos = list(range(len(x_vals)))
                        ax.bar(x_pos, y_vals, color=colors, width=bar_width)
                        ax.set_xticks(x_pos)
                        ax.set_xticklabels(x_vals, rotation=45, fontsize=9)
                        ax.set_xlabel(x_label)
                        ax.set_ylabel(y_label)
                        fig.tight_layout()
                    except Exception:
                        # fallback to pandas plotting if something fails
                        try:
                            plot_kwargs = {'kind': 'bar', 'x': x_col, 'y': y_col, 'ax': ax}
                            if colormap:
                                plot_kwargs['colormap'] = colormap
                            self.current_full_df.plot(**plot_kwargs)
                        except Exception:
                            pass

                    # Gridlines
                    try:
                        ax.grid(grid_chk.isChecked(), axis='y', linestyle='--', alpha=0.6)
                    except Exception:
                        pass

                    # Log scale
                    if log_scale:
                        try:
                            ax.set_yscale('log')
                        except Exception:
                            pass

                    # Axis bounds and major unit
                    try:
                        minv = float(axis_min_le.text()) if axis_min_le.text().strip() else None
                    except Exception:
                        minv = None
                    try:
                        maxv = float(axis_max_le.text()) if axis_max_le.text().strip() else None
                    except Exception:
                        maxv = None
                    try:
                        unitv = float(axis_unit_le.text()) if axis_unit_le.text().strip() else None
                    except Exception:
                        unitv = None

                    try:
                        if minv is not None or maxv is not None:
                            cur_low, cur_high = ax.get_ylim()
                            low = minv if minv is not None else cur_low
                            high = maxv if maxv is not None else cur_high
                            ax.set_ylim(bottom=low, top=high)
                    except Exception:
                        pass
                    if unitv:
                        try:
                            import matplotlib.ticker as mticker
                            ax.yaxis.set_major_locator(mticker.MultipleLocator(unitv))
                        except Exception:
                            pass

                    # Data labels for bars
                    if show_labels:
                        for p in ax.patches:
                            try:
                                h = p.get_height()
                                if h is None:
                                    continue
                                if h == 0:
                                    continue
                                xcen = p.get_x() + p.get_width() / 2
                                ax.annotate(f"{h:,}", (xcen, h), xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontsize=9)
                            except Exception:
                                continue
                elif chart_type == "Bar + Line":
                    # Combo chart: bars with an overlaid line (uses bar agg/raw mode)
                    try:
                        df_plot = self.current_full_df[[x_col, y_col]].copy()
                        df_plot = df_plot.dropna(subset=[x_col, y_col])
                        try:
                            df_plot[y_col] = pd.to_numeric(df_plot[y_col], errors='coerce')
                        except Exception:
                            pass

                        agg_mode = agg_mode_combo.currentText() if 'agg_mode_combo' in locals() else 'Aggregate (sum)'
                        if agg_mode and agg_mode.startswith('Aggregate'):
                            try:
                                agg = df_plot.groupby(x_col)[y_col].sum()
                            except Exception:
                                agg = pd.Series(dtype=float)
                            try:
                                if selected_categories:
                                    agg = agg[agg.index.astype(str).isin(selected_categories)]
                            except Exception:
                                pass
                            x_vals = list(agg.index.astype(str))
                            y_vals = list(agg.values)
                        else:
                            try:
                                if selected_categories:
                                    df_plot = df_plot[df_plot[x_col].astype(str).isin(selected_categories)]
                            except Exception:
                                pass
                            x_vals = list(df_plot[x_col].astype(str))
                            try:
                                y_vals = list(pd.to_numeric(df_plot[y_col], errors='coerce'))
                            except Exception:
                                y_vals = list(df_plot[y_col].tolist())
                    except Exception:
                        x_vals = []
                        y_vals = []

                    # Reverse if requested
                    if reverse_chk.isChecked():
                        x_vals = x_vals[::-1]
                        y_vals = y_vals[::-1]

                    # Bar width from gap
                    try:
                        gap = max(0, min(90, int(gap_spin.value())))
                        bar_width = max(0.1, min(0.95, 1.0 - gap / 100.0))
                    except Exception:
                        bar_width = 0.5

                    # Colors
                    colors = None
                    if colormap:
                        try:
                            cmap = plt.get_cmap(colormap)
                            colors = [cmap(i / max(len(y_vals), 1)) for i in range(len(y_vals))]
                        except Exception:
                            colors = None

                    # Highlight top N
                    try:
                        top_n = int(highlight_spin.value())
                    except Exception:
                        top_n = 0
                    if top_n and top_n > 0 and len(y_vals) > 0:
                        idxs = sorted(range(len(y_vals)), key=lambda i: (y_vals[i] if y_vals[i] is not None else -float('inf')), reverse=True)[:top_n]
                        color_map = {'Red': 'red', 'Orange': 'orange', 'Green': 'green', 'Blue': 'blue'}
                        hcol = color_map.get(highlight_color_combo.currentText(), 'red') if highlight_color_combo.currentText() != 'Default' else 'red'
                        if colors is None:
                            colors = ['#4CAF50'] * len(y_vals)
                        for i in range(len(colors)):
                            if i in idxs:
                                colors[i] = hcol

                    # Draw bars
                    try:
                        x_pos = list(range(len(x_vals)))
                        ax.bar(x_pos, y_vals, color=colors, width=bar_width)
                        ax.set_xticks(x_pos)
                        ax.set_xticklabels(x_vals, rotation=45, fontsize=9)
                        ax.set_xlabel(x_label)
                        ax.set_ylabel(y_label)
                        fig.tight_layout()
                    except Exception:
                        try:
                            plot_kwargs = {'kind': 'bar', 'x': x_col, 'y': y_col, 'ax': ax}
                            if colormap:
                                plot_kwargs['colormap'] = colormap
                            self.current_full_df.plot(**plot_kwargs)
                        except Exception:
                            pass

                    # Now overlay the line using line controls
                    try:
                        # prepare line y-values (apply smoothing if requested)
                        # Allow choosing a different Y column for the line when secondary Y is enabled
                        try:
                            chosen_line_col = y_col
                            if 'sec_y_chk' in locals() and sec_y_chk.isChecked():
                                try:
                                    sel = line_y_combo.currentText()
                                    if sel:
                                        chosen_line_col = sel
                                except Exception:
                                    chosen_line_col = y_col

                            # compute line_y aligned to x_vals
                            if chosen_line_col == y_col:
                                line_y = list(y_vals)
                            else:
                                # different column selected for the line
                                if agg_mode and agg_mode.startswith('Aggregate'):
                                    try:
                                        line_series = self.current_full_df.groupby(x_col)[chosen_line_col].sum()
                                        # align to x_vals (which may come from agg.index)
                                        line_y = [float(line_series.get(lbl, 0)) for lbl in x_vals]
                                    except Exception:
                                        line_y = [0.0] * len(x_vals)
                                else:
                                    # Raw mode: attempt to use the same ordered rows used for bars if available
                                    try:
                                        if 'df_plot' in locals():
                                            line_y = list(pd.to_numeric(df_plot[chosen_line_col], errors='coerce'))
                                        else:
                                            df_line = self.current_full_df[[x_col, chosen_line_col]].copy()
                                            df_line = df_line.dropna(subset=[x_col, chosen_line_col])
                                            if selected_categories:
                                                df_line = df_line[df_line[x_col].astype(str).isin(selected_categories)]
                                            line_y = list(pd.to_numeric(df_line[chosen_line_col], errors='coerce'))
                                    except Exception:
                                        # fallback to zeros matching length
                                        line_y = [0.0] * len(x_vals)

                        except Exception:
                            line_y = list(y_vals)

                        # apply smoothing if requested
                        if smoothing and int(smoothing) > 0:
                            try:
                                import numpy as _np
                                ser = pd.Series(line_y)
                                line_y = ser.rolling(window=int(smoothing), min_periods=1).mean().tolist()
                            except Exception:
                                pass

                        # line style
                        try:
                            lw = float(line_width_spin.value())
                        except Exception:
                            lw = 1.5
                        try:
                            chosen_color = line_color_combo.currentText()
                            color_map2 = {'Blue':'blue','Red':'red','Green':'green','Orange':'orange','Purple':'purple','Black':'black'}
                            line_color = color_map2.get(chosen_color, None)
                            if chosen_color == 'Default':
                                line_color = None
                        except Exception:
                            line_color = None
                        try:
                            show_markers = bool(marker_chk.isChecked())
                        except Exception:
                            show_markers = False
                        try:
                            marker_text = marker_type_combo.currentText()
                            marker_map = {'Circle (o)': 'o', 'Square (s)': 's', 'Triangle (^)': '^', 'Diamond (D)': 'D', 'Plus (+)': '+', 'None': None}
                            marker_sym = marker_map.get(marker_text, 'o')
                        except Exception:
                            marker_sym = 'o'
                        try:
                            msize = int(marker_size_spin.value())
                        except Exception:
                            msize = 6

                        plot_marker = marker_sym if show_markers and marker_sym is not None else None
                        # If user requests a secondary Y axis for the line, create a twin axis
                        try:
                            if 'sec_y_chk' in locals() and sec_y_chk.isChecked():
                                ax2 = ax.twinx()
                                try:
                                    ax2.plot(x_pos, line_y, color=line_color or 'black', linewidth=lw, marker=plot_marker, markersize=msize, zorder=5)
                                    ax2.set_ylabel(f"{y_label} (line)")
                                except Exception:
                                    pass
                            else:
                                ax.plot(x_pos, line_y, color=line_color or 'black', linewidth=lw, marker=plot_marker, markersize=msize, zorder=5)
                        except Exception:
                            # fallback to plotting on primary axis
                            try:
                                ax.plot(x_pos, line_y, color=line_color or 'black', linewidth=lw, marker=plot_marker, markersize=msize, zorder=5)
                            except Exception:
                                pass
                    except Exception:
                        pass

                    # Grid and axis handling
                    try:
                        ax.grid(grid_chk.isChecked(), axis='y', linestyle='--', alpha=0.6)
                    except Exception:
                        pass
                    if log_scale:
                        try:
                            ax.set_yscale('log')
                        except Exception:
                            pass
                    try:
                        minv = float(axis_min_le.text()) if axis_min_le.text().strip() else None
                    except Exception:
                        minv = None
                    try:
                        maxv = float(axis_max_le.text()) if axis_max_le.text().strip() else None
                    except Exception:
                        maxv = None
                    try:
                        unitv = float(axis_unit_le.text()) if axis_unit_le.text().strip() else None
                    except Exception:
                        unitv = None
                    try:
                        if minv is not None or maxv is not None:
                            cur_low, cur_high = ax.get_ylim()
                            low = minv if minv is not None else cur_low
                            high = maxv if maxv is not None else cur_high
                            ax.set_ylim(bottom=low, top=high)
                    except Exception:
                        pass
                    if unitv:
                        try:
                            import matplotlib.ticker as mticker
                            ax.yaxis.set_major_locator(mticker.MultipleLocator(unitv))
                        except Exception:
                            pass

                    # Data labels for bars
                    if show_labels:
                        for p in ax.patches:
                            try:
                                h = p.get_height()
                                if h is None:
                                    continue
                                if h == 0:
                                    continue
                                xcen = p.get_x() + p.get_width() / 2
                                ax.annotate(f"{h:,}", (xcen, h), xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontsize=9)
                            except Exception:
                                continue
                elif chart_type == "Line Chart":
                    # Prepare x/y
                    try:
                        x_vals = list(self.current_full_df[x_col].astype(str))
                        y_series = self.current_full_df[y_col]
                        y_vals = list(pd.to_numeric(y_series, errors='coerce'))
                    except Exception:
                        x_vals = []
                        y_vals = []

                    # Read line controls
                    try:
                        lw = float(line_width_spin.value())
                    except Exception:
                        lw = 1.5
                    try:
                        chosen_color = line_color_combo.currentText()
                        color_map = {'Blue':'blue','Red':'red','Green':'green','Orange':'orange','Purple':'purple','Black':'black'}
                        line_color = color_map.get(chosen_color, None)
                        if chosen_color == 'Default':
                            line_color = None
                    except Exception:
                        line_color = None
                    try:
                        show_markers = bool(marker_chk.isChecked())
                    except Exception:
                        show_markers = False
                    try:
                        marker_text = marker_type_combo.currentText()
                        marker_map = {'Circle (o)': 'o', 'Square (s)': 's', 'Triangle (^)': '^', 'Diamond (D)': 'D', 'Plus (+)': '+', 'None': None}
                        marker_sym = marker_map.get(marker_text, 'o')
                    except Exception:
                        marker_sym = 'o'
                    try:
                        marker_size = int(marker_size_spin.value())
                    except Exception:
                        marker_size = 6
                    emphasize_x = (emphasize_le.text().strip() if hasattr(self, 'apply_dark_dialog_styling') else '')
                    trend_on = bool(trend_chk.isChecked())
                    trend_type = trend_type_combo.currentText() if hasattr(self, 'apply_dark_dialog_styling') else 'Linear'
                    target_on = bool(target_chk.isChecked())
                    try:
                        target_val = float(target_le.text()) if target_le.text().strip() else None
                    except Exception:
                        target_val = None

                    # Plot main line
                    try:
                        plot_marker = marker_sym if show_markers and marker_sym is not None else None
                        ax.plot(x_vals, y_vals, linewidth=lw, color=line_color, marker=plot_marker, markersize=marker_size, label='Series')
                    except Exception:
                        try:
                            plot_kwargs = {'kind': 'line', 'x': x_col, 'y': y_col, 'ax': ax}
                            if colormap:
                                plot_kwargs['colormap'] = colormap
                            self.current_full_df.plot(**plot_kwargs)
                        except Exception:
                            pass

                    # Smoothing (show smoothed line using rolling mean)
                    try:
                        if smoothing and smoothing > 1 and len(y_vals) > 0:
                            sm = pd.Series(y_vals).rolling(window=smoothing, min_periods=1).mean()
                            ax.plot(x_vals, sm, linestyle='--', linewidth=max(0.8, lw-0.5), color=line_color, label=f'Smoothed ({smoothing})')
                            ax.legend()
                    except Exception:
                        pass

                    # Trendline
                    if trend_on and len(y_vals) > 1:
                        try:
                            import numpy as np
                            xi = np.arange(len(y_vals))
                            yi = np.array([float(v) if v is not None else np.nan for v in y_vals], dtype=float)
                            mask = ~np.isnan(yi)
                            if mask.sum() > 1:
                                if trend_type == 'Linear':
                                    coef = np.polyfit(xi[mask], yi[mask], 1)
                                    fit = np.poly1d(coef)(xi)
                                    ax.plot(x_vals, fit, linestyle=':', linewidth=max(1.0, lw-0.5), color='black', label='Trend')
                                else:
                                    # Moving average trend uses smoothing window
                                    tw = max(1, int(smoothing) if smoothing and smoothing > 0 else 3)
                                    mv = pd.Series(yi).rolling(window=tw, min_periods=1).mean()
                                    ax.plot(x_vals, mv, linestyle=':', linewidth=max(1.0, lw-0.5), color='gray', label='Trend (MA)')
                                try:
                                    ax.legend()
                                except Exception:
                                    pass
                        except Exception:
                            pass

                    # Target / average line
                    if target_on and target_val is not None:
                        try:
                            ax.axhline(target_val, color='red', linestyle='--', linewidth=1.25, label='Target')
                            try:
                                ax.legend()
                            except Exception:
                                pass
                        except Exception:
                            pass

                    # Emphasize a specific X value (draw a larger marker)
                    if emphasize_x:
                        try:
                            # find first matching index
                            idxs = [i for i, xv in enumerate(x_vals) if str(xv) == emphasize_x]
                            if idxs:
                                for ii in idxs:
                                    try:
                                        ax.scatter(ii, y_vals[ii], s=max(40, marker_size*8), c='gold', edgecolors='black', zorder=5)
                                    except Exception:
                                        pass
                                # if x-axis uses string labels, keep them
                                ax.set_xticks(list(range(len(x_vals))))
                                ax.set_xticklabels(x_vals, rotation=45, fontsize=9)
                        except Exception:
                            pass

                    ax.set_xlabel(x_label)
                    ax.set_ylabel(y_label)
                    if log_scale:
                        try:
                            ax.set_yscale('log')
                        except Exception:
                            pass
                elif chart_type == "Pie Chart":
                    # For pie chart, we need aggregated data (sum per category)
                    if self.current_full_df[y_col].dtype in ['int64', 'float64']:
                        pie_data = self.current_full_df.groupby(x_col)[y_col].sum()
                        # Group small slices into 'Other' for readability using configured threshold
                        threshold = pie_threshold if pie_threshold is not None else 0.02
                        total = pie_data.sum()
                        mask = pie_data / total < threshold
                        if mask.any():
                            pie_data_grouped = pie_data[~mask].copy()
                            pie_data_grouped['Other'] = pie_data[mask].sum()
                            pie_data = pie_data_grouped

                        labels_list = list(pie_data.index)

                        # Colors from palette if requested
                        pie_colors = None
                        try:
                            if colormap:
                                cmap = plt.get_cmap(colormap)
                                pie_colors = [cmap(i / max(len(pie_data), 1)) for i in range(len(pie_data))]
                        except Exception:
                            pie_colors = None

                        # Per-slice color override (if user specified a target category and color)
                        try:
                            target_cat = pie_color_target_le.text().strip() if 'pie_color_target_le' in locals() or 'pie_color_target_le' in globals() else ''
                        except Exception:
                            target_cat = ''
                        try:
                            target_color = pie_color_combo.currentText() if 'pie_color_combo' in locals() or 'pie_color_combo' in globals() else 'Default'
                        except Exception:
                            target_color = 'Default'

                        # Normalize target color to matplotlib-friendly name
                        color_map_override = None
                        if target_color and target_color != 'Default':
                            color_map_override = target_color.lower()
                            # quick name tweaks
                            if color_map_override == 'gray':
                                color_map_override = 'grey'

                        # Build colors list
                        try:
                            if pie_colors is None:
                                # fallback palette
                                cmap = plt.get_cmap('tab20')
                                pie_colors = [cmap(i / max(len(pie_data), 1)) for i in range(len(pie_data))]
                            # apply override for target category
                            if color_map_override and target_cat:
                                new_colors = []
                                for lbl, col in zip(labels_list, pie_colors):
                                    if str(lbl) == target_cat:
                                        try:
                                            new_colors.append(color_map_override)
                                        except Exception:
                                            new_colors.append(col)
                                    else:
                                        new_colors.append(col)
                                pie_colors = new_colors
                        except Exception:
                            pass

                        # Explode handling: small offset for the specified category
                        explode = [0.0] * len(pie_data)
                        try:
                            explode_target = explode_le.text().strip() if 'explode_le' in locals() or 'explode_le' in globals() else ''
                            if explode_target:
                                for i, lbl in enumerate(labels_list):
                                    if str(lbl) == explode_target:
                                        explode[i] = 0.12
                                        break
                        except Exception:
                            pass

                        # Rotation/starting angle
                        try:
                            start_angle = int(pie_rotate_spin.value()) if 'pie_rotate_spin' in locals() or 'pie_rotate_spin' in globals() else 90
                        except Exception:
                            start_angle = 90

                        total = pie_data.sum()
                        # Build autopct functions that can include the category label inside the slice
                        def make_autopct_with_labels(labels):
                            def my_autopct(pct):
                                try:
                                    val = int(round(pct * total / 100.0))
                                except Exception:
                                    val = 0
                                # use an incrementing index captured on the function
                                label = labels[my_autopct.idx] if my_autopct.idx < len(labels) else ''
                                my_autopct.idx += 1
                                return f"{label}\n{pct:.1f}%"
                            my_autopct.idx = 0
                            return my_autopct

                        def make_autopct_simple():
                            def my_autopct(pct):
                                return f"{pct:.1f}%"
                            return my_autopct

                        try:
                            if pie_labels_chk.isChecked():
                                labels_arg = None
                                autopct = make_autopct_with_labels(labels_list)
                            else:
                                labels_arg = labels_list
                                autopct = make_autopct_simple()
                        except Exception:
                            labels_arg = labels_list
                            autopct = make_autopct_simple()

                        wedges, texts, autotexts = ax.pie(
                            pie_data,
                            labels=labels_arg,
                            autopct=autopct,
                            textprops={'fontsize': 10},
                            startangle=start_angle,
                            colors=pie_colors,
                            explode=explode
                        )

                        # Use legend to show category names if labels are not shown on slices
                        try:
                            ax.legend(wedges, labels_list, title=x_label, loc="center left", bbox_to_anchor=(1, 0, 0.5, 1), fontsize=9)
                        except Exception:
                            pass

                        for autotext in autotexts:
                            try:
                                autotext.set_fontsize(9)
                            except Exception:
                                pass
                        ax.set_ylabel("")
                        ax.set_xlabel("")
                    else:
                        # Non-blocking: report invalid data via console and status label
                        try:
                            print("Pie charts require numeric Y-axis data.")
                        except Exception:
                            pass
                        try:
                            if hasattr(self, 'transaction_count_label'):
                                self.transaction_count_label.setText("Pie charts require numeric Y-axis data")
                        except Exception:
                            pass
                        return

                # Set the fixed title label above the chart (prevents clipping)
                try:
                    chart_title_label.setText(f"{chart_type}: {y_label} by {x_label}")
                except Exception:
                    try:
                        ax.set_title(f"{chart_type}: {y_label} by {x_label}")
                    except Exception:
                        pass

                # Remove old canvas if exists
                if self.chart_canvas:
                    chart_display_layout.removeWidget(self.chart_canvas)
                    self.chart_canvas.deleteLater()

                # Create new canvas and make it request the pixel size of the figure so
                # the outer QScrollArea will show scrollbars when the figure is larger
                # than the dialog (prevents titles/labels from being cut off).
                self.chart_canvas = FigureCanvas(fig)
                try:
                    # compute pixel size from figure inches * dpi
                    w_px = int(fig.get_figwidth() * fig.dpi)
                    h_px = int(fig.get_figheight() * fig.dpi)
                    # add a little padding for labels/title (increase to avoid clipping)
                    h_px += 140
                    self.chart_canvas.setMinimumSize(w_px, h_px)
                    self.chart_canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                except Exception:
                    pass
                try:
                    # ensure the canvas renders and layout is applied
                    self.chart_canvas.draw_idle()
                except Exception:
                    pass
                chart_display_layout.removeWidget(chart_placeholder)
                chart_display_layout.addWidget(self.chart_canvas)
                chart_placeholder.hide()

            except Exception as e:
                # Log error and update status label instead of showing modal dialog
                try:
                    print(f"Failed to generate chart: {e}")
                except Exception:
                    pass
                try:
                    if hasattr(self, 'transaction_count_label'):
                        self.transaction_count_label.setText("Chart generation failed — see console")
                except Exception:
                    pass
                return

        # Trend analysis removed per UI simplification

        def export_chart_png():
            if not self.chart_canvas:
                try:
                    print("Export requested but no chart has been generated yet.")
                except Exception:
                    pass
                try:
                    if hasattr(self, 'transaction_count_label'):
                        self.transaction_count_label.setText("No chart to export — generate chart first")
                except Exception:
                    pass
                return

            try:
                from PyQt6.QtWidgets import QFileDialog
                file_path, _ = QFileDialog.getSaveFileName(
                    dlg,
                    "Save Chart as PNG",
                    "",
                    "PNG Files (*.png)"
                )

                if file_path:
                    self.chart_canvas.figure.savefig(file_path, format='png', dpi=300, bbox_inches='tight')
                    from Simplisql import MainWindow
                    MainWindow.show_styled_message_box(
                        dlg,
                        "Export Successful",
                        f"Chart saved as PNG:\n{file_path}",
                        icon=QMessageBox.Icon.Information
                    )
            except Exception as e:
                try:
                    print(f"Failed to export PNG: {e}")
                except Exception:
                    pass
                try:
                    if hasattr(self, 'transaction_count_label'):
                        self.transaction_count_label.setText("Export failed — see console")
                except Exception:
                    pass

        # SVG export removed; PNG-only inline export available

        def safe_generate():
            try:
                generate_chart()
            except Exception as e:
                # Non-blocking error handling: log and update status label
                try:
                    print(f"An error occurred while generating the chart: {e}")
                except Exception:
                    pass
                try:
                    if hasattr(self, 'transaction_count_label'):
                        self.transaction_count_label.setText("Chart generation error — see console")
                except Exception:
                    pass

        generate_btn.clicked.connect(safe_generate)
        save_png_btn.clicked.connect(export_chart_png)

        # Wire maximize toggle behavior and honor 'Open maximized' option
        try:
            def _set_maximized_state(maxed: bool):
                try:
                    if maxed:
                        # Use full-screen to ensure the dialog expands to cover the entire screen
                        try:
                            dlg.showFullScreen()
                        except Exception:
                            dlg.showMaximized()
                        if top_max_btn:
                            try:
                                top_max_btn.setIcon(dlg.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarNormalButton))
                            except Exception:
                                top_max_btn.setText("⤡")
                            top_max_btn.setToolTip("Restore")
                    else:
                        dlg.showNormal()
                        if top_max_btn:
                            try:
                                top_max_btn.setIcon(dlg.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarMaxButton))
                            except Exception:
                                top_max_btn.setText("⤢")
                            top_max_btn.setToolTip("Maximize")
                except Exception:
                    pass

            def _toggle_maximize():
                try:
                    is_max = bool(dlg.windowState() & Qt.WindowState.WindowMaximized)
                    _set_maximized_state(not is_max)
                except Exception:
                    # Fallback using isMaximized if windowState not available
                    try:
                        if dlg.isMaximized():
                            _set_maximized_state(False)
                        else:
                            _set_maximized_state(True)
                    except Exception:
                        pass

            # inline maximize button removed; wire only the header button
            # Also wire the top-right header maximize button if present
            try:
                if top_max_btn is not None:
                    top_max_btn.clicked.connect(_toggle_maximize)
            except Exception:
                pass

            # If user requested opening maximized, apply before exec
            if open_max_chk.isChecked():
                _set_maximized_state(True)
            else:
                # ensure default tooltip text for header button
                if top_max_btn is not None:
                    top_max_btn.setToolTip("Maximize")

        except Exception:
            pass

        dlg.exec()
