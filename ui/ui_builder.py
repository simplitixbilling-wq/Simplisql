"""
UI Builder Module

Provides comprehensive UI construction and theming functionality for the DuckDB Query Editor:
- Main UI initialization with header, editor, and results sections
- Action bar construction (grouped and simplified variants)
- Header button setup with menus
- Theme application and styling
- Dialog styling utilities

This module separates all UI construction logic from business logic, making the main
editor class focused on functionality rather than UI setup.

Dependencies:
    - self attributes: Various UI widgets, theme settings, connection handlers
    - External methods: All feature methods (execute_query, upload_files, etc.)
    - PyQt6: Full UI widget library
    - Utility functions: get_resource_path for PyInstaller compatibility

Author: Refactored from Simplsql.py Phase 11
"""

import os
import re
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFrame, QPushButton, QToolButton, QMenu,
    QComboBox, QLabel, QWidget, QTextEdit, QLineEdit, QTableView,
    QSizePolicy, QDialog, QHeaderView
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QPixmap, QAction, QShortcut, QKeySequence, QTextCursor
from ui.widgets import CustomPlainTextEdit
from utils.paths import get_resource_path


class UIBuilder:
    """Mixin class providing UI construction and theming functionality"""
    
    def build_grouped_action_bar(self, parent_layout: QVBoxLayout, button_styles: str):
        """
        Create a compact, grouped action bar with Files, Queries, Data Tools, and Dashboard.
        
        Features:
        - Primary Run and Load actions
        - Icon-only grouped buttons with menus
        - Saved queries dropdown
        - Theme toggle and AI Assistant buttons
        - Responsive layout with separators
        
        Args:
            parent_layout: Parent QVBoxLayout to insert the bar into
            button_styles: CSS string for button styling
            
        Called by: init_ui during main UI construction
        """
        try:
            bar = QFrame()
            bar.setObjectName("actionBar")
            # Store reference to bar for theme updates
            self.action_bar = bar
            # Slightly shorter bar and tighter paddings for compact look
            bar.setFixedHeight(36)
            # Initial styling - will be updated by apply_theme()
            bar.setStyleSheet("""
                #actionBar { background-color: #2b2d30; border-radius: 6px; }
                QToolButton, QPushButton { padding: 4px 8px; border-radius: 6px; font-size:13px; }
                QToolButton.iconButton, QToolButton { font-size:16px; }
                QToolButton::menu-indicator { image: none; }
                QToolButton:hover, QPushButton:hover { background-color: #3a3f42; }
                /* subtle vertical divider style used for separators inserted below */
                /* Divider color is applied by apply_theme() to match current theme */
            """)
            h = QHBoxLayout(bar)
            h.setContentsMargins(6, 4, 6, 4)
            h.setSpacing(6)

            # Primary actions
            run_btn = QPushButton("🚀 Run SQL")
            run_btn.setToolTip("Run current SQL (Ctrl+Enter)")
            run_btn.setStyleSheet(button_styles + "QPushButton { background-color: #2e7d32; color: white; padding:4px 10px;}" )
            run_btn.clicked.connect(self.execute_active_editor)
            if hasattr(self, 'run_buttons'):
                self.run_buttons.append(run_btn)

            load_btn = QPushButton("📊 View Data")
            load_btn.setToolTip("Load data with preview, filters and column pick")
            load_btn.setStyleSheet(button_styles + "QPushButton { background-color: #1b5e20; color: white; padding:4px 10px; }")
            load_btn.clicked.connect(self.load_data_advanced)

            h.addWidget(run_btn)
            h.addWidget(load_btn)

            # Helper to create a split-button style tool button with a menu
            def make_icon_menu_button(icon_text: str, tooltip: str, items: list[tuple[str, callable]]):
                """Create a compact icon-only QToolButton that shows a menu on click and a tooltip on hover."""
                btn = QToolButton()
                # Use the emoji/text as the visible icon-like content
                btn.setText(icon_text)
                btn.setToolTip(tooltip)
                btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
                # keep the button visually raised so :pressed styles apply
                btn.setAutoRaise(False)
                # compact square appearance like the dashboard button
                btn.setStyleSheet(button_styles + "QToolButton { background-color: #3a3d40; color: #e8e8e8; padding:4px; width:32px; height:28px; border-radius:6px; font-size:14px; } QToolButton:pressed { background-color: #2f3436; }")
                menu = QMenu(btn)
                # Apply dark menu styling so selections are visible in the theme
                menu.setStyleSheet(
                    "QMenu { background-color: #3c3f41; color: #ffffff; border: 2px solid #ffffff; padding:8px; border-radius:6px; }"
                    "QMenu::item { background-color: transparent; padding:8px 24px; }"
                    "QMenu::item:selected { background-color: #0d7377; color: #ffffff; font-weight: bold; }"
                )
                for text, slot in items:
                    act = QAction(text, btn)
                    act.triggered.connect(slot)
                    menu.addAction(act)
                btn.setMenu(menu)
                return btn

            # Files group (icon-only button, menu shown on click)
            files_btn = make_icon_menu_button("📁", "Files", [
                ("Upload Files (Multi-Select Supported)", self.upload_files),
                ("Delete File", self.delete_parquet),
                ("Refresh", self.refresh_parquet_files),
            ])

            # Queries group (icon-only button)
            queries_btn = make_icon_menu_button("📝", "Queries", [
                ("Save Query", self.show_save_query_popup),
                ("Delete Query", self.delete_selected_query),
            ])

            # Saved queries dropdown positioned next to Queries
            # Use existing queries combo if available, otherwise create new and assign to self
            if hasattr(self, 'query_dropdown') and isinstance(self.query_dropdown, QComboBox):
                saved_combo = self.query_dropdown
            else:
                saved_combo = QComboBox()
            # Reparent into the bar so it remains visible when old frames are hidden
            saved_combo.setParent(bar)
            saved_combo.setMinimumWidth(220)
            saved_combo.setMaximumWidth(280)
            # Ensure the editor references the combo that lives in the bar
            self.query_dropdown = saved_combo
            # Reconnect signals (safe if they were already connected; duplicate connections are acceptable)
            try:
                self.query_dropdown.currentIndexChanged.connect(self.load_selected_query)
                self.query_dropdown.activated.connect(self.load_selected_query)
            except Exception:
                pass

            # Data tools group (icon-only button)
            data_btn = make_icon_menu_button("🧰", "Data Tools", [
                ("Get Distinct", self.get_distinct_values),
                ("Pivot Table", self.pivot_table_dialog),
                ("Aggregate", self.perform_aggregation),
                ("Join Tables", self.join_tables),
                ("Split by Column", self.split_file_by_column),
                ("Fix CSV Columns", self.fix_csv_columns),
            ])

            # Theme menu (icon-only button)
            theme_btn = make_icon_menu_button("🎨", "Themes", [
                ("Dark Theme", lambda: self.set_theme("dark")),
                ("Light Theme", lambda: self.set_theme("light")),
            ])

            # AI Assistant button (icon-only button)
            ai_btn = QPushButton("")
            ai_btn.setToolTip("AI Assistant")
            ai_btn.setStyleSheet(button_styles + "QPushButton { background-color: #7b1fa2; color: white; padding:4px; width:32px; height:28px; font-size:14px; } QPushButton:pressed { background-color: #6a1b8f; }")
            ai_btn.setText("🤖")
            ai_btn.clicked.connect(self.show_ai_assistant)

            # Dashboard standalone action (icon-like button)
            # Icon-only Dashboard button (compact)
            dash_btn = QPushButton("")
            dash_btn.setToolTip("Dashboard")
            # Icon-only compact dashboard button
            dash_btn.setStyleSheet(button_styles + "QPushButton { background-color: #455a64; color: white; padding:4px; width:32px; height:28px; font-size:14px; } QPushButton:pressed { background-color: #3b4f56; }")
            dash_btn.setText("\U0001F4CA")
            dash_btn.clicked.connect(self.show_dashboard)

            # Charts button (icon-only button)
            charts_btn = QPushButton("")
            charts_btn.setToolTip("Charts")
            charts_btn.setStyleSheet(button_styles + "QPushButton { background-color: #ff6f00; color: white; padding:4px; width:32px; height:28px; font-size:14px; } QPushButton:pressed { background-color: #e65100; }")
            charts_btn.setText("📊")
            charts_btn.clicked.connect(self.show_charts)

            # Left-side groups: Files, Queries, Data Tools, Saved Queries, Load Data
            left_group = QWidget()
            left_layout = QHBoxLayout(left_group)
            left_layout.setContentsMargins(0, 0, 0, 0)
            left_layout.setSpacing(4)

            def add_with_divider_left(widget):
                # Insert a separator before the widget if this is not the first item
                if left_layout.count() > 0:
                    sep = QFrame()
                    sep.setFrameShape(QFrame.Shape.VLine)
                    sep.setFrameShadow(QFrame.Shadow.Plain)
                    # explicit white vertical separator for icon group - thicker for visibility
                    sep.setFixedWidth(3)
                    sep.setLineWidth(3)
                    sep.setStyleSheet("background-color: #ffffff; border: 1px solid #ffffff; margin:0 6px;")
                    left_layout.addWidget(sep)
                left_layout.addWidget(widget)

            add_with_divider_left(files_btn)
            add_with_divider_left(queries_btn)
            add_with_divider_left(data_btn)
            add_with_divider_left(theme_btn)
            # AI Assistant after Themes
            add_with_divider_left(ai_btn)
            # Dashboard after AI
            add_with_divider_left(dash_btn)
            # Charts after Dashboard
            add_with_divider_left(charts_btn)

            h.addWidget(left_group)

            # Spacer to push right-side actions to the far right
            spacer = QWidget()
            spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            h.addWidget(spacer)

            # Right-side: View Data, Run, then Saved Queries (saved query last)
            # Place View Data immediately before Run
            load_btn.setStyleSheet(button_styles + "QPushButton { background-color: #1b5e20; color: white; padding:6px 12px; }")
            h.addWidget(load_btn)
            run_btn.setText("🚀 Run")
            run_btn.setStyleSheet(button_styles + "QPushButton { background-color: #2e7d32; color: white; padding:6px 12px; }")
            h.addWidget(run_btn)
            # Saved queries dropdown to the far right (last)
            h.addWidget(saved_combo)

            # Insert under the main heading label
            parent_layout.insertWidget(1, bar)
        except Exception as e:
            print(f"Error building action bar: {e}")

    def add_header_action_buttons(self, header_layout):
        """
        Add action buttons (Files, Queries, Data Tools, Dashboard) to the header layout.
        
        Creates comprehensive header with all primary actions:
        - File operations
        - Query management
        - Data tools
        - Workflow management
        - Theme toggle
        - AI Assistant
        - Run/View buttons
        
        Args:
            header_layout: QHBoxLayout of the header frame
            
        Called by: init_ui during header construction
        """
        try:
            button_styles = """
            QPushButton, QToolButton {
                border: none;
                padding: 6px 10px;
                border-radius: 6px;
                font-weight: bold;
                color: white;
                font-size: 11px;
            }
            QPushButton:hover, QToolButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
            QPushButton:pressed, QToolButton:pressed {
                background-color: rgba(255, 255, 255, 0.2);
            }
            QToolButton::menu-indicator { image: none; }
            """

            # Helper to create a split-button style tool button with a menu
            def make_icon_menu_button(icon_text: str, tooltip: str, items: list[tuple[str, callable]]):
                """Create a compact icon-only QToolButton that shows a menu on click and a tooltip on hover."""
                btn = QToolButton()
                btn.setText(icon_text)
                btn.setToolTip(tooltip)
                btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
                btn.setAutoRaise(False)
                btn.setStyleSheet(button_styles + "QToolButton { background-color: rgba(255, 255, 255, 0.1); padding: 6px 8px; }")
                menu = QMenu(btn)
                menu.setStyleSheet(
                    "QMenu { background-color: #3c3f41; color: #ffffff; border: 2px solid #ffffff; padding:8px; border-radius:6px; }"
                    "QMenu::item { background-color: transparent; padding:8px 24px; }"
                    "QMenu::item:selected { background-color: #0d7377; color: #ffffff; font-weight: bold; }"
                )
                for text, slot in items:
                    act = QAction(text, btn)
                    act.triggered.connect(slot)
                    menu.addAction(act)
                btn.setMenu(menu)
                return btn

            # Files button
            files_btn = make_icon_menu_button("📁", "Files", [
                ("Upload Files (Multi-Select Supported)", self.upload_files),
                ("Delete File", self.delete_parquet),
                ("Refresh", self.refresh_parquet_files),
            ])

            # Queries button
            queries_btn = make_icon_menu_button("📝", "Queries", [
                ("Query Templates", self.show_query_templates),
                ("SQL Syntax Helper", self.show_sql_syntax_helper),
                ("Save Query", self.show_save_query_popup),
                ("Delete Query", self.delete_selected_query),
            ])

            # Data tools button
            data_btn = make_icon_menu_button("🧰", "Data Tools", [
                ("Get Distinct", self.get_distinct_values),
                ("Aggregate", self.perform_aggregation),
                ("Pivot Table", self.pivot_table_dialog),
                ("Split by Column", self.split_file_by_column),
                ("Join Tables", self.join_tables),
                ("Fix CSV Columns", self.fix_csv_columns),
            ])

            # Workflow button
            workflow_btn = make_icon_menu_button("⚙️", "Workflows", [
                ("Create Workflow", self.create_workflow_wizard),
                ("Manage Workflows", self.manage_workflows),
                ("Run Workflow", self.run_workflow_dialog),
            ])

            # Dashboard button
            dash_btn = QPushButton("📊")
            dash_btn.setToolTip("Dashboard")
            dash_btn.setStyleSheet(button_styles + "QPushButton { background-color: rgba(255, 255, 255, 0.1); padding: 7px 10px; }")
            dash_btn.clicked.connect(self.show_dashboard)

            # Charts button
            charts_btn = QPushButton("📈")
            charts_btn.setToolTip("Charts")
            charts_btn.setStyleSheet(button_styles + "QPushButton { background-color: rgba(255, 255, 255, 0.1); padding: 7px 10px; }")
            charts_btn.clicked.connect(self.show_charts)

            load_btn = QPushButton("📊 View")
            load_btn.setToolTip("Load data with preview, filters and column pick")
            load_btn.setStyleSheet(button_styles + "QPushButton { background-color: #1b5e20; color: white; padding: 6px 10px; }")
            load_btn.clicked.connect(self.load_data_advanced)

            # Saved queries dropdown
            if hasattr(self, 'query_dropdown') and isinstance(self.query_dropdown, QComboBox):
                saved_combo = self.query_dropdown
            else:
                saved_combo = QComboBox()
            saved_combo.setMinimumWidth(180)
            saved_combo.setMaximumWidth(220)
            saved_combo.setStyleSheet("""
                QComboBox { 
                    background-color: rgba(255, 255, 255, 0.1); 
                    color: white; 
                    border: 1px solid rgba(255, 255, 255, 0.2);
                    border-radius: 6px;
                    padding: 4px 8px;
                    font-size: 11px;
                }
                QComboBox:hover {
                    background-color: rgba(255, 255, 255, 0.15);
                }
                QComboBox::drop-down {
                    border: none;
                    width: 20px;
                }
                QComboBox::down-arrow {
                    border: none;
                    width: 0;
                    height: 0;
                    border-left: 5px solid transparent;
                    border-right: 5px solid transparent;
                    border-top: 5px solid white;
                }
            """)
            self.query_dropdown = saved_combo
            
            # Reconnect signals
            try:
                self.query_dropdown.currentIndexChanged.connect(self.load_selected_query)
                self.query_dropdown.activated.connect(self.load_selected_query)
            except Exception:
                pass
            
             # Primary action buttons (Run Query, View Data)
            run_btn = QPushButton("🚀 Run SQL")
            run_btn.setToolTip("Run current SQL (Ctrl+Enter)")
            run_btn.setStyleSheet(button_styles + "QPushButton { background-color: #2e7d32; color: white; padding: 6px 10px; }")
            run_btn.clicked.connect(self.execute_active_editor)
            if hasattr(self, 'run_buttons'):
                self.run_buttons.append(run_btn)

            # Run to Store button - wraps query with COPY() and saves to CSV
            run_to_store_btn = QPushButton("💾 Run to Store")
            run_to_store_btn.setToolTip("Run query and save results directly to CSV file")
            run_to_store_btn.setStyleSheet(button_styles + "QPushButton { background-color: #1976d2; color: white; padding: 6px 10px; }")
            run_to_store_btn.clicked.connect(self.execute_query_to_store)

            # Add buttons to header with separators
            def add_header_button_with_separator(button):
                # Add a white separator for icon buttons so it is visible across themes
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.VLine)
                sep.setFrameShadow(QFrame.Shadow.Plain)
                sep.setFixedWidth(3)
                sep.setLineWidth(3)
                sep.setStyleSheet("background-color: #ffffff; border: 1px solid #ffffff; margin: 0 6px;")
                header_layout.addWidget(sep)
                header_layout.addWidget(button)

            # Add all buttons to header
            add_header_button_with_separator(files_btn)
            add_header_button_with_separator(queries_btn) 
            add_header_button_with_separator(data_btn)
            add_header_button_with_separator(workflow_btn)
            add_header_button_with_separator(dash_btn)
            add_header_button_with_separator(charts_btn)
            
            
            # Compact theme toggle button (with separator like other icons)
            theme_toggle = QPushButton()
            theme_toggle.setToolTip("Toggle theme")
            theme_toggle.setFixedSize(36, 28)
            theme_toggle.setText("🌓")
            theme_toggle.setStyleSheet(button_styles + "QPushButton { background-color: rgba(255,255,255,0.06); color: white; padding:4px; border-radius:6px; }")
            theme_toggle.clicked.connect(self.toggle_theme)
            add_header_button_with_separator(theme_toggle)

            # AI Assistant button (purple with robot icon)
            ai_assistant_btn = QPushButton()
            ai_assistant_btn.setToolTip("AI Assistant - Chat with AI about your data, SQL queries, and workflows")
            ai_assistant_btn.setFixedSize(36, 28)
            ai_assistant_btn.setText("🤖")
            ai_assistant_btn.setStyleSheet(button_styles + "QPushButton { background-color: #7b1fa2; color: white; padding:4px; border-radius:6px; } QPushButton:hover { background-color: #9c27b0; }")
            ai_assistant_btn.clicked.connect(self.show_ai_assistant)
            add_header_button_with_separator(ai_assistant_btn)

            # Add View Data after AI button (helper will add a single separator before the button)
            add_header_button_with_separator(load_btn)

            # Add dropdown (with white separator directly before it for clear separation)
            sep_dropdown = QFrame()
            sep_dropdown.setFrameShape(QFrame.Shape.VLine)
            sep_dropdown.setFrameShadow(QFrame.Shadow.Plain)
            sep_dropdown.setFixedWidth(3)
            sep_dropdown.setLineWidth(3)
            sep_dropdown.setStyleSheet("background-color: #ffffff; border: 1px solid #ffffff; margin: 0 6px;")
            header_layout.addWidget(sep_dropdown)
            header_layout.addWidget(saved_combo)
            
            # Add Run button and Run to Store button last
            add_header_button_with_separator(run_btn)
            add_header_button_with_separator(run_to_store_btn)

        except Exception as e:
            print(f"Error adding header action buttons: {e}")

    def build_simplified_action_bar(self, parent_layout: QVBoxLayout):
        """
        Create a simplified action bar with just Run Query, View Data, and Saved Queries dropdown.
        
        Minimal action bar variant with only essential controls.
        
        Args:
            parent_layout: Parent QVBoxLayout to insert the bar into
            
        Called by: Alternative UI layouts (currently unused but available)
        """
        try:
            bar = QFrame()
            bar.setObjectName("actionBar")
            bar.setFixedHeight(36)
            bar.setStyleSheet("""
                #actionBar { background-color: #2b2d30; border-radius: 6px; }
                QPushButton { padding: 6px 12px; border-radius: 6px; font-size:13px; font-weight: bold; }
                QPushButton:hover { background-color: #3a3f42; }
                QComboBox { background-color: #313335; color: #d0d0d0; }
            """)
            h = QHBoxLayout(bar)
            h.setContentsMargins(6, 4, 6, 4)
            h.setSpacing(6)

            # Primary actions
            run_btn = QPushButton("🚀 Run SQL")
            run_btn.setToolTip("Run current SQL (Ctrl+Enter)")
            run_btn.setStyleSheet("QPushButton { background-color: #2e7d32; color: white; }")
            run_btn.clicked.connect(self.execute_active_editor)
            if hasattr(self, 'run_buttons'):
                self.run_buttons.append(run_btn)

            load_btn = QPushButton("📊 View Data")
            load_btn.setToolTip("Load data with preview, filters and column pick")
            load_btn.setStyleSheet("QPushButton { background-color: #1b5e20; color: white; }")
            load_btn.clicked.connect(self.load_data_advanced)

            h.addWidget(run_btn)
            h.addWidget(load_btn)

            # Spacer to push saved queries to the right
            spacer = QWidget()
            spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            h.addWidget(spacer)

            # Saved queries dropdown
            if hasattr(self, 'query_dropdown') and isinstance(self.query_dropdown, QComboBox):
                saved_combo = self.query_dropdown
            else:
                saved_combo = QComboBox()
            saved_combo.setParent(bar)
            saved_combo.setMinimumWidth(220)
            saved_combo.setMaximumWidth(280)
            self.query_dropdown = saved_combo
            
            # Reconnect signals
            try:
                self.query_dropdown.currentIndexChanged.connect(self.load_selected_query)
                self.query_dropdown.activated.connect(self.load_selected_query)
            except Exception:
                pass

            h.addWidget(saved_combo)

            # Insert under the header
            parent_layout.insertWidget(1, bar)
        except Exception as e:
            print(f"Error building simplified action bar: {e}")

    def init_ui(self):
        """
        Initialize the complete user interface.
        
        Constructs all UI elements:
        - Header with branding and action buttons
        - SQL editor panel
        - Results/data preview panel
        - Filter controls
        - Status labels
        - Keyboard shortcuts
        
        This is the main UI entry point called from __init__.
        """
        main_layout = QVBoxLayout(self)
        
        # Attractive Header Bar
        header = QFrame()
        header.setObjectName("appHeader")
        header.setFixedHeight(64)
        header.setStyleSheet("""
            QFrame#appHeader {
                background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #263238, stop:1 #1b2a2f);
                border-radius: 6px;
                margin: 4px 8px;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 6, 12, 6)

        # small colorful icon block with database icon
        icon_frame = QFrame()
        icon_frame.setFixedSize(40, 40)
        icon_frame.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #00bcd4, stop:1 #4caf50); border-radius:8px;")
        
        # Add database icon to the frame
        icon_layout = QVBoxLayout(icon_frame)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        db_icon = QLabel()
        # Load the PNG icon - using resource path for PyInstaller compatibility
        icon_path = get_resource_path("sql.png")
        
        if os.path.exists(icon_path):
            try:
                pixmap = QPixmap(icon_path)
                if not pixmap.isNull():
                    # Scale the icon to fit within the frame (e.g., 30x30 pixels)
                    scaled_pixmap = pixmap.scaled(30, 30, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    db_icon.setPixmap(scaled_pixmap)
                else:
                    db_icon.setText("🗄️")
                    db_icon.setStyleSheet("color: white; font-size: 20px; font-weight: bold;")
            except Exception:
                db_icon.setText("🗄️")
                db_icon.setStyleSheet("color: white; font-size: 20px; font-weight: bold;")
        else:
            # Fallback to emoji if image not found
            db_icon.setText("🗄️")
            db_icon.setStyleSheet("color: white; font-size: 20px; font-weight: bold;")
        
        db_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        db_icon.setStyleSheet("background: transparent;")
        icon_layout.addWidget(db_icon)
        
        header_layout.addWidget(icon_frame)

        # Add a white vertical separator between the icon and title
        icon_sep = QFrame()
        icon_sep.setFrameShape(QFrame.Shape.VLine)
        icon_sep.setFrameShadow(QFrame.Shadow.Plain)
        icon_sep.setFixedWidth(3)
        icon_sep.setLineWidth(3)
        # Explicit white line regardless of theme
        icon_sep.setStyleSheet("background-color: #ffffff; border: 1px solid #ffffff; margin: 0 10px;")
        header_layout.addWidget(icon_sep)

        title_col = QVBoxLayout()
        self.title_label = QLabel("SIMPLISQL")
        # Keep label backgrounds transparent; colors are applied by apply_theme()
        self.title_label.setStyleSheet("background: transparent; font-weight: 900; font-size: 16px; margin:0; padding:0;")
        self.title_label.setContentsMargins(0, 0, 0, 0)
        self.subtitle_label = QLabel("Run SQL · View Data · Build Dashboards · Create Charts")
        self.subtitle_label.setStyleSheet("background: transparent; font-size: 10px; margin:0; padding:0;")
        self.subtitle_label.setContentsMargins(0, 0, 0, 0)
        title_col.addWidget(self.title_label)
        title_col.addWidget(self.subtitle_label)
        header_layout.addLayout(title_col)

        header_layout.addStretch()

        # Add action buttons to header layout
        self.add_header_action_buttons(header_layout)

        # place the header frame at the top
        main_layout.addWidget(header)

        # All action buttons are now in the header - no separate action bar needed

        # (single grouped action bar already built above)
        self.load_saved_queries()

        # Left and Right Frames
        editor_layout = QHBoxLayout()
        main_layout.addLayout(editor_layout)
        

        # Left Frame (SQL Query Editor)
        self.left_frame = QFrame()
        left_layout = QVBoxLayout(self.left_frame)
        editor_layout.addWidget(self.left_frame, 1)  # Expandable
        
    # (Toggle button moved below results table)

        # SQL Query label with validation status
        sql_header_row = QHBoxLayout()
        self.sql_text_label = QLabel("SQL Query:")
        sql_header_row.addWidget(self.sql_text_label)

        self.editor_mode_combo = QComboBox()
        self.editor_mode_combo.addItems(["SQL Notepad", "Python Notepad"])
        self.editor_mode_combo.setMaximumWidth(150)
        self.editor_mode_combo.currentTextChanged.connect(self.on_editor_mode_selector_changed)
        sql_header_row.addWidget(self.editor_mode_combo)
        
        # Validation status indicator
        self.validation_status_label = QLabel("✓ Ready")
        self.validation_status_label.setStyleSheet("color: #4caf50; font-size: 10px; font-weight: bold;")
        sql_header_row.addWidget(self.validation_status_label)
        
        # Validate button
        self.validate_btn = QPushButton("🔍 Check SQL")
        self.validate_btn.setToolTip("Validate SQL syntax (Ctrl+Shift+V)")
        self.validate_btn.setMaximumWidth(100)
        self.validate_btn.setStyleSheet("""
            QPushButton {
                background-color: #1976d2;
                color: white;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1565c0;
            }
        """)
        self.validate_btn.clicked.connect(self.validate_sql)
        sql_header_row.addWidget(self.validate_btn)
        sql_header_row.addStretch()
        left_layout.addLayout(sql_header_row)

        self.sql_text = CustomPlainTextEdit()
        self.sql_text.setFont(QFont("Consolas", 12))
        # Connect text changed signal for real-time validation indicator
        self.sql_text.textChanged.connect(self.on_sql_text_changed)
        left_layout.addWidget(self.sql_text)    

        # Set up Ctrl+Enter shortcut
        self.run_shortcut = QShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_Return), self.sql_text)
        self.run_shortcut.activated.connect(self.execute_active_editor)
        
        # Shortcut for SQL validation
        self.validate_shortcut = QShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Modifier.SHIFT | Qt.Key.Key_V), self.sql_text)
        self.validate_shortcut.activated.connect(self.validate_sql)

        # Shortcut to toggle maximize/minimize results
        self.toggle_shortcut = QShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_M), self)
        self.toggle_shortcut.activated.connect(self.toggle_results_maximize)

        # Shortcut to comment selected lines (Ctrl + /)
        self.comment_shortcut = QShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_Slash), self.sql_text)
        self.comment_shortcut.activated.connect(self.comment_selected_lines)

        # Shortcut to uncomment selected lines (Ctrl + \)
        self.uncomment_shortcut = QShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_Backslash), self.sql_text)
        self.uncomment_shortcut.activated.connect(self.uncomment_selected_lines)

        # Inside UIBuilder.init_ui() in ui_builder.py
        self.save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self.save_shortcut.activated.connect(self.show_smart_save_dialog)

        # Install event filter on QTextEdit
        self.sql_text.installEventFilter(self)
        # No floating overlays/popups: do not connect cursor/scroll to any popup handlers

        # Right Frame (File List + Data Preview)
        right_frame = QFrame()
        right_layout = QVBoxLayout(right_frame)
        editor_layout.addWidget(right_frame, 1)  # Expandable


        self.file_dropdown_label = QLabel(f'Show File Loaded in path : {self.doc_dir}' )
        right_layout.addWidget(self.file_dropdown_label)

        self.file_dropdown = QComboBox()
        self.file_dropdown.setStyleSheet("QComboBox { background-color: #313335; color: #d0d0d0; }")  # Dark background
        self.file_dropdown.setMinimumWidth(160)
        # Allow the dropdown to expand to fill available width
        self.file_dropdown.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.file_dropdown.currentTextChanged.connect(self.Parquet_view_describe)

        # Small Excel export icon button next to the dropdown (right aligned)
        file_row = QHBoxLayout()
        file_row.setSpacing(6)
        # dropdown expands, export button stays compact to the right
        self.file_dropdown.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        file_row.addWidget(self.file_dropdown)
        self.excel_export_btn = QPushButton("")
        self.excel_export_btn.setToolTip("Export current view to CSV")
        self.excel_export_btn.setFixedSize(22, 22)
        self.excel_export_btn.setStyleSheet("QPushButton { background-color: #2e7d32; color: white; border-radius:4px; padding:0px; }")
        self.excel_export_btn.setText("\U0001F4C4")  # page-like icon
        # Use existing export_to_csv implementation
        self.excel_export_btn.clicked.connect(self.export_to_csv)
        # Add a small Save Parquet button next to the export icon to save current visible table to parquet in default folder
        self.save_parquet_btn = QPushButton("")
        self.save_parquet_btn.setToolTip("Save current view to Parquet (default folder)")
        self.save_parquet_btn.setFixedSize(22, 22)
        self.save_parquet_btn.setStyleSheet("QPushButton { background-color: #2196F3; color: white; border-radius:4px; padding:0px; }")
        self.save_parquet_btn.setText("\U0001F4BE")  # floppy disk icon
        self.save_parquet_btn.clicked.connect(self.save_current_view_to_parquet_default)
        
        # Toggle maximize/minimize results button - moved to be after save data button
        self.toggle_results_btn = QPushButton("🗗")
        self.toggle_results_btn.setToolTip("Toggle maximize/minimize results pane (Ctrl+M)")
        self.toggle_results_btn.setFixedSize(30, 26)
        self.toggle_results_btn.setStyleSheet("QPushButton { background-color: #607d8b; color: white; border-radius:4px; padding:4px 8px; }")
        self.toggle_results_btn.clicked.connect(self.toggle_results_maximize)
        
        # align icons to the right within the row
        file_row.addWidget(self.excel_export_btn, 0, Qt.AlignmentFlag.AlignRight)
        file_row.addWidget(self.save_parquet_btn, 0, Qt.AlignmentFlag.AlignRight)
        file_row.addWidget(self.toggle_results_btn, 0, Qt.AlignmentFlag.AlignRight)
        right_layout.addLayout(file_row)

        # self.results_frame_label = QLabel("Transaction Records:")
        # right_layout.addWidget(self.results_frame_label)

        # Per-column filter row
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter column:"))
        self.filter_column_combo = QComboBox()
        filter_row.addWidget(self.filter_column_combo)
        
        # Add filter operator combo
        self.filter_operator_combo = QComboBox()
        self.filter_operator_combo.addItems([
            "contains", "not contains", "equals", "not equals", 
            "starts with", "ends with", "greater than", "less than"
        ])
        self.filter_operator_combo.setCurrentText("contains")
        filter_row.addWidget(self.filter_operator_combo)
        
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Enter filter text (use commas for multiple values: val1, val2)")
        filter_row.addWidget(self.filter_input)
        self.filter_apply_btn = QPushButton("Apply")
        self.filter_clear_btn = QPushButton("Clear")
        self.enable_sorting_btn = QPushButton("🔀 Enable Sorting")
        self.enable_sorting_btn.setVisible(False)  # Initially hidden
        self.enable_sorting_btn.setToolTip("Enable table column sorting for large datasets (may cause temporary slowdown)")
        # Style will be set by apply_theme method with custom colors
        
        # Theme toggle will be placed in the header (compact) instead of the filter row
        filter_row.addWidget(self.filter_apply_btn)
        filter_row.addWidget(self.filter_clear_btn)
        filter_row.addWidget(self.enable_sorting_btn)
        right_layout.addLayout(filter_row)

        self.results_table = QTableView()
        # Table UX improvements
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectItems)
        self.results_table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.results_table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.results_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results_table.customContextMenuRequested.connect(self._on_table_context_menu)
        # Enable sorting by default
        self.results_table.setSortingEnabled(True)
        # Make header sections clickable so we can use header-click filtering (like Excel)
        try:
            header = self.results_table.horizontalHeader()
            header.setSectionsClickable(True)
            header.sectionClicked.connect(self.on_results_header_clicked)
        except Exception:
            pass
        # Resize behavior
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.results_table.horizontalHeader().setStretchLastSection(False)
        right_layout.addWidget(self.results_table)

        # wire up filter buttons and keyboard shortcuts
        self.filter_apply_btn.clicked.connect(self.apply_column_filter)
        self.filter_clear_btn.clicked.connect(self.clear_column_filter)
        self.enable_sorting_btn.clicked.connect(self.enable_sorting_manually)
        self.filter_input.returnPressed.connect(self.apply_column_filter)  # Enter key to apply filter

        self.transaction_count_label = QLabel("Total Transactions: 0")
        # Right-align the transaction/last-run info in the results area
        self.transaction_count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        # color is applied by apply_theme() so it adapts to dark/light themes
        self.transaction_count_label.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(self.transaction_count_label, 0, Qt.AlignmentFlag.AlignLeft)

        # Add the "Developed by Chandan S" label at the bottom
        self.developer_label = QLabel("Developed by Chandan S - V2")
        self.developer_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)  # Align right and bottom
        self.developer_label.setStyleSheet("""
            color: #00bcd4;
            font-weight: bold;
            font-size: 12px;
            padding: 4px 8px;
            background-color: rgba(0, 188, 212, 0.1);
            border-radius: 3px;
        """)
        main_layout.addWidget(self.developer_label)
        
        self.display_existing_files()
        self.display_existing_files()

        # Sync editor chrome (labels/placeholders/run buttons) with current mode.
        if hasattr(self, '_update_editor_mode_ui'):
            self._update_editor_mode_ui()

    # Overlay functionality removed — no popups or floating overlays are used per user request.

    def apply_theme(self):
        """
        Apply the current theme to all UI elements.
        
        Comprehensive theming including:
        - Main widget styling (background, colors, borders)
        - Input controls (text boxes, dropdowns)
        - Buttons and menus
        - Table styling
        - Header customization
        - Special element styling (action bar, theme toggle)
        
        Called by: init_ui, toggle_theme, set_theme
        """
        if not hasattr(self, 'themes'):
            return
            
        theme = self.themes[self.current_theme]

        # Decide a header background (we previously set header to light for both themes)
        # and compute an adaptive divider color based on header brightness so dividers contrast.
        try:
            header_bg = 'qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #e9eef2, stop:1 #dbe6ea)'
            # extract first hex color from gradient and compute perceived brightness
            m = re.search(r"#([0-9a-fA-F]{6})", header_bg)
            if m:
                hexcol = m.group(1)
                r = int(hexcol[0:2], 16)
                g = int(hexcol[2:4], 16)
                b = int(hexcol[4:6], 16)
                brightness = (r * 299 + g * 587 + b * 114) / 1000
                # if header is light, choose a dark divider; otherwise choose a light divider
                theme['divider'] = '#2f2f2f' if brightness > 130 else '#dcdcdc'
            else:
                theme['divider'] = theme.get('divider', '#dcdcdc')
        except Exception:
            theme['divider'] = theme.get('divider', '#dcdcdc')

        # Apply main widget styling
        main_style = f"""
            QWidget {{
                background-color: {theme['background']};
                color: {theme['text']};
                font-family: 'Segoe UI', Arial, sans-serif;
            }}
            QLineEdit, QTextEdit, QPlainTextEdit {{
                background-color: {theme['input_bg']};
                color: {theme['input_text']};
                border: 1px solid {theme['border']};
                border-radius: 4px;
                padding: 4px;
            }}
            QComboBox {{
                background-color: {theme['input_bg']};
                color: {theme['input_text']};
                border: 1px solid {theme['border']};
                border-radius: 4px;
                padding: 4px;
            }}
            QComboBox::drop-down {{
                border: none;
                background-color: {theme['button_bg']};
            }}
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['text']};
                border: 1px solid {theme['border']};
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover']};
            }}
            QPushButton:pressed {{
                background-color: {theme['button_pressed']};
            }}
            QTableView {{
                background-color: {theme['table_bg']};
                alternate-background-color: {theme['table_alt']};
                color: {theme['text']};
                gridline-color: {theme['border']};
                border: 1px solid {theme['border']};
                font-size: 13px;
            }}
            QHeaderView::section {{
                background-color: {theme['button_bg']};
                color: {theme['text']};
                border: 1px solid {theme['border']};
                padding: 8px 6px;
                font-weight: bold;
                font-size: 13px;
                text-align: center;
                min-height: 25px;
            }}
            QHeaderView::section:hover {{
                background-color: {theme['button_hover']};
            }}
            QMenu {{
                background-color: {theme['menu_bg']};
                color: {theme['menu_text']};
                border: 1px solid {theme['border']};
                padding: 6px;
                border-radius: 6px;
            }}
            QFrame[divider='true'] {{
                background: {theme['divider']};
            }}
            QMenu::item {{
                background-color: transparent;
                padding: 6px 24px;
            }}
            QMenu::item:selected {{
                background-color: {theme['menu_hover']};
                color: #ffffff;
            }}
            QLabel {{
                color: {theme['text']};
                background: transparent;
            }}
        """
        
        self.setStyleSheet(main_style)
        
        # Apply title and subtitle styling with theme-aware colors
        if hasattr(self, 'title_label'):
            # Title should always be high-contrast (white) for readability against header
            self.title_label.setStyleSheet(f"color: #ffffff; background: transparent; font-weight: 900; font-size: 16px;")
        if hasattr(self, 'subtitle_label'):
            # Use a muted version of text color appropriate for each theme
            if self.current_theme == 'dark':
                subtitle_color = "#ffffff"  # Light gray for dark theme
            else:
                subtitle_color = '#ffffff'  # Dark gray for light theme
            self.subtitle_label.setStyleSheet(f"color: {subtitle_color}; background: transparent; font-size: 10px;")

        # Ensure transaction count label is visible in both themes
        if hasattr(self, 'transaction_count_label'):
            # Use a slightly muted text color for the count so it remains readable
            if self.current_theme == 'dark':
                tx_color = "#ffffff"
            else:
                tx_color = "#222222"
            self.transaction_count_label.setStyleSheet(f"color: {tx_color}; font-weight: bold;")

        # Style the header background specifically so it contrasts with title text
        try:
            if self.current_theme == 'dark':
                header_bg = 'qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #e8e8e8, stop:1 #1b2a2f)'
                header_border = 'border: 2px solid #ffffff;'  # White border for dark theme
            else:
                # Lighter, subtler gradient for light theme
                header_bg = 'qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #e8e8e8, stop:1 #1b2a2f)'
                header_border = 'border: 2px solid #ffffff;'  # Black border for light theme
            # Apply to the header frame by overriding appHeader styling
            # We update the existing stylesheet by appending a rule specifically for QFrame#appHeader
            existing = self.styleSheet()
            header_rule = f"\nQFrame#appHeader {{ background: {header_bg}; {header_border} border-radius: 6px; margin: 4px 8px; }}\n"
            # If header rule already present, replace it; otherwise append
            if 'QFrame#appHeader' in existing:
                # naive replace: remove previous QFrame#appHeader block and append ours
                # (keeps things simple and robust for the current stylesheet structure)
                parts = existing.split('QFrame#appHeader')
                new_sheet = parts[0] + 'QFrame#appHeader' + ' ' + '{ background: ' + header_bg + '; ' + header_border + ' border-radius: 6px; margin: 4px 8px; }' + '\n'.join(parts[1:])
                self.setStyleSheet(new_sheet)
            else:
                self.setStyleSheet(existing + header_rule)
        except Exception:
            pass
        
        # Update theme button text and special button styling
        if hasattr(self, 'theme_toggle_btn'):
            if self.current_theme == "dark":
                self.theme_toggle_btn.setText("☀️ Light")
                self.theme_toggle_btn.setToolTip("Switch to light theme")
            else:
                self.theme_toggle_btn.setText("🌙 Dark") 
                self.theme_toggle_btn.setToolTip("Switch to dark theme")
                
            # Apply special styling for theme toggle button
            self.theme_toggle_btn.setStyleSheet("""
                QPushButton { 
                    background-color: #9C27B0; 
                    color: white; 
                    padding: 4px 8px; 
                    border-radius: 4px; 
                    font-weight: bold;
                }
                QPushButton:hover { 
                    background-color: #7B1FA2; 
                }
            """)
            
        # Apply special styling for enable sorting button
        if hasattr(self, 'enable_sorting_btn'):
            self.enable_sorting_btn.setStyleSheet("""
                QPushButton { 
                    background-color: #FF5722; 
                    color: white; 
                    padding: 4px 8px; 
                    border-radius: 4px; 
                    font-weight: bold;
                }
                QPushButton:hover { 
                    background-color: #E64A19; 
                }
            """)
            
        # Update main window theme if controller exists and is ready
        if (hasattr(self, 'controller') and self.controller and 
            hasattr(self.controller, 'apply_main_window_theme') and
            hasattr(self.controller, 'query_editor')):
            self.controller.apply_main_window_theme()
        
        # Apply theme-aware styling to action bar
        if hasattr(self, 'action_bar'):
            if self.current_theme == 'dark':
                action_bar_bg = '#f0f0f0'  # Light white for better visibility in dark theme
                action_bar_hover = '#e0e0e0'  # Slightly darker on hover
            else:
                action_bar_bg = '#e8e8e8'  # Light gray for light theme
                action_bar_hover = '#d4d4d4'  # Slightly darker gray on hover
            
            self.action_bar.setStyleSheet(f"""
                #actionBar {{ background-color: {action_bar_bg}; border-radius: 6px; }}
                QToolButton, QPushButton {{ padding: 4px 8px; border-radius: 6px; font-size:13px; }}
                QToolButton.iconButton, QToolButton {{ font-size:16px; }}
                QToolButton::menu-indicator {{ image: none; }}
                QToolButton:hover, QPushButton:hover {{ background-color: {action_bar_hover}; }}
            """)

    def apply_dark_dialog_styling(self, dialog: QDialog):
        """
        Apply comprehensive dark style to any QDialog.
        
        Provides consistent dark theme styling for all dialog windows
        created by the editor.
        
        Args:
            dialog: QDialog instance to style
            
        Called by: Various dialog creation methods throughout the application
        """
        try:
            dialog.setStyleSheet("""
                QDialog { 
                    background-color: #2b2b2b; 
                    color: #d0d0d0; 
                }
                QLabel { 
                    color: #d0d0d0; 
                    font-weight: normal;
                }
                QLineEdit, QPlainTextEdit, QComboBox { 
                    background-color: #313335; 
                    color: #d0d0d0; 
                    border: 1px solid #555555;
                    padding: 4px;
                    border-radius: 3px;
                }
                QPushButton { 
                    background-color: #454545; 
                    color: #d0d0d0; 
                    border: 1px solid #555555;
                    padding: 6px 12px;
                    border-radius: 3px;
                    font-weight: bold;
                }
                QPushButton:hover { 
                    background-color: #555555; 
                }
                QPushButton:pressed { 
                    background-color: #363636; 
                }
                QCheckBox {
                    color: #d0d0d0;
                }
                QCheckBox::indicator {
                    width: 16px;
                    height: 16px;
                    background-color: #313335;
                    border: 1px solid #555555;
                }
                QCheckBox::indicator:checked {
                    background-color: #4CAF50;
                    border: 1px solid #4CAF50;
                }
            """)
        except Exception:
            pass

    def comment_selected_lines(self):
        """
        Comments out the selected lines in the SQL editor by prepending '--'.
        If no text is selected, comments out the current line.
        """
        cursor = self.sql_text.textCursor()
        self._apply_line_prefix(cursor, "--")

    def uncomment_selected_lines(self):
        """
        Uncomments the selected lines in the SQL editor by removing '--' prefix.
        If no text is selected, uncomments the current line.
        """
        cursor = self.sql_text.textCursor()
        self._remove_line_prefix(cursor, "--")

    def _apply_line_prefix(self, cursor, prefix):
        """Helper to add a prefix to selected lines."""
        if not cursor.hasSelection():
            cursor.select(cursor.SelectionType.BlockUnderCursor)

        start_block_num = cursor.block().blockNumber()
        temp_cursor = QTextCursor(cursor)
        temp_cursor.setPosition(cursor.selectionEnd())
        end_block_num = temp_cursor.block().blockNumber()

        # Start from the beginning of the first selected block
        cursor.setPosition(cursor.selectionStart())
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)

        current_block_num = cursor.block().blockNumber()

        while current_block_num <= end_block_num and cursor.block().isValid():
            cursor.insertText(prefix)
            # Move to the start of the next block
            if current_block_num < end_block_num:
                cursor.movePosition(QTextCursor.MoveOperation.NextBlock)
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            else:
                break # Last block handled
            current_block_num = cursor.block().blockNumber() # Update current block number for loop condition

    def _remove_line_prefix(self, cursor, prefix):
        """Helper to remove a prefix from selected lines."""
        if not cursor.hasSelection():
            cursor.select(cursor.SelectionType.BlockUnderCursor)

        start_block_num = cursor.block().blockNumber()
        temp_cursor = QTextCursor(cursor)
        temp_cursor.setPosition(cursor.selectionEnd())
        end_block_num = temp_cursor.block().blockNumber()

        cursor.setPosition(cursor.selectionStart())
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)

        current_block_num = cursor.block().blockNumber()

        while current_block_num <= end_block_num and cursor.block().isValid():
            block_text = cursor.block().text()
            if block_text.startswith(prefix):
                # Select the prefix and delete it
                cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, len(prefix))
                cursor.deleteChar()
            # Move to the start of the next block
            if current_block_num < end_block_num:
                cursor.movePosition(QTextCursor.MoveOperation.NextBlock)
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            else:
                break # Last block handled
            current_block_num = cursor.block().blockNumber()

    def show_smart_save_dialog(self):
        """
        Triggers on Ctrl+S. Provides a list of existing queries to update 
        or an input field for a new query name.
        """
        query_text = self.get_current_query()
        if not query_text:
            return

        dialog = QDialog(self)
        self.apply_dark_dialog_styling(dialog) # Uses your existing styling
        dialog.setWindowTitle("Save / Update Query")
        dialog.setMinimumWidth(400)
        layout = QVBoxLayout(dialog)

        # Section 1: Update Existing
        layout.addWidget(QLabel("Update an existing query:"))
        existing_combo = QComboBox()
        existing_combo.addItem("-- Select to Overwrite --")
        # Accesses saved_queries loaded in DuckDBQueryEditor.__init__
        existing_combo.addItems(list(self.saved_queries.keys()))
        layout.addWidget(existing_combo)

        # Section 2: Save New
        layout.addWidget(QLabel("\nOR Enter a new name:"))
        new_name_input = QLineEdit()
        # Pre-fill with the currently selected query name if one is active
        if hasattr(self, 'query_dropdown'):
            current_name = self.query_dropdown.currentText()
            if current_name:
                new_name_input.setText(current_name)
        layout.addWidget(new_name_input)

        # Buttons
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Confirm Save")
        save_btn.setStyleSheet("background-color: #2e7d32; color: white;") # Match your 'Run' button
        cancel_btn = QPushButton("Cancel")
        
        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        def process_save():
            typed_name = new_name_input.text().strip()
            selected_name = existing_combo.currentText()

            # Priority: If user typed something new, use that. 
            # Otherwise, use the selection from the dropdown.
            final_name = typed_name if typed_name else (
                selected_name if selected_name != "-- Select to Overwrite --" else ""
            )

            if final_name:
                self.save_query(final_name, query_text) # Uses your existing save logic
                dialog.accept()
            else:
                from Simplisql import MainWindow
                MainWindow.show_styled_message_box(
                    dialog, "Warning", "Please provide a name for the query.", 
                    icon=QMessageBox.Icon.Warning
                )

        save_btn.clicked.connect(process_save)
        cancel_btn.clicked.connect(dialog.reject)
        
        dialog.exec()