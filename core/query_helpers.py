"""
Query Helpers Module

Provides SQL query assistance functionality:
- SQL syntax validation
- Query templates library
- DuckDB function reference
- Interactive syntax helper

This module separates query assistance and validation logic from core
editor functionality, providing comprehensive SQL help to users.

Dependencies:
    - self attributes: conn, sql_text, validation_status_label, uploaded_display_names, doc_dir
    - External methods: apply_dark_dialog_styling
    - PyQt6: Dialog widgets, lists, text editors
    - DuckDB: Query validation via EXPLAIN
    - MainWindow: Styled message boxes

Author: Refactored from Simplsql.py Phase 12A
"""

import os
import re
import duckdb
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QPushButton, QTextEdit, QComboBox, QMessageBox
)
from PyQt6.QtCore import Qt

# MainWindow import moved to methods to avoid circular imports


class QueryHelpers:
    """Mixin class providing query assistance and validation functionality"""
    
    def validate_sql(self):
        """
        Validate SQL syntax without executing the query.
        
        Uses DuckDB's EXPLAIN feature to validate query structure and syntax
        without actually running the query. Provides visual feedback through
        validation status label and detailed error messages.
        
        Features:
        - Auto-fixes common issues (double quotes → single quotes)
        - Handles CTEs and complex queries
        - Integrates with parquet file mapping
        - Shows validation status with colored indicators
        
        Called by: Validate button, Ctrl+Shift+V shortcut
        """
        # Import MainWindow here to avoid circular imports
        from Simplisql import MainWindow

        if getattr(self, 'editor_mode', 'sql') == 'python':
            if hasattr(self, 'validate_python_script'):
                return self.validate_python_script()
            MainWindow.show_styled_message_box(
                self,
                "Validation",
                "Python validation is not available in this build.",
                icon=QMessageBox.Icon.Warning
            )
            return
        
        query = self.sql_text.toPlainText().strip()
        
        # Auto-fix: Replace double quotes with single quotes for file paths
        import re
        query = re.sub(r'"([A-Za-z]:[^"]+)"', r"'\1'", query)
        
        # Remove trailing semicolons for validation
        query = query.rstrip(';').strip()
        
        if not query:
            self.validation_status_label.setText("⚠ Empty Query")
            self.validation_status_label.setStyleSheet("color: #ff9800; font-size: 10px; font-weight: bold;")
            MainWindow.show_styled_message_box(
                self, 
                "Validation", 
                "SQL query is empty. Please enter a query to validate.",
                icon=QMessageBox.Icon.Warning
            )
            return
        
        if self.conn is None:
            MainWindow.show_styled_message_box(
                self, 
                "Error", 
                "Database connection is not established!",
                icon=QMessageBox.Icon.Critical
            )
            return
        
        try:
            # Prepare the query (same logic as execute_query)
            modified_query = query.replace("\\", "/")
            
            # Handle CTEs
            cte_names = set()
            cte_pattern = r"(?i)(?:WITH|,)\s+(\w+)\s+AS\s*\("
            for cte in re.findall(cte_pattern, query):
                cte_names.add(cte.lower())
            
            # Replace table names with parquet files
            if "read_parquet(" not in modified_query.lower():
                for display_name in self.uploaded_display_names:
                    parquet_path = os.path.join(self.doc_dir, f"{display_name}.parquet").replace("\\", "/")
                    pattern = r'\b' + re.escape(display_name) + r'\b'
                    
                    def replacer(match):
                        pos = match.start()
                        before = modified_query[:pos].lower()
                        # Skip if it's a CTE name
                        if any(f"with {cte}" in before or f", {cte}" in before for cte in cte_names):
                            return match.group(0)
                        return f"read_parquet('{parquet_path}')"
                    
                    modified_query = re.sub(pattern, replacer, modified_query, flags=re.IGNORECASE)
            
            # Use EXPLAIN to validate without executing
            validation_query = f"EXPLAIN {modified_query}"
            
            # Try to prepare the query
            self.conn.execute(validation_query)
            
            # If we get here, the query is valid
            self.validation_status_label.setText("✓ Valid SQL")
            self.validation_status_label.setStyleSheet("color: #4caf50; font-size: 10px; font-weight: bold;")
            
            # Show success message with query preview
            preview = query[:200] + "..." if len(query) > 200 else query
            MainWindow.show_styled_message_box(
                self,
                "✓ SQL Validation Successful",
                f"Your SQL query is valid and ready to execute!\n\nQuery preview:\n{preview}",
                icon=QMessageBox.Icon.Information,
                text_color='#4caf50'
            )
            
        except duckdb.ParserException as e:
            # Syntax error
            self.validation_status_label.setText("✗ Syntax Error")
            self.validation_status_label.setStyleSheet("color: #f44336; font-size: 10px; font-weight: bold;")
            
            error_msg = str(e)
            # Try to extract specific error details
            error_lines = error_msg.split('\n')
            main_error = error_lines[0] if error_lines else str(e)
            
            MainWindow.show_styled_message_box(
                self,
                "✗ SQL Syntax Error",
                f"Syntax error detected:\n\n{main_error}\n\nPlease check your SQL syntax and try again.",
                icon=QMessageBox.Icon.Warning,
                text_color='#f44336'
            )
            
        except duckdb.CatalogException as e:
            # Table or column not found
            self.validation_status_label.setText("⚠ Warning")
            self.validation_status_label.setStyleSheet("color: #ff9800; font-size: 10px; font-weight: bold;")
            
            error_text = str(e)
            MainWindow.show_styled_message_box(
                self,
                "⚠ Validation Warning",
                f"Warning: {error_text}\n\nThis might be OK if you're using subqueries or CTEs.\nDouble-check your table and column names.",
                icon=QMessageBox.Icon.Warning,
                text_color='#ff9800'
            )
            
        except Exception as e:
            # Other errors
            self.validation_status_label.setText("⚠ Check Query")
            self.validation_status_label.setStyleSheet("color: #ff9800; font-size: 10px; font-weight: bold;")
            
            MainWindow.show_styled_message_box(
                self,
                "Validation Error",
                f"Unable to fully validate query:\n\n{str(e)}\n\nThe query might still work, but please review it carefully.",
                icon=QMessageBox.Icon.Warning
            )

    def show_query_templates(self):
        """
        Show a dialog with pre-built query templates.
        
        Displays a comprehensive library of SQL query templates for common operations:
        - Basic SELECT statements
        - Filtering and aggregation
        - JOINs (INNER, LEFT)
        - Window functions
        - CTEs
        - CASE statements
        
        Users can browse templates, preview them, and insert into the SQL editor.
        
        Called by: Query Templates button/menu
        """
        templates = {
            "Basic SELECT All": "SELECT * FROM table_name\nLIMIT 100;",
            
            "SELECT Specific Columns": "SELECT column1, column2, column3\nFROM table_name\nLIMIT 100;",
            
            "SELECT with WHERE": "SELECT *\nFROM table_name\nWHERE column_name = 'value'\nLIMIT 100;",
            
            "COUNT Records": "SELECT COUNT(*) as total_records\nFROM table_name;",
            
            "GROUP BY with COUNT": "SELECT column_name, COUNT(*) as count\nFROM table_name\nGROUP BY column_name\nORDER BY count DESC\nLIMIT 100;",
            
            "GROUP BY with SUM": "SELECT \n    column_name,\n    SUM(amount_column) as total_amount,\n    COUNT(*) as count\nFROM table_name\nGROUP BY column_name\nORDER BY total_amount DESC\nLIMIT 100;",
            
            "INNER JOIN": "SELECT \n    a.*,\n    b.column_name\nFROM table1 as a\nINNER JOIN table2 as b\n    ON a.id = b.id\nLIMIT 100;",
            
            "LEFT JOIN": "SELECT \n    a.*,\n    b.column_name\nFROM table1 as a\nLEFT JOIN table2 as b\n    ON a.id = b.id\nLIMIT 100;",
            
            "DISTINCT Values": "SELECT DISTINCT column_name\nFROM table_name\nORDER BY column_name\nLIMIT 100;",
            
            "Date Range Filter": "SELECT *\nFROM table_name\nWHERE date_column >= '2024-01-01'\n  AND date_column < '2024-12-31'\nLIMIT 100;",
            
            "Top N Records": "SELECT *\nFROM table_name\nORDER BY column_name DESC\nLIMIT 10;",
            
            "Aggregations (Multiple)": "SELECT \n    column_name,\n    COUNT(*) as count,\n    SUM(amount) as total,\n    AVG(amount) as average,\n    MIN(amount) as minimum,\n    MAX(amount) as maximum\nFROM table_name\nGROUP BY column_name\nLIMIT 100;",
            
            "CASE Statement": "SELECT \n    column_name,\n    CASE \n        WHEN amount > 1000 THEN 'High'\n        WHEN amount > 100 THEN 'Medium'\n        ELSE 'Low'\n    END as category\nFROM table_name\nLIMIT 100;",
            
            "Subquery Example": "SELECT *\nFROM table_name\nWHERE column_name IN (\n    SELECT column_name\n    FROM other_table\n    WHERE condition = 'value'\n)\nLIMIT 100;",
            
            "WITH CTE (Common Table Expression)": "WITH filtered_data AS (\n    SELECT *\n    FROM table_name\n    WHERE condition = 'value'\n)\nSELECT *\nFROM filtered_data\nLIMIT 100;",
            
            "Find the Error in the file": "DROP TABLE IF EXISTS my_clean_table; \nCREATE TABLE my_clean_table AS\n SELECT * \nFROM read_csv_auto('file.csv', ignore_errors=true, store_rejects=true);\n\n \nSELECT * FROM reject_errors LIMIT 100;",
            
        }
        
        # Create dialog
        dlg = QDialog(self)
        self.apply_dark_dialog_styling(dlg)
        dlg.setWindowTitle("Query Templates")
        dlg.setMinimumSize(700, 500)
        
        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)
        
        info_label = QLabel("Select a template to insert into the SQL editor:")
        info_label.setStyleSheet("color: #d0d0d0; font-weight: bold; font-size: 12px;")
        layout.addWidget(info_label)
        
        # Create list widget for templates
        template_list = QListWidget()
        template_list.setStyleSheet("""
            QListWidget {
                background-color: #3c3f41;
                color: #ffffff;
                border: 2px solid #555555;
                padding: 4px;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 8px;
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
        
        for template_name in templates.keys():
            template_list.addItem(template_name)
        
        layout.addWidget(template_list)
        
        # Preview area
        preview_label = QLabel("Preview:")
        preview_label.setStyleSheet("color: #d0d0d0; font-weight: bold; font-size: 14px;")
        layout.addWidget(preview_label)
        
        preview_text = QTextEdit()
        preview_text.setReadOnly(True)
        preview_text.setMaximumHeight(150)
        preview_text.setStyleSheet("""
            QTextEdit {
                background-color: #2b2d30;
                color: #f0f0f0;
                border: 1px solid #555555;
                font-family: 'Consolas', monospace;
                font-size: 11px;
            }
        """)
        layout.addWidget(preview_text)
        
        # Update preview when selection changes
        def update_preview():
            current_item = template_list.currentItem()
            if current_item:
                template_name = current_item.text()
                preview_text.setPlainText(templates[template_name])
        
        template_list.currentItemChanged.connect(update_preview)
        template_list.itemDoubleClicked.connect(lambda: insert_and_close())
        
        # Buttons
        btn_row = QHBoxLayout()
        insert_btn = QPushButton("Insert Template")
        insert_btn.setStyleSheet("QPushButton { background-color: #2e7d32; color: white; padding: 6px 12px; }")
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("QPushButton { padding: 6px 12px; }")
        
        def insert_and_close():
            current_item = template_list.currentItem()
            if current_item:
                template_name = current_item.text()
                template_sql = templates[template_name]
                self.sql_text.setPlainText(template_sql)
                dlg.accept()
        
        insert_btn.clicked.connect(insert_and_close)
        cancel_btn.clicked.connect(dlg.reject)
        
        btn_row.addStretch()
        btn_row.addWidget(insert_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)
        
        # Select first item by default
        if template_list.count() > 0:
            template_list.setCurrentRow(0)
        
        dlg.exec()

    def show_sql_syntax_helper(self):
        """
        Show DuckDB SQL syntax helper with comprehensive function documentation.
        
        Displays an interactive reference guide for DuckDB SQL functions organized by category:
        - File reading functions (read_parquet, read_csv, read_json)
        - Aggregate functions (COUNT, SUM, AVG, etc.)
        - Date/time functions
        - String functions
        - Window functions
        - Type casting
        - Conditional logic
        - DuckDB-specific features
        
        Users can browse categories, view function syntax and examples, and insert
        functions directly into the SQL editor.
        
        Called by: SQL Syntax Helper button/menu
        """
        
        # Create comprehensive DuckDB function reference
        function_categories = {
            "📁 File Reading Functions": {
                "read_parquet('file.parquet')": 
                    "Read Parquet file directly in SQL\n"
                    "Example: SELECT * FROM read_parquet('data.parquet')",
                
                "read_csv('file.csv')": 
                    "Read CSV file with automatic detection\n"
                    "Example: SELECT * FROM read_csv('data.csv')",
                
                "read_csv_auto(...)": 
                    "Read CSV with advanced parameters for complex files\n"
                    "Syntax: SELECT * FROM read_csv_auto('file.csv', delim=',', header=True, nullstr='NA', ignore_errors=True, quote='\"', sample_size=20480)\n\n"
                    "Advanced Parameters:\n"
                    "• delim: The column separator (e.g., ',', ';', '|')\n"
                    "• header: Set to True if the first row contains column names\n"
                    "• nullstr: String that represents a NULL value (e.g., 'NULL', 'N/A')\n"
                    "• ignore_errors: Skip rows with formatting errors instead of stopping\n"
                    "• quote: Character used for quoted values (default '\"')\n"
                    "• escape: Character used to escape quotes within values\n"
                    "• sample_size: Number of rows to sample for type detection (default 20480)\n"
                    "• all_varchar: Force all columns to be read as strings to avoid type errors",
                
                "read_json('file.json')": 
                    "Read JSON file\n"
                    "Example: SELECT * FROM read_json('data.json')",
            },
            
            "�️ File Path Functions": {
                "FILE_BASENAME(filepath)": "Extract filename from full path\nExample: SELECT FILE_BASENAME('C:/Users/data.csv') → 'data.csv'\nUsage: SELECT FILE_BASENAME(file_path) FROM files",
                "FILE_DIRNAME(filepath)": "Extract directory path from full path\nExample: SELECT FILE_DIRNAME('C:/Users/data.csv') → 'C:/Users'\nUsage: SELECT FILE_DIRNAME(file_path) FROM files",
                "FILE_NAME_NO_EXT(filepath)": "Extract filename without extension\nExample: SELECT FILE_NAME_NO_EXT('C:/data.csv') → 'data'\nUsage: SELECT FILE_NAME_NO_EXT(file_path) FROM files",
                "FILE_EXTENSION(filepath)": "Extract file extension\nExample: SELECT FILE_EXTENSION('C:/data.csv') → '.csv'\nUsage: SELECT FILE_EXTENSION(file_path) FROM files",
            },
            
            "�📊 Aggregate Functions": {
                "COUNT(column)": "Count non-null values\nExample: SELECT COUNT(customer_id) FROM sales",
                "COUNT(*)": "Count all rows including nulls\nExample: SELECT COUNT(*) FROM orders",
                "COUNT(DISTINCT column)": "Count unique values\nExample: SELECT COUNT(DISTINCT product_id) FROM sales",
                "SUM(column)": "Sum numeric values\nExample: SELECT SUM(amount) FROM transactions",
                "AVG(column)": "Average of numeric values\nExample: SELECT AVG(price) FROM products",
                "MIN(column) / MAX(column)": "Minimum/Maximum value\nExample: SELECT MIN(price), MAX(price) FROM products",
                "STDDEV(column)": "Standard deviation\nExample: SELECT STDDEV(salary) FROM employees",
                "VARIANCE(column)": "Statistical variance\nExample: SELECT VARIANCE(sales_amount) FROM revenue",
            },
            
            "📅 Date/Time Functions": {
                "CURRENT_DATE": "Get current date\nExample: SELECT CURRENT_DATE",
                "CURRENT_TIMESTAMP": "Get current date and time\nExample: SELECT CURRENT_TIMESTAMP",
                "DATE_TRUNC('day', date_col)": "Truncate date to specified precision\nUnits: year, month, day, hour, minute, second\nExample: SELECT DATE_TRUNC('month', order_date) FROM orders",
                "DATE_PART('year', date_col)": "Extract part of date\nParts: year, month, day, hour, minute, second\nExample: SELECT DATE_PART('year', created_at) FROM users",
                "EXTRACT(year FROM date_col)": "Extract date component (SQL standard)\nExample: SELECT EXTRACT(month FROM order_date) FROM orders",
                "AGE(date1, date2)": "Calculate interval between dates\nExample: SELECT AGE(end_date, start_date) FROM projects",
                "date_col + INTERVAL '1 day'": "Add time interval to date\nExample: SELECT order_date + INTERVAL '7 days' FROM orders",
                "date_col - INTERVAL '1 month'": "Subtract time interval\nExample: SELECT created_at - INTERVAL '30 days' FROM logs",
            },
            
            "🔤 String Functions": {
                "CONCAT(str1, str2, ...)": "Concatenate strings\nExample: SELECT CONCAT(first_name, ' ', last_name) FROM users",
                "||": "String concatenation operator\nExample: SELECT first_name || ' ' || last_name FROM users",
                "SUBSTRING(string, start, length)": "Extract substring\nExample: SELECT SUBSTRING(product_code, 1, 3) FROM products",
                "UPPER(string) / LOWER(string)": "Convert case\nExample: SELECT UPPER(email) FROM users",
                "TRIM(string)": "Remove leading/trailing spaces\nExample: SELECT TRIM(customer_name) FROM customers",
                "REPLACE(string, from, to)": "Replace substring\nExample: SELECT REPLACE(phone, '-', '') FROM contacts",
                "LENGTH(string)": "String length\nExample: SELECT LENGTH(description) FROM products",
                "SPLIT_PART(string, delimiter, index)": "Split string and get part\nExample: SELECT SPLIT_PART(email, '@', 2) FROM users",
                "LIKE / ILIKE": "Pattern matching (ILIKE is case-insensitive)\nExample: SELECT * FROM products WHERE name ILIKE '%phone%'",
                "REGEXP_MATCHES(string, pattern)": "Regular expression matching\nExample: SELECT * FROM logs WHERE message REGEXP_MATCHES('error|warning')",
            },
            
            "🔄 Type Casting": {
                "CAST(value AS type)": "Standard type casting\nExample: SELECT CAST(price AS INTEGER) FROM products",
                "TRY_CAST(value AS type)": "Safe casting (returns NULL on error)\nExample: SELECT TRY_CAST(user_input AS INTEGER) FROM data",
                "::type": "DuckDB shorthand casting\nExample: SELECT price::INTEGER FROM products",
                "Common types": "INTEGER, BIGINT, DOUBLE, VARCHAR, DATE, TIMESTAMP, BOOLEAN\nExample: SELECT amount::DOUBLE, date_str::DATE FROM sales",
            },
            
            "🪟 Window Functions": {
                "ROW_NUMBER() OVER (...)": "Assign unique row numbers\nExample: SELECT ROW_NUMBER() OVER (ORDER BY sales DESC) FROM revenue",
                "RANK() OVER (...)": "Ranking with gaps for ties\nExample: SELECT RANK() OVER (PARTITION BY category ORDER BY price) FROM products",
                "DENSE_RANK() OVER (...)": "Ranking without gaps\nExample: SELECT DENSE_RANK() OVER (ORDER BY score DESC) FROM students",
                "LAG(column, offset) OVER (...)": "Access previous row value\nExample: SELECT LAG(price, 1) OVER (ORDER BY date) FROM stock_prices",
                "LEAD(column, offset) OVER (...)": "Access next row value\nExample: SELECT LEAD(sales, 1) OVER (ORDER BY month) FROM monthly_sales",
                "FIRST_VALUE(column) OVER (...)": "First value in window\nExample: SELECT FIRST_VALUE(price) OVER (PARTITION BY category ORDER BY date) FROM prices",
                "PARTITION BY": "Define window partitions\nExample: SELECT SUM(amount) OVER (PARTITION BY customer_id) FROM orders",
            },
            
            "🔀 Data Operations": {
                "DISTINCT": "Remove duplicate rows\nExample: SELECT DISTINCT customer_id FROM orders",
                "UNION / UNION ALL": "Combine query results (UNION removes duplicates)\nExample: SELECT id FROM table1 UNION ALL SELECT id FROM table2",
                "INTERSECT": "Return common rows between queries\nExample: SELECT id FROM table1 INTERSECT SELECT id FROM table2",
                "EXCEPT": "Return rows in first query but not second\nExample: SELECT id FROM all_ids EXCEPT SELECT id FROM processed_ids",
                "LIMIT n": "Limit number of rows returned\nExample: SELECT * FROM large_table LIMIT 1000",
                "OFFSET n": "Skip first n rows\nExample: SELECT * FROM data ORDER BY id LIMIT 100 OFFSET 200",
            },
            
            "🎯 Conditional Logic": {
                "CASE WHEN ... THEN ... END": "Conditional expressions\nExample: SELECT CASE WHEN price > 100 THEN 'Expensive' ELSE 'Cheap' END FROM products",
                "COALESCE(val1, val2, ...)": "Return first non-NULL value\nExample: SELECT COALESCE(phone, email, 'No contact') FROM customers",
                "NULLIF(val1, val2)": "Return NULL if values are equal\nExample: SELECT NULLIF(discount, 0) FROM sales",
                "IFNULL(value, replacement)": "Replace NULL with value\nExample: SELECT IFNULL(middle_name, '') FROM users",
            },
            
            "💾 DuckDB Specific": {
                "COPY (...) TO 'file.csv'": "Export query results to file\nExample: COPY (SELECT * FROM table) TO 'output.csv' (HEADER, DELIMITER ',')",
                "DESCRIBE table_name": "Show table schema\nExample: DESCRIBE my_table",
                "SHOW TABLES": "List all tables\nExample: SHOW TABLES",
                "PRAGMA table_info('table')": "Get detailed table info\nExample: PRAGMA table_info('customers')",
                "PRAGMA threads=8": "Set number of threads\nExample: PRAGMA threads=8",
                "PRAGMA memory_limit='16GB'": "Set memory limit\nExample: PRAGMA memory_limit='16GB'",
                "Drop table_name if exists": "Drop table if it exists\nExample: DROP TABLE IF EXISTS temp_table",
                "Drop table_name COOL if exists;\n\n\nCREATE TABLE COOL AS ": "Create a new table\nExample: CREATE TABLE new_table (id INTEGER, name VARCHAR, created_at DATE);"
            },
        }
        
        # Create dialog
        dlg = QDialog(self)
        self.apply_dark_dialog_styling(dlg)
        dlg.setWindowTitle("SQL Syntax Helper - DuckDB Functions")
        dlg.setMinimumSize(850, 600)
        
        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)
        
        # Determine theme colors
        is_dark = getattr(self, 'current_theme', 'dark') == 'dark'
        
        if is_dark:
            info_color = "#d0d0d0"
            label_color = "#d0d0d0"
            combo_bg = "#3c3f41"
            combo_fg = "#ffffff"
            combo_border = "#555555"
            list_bg = "#3c3f41"
            list_fg = "#ffffff"
            list_border = "#555555"
            list_selected_bg = "#0d7377"
            list_selected_fg = "#ffffff"
            list_hover_bg = "#4a5568"
            details_bg = "#2b2d30"
            details_fg = "#f0f0f0"
            details_border = "#555555"
            heading_color = "#0d7377"
        else:  # Light theme
            info_color = "#333333"
            label_color = "#333333"
            combo_bg = "#ffffff"
            combo_fg = "#000000"
            combo_border = "#cccccc"
            list_bg = "#ffffff"
            list_fg = "#000000"
            list_border = "#cccccc"
            list_selected_bg = "#0d7377"
            list_selected_fg = "#ffffff"
            list_hover_bg = "#e0e0e0"
            details_bg = "#f5f5f5"
            details_fg = "#000000"
            details_border = "#cccccc"
            heading_color = "#0d7377"
        
        # Info label
        info_label = QLabel("📚 DuckDB Function Reference - Click a function to see syntax and examples")
        info_label.setStyleSheet(f"color: {info_color}; font-weight: bold; font-size: 13px; padding: 8px;")
        layout.addWidget(info_label)
        
        # Create horizontal layout for category list and details
        content_layout = QHBoxLayout()
        
        # Left side: Category and function list
        from PyQt6.QtWidgets import QWidget
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        category_label = QLabel("Select Category:")
        category_label.setStyleSheet(f"color: {label_color}; font-weight: bold; font-size: 14px;")
        left_layout.addWidget(category_label)
        
        category_combo = QComboBox()
        category_combo.addItems(list(function_categories.keys()))
        category_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {combo_bg};
                color: {combo_fg};
                border: 2px solid {combo_border};
                padding: 6px;
                font-size: 12px;
            }}
            QComboBox:hover {{
                border: 2px solid #0d7377;
            }}
            QComboBox::drop-down {{
                border: 0px;
            }}
        """)
        left_layout.addWidget(category_combo)
        
        function_label = QLabel("Functions:")
        function_label.setStyleSheet(f"color: {label_color}; font-weight: bold; font-size: 14px; margin-top: 10px;")
        left_layout.addWidget(function_label)
        
        function_list = QListWidget()
        function_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {list_bg};
                color: {list_fg};
                border: 2px solid {list_border};
                padding: 4px;
                font-size: 12px;
                font-family: 'Consolas', monospace;
            }}
            QListWidget::item {{
                padding: 8px;
                border-radius: 3px;
            }}
            QListWidget::item:selected {{
                background-color: {list_selected_bg};
                color: {list_selected_fg};
                font-weight: bold;
            }}
            QListWidget::item:hover {{
                background-color: {list_hover_bg};
            }}
        """)
        left_layout.addWidget(function_list)
        
        # Right side: Details
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        details_label = QLabel("Details & Examples:")
        details_label.setStyleSheet(f"color: {label_color}; font-weight: bold; font-size: 14px;")
        right_layout.addWidget(details_label)
        
        details_text = QTextEdit()
        details_text.setReadOnly(True)
        details_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {details_bg};
                color: {details_fg};
                border: 2px solid {details_border};
                font-family: 'Consolas', monospace;
                font-size: 12px;
                padding: 10px;
                line-height: 1.5;
            }}
        """)
        right_layout.addWidget(details_text)
        
        # Add to content layout
        content_layout.addWidget(left_widget, 1)
        content_layout.addWidget(right_widget, 2)
        layout.addLayout(content_layout)
        
        # Update function list when category changes
        def update_function_list():
            function_list.clear()
            category = category_combo.currentText()
            if category in function_categories:
                for func_name in function_categories[category].keys():
                    function_list.addItem(func_name)
                if function_list.count() > 0:
                    function_list.setCurrentRow(0)
        
        # Update details when function is selected
        def update_details():
            current_item = function_list.currentItem()
            if current_item:
                func_name = current_item.text()
                category = category_combo.currentText()
                if category in function_categories and func_name in function_categories[category]:
                    details = function_categories[category][func_name]
                    formatted_details = f"<h3 style='color: {heading_color};'>{func_name}</h3>"
                    formatted_details += f"<pre style='color: {details_fg}; white-space: pre-wrap;'>{details}</pre>"
                    details_text.setHtml(formatted_details)
        
        category_combo.currentTextChanged.connect(update_function_list)
        function_list.currentItemChanged.connect(update_details)
        function_list.itemDoubleClicked.connect(lambda: insert_function_and_close())
        
        # Insert button
        def insert_function_and_close():
            current_item = function_list.currentItem()
            if current_item:
                func_name = current_item.text()
                # Insert function name at cursor position
                cursor = self.sql_text.textCursor()
                cursor.insertText(func_name)
                dlg.accept()
        
        # Buttons
        btn_row = QHBoxLayout()
        insert_btn = QPushButton("Insert Function")
        insert_btn.setStyleSheet("QPushButton { background-color: #2e7d32; color: white; padding: 8px 16px; }")
        insert_btn.clicked.connect(insert_function_and_close)
        
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("QPushButton { padding: 8px 16px; }")
        close_btn.clicked.connect(dlg.reject)
        
        btn_row.addStretch()
        btn_row.addWidget(insert_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
        
        # Initialize with first category
        update_function_list()
        
        dlg.exec()
