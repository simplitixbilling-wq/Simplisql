"""
Query Management Module
=======================
This module contains query execution and data loading functionality for SimplSQL.

Extracted methods:
- Query execution: execute_query(), execute_query_to_store(), execute_query_background()
- Data loading: load_data_advanced()

These methods handle all SQL query execution, result processing, and advanced data loading.
"""

import os
import re
import time
import socket
from datetime import datetime
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit,
    QCheckBox, QListWidget, QPushButton, QProgressDialog, QApplication,
    QFileDialog, QInputDialog, QMessageBox, QAbstractItemView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors


def get_system_ip():
    """
    Get the system's IP address.
    Returns the local IP address or 'Unavailable' if cannot be determined.
    """
    try:
        # Create a socket to determine the local IP
        # This doesn't actually make a connection
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # Google DNS, doesn't need to be reachable
        ip_address = s.getsockname()[0]
        s.close()
        return ip_address
    except Exception:
        try:
            # Fallback: get hostname and resolve it
            hostname = socket.gethostname()
            ip_address = socket.gethostbyname(hostname)
            return ip_address
        except Exception:
            return "Unavailable"


def generate_audit_pdf(pdf_path, query_text, summary_data):
    """
    Generate a PDF audit report with query text and execution summary.
    
    Args:
        pdf_path: Full path where PDF should be saved
        query_text: The SQL query that was executed
        summary_data: Dictionary containing execution metrics
    """
    try:
        # Create PDF document
        doc = SimpleDocTemplate(pdf_path, pagesize=letter,
                                rightMargin=0.75*inch, leftMargin=0.75*inch,
                                topMargin=0.75*inch, bottomMargin=0.75*inch)
        
        # Container for the 'Flowable' objects
        elements = []
        
        # Define styles
        styles = getSampleStyleSheet()
        title_style = styles['Heading1']
        heading_style = styles['Heading2']
        normal_style = styles['Normal']
        
        # Title
        title = Paragraph("SimplSQL Query Audit Report", title_style)
        elements.append(title)
        elements.append(Spacer(1, 0.3*inch))
        
        # Execution Details Section
        details_heading = Paragraph("Execution Details", heading_style)
        elements.append(details_heading)
        elements.append(Spacer(1, 0.1*inch))
        
        # Create summary table
        summary_table_data = [
            ['Metric', 'Value'],
            ['Status', summary_data.get('Status', 'N/A')],
            ['Rows Exported', str(summary_data.get('Rows Exported', 'N/A'))],
            ['File Name', summary_data.get('File Name', 'N/A')],
            ['File Size', f"{summary_data.get('File Size (MB)', 'N/A')} MB"],
            ['Execution Time', f"{summary_data.get('Execution Time (s)', 'N/A')} seconds"],
            ['Stored At', summary_data.get('Stored At', 'N/A')],
            ['Output Location', summary_data.get('Output Location', 'N/A')],
            ['System IP', summary_data.get('System IP', 'N/A')]
        ]
        
        summary_table = Table(summary_table_data, colWidths=[2*inch, 4.5*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        
        elements.append(summary_table)
        elements.append(Spacer(1, 0.3*inch))
        
        # SQL Query Section
        query_heading = Paragraph("SQL Query", heading_style)
        elements.append(query_heading)
        elements.append(Spacer(1, 0.1*inch))
        
        # Format query text - wrap in pre-formatted style
        query_lines = query_text.split('\n')
        for line in query_lines:
            # Escape special characters for PDF
            safe_line = line.replace('<', '&lt;').replace('>', '&gt;')
            query_para = Paragraph(f"<font name='Courier' size='8'>{safe_line}</font>", normal_style)
            elements.append(query_para)
        
        elements.append(Spacer(1, 0.3*inch))
        
        # Footer
        footer_text = f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        footer = Paragraph(f"<i>{footer_text}</i>", normal_style)
        elements.append(Spacer(1, 0.2*inch))
        elements.append(footer)
        
        # Build PDF
        doc.build(elements)
        return True
        
    except Exception as e:
        print(f"⚠️ PDF generation failed: {e}")
        return False


class QueryExecutionThread(QThread):
    """Background thread for query execution"""
    finished = pyqtSignal(object)  # Emits result DataFrame or None
    error = pyqtSignal(str)  # Emits error message
    
    def __init__(self, conn, query):
        super().__init__()
        self.conn = conn
        self.query = query
        
    def run(self):
        try:
            result = self.conn.execute(self.query).fetchdf()
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class QueryManager:
    """
    Mixin class containing query execution and data loading methods.
    
    This class requires the following attributes from the parent class:
    - self.conn: DuckDB connection
    - self.sql_text: QPlainTextEdit for SQL query input
    - self.doc_dir: Path to ParquetFiles directory
    - self.apply_progress_dialog_styling(): Progress dialog styling method
    - self.apply_dark_dialog_styling(): Dialog styling method
    - self.populate_treeview(): Method to display results
    - self.safe_arithmetic_replace(): Method for arithmetic operations
    - self.arithmetic_pattern: Regex pattern for arithmetic
    - self.arithmetic_replacer(): Method to replace arithmetic
    - self.show_styled_message_box(): Message box method (via MainWindow)
    - self.show_error_message_box_with_copy(): Error message box (via MainWindow)
    """

    def _normalize_duckdb_datetime_sql(self, query: str) -> str:
        """Auto-fix common non-DuckDB date/time patterns to DuckDB-compatible SQL."""
        if not query:
            return query

        sql = query

        # Fix malformed artifacts like: TRY_CAST(INTERVAL AS DOUBLE)) '6' MONTH
        sql = re.sub(
            r"(?i)TRY_CAST\s*\(\s*INTERVAL\s+AS\s+DOUBLE\s*\)\s*\)\s*['\"](-?\d+)['\"]\s*"
            r"(DAY|DAYS|WEEK|WEEKS|MONTH|MONTHS|YEAR|YEARS|HOUR|HOURS|MINUTE|MINUTES|SECOND|SECONDS)\b",
            lambda m: f"INTERVAL {m.group(1)} {m.group(2).upper().rstrip('S')}",
            sql,
        )

        # Normalize INTERVAL literal forms: INTERVAL '6' MONTH -> INTERVAL 6 MONTH
        sql = re.sub(
            r"(?i)\bINTERVAL\s*['\"](-?\d+)['\"]\s*"
            r"(DAY|DAYS|WEEK|WEEKS|MONTH|MONTHS|YEAR|YEARS|HOUR|HOURS|MINUTE|MINUTES|SECOND|SECONDS)\b",
            lambda m: f"INTERVAL {m.group(1)} {m.group(2).upper().rstrip('S')}",
            sql,
        )

        # Normalize bare quoted interval quantities after +/-: date_col - '6' MONTH
        sql = re.sub(
            r"(?i)([+\-]\s*)['\"](-?\d+)['\"]\s*"
            r"(DAY|DAYS|WEEK|WEEKS|MONTH|MONTHS|YEAR|YEARS|HOUR|HOURS|MINUTE|MINUTES|SECOND|SECONDS)\b",
            lambda m: f"{m.group(1)}INTERVAL {m.group(2)} {m.group(3).upper().rstrip('S')}",
            sql,
        )

        # DATE_FORMAT(expr, fmt) -> STRFTIME(expr, fmt)
        sql = re.sub(r"(?i)\bDATE_FORMAT\s*\(", "STRFTIME(", sql)

        # GETDATE() -> CURRENT_TIMESTAMP
        sql = re.sub(r"(?i)\bGETDATE\s*\(\s*\)", "CURRENT_TIMESTAMP", sql)

        # TIMESTAMPDIFF(unit, start, end) -> DATE_DIFF('unit', CAST(start AS DATE), CAST(end AS DATE))
        sql = re.sub(
            r"(?i)\bTIMESTAMPDIFF\s*\(\s*'?([A-Za-z]+)'?\s*,\s*([^,]+?)\s*,\s*([^)]+?)\s*\)",
            lambda m: (
                f"DATE_DIFF('{m.group(1).lower()}', "
                f"CAST({m.group(2).strip()} AS DATE), CAST({m.group(3).strip()} AS DATE))"
            ),
            sql,
        )

        # DATEADD(unit, amount, date_expr) -> DATE_ADD(CAST(date_expr AS DATE), INTERVAL amount unit)
        sql = re.sub(
            r"(?i)\bDATEADD\s*\(\s*'?([A-Za-z]+)'?\s*,\s*([^,]+?)\s*,\s*([^)]+?)\s*\)",
            lambda m: (
                f"DATE_ADD(CAST({m.group(3).strip()} AS DATE), "
                f"INTERVAL {m.group(2).strip()} {m.group(1).upper().rstrip('S')})"
            ),
            sql,
        )

        # DATEDIFF(unit, start, end) -> DATE_DIFF('unit', CAST(start AS DATE), CAST(end AS DATE))
        sql = re.sub(
            r"(?i)\bDATEDIFF\s*\(\s*'?([A-Za-z]+)'?\s*,\s*([^,]+?)\s*,\s*([^)]+?)\s*\)",
            lambda m: (
                f"DATE_DIFF('{m.group(1).lower()}', "
                f"CAST({m.group(2).strip()} AS DATE), CAST({m.group(3).strip()} AS DATE))"
            ),
            sql,
        )

        # DATETRUNC(unit, expr) -> DATE_TRUNC('unit', CAST(expr AS TIMESTAMP))
        sql = re.sub(
            r"(?i)\bDATETRUNC\s*\(\s*'?([A-Za-z]+)'?\s*,\s*([^)]+?)\s*\)",
            lambda m: f"DATE_TRUNC('{m.group(1).lower()}', CAST({m.group(2).strip()} AS TIMESTAMP))",
            sql,
        )

        # DATE_TRUNC(unit, expr) where unit is unquoted -> quote it
        sql = re.sub(
            r"(?i)\bDATE_TRUNC\s*\(\s*([A-Za-z]+)\s*,\s*([^)]+?)\s*\)",
            lambda m: f"DATE_TRUNC('{m.group(1).lower()}', {m.group(2).strip()})",
            sql,
        )

        # EXTRACT(year, expr) -> EXTRACT('year' FROM CAST(expr AS DATE))
        sql = re.sub(
            r"(?i)\bEXTRACT\s*\(\s*([A-Za-z]+)\s*,\s*([^)]+?)\s*\)",
            lambda m: f"EXTRACT('{m.group(1).lower()}' FROM CAST({m.group(2).strip()} AS DATE))",
            sql,
        )

        return sql
    
    def execute_query(self):
        """Execute SQL query and display results"""
        from Simplisql import MainWindow
        
        original_query = self.sql_text.toPlainText().strip()
        query = original_query.replace("\\", "/")
        
        # Auto-fix: Replace double quotes with single quotes for file paths
        # This handles cases like: SELECT * FROM "C:\path\file.csv"
        # Pattern matches: "C:\..." or "C:/..." or any path with drive letter
        query_before_fix = query
        query = re.sub(r'"([A-Za-z]:[^"]+)"', r"'\1'", query)
        
        # Notify user if query was auto-corrected
        if query != query_before_fix:
            print("💡 Auto-corrected: Replaced double quotes (\") with single quotes (') in file paths")
        
        # Remove trailing semicolons (DuckDB doesn't need them and they can cause issues)
        query = query.rstrip(';').strip()
        
        self.arithmetic_pattern = (
            r"(?i)\b(?!(?:select|from|where|group|order|join)\b)([\w\.]+)\s*([+\-*/])\s*([\w\.]+)"
        )

        if not query:
            MainWindow.show_styled_message_box(self, "Warning", "SQL query cannot be empty!", icon=QMessageBox.Icon.Information)
            return
        if self.conn is None:
            MainWindow.show_error_message_box_with_copy(
                self, 
                "Database Connection Error", 
                "Database connection is not established!",
                detailed_text="The DuckDB connection is None. This might be due to initialization failure or connection being closed unexpectedly."
            )
            return

        try:
            cte_names = set()
            cte_pattern = r"(?i)(?:WITH|,)\s+(\w+)\s+AS\s*\("
            for cte in re.findall(cte_pattern, query):
                cte_names.add(cte)

            if "read_parquet(" in query.lower():
                modified_query = query
            else:
                table_pattern = (
                    r"(?si)\b(FROM|JOIN)\s+(\w+)"
                    r"(?:\s+(?:AS\s+)?(?!JOIN\b|WHERE\b|ON\b|ORDER\b|GROUP\b|HAVING\b|LIMIT\b|"
                    r"UNION\b|LEFT\b|RIGHT\b|INNER\b|OUTER\b|CROSS\b|FULL\b|QUALIFY\b|FILTER\b|EXCLUDE\b|REPLACE\b)(\w+))?"
                    r"(?=\s|$)"
                )

                def table_replacer(m):
                    keyword = m.group(1)
                    table_name = m.group(2)
                    alias = m.group(3) if m.group(3) else table_name
                    if table_name in cte_names:
                        return m.group(0)
                    parquet_file = os.path.join(
                        self.doc_dir, f"{table_name}.parquet"
                    ).replace("\\", "/")
                    # Quote the alias to handle table names starting with numbers or containing special characters
                    quoted_alias = f'"{alias}"'
                    return f"{keyword} (SELECT * FROM read_parquet('{parquet_file}')) AS {quoted_alias}"

                modified_query = re.sub(table_pattern, table_replacer, query)

            agg_pattern = r"(?i)\b(sum|avg|min|max|stddev|variance)\s*\(\s*([^\(\)]+)\s*\)"

            def agg_replacer(match):
                aggregator = match.group(1).strip().upper()
                expression = match.group(2).strip()

                if aggregator in ("MIN", "MAX") and "date" in expression.lower():
                    return f"{aggregator}(TRY_CAST({expression} AS DATE))"
                return f"{aggregator}(TRY_CAST({expression} AS DOUBLE))"

            modified_query = re.sub(agg_pattern, agg_replacer, modified_query)

            datediff_pattern = (
                r"(?i)\bDATEDIFF\s*\(\s*([A-Za-z]+)\s*,\s*([^,]+)\s*,\s*([^)]+)\)"
            )

            def datediff_replacer(m):
                datepart = m.group(1).strip()
                date1 = m.group(2).strip()
                date2 = m.group(3).strip()
                return (
                    f"DATEDIFF('{datepart}', CAST({date1} AS DATE), CAST({date2} AS DATE))"
                )

            modified_query = re.sub(datediff_pattern, datediff_replacer, modified_query)

            dateadd_pattern = r"(?i)\bDATEADD\s*\(\s*(\w+)\s*,\s*([^,]+)\s*,\s*([^)]+)\)"

            def dateadd_replacer(m):
                datepart = m.group(1).strip()
                amount = m.group(2).strip()
                date_expr = m.group(3).strip()
                return f"DATEADD('{datepart}', {amount}, CAST({date_expr} AS DATE))"

            modified_query = re.sub(dateadd_pattern, dateadd_replacer, modified_query)

            datetrunc_pattern = r"(?i)\bDATETRUNC\s*\(\s*(\w+)\s*,\s*([^)]+)\)"

            def datetrunc_replacer(m):
                datepart = m.group(1).strip()
                date_expr = m.group(2).strip()
                return f"DATETRUNC('{datepart}', CAST({date_expr} AS DATE))"

            modified_query = re.sub(datetrunc_pattern, datetrunc_replacer, modified_query)

            extract_pattern = r"(?i)\bEXTRACT\s*\(\s*(\w+)\s+FROM\s+([^)]+)\)"

            def extract_replacer(m):
                datepart = m.group(1).strip()
                date_expr = m.group(2).strip()
                return f"EXTRACT('{datepart}' FROM CAST({date_expr} AS DATE))"

            modified_query = re.sub(extract_pattern, extract_replacer, modified_query)

            modified_query = self.safe_arithmetic_replace(
                modified_query, self.arithmetic_pattern, self.arithmetic_replacer
            )

            # Normalize cross-dialect date/time patterns before execution.
            query = self._normalize_duckdb_datetime_sql(query)
            modified_query = self._normalize_duckdb_datetime_sql(modified_query)

            file_paths = re.findall(r"read_parquet\('([^']+)'\)", modified_query)
            if file_paths:
                print("\n📄 Files involved in this query:")
                for path in file_paths:
                    print(f"   - {os.path.basename(path)}")

            start_time = time.time()
            print(f"below is the query" + "\n" + query)
            print(modified_query)
            print(f"\n🚀 Query Execution Started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Show progress dialog for query execution with continuous animation
            progress = QProgressDialog("Preparing query...", "Cancel", 0, 100, self)
            progress.setWindowTitle("Query Progress")
            progress.setWindowModality(Qt.WindowModality.ApplicationModal)
            progress.setMinimumDuration(0)  # Show immediately
            progress.setValue(0)
            
            self.apply_progress_dialog_styling(progress, "#4CAF50")  # Green for query execution
            
            progress.show()
            QApplication.processEvents()
            
            self.conn.execute("PRAGMA threads=8;")
            self.conn.execute("PRAGMA memory_limit='16GB';")
            self.conn.execute("PRAGMA enable_progress_bar=true;")
            
            try:
                # Create a background thread for query execution
                query_result = [None]
                query_error = [None]
                query_finished = [False]
                
                def execute_query_background():
                    try:
                        # First try the original query
                        query_result[0] = self.conn.execute(query).fetchdf()
                    except Exception as e1:
                        try:
                            # If original fails, try the modified (parquet) query
                            query_result[0] = self.conn.execute(modified_query).fetchdf()
                        except Exception as e2:
                            query_error[0] = (e1, e2)
                    finally:
                        query_finished[0] = True
                
                import threading
                query_thread = threading.Thread(target=execute_query_background, daemon=True)
                query_thread.start()
                
                # Show progress while waiting for query
                progress_value = 10
                while not query_finished[0]:
                    if progress.wasCanceled():
                        progress.close()
                        MainWindow.show_styled_message_box(
                            self, 
                            "Cancelled", 
                            "Query execution was cancelled. Note: The query may still be running in the background.",
                            icon=QMessageBox.Icon.Warning
                        )
                        return
                    
                    # Animate progress
                    progress_value = (progress_value + 5) % 90 + 10  # Cycle between 10-90
                    progress.setValue(progress_value)
                    elapsed = time.time() - start_time
                    progress.setLabelText(f"Executing query... ({elapsed:.1f}s elapsed)")
                    QApplication.processEvents()
                    time.sleep(0.1)
                
                # Check for errors
                if query_error[0]:
                    # If both errors, show both
                    if isinstance(query_error[0], tuple) and len(query_error[0]) == 2:
                        e1, e2 = query_error[0]
                        error_msg = f"<b>Original Query Error:</b><br>{e1}<br><br><b>Fallback (Parquet) Query Error:</b><br>{e2}"
                        MainWindow.show_error_message_box_with_copy(
                            self,
                            "SQL Error",
                            error_msg,
                            detailed_text=f"Original Query Error:\n{e1}\n\nFallback (Parquet) Query Error:\n{e2}"
                        )
                        progress.close()
                        return
                    else:
                        raise query_error[0]
                df = query_result[0]
                progress.setValue(100)
                progress.close()
                
            except Exception as thread_error:
                progress.close()
                raise thread_error

            end_time = time.time()
            elapsed_time = end_time - start_time

            print(f"✅ Query Execution Completed at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"⏱️ Total Execution Time: {elapsed_time:.2f} seconds")
            print(f"📊 Result shape: {df.shape}")

            self.populate_treeview(df)
            self.current_full_df = df

        except Exception as e:
            error_text = str(e)
            query_text = self.sql_text.toPlainText().strip()

            # Try to locate the problematic line in the query
            token_match = re.search(r'near\s+"(\w+)"', error_text)
            error_line = ""

            if token_match:
                error_token = token_match.group(1)
                # Find the line containing the error token
                for line in query_text.splitlines():
                    if error_token in line:
                        error_line = line.strip()
                        break

            # If no line found, fallback to full message
            if not error_line:
                error_line = "(Could not identify error line)"

            formatted_message = f"""
                <b>DuckDB Error:</b><br>{error_text}<br><br>
                <b>Problematic Line:</b><br><pre style='color:orange;'>{error_line}</pre>
            """

            # Use the copy-enabled error message box
            plain_error_text = f"DuckDB Error: {error_text}\n\nProblematic Line: {error_line}"
            MainWindow.show_error_message_box_with_copy(
                self,
                "SQL Error",
                formatted_message,
                detailed_text=plain_error_text
            )

        except Exception as e:
            error_text = str(e)
            query_text = self.sql_text.toPlainText().strip()

            token_match = re.search(r'near\s+"(\w+)"', error_text)
            error_line = ""

            if token_match:
                error_token = token_match.group(1)
                for line in query_text.splitlines():
                    if error_token in line:
                        error_line = line.strip()
                        break

            if not error_line:
                error_line = "(Could not identify error line)"

            formatted_message = f"""
                <b>Unhandled Error:</b><br>{error_text}<br><br>
                <b>Problematic Line:</b><br><pre style='color:orange;'>{error_line}</pre>
            """

            # Use the copy-enabled error message box
            plain_error_text = f"Unhandled Error: {error_text}\n\nProblematic Line: {error_line}\n\nFull Query:\n{query_text}"
            MainWindow.show_error_message_box_with_copy(
                self,
                "SQL Error", 
                formatted_message,
                detailed_text=plain_error_text
            )

    def execute_query_background(self):
        """Legacy method - calls execute_query()"""
        self.execute_query()

    def execute_query_to_store(self):
        """Execute SQL query wrapped in COPY() to save results directly to CSV file"""
        from Simplisql import MainWindow
        
        query = self.sql_text.toPlainText().strip()
        
        # Auto-fix: Replace double quotes with single quotes for file paths
        query = re.sub(r'"([A-Za-z]:[^"]+)"', r"'\1'", query)
        
        # Remove trailing semicolons
        query = query.rstrip(';').strip()
        
        if not query:
            MainWindow.show_styled_message_box(self, "Warning", "SQL query cannot be empty!", icon=QMessageBox.Icon.Information)
            return
            
        if self.conn is None:
            MainWindow.show_styled_message_box(
                self, "Error", "Database connection is not established!", icon=QMessageBox.Icon.Information
            )
            return

        try:
            # Get output folder from user
            output_folder = QFileDialog.getExistingDirectory(
                self,
                "Select Output Folder",
                self.doc_dir,  # Default to ParquetFiles directory
                QFileDialog.Option.ShowDirsOnly
            )
            
            if not output_folder:
                return  # User cancelled
            
            # Get filename from user
            filename, ok = QInputDialog.getText(
                self, 
                'Save Query Results', 
                'Enter filename (without extension):',
                text=f'query_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
            )
            
            if not ok or not filename:
                return  # User cancelled
            
            # Sanitize filename
            filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
            csv_path = os.path.join(output_folder, f"{filename}.csv").replace("\\", "/")
            
            # Apply same query transformations as execute_query
            cte_names = set()
            cte_pattern = r"(?i)(?:WITH|,)\s+(\w+)\s+AS\s*\("
            for cte in re.findall(cte_pattern, query):
                cte_names.add(cte)

            if "read_parquet(" in query.lower():
                modified_query = query
            else:
                table_pattern = (
                    r"(?si)\b(FROM|JOIN)\s+(\w+)"
                    r"(?:\s+(?:AS\s+)?(?!JOIN\b|WHERE\b|ON\b|ORDER\b|GROUP\b|HAVING\b|LIMIT\b|"
                    r"UNION\b|LEFT\b|RIGHT\b|INNER\b|OUTER\b|CROSS\b|FULL\b|QUALIFY\b|FILTER\b|EXCLUDE\b|REPLACE\b)(\w+))?"
                    r"(?=\s|$)"
                )

                def table_replacer(m):
                    keyword = m.group(1)
                    table_name = m.group(2)
                    alias = m.group(3) if m.group(3) else table_name
                    if table_name in cte_names:
                        return m.group(0)
                    parquet_file = os.path.join(
                        self.doc_dir, f"{table_name}.parquet"
                    ).replace("\\", "/")
                    quoted_alias = f'"{alias}"'
                    return f"{keyword} (SELECT * FROM read_parquet('{parquet_file}')) AS {quoted_alias}"

                modified_query = re.sub(table_pattern, table_replacer, query)

            # Normalize cross-dialect date/time patterns for export path too.
            modified_query = self._normalize_duckdb_datetime_sql(modified_query)

            # Wrap query in COPY statement
            copy_query = f"COPY ({modified_query}) TO '{csv_path}' (HEADER, DELIMITER ',')"
            
            print(f"\n💾 Saving query results to CSV...")
            print(f"📁 Output path: {csv_path}")
            print(f"🔍 Query:\n{modified_query}")
            
            # Show progress dialog
            progress = QProgressDialog("Executing query and saving results...", "Cancel", 0, 100, self)
            progress.setWindowTitle("Export Progress")
            progress.setWindowModality(Qt.WindowModality.ApplicationModal)
            progress.setMinimumDuration(0)
            progress.setValue(0)
            self.apply_progress_dialog_styling(progress, "#FF9800")  # Orange for export
            progress.show()
            QApplication.processEvents()
            
            start_time = time.time()
            
            # Configure DuckDB for performance
            progress.setValue(20)
            progress.setLabelText("Configuring DuckDB...")
            QApplication.processEvents()
            
            self.conn.execute("PRAGMA threads=8;")
            self.conn.execute("PRAGMA memory_limit='16GB';")
            
            # Execute COPY query
            progress.setValue(40)
            progress.setLabelText("Executing query...")
            QApplication.processEvents()
            
            self.conn.execute(copy_query)
            
            progress.setValue(100)
            end_time = time.time()
            elapsed_time = end_time - start_time
            
            progress.close()
            
            # Capture store timestamp
            store_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Get file size
            file_size = os.path.getsize(csv_path)
            file_size_mb = file_size / (1024 * 1024)
            
            # Count rows in the CSV file (quick approximation)
            try:
                row_count = sum(1 for _ in open(csv_path)) - 1  # -1 for header
            except:
                row_count = "unknown"
            
            # Update status label with timestamp
            status_text = (
                f"✅ Exported {row_count} rows | "
                f"File: {os.path.basename(csv_path)} ({file_size_mb:.2f} MB) | "
                f"Time: {elapsed_time:.2f}s | "
                f"Stored: {store_timestamp} | "
                f"Location: {output_folder}"
            )
            self.transaction_count_label.setText(status_text)
            
            # Also display summary in the table view
            import pandas as pd
            summary_df = pd.DataFrame([{
                'Status': '✅ Export Completed',
                'Rows Exported': row_count,
                'File Name': os.path.basename(csv_path),
                'File Size (MB)': f"{file_size_mb:.2f}",
                'Execution Time (s)': f"{elapsed_time:.2f}",
                'Stored At': store_timestamp,
                'Output Location': output_folder
            }])
            self.populate_treeview(summary_df, set_full=True)
            
            print(f"✅ Export completed in {elapsed_time:.2f} seconds")
            print(f"📄 File saved: {os.path.basename(csv_path)}")
            print(f"📊 Rows: {row_count}, Size: {file_size_mb:.2f} MB")
            print(f"🕒 Stored at: {store_timestamp}")
            
            # Generate PDF audit report
            pdf_filename = filename + "_audit.pdf"
            pdf_path = os.path.join(output_folder, pdf_filename).replace("\\", "/")
            
            # Get system IP address
            system_ip = get_system_ip()
            
            summary_data = {
                'Status': '✅ Export Completed',
                'Rows Exported': row_count,
                'File Name': os.path.basename(csv_path),
                'File Size (MB)': file_size_mb,
                'Execution Time (s)': elapsed_time,
                'Stored At': store_timestamp,
                'Output Location': output_folder,
                'System IP': system_ip
            }
            
            pdf_success = generate_audit_pdf(pdf_path, query, summary_data)
            
            if pdf_success:
                print(f"📄 PDF audit report generated: {pdf_filename}")
                success_message = (
                    f"Query results saved successfully!\n\n"
                    f"Rows: {row_count}\n"
                    f"CSV File: {os.path.basename(csv_path)}\n"
                    f"PDF Audit: {pdf_filename}\n"
                    f"Size: {file_size_mb:.2f} MB\n"
                    f"Time: {elapsed_time:.2f}s\n"
                    f"Stored At: {store_timestamp}\n"
                    f"Location: {output_folder}"
                )
            else:
                print(f"⚠️ PDF audit report generation failed, but CSV export succeeded")
                success_message = (
                    f"Query results saved successfully!\n\n"
                    f"Rows: {row_count}\n"
                    f"File: {os.path.basename(csv_path)}\n"
                    f"Size: {file_size_mb:.2f} MB\n"
                    f"Time: {elapsed_time:.2f}s\n"
                    f"Stored At: {store_timestamp}\n"
                    f"Location: {output_folder}\n\n"
                    f"Note: PDF audit report could not be generated."
                )
            
            MainWindow.show_styled_message_box(
                self,
                "Success",
                success_message,
                icon=QMessageBox.Icon.Information
            )
            
        except Exception as e:
            error_details = f"Export failed\nQuery: {query[:200]}...\nError: {str(e)}"
            print(f"❌ Export error: {e}")
            
            MainWindow.show_error_message_box_with_copy(
                self, 
                "Export Error", 
                f"Failed to save query results:\n{str(e)}", 
                detailed_text=error_details
            )

    def load_data_advanced(self):
        """Dialog-driven advanced data loading with preview, filtering, and column selection"""
        from Simplisql import MainWindow
        
        # Get list of parquet files
        try:
            files = [f for f in os.listdir(self.doc_dir) if f.endswith('.parquet')]
            base_names = [os.path.splitext(f)[0] for f in files]
        except Exception:
            base_names = []

        if not base_names:
            MainWindow.show_styled_message_box(self, "No Files", "No parquet files found in the ParquetFiles folder.", icon=QMessageBox.Icon.Warning)
            return

        # Create advanced load dialog
        dialog = QDialog(self)
        self.apply_dark_dialog_styling(dialog)
        dialog.setWindowTitle("Advanced Data Load")
        dialog.setMinimumSize(600, 500)
        dlg_layout = QVBoxLayout(dialog)

        # File selection
        file_label = QLabel("Select Parquet File:")
        file_label.setStyleSheet("color: #d0d0d0; font-weight: bold; font-size: 12px;")
        dlg_layout.addWidget(file_label)
        file_combo = QComboBox()
        file_combo.addItems(base_names)
        dlg_layout.addWidget(file_combo)

        # Preview size input
        preview_label = QLabel("Preview Size (rows to load, 0 = all):")
        preview_label.setStyleSheet("color: #d0d0d0; font-weight: bold; font-size: 12px;")
        dlg_layout.addWidget(preview_label)
        preview_input = QLineEdit()
        preview_input.setText("")
        preview_input.setPlaceholderText("Leave blank or 0 to load all rows")
        dlg_layout.addWidget(preview_input)

        # Column selection area
        col_label = QLabel("Select Columns:")
        col_label.setStyleSheet("color: #d0d0d0; font-weight: bold; font-size: 12px;")
        dlg_layout.addWidget(col_label)
        
        # Select All checkbox
        self.select_all_cb = QCheckBox("Select All")
        self.select_all_cb.setStyleSheet("""
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
                background-color: #0078d4;
                border: 1px solid #0078d4;
            }
        """)
        dlg_layout.addWidget(self.select_all_cb)
        
        # Column list widget
        column_list = QListWidget()
        column_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        column_list.setStyleSheet("""
            QListWidget {
                background-color: #2d2d2d;
                color: #d0d0d0;
                border: 1px solid #555;
                font-size: 11px;
            }
            QListWidget::item:selected {
                background-color: #0078d4;
                color: white;
            }
            QListWidget::item:hover {
                background-color: #3d3d3d;
            }
        """)
        dlg_layout.addWidget(column_list)

        # WHERE clause input
        where_label = QLabel("WHERE Clause (optional):")
        where_label.setStyleSheet("color: #d0d0d0; font-weight: bold; font-size: 12px;")
        dlg_layout.addWidget(where_label)
        where_input = QLineEdit()
        where_input.setPlaceholderText("e.g., column_name > 100")
        dlg_layout.addWidget(where_input)

        # Load columns when file is selected
        def load_columns():
            try:
                file_name = file_combo.currentText()
                file_path = os.path.join(self.doc_dir, f"{file_name}.parquet").replace("\\", "/")
                
                # Use DuckDB to get column names efficiently
                query = f"DESCRIBE SELECT * FROM read_parquet('{file_path}')"
                schema_df = self.conn.execute(query).fetchdf()
                columns = schema_df['column_name'].tolist()
                
                # Populate column list
                column_list.clear()
                for col in columns:
                    column_list.addItem(col)
                
                # Select all by default
                for i in range(column_list.count()):
                    column_list.item(i).setSelected(True)
                    
                self.select_all_cb.setChecked(True)
                
            except Exception as e:
                MainWindow.show_styled_message_box(
                    self, 
                    "Error", 
                    f"Failed to load columns:\n{str(e)}", 
                    icon=QMessageBox.Icon.Critical
                )

        # Connect select all checkbox
        def toggle_select_all(state):
            for i in range(column_list.count()):
                column_list.item(i).setSelected(state == Qt.CheckState.Checked.value)
        
        self.select_all_cb.stateChanged.connect(toggle_select_all)
        
        # Load columns when file selection changes
        file_combo.currentIndexChanged.connect(load_columns)
        
        # Initial column load
        load_columns()

        # Buttons
        button_layout = QHBoxLayout()
        load_btn = QPushButton("Load Data")
        load_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #005a9e;
            }
        """)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #555;
                color: white;
                border: none;
                padding: 8px 16px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #666;
            }
        """)
        button_layout.addStretch()
        button_layout.addWidget(load_btn)
        button_layout.addWidget(cancel_btn)
        dlg_layout.addLayout(button_layout)

        # Load button handler
        def on_load():
            try:
                file_name = file_combo.currentText()
                file_path = os.path.join(self.doc_dir, f"{file_name}.parquet").replace("\\", "/")
                
                # Get selected columns
                selected_cols = [column_list.item(i).text() for i in range(column_list.count()) 
                                if column_list.item(i).isSelected()]
                
                if not selected_cols:
                    MainWindow.show_styled_message_box(
                        self, 
                        "Warning", 
                        "Please select at least one column!", 
                        icon=QMessageBox.Icon.Warning
                    )
                    return
                
                # Build SQL query
                cols_str = ", ".join([f'"{col}"' for col in selected_cols])
                query = f"SELECT {cols_str} FROM read_parquet('{file_path}')"
                
                # Add WHERE clause if provided
                where_clause = where_input.text().strip()
                if where_clause:
                    query += f" WHERE {where_clause}"
                
                # Add LIMIT if preview size specified
                preview_size = preview_input.text().strip()
                if preview_size and preview_size != "0":
                    try:
                        limit_val = int(preview_size)
                        query += f" LIMIT {limit_val}"
                    except ValueError:
                        MainWindow.show_styled_message_box(
                            self, 
                            "Warning", 
                            "Invalid preview size! Loading all rows.", 
                            icon=QMessageBox.Icon.Warning
                        )
                
                print(f"\n🔍 Advanced Load Query:\n{query}")
                
                # Show progress dialog
                progress = QProgressDialog("Loading data...", "Cancel", 0, 100, self)
                progress.setWindowTitle("Data Loading")
                progress.setWindowModality(Qt.WindowModality.ApplicationModal)
                progress.setMinimumDuration(0)
                progress.setValue(0)
                self.apply_progress_dialog_styling(progress, "#9C27B0")  # Purple for advanced load
                progress.show()
                QApplication.processEvents()
                
                # Configure DuckDB
                progress.setValue(20)
                progress.setLabelText("Configuring DuckDB...")
                QApplication.processEvents()
                
                self.conn.execute("PRAGMA threads=8;")
                self.conn.execute("PRAGMA memory_limit='16GB';")
                
                # Execute query
                progress.setValue(50)
                progress.setLabelText("Executing query...")
                QApplication.processEvents()
                
                start_time = time.time()
                df = self.conn.execute(query).fetchdf()
                end_time = time.time()
                
                progress.setValue(80)
                progress.setLabelText("Loading into table...")
                QApplication.processEvents()
                
                # Load data into results table
                self.populate_treeview(df, set_full=True, skip_large_prompt=False)
                
                progress.setValue(100)
                progress.close()
                
                elapsed = end_time - start_time
                print(f"✅ Advanced load completed in {elapsed:.2f} seconds")
                print(f"📊 Loaded {len(df):,} rows × {len(df.columns)} columns")
                
                dialog.accept()
                
            except Exception as e:
                MainWindow.show_error_message_box_with_copy(
                    self,
                    "Load Error",
                    f"Failed to load data:\n{str(e)}",
                    detailed_text=f"File: {file_name}\nQuery: {query}\nError: {str(e)}"
                )

        load_btn.clicked.connect(on_load)
        cancel_btn.clicked.connect(dialog.reject)

        dialog.exec()
