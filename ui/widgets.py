"""
UI Widgets Module
-----------------
Custom widgets and dialogs for SimplSQL.

Components:
- SearchDialog: Find and replace dialog for text editors
- CustomPlainTextEdit: SQL editor with autocomplete and search
"""

import re
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QCheckBox, QMessageBox, QPlainTextEdit, QApplication
)
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QTextCursor, QTextDocument, QKeyEvent

try:
    from PyQt6.QtWidgets import QCompleter
    from PyQt6.QtCore import QStringListModel
except ImportError:
    QCompleter = None
    QStringListModel = None


class SearchDialog(QDialog):
    """Search and Replace dialog for text editors"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_editor = parent
        self.init_ui()
        self.last_search_pos = 0
        
    def init_ui(self):
        self.setWindowTitle("Find & Replace")
        self.setModal(True)
        self.resize(400, 180)
        
        layout = QVBoxLayout()
        
        # Search section
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Find:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter text to find...")
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)
        
        # Replace section
        replace_layout = QHBoxLayout()
        replace_layout.addWidget(QLabel("Replace:"))
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("Enter replacement text...")
        replace_layout.addWidget(self.replace_input)
        layout.addLayout(replace_layout)
        
        # Options
        options_layout = QHBoxLayout()
        self.case_sensitive = QCheckBox("Case Sensitive")
        self.whole_word = QCheckBox("Whole Word")
        options_layout.addWidget(self.case_sensitive)
        options_layout.addWidget(self.whole_word)
        layout.addLayout(options_layout)
        
        # Shortcuts info
        shortcuts_label = QLabel("Shortcuts: Ctrl+F = Find, Ctrl+H = Replace, F3 = Next, Shift+F3 = Previous, Esc = Close")
        shortcuts_label.setStyleSheet("font-size: 9pt; color: #888888; font-style: italic;")
        layout.addWidget(shortcuts_label)
        
        # Buttons
        buttons_layout = QHBoxLayout()
        self.find_next_btn = QPushButton("Find Next")
        self.find_prev_btn = QPushButton("Find Previous") 
        self.replace_btn = QPushButton("Replace")
        self.replace_all_btn = QPushButton("Replace All")
        self.close_btn = QPushButton("Close")
        
        buttons_layout.addWidget(self.find_prev_btn)
        buttons_layout.addWidget(self.find_next_btn)
        buttons_layout.addWidget(self.replace_btn)
        buttons_layout.addWidget(self.replace_all_btn)
        buttons_layout.addWidget(self.close_btn)
        layout.addLayout(buttons_layout)
        
        self.setLayout(layout)
        
        # Apply styling
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
                border: 1px solid #555555;
            }
            QLabel {
                color: #ffffff;
                font-weight: bold;
                min-width: 60px;
            }
            QLineEdit {
                background-color: #3c3c3c;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 5px;
                font-size: 11pt;
            }
            QLineEdit:focus {
                border: 2px solid #0078d4;
            }
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 12px;
                font-weight: bold;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
            QCheckBox {
                color: #ffffff;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QCheckBox::indicator:unchecked {
                background-color: #3c3c3c;
                border: 1px solid #555555;
                border-radius: 2px;
            }
            QCheckBox::indicator:checked {
                background-color: #0078d4;
                border: 1px solid #0078d4;
                border-radius: 2px;
            }
            QCheckBox::indicator:checked::after {
                content: "✓";
                color: white;
                font-weight: bold;
            }
        """)
        
        # Connect signals
        self.find_next_btn.clicked.connect(self.find_next)
        self.find_prev_btn.clicked.connect(self.find_previous)
        self.replace_btn.clicked.connect(self.replace_current)
        self.replace_all_btn.clicked.connect(self.replace_all)
        self.close_btn.clicked.connect(self.close)
        self.search_input.returnPressed.connect(self.find_next)
        self.replace_input.returnPressed.connect(self.replace_current)
        
        # Focus on search input
        self.search_input.setFocus()
        
    def find_next(self):
        if not self.parent_editor or not self.search_input.text():
            return
            
        search_text = self.search_input.text()
        flags = QTextDocument.FindFlag(0)
        
        if self.case_sensitive.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if self.whole_word.isChecked():
            flags |= QTextDocument.FindFlag.FindWholeWords
            
        cursor = self.parent_editor.textCursor()
        found_cursor = self.parent_editor.document().find(search_text, cursor, flags)
        
        if found_cursor.isNull():
            # Not found from current position, try from beginning
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            found_cursor = self.parent_editor.document().find(search_text, cursor, flags)
            
        if not found_cursor.isNull():
            self.parent_editor.setTextCursor(found_cursor)
            self.parent_editor.ensureCursorVisible()
            return True
        return False
        
    def find_previous(self):
        if not self.parent_editor or not self.search_input.text():
            return
            
        search_text = self.search_input.text()
        flags = QTextDocument.FindFlag.FindBackward
        
        if self.case_sensitive.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if self.whole_word.isChecked():
            flags |= QTextDocument.FindFlag.FindWholeWords
            
        cursor = self.parent_editor.textCursor()
        found_cursor = self.parent_editor.document().find(search_text, cursor, flags)
        
        if found_cursor.isNull():
            # Not found from current position, try from end
            cursor.movePosition(QTextCursor.MoveOperation.End)
            found_cursor = self.parent_editor.document().find(search_text, cursor, flags)
            
        if not found_cursor.isNull():
            self.parent_editor.setTextCursor(found_cursor)
            self.parent_editor.ensureCursorVisible()
            return True
        return False
        
    def replace_current(self):
        if not self.parent_editor:
            return
            
        cursor = self.parent_editor.textCursor()
        if cursor.hasSelection():
            search_text = self.search_input.text()
            selected_text = cursor.selectedText()
            
            # Check if selected text matches search text
            if self.case_sensitive.isChecked():
                matches = selected_text == search_text
            else:
                matches = selected_text.lower() == search_text.lower()
                
            if matches:
                cursor.insertText(self.replace_input.text())
                self.find_next()  # Find next occurrence
                
    def replace_all(self):
        if not self.parent_editor or not self.search_input.text():
            return
            
        search_text = self.search_input.text()
        replace_text = self.replace_input.text()
        
        # Get all text
        all_text = self.parent_editor.toPlainText()
        
        # Perform replacement
        if self.case_sensitive.isChecked():
            new_text = all_text.replace(search_text, replace_text)
        else:
            # Case insensitive replacement
            pattern = re.escape(search_text)
            new_text = re.sub(pattern, replace_text, all_text, flags=re.IGNORECASE)
            
        # Count replacements
        if self.case_sensitive.isChecked():
            count = all_text.count(search_text)
        else:
            count = len(re.findall(re.escape(search_text), all_text, re.IGNORECASE))
            
        # Set new text
        self.parent_editor.setPlainText(new_text)
        
        # Show message
        QMessageBox.information(self, "Replace All", f"Replaced {count} occurrence(s).")
        
    def showEvent(self, event):
        super().showEvent(event)
        # If there's selected text, use it as search term (only if search field is empty)
        if (self.parent_editor and self.parent_editor.textCursor().hasSelection() 
            and not self.search_input.text()):
            selected_text = self.parent_editor.textCursor().selectedText()
            self.search_input.setText(selected_text)
        self.search_input.setFocus()
        self.search_input.selectAll()
    
    def keyPressEvent(self, event):
        """Handle Escape key to close dialog"""
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)


class CustomPlainTextEdit(QPlainTextEdit):
    """PlainTextEdit with SQL auto-completion and search functionality"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self.setTabStopDistance(32)  # 4 spaces
        except AttributeError:
            self.setTabStopWidth(32)  # Older Qt versions

        self._completer = None
        self._completer_model = None
        self._completions = []

        # Seed with common SQL keywords and functions
        seed = [
            'SELECT', 'FROM', 'WHERE', 'GROUP BY', 'ORDER BY', 'LIMIT', 'JOIN', 'LEFT JOIN', 'RIGHT JOIN',
            'INNER JOIN', 'ON', 'AS', 'AND', 'OR', 'NOT', 'IN', 'IS', 'NULL', 'COUNT', 'SUM', 'AVG', 'MIN', 'MAX',
            'CREATE', 'DROP', 'WITH', 'CTE', 'UNION', 'EXCEPT', 'INTERSECT', 'INSERT', 'VALUES', 'UPDATE', 'DELETE',
            'DISTINCT', 'CAST', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'LIKE', 'ILIKE'
        ]
        self._completions = seed

        # Disable automatic inline completion popups per user preference (no popups desired)
        self._completer = None
        self._completer_model = None
        
        # Initialize search dialog
        self._search_dialog = None

    def keyPressEvent(self, event: QKeyEvent):
        # Handle Ctrl+F for search and Ctrl+H for replace
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_F:
                self.show_search_dialog(focus_replace=False)
                return
            elif event.key() == Qt.Key.Key_H:
                self.show_search_dialog(focus_replace=True)
                return
            
        # Handle F3 for Find Next (if search dialog exists and has search text)
        if event.key() == Qt.Key.Key_F3 and self._search_dialog is not None:
            if event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
                self._search_dialog.find_previous()
                return
            else:
                self._search_dialog.find_next()
                return
            
        # Tab inserts spaces
        if event.key() == Qt.Key.Key_Tab:
            self.insertPlainText("    ")  # 4 spaces
            return

        super().keyPressEvent(event)

        # Completions are disabled to avoid any popup UI.

    def show_search_dialog(self, focus_replace=False):
        """Show the search and replace dialog"""
        if self._search_dialog is None:
            self._search_dialog = SearchDialog(self)
        
        self._search_dialog.show()
        self._search_dialog.raise_()
        self._search_dialog.activateWindow()
        
        # Focus on replace field if requested
        if focus_replace:
            self._search_dialog.replace_input.setFocus()
            self._search_dialog.replace_input.selectAll()

    def update_completer_with_tables_and_columns(self, table_column_dict: dict):
        """Add table and column names to the completer model.

        table_column_dict: {table_display_name: [col1, col2, ...], ...}
        """
        additions = []
        for t, cols in table_column_dict.items():
            additions.append(t)
            if cols:
                additions.extend(cols)

        # Merge while preserving existing
        new_list = list(dict.fromkeys(self._completions + additions))
        self._completions = new_list
        try:
            if self._completer_model:
                self._completer_model.setStringList(new_list)
        except Exception:
            pass
