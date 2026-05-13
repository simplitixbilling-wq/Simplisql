"""
Python Execution Manager
========================
Provides Python notepad execution and validation for SimpliSQL Milestone 1.
DS/ML library bundling added in Milestone 3.
"""

import io
import os
import traceback
from contextlib import redirect_stderr, redirect_stdout
from typing import Generator

import duckdb
import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QProgressDialog, QMessageBox


# ---------------------------------------------------------------------------
# Milestone 3 – DS/ML library registry
# ---------------------------------------------------------------------------
# Each entry: (import_name, alias, friendly_label, pip_name)
_DS_LIBRARIES = [
    ("numpy",            "np",       "NumPy",           "numpy"),
    ("matplotlib",       "plt",      "Matplotlib",      "matplotlib"),       # injected as plt (pyplot)
    ("seaborn",          "sns",      "Seaborn",         "seaborn"),
    ("plotly.express",   "px",       "Plotly Express",  "plotly"),
    ("sklearn",          "sklearn",  "Scikit-learn",    "scikit-learn"),
    ("scipy",            "scipy",    "SciPy",           "scipy"),
    ("statsmodels",      "sm",       "Statsmodels",     "statsmodels"),
    ("xgboost",          "xgb",      "XGBoost",         "xgboost"),
    ("lightgbm",         "lgb",      "LightGBM",        "lightgbm"),
    ("catboost",         "cb",       "CatBoost",        "catboost"),
    ("shap",             "shap",     "SHAP",            "shap"),
    ("joblib",           "joblib",   "Joblib",          "joblib"),
]

# Alias overrides: matplotlib is injected as pyplot under "plt"
_ALIAS_OVERRIDES = {
    "matplotlib": ("matplotlib.pyplot", "plt"),
}


def get_ds_library_status() -> list[dict]:
    """
    Probe which DS/ML libraries are importable.

    Returns a list of dicts:
        {"import_name": str, "alias": str, "label": str,
         "pip_name": str, "available": bool, "version": str}
    """
    import importlib
    results = []
    for import_name, alias, label, pip_name in _DS_LIBRARIES:
        real_import = _ALIAS_OVERRIDES.get(import_name, (import_name,))[0]
        try:
            mod = importlib.import_module(real_import)
            version = getattr(mod, "__version__", "?")
        except ImportError:
            mod = None
            version = ""
        results.append({
            "import_name": import_name,
            "alias": alias,
            "label": label,
            "pip_name": pip_name,
            "available": mod is not None,
            "version": version,
        })
    return results


class PythonExecutionManager:
    """Mixin class that adds Python script validation and execution support."""

    PYTHON_DF_SAFE_LIMIT = 1_000_000

    def _get_table_parquet_path(self, table_name: str) -> str:
        """Resolve parquet path for a logical table name."""
        table_name = (table_name or "").strip()
        if not table_name:
            raise ValueError("table_name cannot be empty")

        doc_dir = getattr(self, "doc_dir", "")
        parquet_path = os.path.join(doc_dir, f"{table_name}.parquet").replace("\\", "/")
        if not os.path.exists(parquet_path):
            raise FileNotFoundError(f"Table '{table_name}' not found at {parquet_path}")
        return parquet_path

    def _warn_large_df_conversion(self, row_count: int, source_name: str = "result"):
        """Warn user when materializing very large datasets to DataFrame."""
        from Simplisql import MainWindow

        if row_count > self.PYTHON_DF_SAFE_LIMIT:
            MainWindow.show_styled_message_box(
                self,
                "Large Data Warning",
                (
                    f"Converting {row_count:,} rows from {source_name} to a pandas DataFrame can be slow and memory-heavy.\n\n"
                    "Tip: Keep heavy transformations in DuckDB (relation/sql helpers) and convert only the final subset."
                ),
                icon=QMessageBox.Icon.Warning,
            )

    def _relation_to_df(self, relation, limit: int | None = None, source_name: str = "result"):
        """Convert a DuckDB relation to DataFrame with optional LIMIT and size guardrail."""
        rel = relation.limit(limit) if isinstance(limit, int) and limit > 0 else relation
        try:
            row_count = int(rel.count("*").fetchone()[0])
        except Exception:
            row_count = -1
        if row_count > 0:
            self._warn_large_df_conversion(row_count, source_name=source_name)
        return rel.df()

    def _query_to_df_chunks(self, query: str, chunk_size: int = 100_000) -> Generator[pd.DataFrame, None, None]:
        """Yield query results as DataFrame chunks to avoid large one-shot materialization."""
        sql = (query or "").strip().rstrip(";")
        if not sql:
            raise ValueError("query cannot be empty")
        if chunk_size <= 0:
            raise ValueError("chunk_size must be > 0")

        offset = 0
        while True:
            batch_sql = f"SELECT * FROM ({sql}) q LIMIT {chunk_size} OFFSET {offset}"
            chunk_df = self.conn.execute(batch_sql).fetchdf()
            if chunk_df.empty:
                break
            yield chunk_df
            if len(chunk_df) < chunk_size:
                break
            offset += chunk_size

    def _register_tables_as_views(self):
        """Register all uploaded parquet tables as DuckDB views.

        After this, plain table names work in sql() just like in the SQL notepad:
            sql("SELECT * FROM my_table LIMIT 10")
        Views are CREATE OR REPLACE so re-running is safe.
        """
        conn = getattr(self, "conn", None)
        if conn is None:
            return
        display_names = list(getattr(self, "uploaded_display_names", []) or [])
        uploaded_files = list(getattr(self, "uploaded_files", []) or [])
        doc_dir = getattr(self, "doc_dir", "")

        for idx, table_name in enumerate(display_names):
            # Resolve parquet path
            if idx < len(uploaded_files) and uploaded_files[idx]:
                parquet_path = uploaded_files[idx].replace("\\", "/")
            else:
                parquet_path = os.path.join(doc_dir, f"{table_name}.parquet").replace("\\", "/")

            if not os.path.exists(parquet_path):
                continue
            try:
                conn.execute(
                    f"CREATE OR REPLACE VIEW \"{table_name}\" AS "
                    f"SELECT * FROM read_parquet('{parquet_path}')"
                )
            except Exception:
                pass  # Non-fatal: load_relation() still works as fallback

    def _build_python_runtime_context(self):
        """Build runtime globals/locals for Python script execution."""

        # ── Register all uploaded tables as DuckDB views ──────────────
        # This lets sql("SELECT * FROM my_table ...") work without file paths.
        self._register_tables_as_views()

        def load_relation(table_name: str):
            """Load a table as lazy DuckDB relation (preferred for big data)."""
            parquet_path = self._get_table_parquet_path(table_name)
            return self.conn.from_parquet(parquet_path)

        def load_table(table_name: str):
            """Load a table as pandas DataFrame (convenience API)."""
            rel = load_relation(table_name)
            return self._relation_to_df(rel, source_name=f"table '{table_name}'")

        def sql(query: str):
            """Return a DuckDB relation for SQL text (keeps processing inside DuckDB)."""
            sql_text = (query or "").strip().rstrip(";")
            if not sql_text:
                raise ValueError("query cannot be empty")
            return self.conn.sql(sql_text)

        def to_df(obj, limit: int | None = None):
            """Convert relation/query/DataFrame to pandas with optional limit + guardrails."""
            if isinstance(obj, pd.DataFrame):
                if isinstance(limit, int) and limit > 0:
                    return obj.head(limit)
                if len(obj) > self.PYTHON_DF_SAFE_LIMIT:
                    self._warn_large_df_conversion(len(obj), source_name="DataFrame")
                return obj
            if isinstance(obj, str):
                rel = sql(obj)
                return self._relation_to_df(rel, limit=limit, source_name="query")
            if hasattr(obj, "df") and hasattr(obj, "count"):
                return self._relation_to_df(obj, limit=limit, source_name="relation")
            raise TypeError("Unsupported object type for to_df(). Use relation, SQL string, or DataFrame.")

        def stream_df(query: str, chunk_size: int = 100_000):
            """Yield query results as DataFrame chunks for memory-safe processing."""
            return self._query_to_df_chunks(query, chunk_size=chunk_size)

        # ── File I/O helpers ───────────────────────────────────────────
        def read_path(path: str, sheet=0, **kwargs) -> pd.DataFrame:
            """Read any file into a DataFrame. Supports:
            csv, tsv, txt, xlsx, xls, xlsm, json, jsonl, xml,
            parquet, orc, feather, pkl/pickle.
            For zip files use read_zip().
            Example:
                df = read_path(r'C:/data/sales.csv')
                df = read_path(r'C:/data/report.xlsx', sheet='Sheet2')
            """
            import os as _os
            ext = _os.path.splitext(path)[-1].lower().lstrip(".")
            if ext in ("csv", "tsv", "txt"):
                sep = "\t" if ext == "tsv" else kwargs.pop("sep", ",")
                return pd.read_csv(path, sep=sep, **kwargs)
            if ext in ("xlsx", "xls", "xlsm", "xlsb"):
                return pd.read_excel(path, sheet_name=sheet, **kwargs)
            if ext == "json":
                try:
                    return pd.read_json(path, **kwargs)
                except Exception:
                    return pd.read_json(path, lines=True, **kwargs)
            if ext == "jsonl":
                return pd.read_json(path, lines=True, **kwargs)
            if ext == "xml":
                return pd.read_xml(path, **kwargs)
            if ext == "parquet":
                return pd.read_parquet(path, **kwargs)
            if ext == "orc":
                return pd.read_orc(path, **kwargs)
            if ext in ("feather", "ftr"):
                return pd.read_feather(path, **kwargs)
            if ext in ("pkl", "pickle"):
                return pd.read_pickle(path, **kwargs)
            # Fallback: try CSV
            return pd.read_csv(path, **kwargs)

        def read_zip(zip_path: str, inner_file: str | None = None, sheet=0, **kwargs) -> pd.DataFrame:
            """Read a file inside a zip archive into a DataFrame.
            If the zip contains a single file, inner_file is optional.
            Example:
                df = read_zip(r'C:/data/archive.zip')
                df = read_zip(r'C:/data/archive.zip', 'sales_2024.csv')
                df = read_zip(r'C:/data/reports.zip', 'Q1.xlsx', sheet='Jan')
            """
            import zipfile as _zf, io as _io
            with _zf.ZipFile(zip_path) as zf:
                names = zf.namelist()
                if inner_file is None:
                    # Auto-pick: skip __MACOSX entries, pick first readable file
                    candidates = [n for n in names if not n.startswith("__") and not n.endswith("/")]
                    if not candidates:
                        raise FileNotFoundError(f"No readable files found in {zip_path}")
                    inner_file = candidates[0]
                data = _io.BytesIO(zf.read(inner_file))
            return read_path.__wrapped__(data, sheet=sheet, ext=inner_file.rsplit(".", 1)[-1], **kwargs) \
                if hasattr(read_path, "__wrapped__") \
                else _read_bytes(data, inner_file, sheet, **kwargs)

        def _read_bytes(buf, filename: str, sheet=0, **kwargs) -> pd.DataFrame:
            ext = filename.rsplit(".", 1)[-1].lower()
            if ext in ("csv", "tsv", "txt"):
                sep = "\t" if ext == "tsv" else kwargs.pop("sep", ",")
                return pd.read_csv(buf, sep=sep, **kwargs)
            if ext in ("xlsx", "xls", "xlsm", "xlsb"):
                return pd.read_excel(buf, sheet_name=sheet, **kwargs)
            if ext == "json":
                return pd.read_json(buf, **kwargs)
            if ext == "jsonl":
                return pd.read_json(buf, lines=True, **kwargs)
            if ext == "xml":
                return pd.read_xml(buf, **kwargs)
            if ext == "parquet":
                return pd.read_parquet(buf, **kwargs)
            return pd.read_csv(buf, **kwargs)

        # Patch read_zip to use _read_bytes without circular ref
        _orig_read_zip = read_zip
        def read_zip(zip_path: str, inner_file: str | None = None, sheet=0, **kwargs) -> pd.DataFrame:
            import zipfile as _zf, io as _io
            with _zf.ZipFile(zip_path) as zf:
                names = zf.namelist()
                if inner_file is None:
                    candidates = [n for n in names if not n.startswith("__") and not n.endswith("/")]
                    if not candidates:
                        raise FileNotFoundError(f"No readable files found in {zip_path}")
                    inner_file = candidates[0]
                data = _io.BytesIO(zf.read(inner_file))
            return _read_bytes(data, inner_file, sheet=sheet, **kwargs)

        def save_result(df: pd.DataFrame, path: str, sheet_name: str = "Sheet1",
                        index: bool = False, **kwargs) -> str:
            """Save a DataFrame to any path. Format auto-detected from extension.
            Supports: csv, tsv, txt, xlsx, json, jsonl, xml, parquet, feather, pkl/pickle.
            Creates parent directories automatically.
            Returns the absolute path written.
            Example:
                save_result(result_df, r'C:/output/report.xlsx')
                save_result(result_df, r'C:/output/data.csv', sep=';')
                save_result(result_df, r'C:/output/data.json', orient='records')
            """
            import os as _os
            _os.makedirs(_os.path.dirname(_os.path.abspath(path)), exist_ok=True)
            ext = _os.path.splitext(path)[-1].lower().lstrip(".")
            if ext in ("csv", "txt"):
                sep = kwargs.pop("sep", ",")
                df.to_csv(path, index=index, sep=sep, **kwargs)
            elif ext == "tsv":
                df.to_csv(path, index=index, sep="\t", **kwargs)
            elif ext in ("xlsx", "xls", "xlsm"):
                df.to_excel(path, sheet_name=sheet_name, index=index, **kwargs)
            elif ext == "json":
                orient = kwargs.pop("orient", "records")
                df.to_json(path, orient=orient, **kwargs)
            elif ext == "jsonl":
                df.to_json(path, orient="records", lines=True, **kwargs)
            elif ext == "xml":
                df.to_xml(path, index=index, **kwargs)
            elif ext == "parquet":
                df.to_parquet(path, index=index, **kwargs)
            elif ext in ("feather", "ftr"):
                df.to_feather(path, **kwargs)
            elif ext in ("pkl", "pickle"):
                df.to_pickle(path, **kwargs)
            else:
                df.to_csv(path, index=index, **kwargs)  # safe fallback
            return _os.path.abspath(path)

        globals_scope = {
            "__builtins__": __builtins__,
            "pd": pd,
            "duckdb": duckdb,
            "conn": getattr(self, "conn", None),
            "load_relation": load_relation,
            "load_table": load_table,
            "sql": sql,
            "to_df": to_df,
            "stream_df": stream_df,
            "read_path": read_path,
            "read_zip": read_zip,
            "save_result": save_result,
        }

        # ── Milestone 3: inject all available DS/ML libraries ──────────
        import importlib
        for entry in get_ds_library_status():
            if not entry["available"]:
                continue
            real_import, alias = _ALIAS_OVERRIDES.get(
                entry["import_name"], (entry["import_name"], entry["alias"])
            )
            try:
                globals_scope[alias] = importlib.import_module(real_import)
            except ImportError:
                pass

        # Convenience: also inject sklearn sub-modules used most often
        _sklearn_extras = {
            "linear_model":    "sklearn.linear_model",
            "ensemble":        "sklearn.ensemble",
            "tree":            "sklearn.tree",
            "preprocessing":   "sklearn.preprocessing",
            "model_selection": "sklearn.model_selection",
            "metrics":         "sklearn.metrics",
            "decomposition":   "sklearn.decomposition",
            "cluster":         "sklearn.cluster",
            "pipeline":        "sklearn.pipeline",
        }
        if globals_scope.get("sklearn") is not None:
            for attr, mod_path in _sklearn_extras.items():
                try:
                    globals_scope[attr] = importlib.import_module(mod_path)
                except ImportError:
                    pass

        current_df = getattr(self, "current_full_df", None)
        if isinstance(current_df, pd.DataFrame):
            globals_scope["df"] = current_df
        return globals_scope, {}

    def validate_python_script(self):
        """Validate Python syntax in the editor without executing."""
        from Simplisql import MainWindow

        script = self.sql_text.toPlainText().strip()
        if not script:
            self.validation_status_label.setText("⚠ Empty Script")
            self.validation_status_label.setStyleSheet("color: #ff9800; font-size: 10px; font-weight: bold;")
            MainWindow.show_styled_message_box(
                self,
                "Validation",
                "Python script is empty. Please enter script code to validate.",
                icon=QMessageBox.Icon.Warning,
            )
            return

        try:
            compile(script, "<python_notepad>", "exec")
            self.validation_status_label.setText("✓ Valid Python")
            self.validation_status_label.setStyleSheet("color: #4caf50; font-size: 10px; font-weight: bold;")
            MainWindow.show_styled_message_box(
                self,
                "✓ Python Validation Successful",
                "Your Python script is valid and ready to execute!",
                icon=QMessageBox.Icon.Information,
                text_color="#4caf50",
            )
        except SyntaxError as exc:
            self.validation_status_label.setText("✗ Syntax Error")
            self.validation_status_label.setStyleSheet("color: #f44336; font-size: 10px; font-weight: bold;")
            details = f"Line {exc.lineno}: {exc.msg}"
            MainWindow.show_styled_message_box(
                self,
                "✗ Python Syntax Error",
                f"Syntax error detected:\n\n{details}",
                icon=QMessageBox.Icon.Warning,
                text_color="#f44336",
            )

    def execute_python_script(self):
        """Execute the current Python script from the notepad."""
        from Simplisql import MainWindow

        script = self.sql_text.toPlainText().strip()
        if not script:
            MainWindow.show_styled_message_box(
                self,
                "Warning",
                "Python script cannot be empty!",
                icon=QMessageBox.Icon.Warning,
            )
            return

        progress = QProgressDialog("Running Python script...", None, 0, 0, self)
        progress.setWindowTitle("Python Execution")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()

        try:
            compile(script, "<python_notepad>", "exec")
            runtime_globals, runtime_locals = self._build_python_runtime_context()

            stdout_buffer = io.StringIO()
            stderr_buffer = io.StringIO()

            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                exec(script, runtime_globals, runtime_locals)

            result_df = runtime_locals.get("result_df")
            if result_df is None:
                result_df = runtime_globals.get("result_df")

            result_relation = runtime_locals.get("result_relation")
            if result_relation is None:
                result_relation = runtime_globals.get("result_relation")

            result_sql = runtime_locals.get("result_sql")
            if result_sql is None:
                result_sql = runtime_globals.get("result_sql")

            output_text = stdout_buffer.getvalue().strip()
            error_text = stderr_buffer.getvalue().strip()

            if isinstance(result_df, pd.DataFrame):
                if len(result_df) > self.PYTHON_DF_SAFE_LIMIT:
                    self._warn_large_df_conversion(len(result_df), source_name="result_df")
                self.populate_treeview(result_df)
                self.current_full_df = result_df
                self.validation_status_label.setText("✓ Python Executed")
                self.validation_status_label.setStyleSheet("color: #4caf50; font-size: 10px; font-weight: bold;")
                self.transaction_count_label.setText(
                    f"✅ Python result_df displayed | Rows: {len(result_df)} | Columns: {len(result_df.columns)}"
                )
            elif result_relation is not None and hasattr(result_relation, "df") and hasattr(result_relation, "count"):
                relation_df = self._relation_to_df(result_relation, limit=2000, source_name="result_relation")
                self.populate_treeview(relation_df)
                self.current_full_df = relation_df
                self.validation_status_label.setText("✓ Python Executed")
                self.validation_status_label.setStyleSheet("color: #4caf50; font-size: 10px; font-weight: bold;")
                self.transaction_count_label.setText(
                    f"✅ Python relation preview displayed | Rows shown: {len(relation_df)}"
                )
            elif isinstance(result_sql, str) and result_sql.strip():
                relation_df = self._relation_to_df(
                    self.conn.sql(result_sql.strip().rstrip(";")),
                    limit=2000,
                    source_name="result_sql",
                )
                self.populate_treeview(relation_df)
                self.current_full_df = relation_df
                self.validation_status_label.setText("✓ Python Executed")
                self.validation_status_label.setStyleSheet("color: #4caf50; font-size: 10px; font-weight: bold;")
                self.transaction_count_label.setText(
                    f"✅ Python SQL preview displayed | Rows shown: {len(relation_df)}"
                )
            elif output_text:
                lines = output_text.splitlines()
                preview_lines = lines[:200]
                output_df = pd.DataFrame({"Python Output": preview_lines})
                self.populate_treeview(output_df)
                self.current_full_df = output_df
                self.validation_status_label.setText("✓ Python Executed")
                self.validation_status_label.setStyleSheet("color: #4caf50; font-size: 10px; font-weight: bold;")
                self.transaction_count_label.setText(
                    f"✅ Python executed | Output lines: {len(lines)}"
                )
                if len(lines) > 200:
                    MainWindow.show_styled_message_box(
                        self,
                        "Output Truncated",
                        "Python output had more than 200 lines; showing the first 200 lines in results.",
                        icon=QMessageBox.Icon.Information,
                    )
            else:
                self.validation_status_label.setText("✓ Python Executed")
                self.validation_status_label.setStyleSheet("color: #4caf50; font-size: 10px; font-weight: bold;")
                self.transaction_count_label.setText("✅ Python executed successfully")
                MainWindow.show_styled_message_box(
                    self,
                    "Success",
                    (
                        "Python script executed successfully.\n\n"
                        "Tips:\n"
                        "- For big data, use load_relation()/sql() and keep transforms inside DuckDB.\n"
                        "- Set result_relation (DuckDB relation), result_sql (SQL text), or result_df (DataFrame) to display output."
                    ),
                    icon=QMessageBox.Icon.Information,
                )

            if error_text:
                MainWindow.show_styled_message_box(
                    self,
                    "Python stderr",
                    f"Script completed with stderr output:\n\n{error_text}",
                    icon=QMessageBox.Icon.Warning,
                )

        except Exception as exc:
            self.validation_status_label.setText("✗ Python Error")
            self.validation_status_label.setStyleSheet("color: #f44336; font-size: 10px; font-weight: bold;")
            err_trace = traceback.format_exc()
            MainWindow.show_error_message_box_with_copy(
                self,
                "Python Execution Error",
                f"<b>Python Error:</b><br>{str(exc)}",
                detailed_text=err_trace,
            )
        finally:
            progress.close()
