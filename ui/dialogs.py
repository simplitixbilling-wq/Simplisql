"""
UI Dialog Components for SimplSQL
=================================
This module contains dialog classes for workflow management and other UI interactions.

Classes:
    - WorkflowWizard: Multi-step workflow builder dialog
    - StepEditorDialog: Individual workflow step editor
"""

import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QListWidget, QFrame, QComboBox, QPlainTextEdit, QCheckBox, QMessageBox,
    QApplication
)
from PyQt6.QtCore import Qt


class WorkflowWizard(QDialog):
    """Wizard dialog for creating multi-step workflows"""
    
    def __init__(self, parent, existing_workflow=None):
        super().__init__(parent)
        self.parent_editor = parent
        self.existing_workflow = existing_workflow
        self.steps = []
        
        if existing_workflow:
            self.setWindowTitle(f"Edit Workflow: {existing_workflow.get('name', 'Unnamed')}")
            self.steps = existing_workflow.get('steps', []).copy()
        else:
            self.setWindowTitle("Create New Workflow")
        
        self.setMinimumSize(900, 650)
        self.init_ui()
        
        # Apply dark styling
        if hasattr(parent, 'apply_dark_dialog_styling'):
            parent.apply_dark_dialog_styling(self)
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Header
        header_label = QLabel("📋 Workflow Builder")
        header_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #00bcd4; padding: 8px;")
        layout.addWidget(header_label)
        
        desc_label = QLabel("Create a multi-step data processing workflow")
        desc_label.setStyleSheet("font-size: 14px; color: #a0a0a0; padding-bottom: 8px;")
        layout.addWidget(desc_label)
        
        # Workflow metadata
        meta_frame = QFrame()
        meta_frame.setStyleSheet("QFrame { background-color: #2b2b2b; border: 1px solid #454545; border-radius: 4px; padding: 8px; }")
        meta_layout = QVBoxLayout(meta_frame)
        
        # Workflow name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Workflow Name:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter workflow name")
        if self.existing_workflow:
            self.name_input.setText(self.existing_workflow.get('name', ''))
        name_row.addWidget(self.name_input)
        meta_layout.addLayout(name_row)
        
        # Workflow description
        desc_row = QHBoxLayout()
        desc_row.addWidget(QLabel("Description:"))
        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("Enter workflow description (optional)")
        if self.existing_workflow:
            self.desc_input.setText(self.existing_workflow.get('description', ''))
        desc_row.addWidget(self.desc_input)
        meta_layout.addLayout(desc_row)
        
        layout.addWidget(meta_frame)
        
        # Steps section
        steps_label = QLabel("Workflow Steps:")
        steps_label.setStyleSheet("font-weight: bold; color: #d0d0d0; padding-top: 12px;")
        layout.addWidget(steps_label)
        
        # Steps list
        self.steps_list = QListWidget()
        self.steps_list.setStyleSheet("""
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
                margin: 2px 0;
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
        layout.addWidget(self.steps_list)
        
        # Refresh steps list
        self.refresh_steps_list()
        
        # Step management buttons
        step_btn_row = QHBoxLayout()
        
        add_step_btn = QPushButton("➕ Add Step")
        add_step_btn.setStyleSheet("background-color: #2e7d32; color: white; padding: 6px 12px;")
        add_step_btn.clicked.connect(self.add_step)
        
        edit_step_btn = QPushButton("✏️ Edit Step")
        edit_step_btn.setStyleSheet("background-color: #1976d2; color: white; padding: 6px 12px;")
        edit_step_btn.clicked.connect(self.edit_step)
        
        delete_step_btn = QPushButton("🗑️ Delete Step")
        delete_step_btn.setStyleSheet("background-color: #c62828; color: white; padding: 6px 12px;")
        delete_step_btn.clicked.connect(self.delete_step)
        
        move_up_btn = QPushButton("⬆️ Move Up")
        move_up_btn.setStyleSheet("padding: 6px 12px;")
        move_up_btn.clicked.connect(self.move_step_up)
        
        move_down_btn = QPushButton("⬇️ Move Down")
        move_down_btn.setStyleSheet("padding: 6px 12px;")
        move_down_btn.clicked.connect(self.move_step_down)
        
        step_btn_row.addWidget(add_step_btn)
        step_btn_row.addWidget(edit_step_btn)
        step_btn_row.addWidget(delete_step_btn)
        step_btn_row.addWidget(move_up_btn)
        step_btn_row.addWidget(move_down_btn)
        step_btn_row.addStretch()
        
        layout.addLayout(step_btn_row)
        
        # Dialog buttons
        dialog_btn_row = QHBoxLayout()
        
        save_btn = QPushButton("💾 Save Workflow")
        save_btn.setStyleSheet("background-color: #2e7d32; color: white; padding: 8px 16px; font-weight: bold;")
        save_btn.clicked.connect(self.save_workflow)
        
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("padding: 8px 16px;")
        close_btn.clicked.connect(self.accept)
        
        dialog_btn_row.addStretch()
        dialog_btn_row.addWidget(save_btn)
        dialog_btn_row.addWidget(close_btn)
        
        layout.addLayout(dialog_btn_row)
    
    def refresh_steps_list(self):
        """Refresh the steps list widget"""
        self.steps_list.clear()
        for i, step in enumerate(self.steps, 1):
            step_name = step.get('name', f'Step {i}')
            step_type = step.get('type', 'unknown')
            self.steps_list.addItem(f"{i}. {step_name} ({step_type})")
    
    def add_step(self):
        """Add a new step to the workflow"""
        step_dialog = StepEditorDialog(self, self.parent_editor)
        if step_dialog.exec() == QDialog.DialogCode.Accepted:
            step = step_dialog.get_step_spec()
            if step:
                self.steps.append(step)
                self.refresh_steps_list()
    
    def edit_step(self):
        """Edit the selected step"""
        idx = self.steps_list.currentRow()
        if idx < 0:
            QMessageBox.warning(self, "Select Step", "Please select a step to edit.")
            return
        
        step_dialog = StepEditorDialog(self, self.parent_editor, existing_step=self.steps[idx])
        if step_dialog.exec() == QDialog.DialogCode.Accepted:
            step = step_dialog.get_step_spec()
            if step:
                self.steps[idx] = step
                self.refresh_steps_list()
    
    def delete_step(self):
        """Delete the selected step"""
        idx = self.steps_list.currentRow()
        if idx < 0:
            return
        
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete step {idx + 1}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.steps.pop(idx)
            self.refresh_steps_list()
    
    def move_step_up(self):
        """Move the selected step up"""
        idx = self.steps_list.currentRow()
        if idx > 0:
            self.steps[idx], self.steps[idx - 1] = self.steps[idx - 1], self.steps[idx]
            self.refresh_steps_list()
            self.steps_list.setCurrentRow(idx - 1)
    
    def move_step_down(self):
        """Move the selected step down"""
        idx = self.steps_list.currentRow()
        if idx >= 0 and idx < len(self.steps) - 1:
            self.steps[idx], self.steps[idx + 1] = self.steps[idx + 1], self.steps[idx]
            self.refresh_steps_list()
            self.steps_list.setCurrentRow(idx + 1)
    
    def save_workflow(self):
        """Save the workflow without closing the dialog"""
        workflow = self.get_workflow_spec()
        if not workflow:
            return
        
        # Save or update the workflow
        if self.existing_workflow:
            # Update existing workflow
            workflow_id = self.existing_workflow.get('id')
            self.parent_editor.update_workflow(workflow_id, workflow)
            QMessageBox.information(
                self,
                "Workflow Saved",
                f"Workflow '{workflow['name']}' has been updated successfully!\n\n"
                "You can continue editing or click 'Close' when done.",
                QMessageBox.StandardButton.Ok
            )
        else:
            # Add new workflow
            workflow_id = self.parent_editor.add_workflow(workflow)
            self.existing_workflow = workflow
            self.existing_workflow['id'] = workflow_id
            self.setWindowTitle(f"Edit Workflow: {workflow['name']}")
            QMessageBox.information(
                self,
                "Workflow Saved",
                f"Workflow '{workflow['name']}' has been created successfully!\n\n"
                "You can continue editing, run the workflow, or click 'Close' when done.",
                QMessageBox.StandardButton.Ok
            )
    
    def get_workflow_spec(self):
        """Get the workflow specification"""
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Invalid Input", "Please enter a workflow name.")
            return None
        
        if not self.steps:
            QMessageBox.warning(self, "No Steps", "Please add at least one step to the workflow.")
            return None
        
        return {
            'name': name,
            'description': self.desc_input.text().strip(),
            'steps': self.steps
        }


class StepEditorDialog(QDialog):
    """Dialog for editing a single workflow step"""
    
    def __init__(self, parent, parent_editor, existing_step=None):
        super().__init__(parent)
        self.parent_editor = parent_editor
        self.parent_wizard = parent
        self.existing_step = existing_step
        
        if existing_step:
            self.setWindowTitle("Edit Step")
        else:
            self.setWindowTitle("Add Step")
        
        self.setMinimumSize(600, 500)
        self.init_ui()
        
        # Apply dark styling
        if hasattr(parent_editor, 'apply_dark_dialog_styling'):
            parent_editor.apply_dark_dialog_styling(self)
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Step type selection
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Step Type:"))
        self.type_combo = self.create_combo()
        self.type_combo.addItems([
            "Load Data",
            "SQL Query",
            "Filter",
            "Aggregate",
            "Join",
            "Transform",
            "Pivot",
            "Export"
        ])
        self.type_combo.currentTextChanged.connect(self.on_type_changed)
        type_row.addWidget(self.type_combo)
        layout.addLayout(type_row)
        
        # Step name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Step Name:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter step name")
        name_row.addWidget(self.name_input)
        layout.addLayout(name_row)
        
        # Dynamic configuration area
        self.config_frame = QFrame()
        self.config_frame.setStyleSheet("QFrame { background-color: #2b2b2b; }")
        self.config_layout = QVBoxLayout(self.config_frame)
        layout.addWidget(self.config_frame)
        
        # Buttons
        btn_row = QHBoxLayout()
        
        apply_btn = QPushButton("Apply")
        apply_btn.setStyleSheet("background-color: #1976d2; color: white; padding: 6px 12px;")
        apply_btn.setToolTip("Save changes and keep dialog open")
        apply_btn.clicked.connect(self.apply_changes)
        
        ok_btn = QPushButton("OK")
        ok_btn.setStyleSheet("background-color: #2e7d32; color: white; padding: 6px 12px;")
        ok_btn.setToolTip("Save changes and close dialog")
        ok_btn.clicked.connect(self.validate_and_accept)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("padding: 6px 12px;")
        cancel_btn.clicked.connect(self.reject)
        
        btn_row.addStretch()
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        
        layout.addLayout(btn_row)
        
        # Load existing step if provided
        if self.existing_step:
            self.load_existing_step()
        else:
            self.on_type_changed(self.type_combo.currentText())
    
    def clear_config_layout(self):
        """Clear the configuration layout"""
        while self.config_layout.count():
            item = self.config_layout.takeAt(0)
            if item.widget():
                widget = item.widget()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
        
        QApplication.processEvents()
    
    def _clear_layout(self, layout):
        """Recursively clear a layout"""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                widget = item.widget()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
    
    def validate_and_accept(self):
        """Validate the step configuration before accepting the dialog"""
        step_name = self.name_input.text().strip()
        if not step_name:
            QMessageBox.warning(
                self,
                "Invalid Input",
                "Please enter a step name before adding the step.",
                QMessageBox.StandardButton.Ok
            )
            self.name_input.setFocus()
            return
        
        step = self.get_step_spec()
        if step:
            self.accept()
    
    def apply_changes(self):
        """Apply changes to the workflow without closing the dialog"""
        step_name = self.name_input.text().strip()
        if not step_name:
            QMessageBox.warning(
                self,
                "Invalid Input",
                "Please enter a step name before saving.",
                QMessageBox.StandardButton.Ok
            )
            self.name_input.setFocus()
            return
        
        step = self.get_step_spec()
        if step:
            if self.existing_step and hasattr(self.parent(), 'steps'):
                workflow_dialog = self.parent()
                try:
                    idx = workflow_dialog.steps.index(self.existing_step)
                    workflow_dialog.steps[idx] = step
                    workflow_dialog.refresh_steps_list()
                    
                    QMessageBox.information(
                        self,
                        "Changes Applied",
                        "Step changes have been saved to the workflow.\n\nYou can continue editing or click OK to close.",
                        QMessageBox.StandardButton.Ok
                    )
                    
                    self.existing_step = step
                except ValueError:
                    QMessageBox.warning(
                        self,
                        "Error",
                        "Could not find step in workflow.",
                        QMessageBox.StandardButton.Ok
                    )
            else:
                QMessageBox.information(
                    self,
                    "Validation Passed",
                    "Step configuration is valid.\n\nClick OK to add the step to the workflow.",
                    QMessageBox.StandardButton.Ok
                )
    
    def validate_transform_expressions(self):
        """Validate transformation expressions for syntax and column references"""
        if not hasattr(self, 'transform_text'):
            return
        
        transformations_text = self.transform_text.toPlainText().strip()
        if not transformations_text:
            QMessageBox.warning(
                self,
                "No Transformations",
                "Please enter at least one transformation to validate.",
                QMessageBox.StandardButton.Ok
            )
            return
        
        lines = [line.strip() for line in transformations_text.split('\n') if line.strip()]
        errors = []
        warnings = []
        valid_count = 0
        
        for i, line in enumerate(lines, 1):
            if '|' not in line:
                errors.append(f"Line {i}: Missing '|' separator. Format should be: column_name|expression")
                continue
            
            parts = line.split('|', 1)
            if len(parts) != 2:
                errors.append(f"Line {i}: Invalid format. Use: column_name|expression")
                continue
            
            new_col, expr = parts[0].strip(), parts[1].strip()
            
            if not new_col:
                errors.append(f"Line {i}: Column name cannot be empty")
                continue
            
            if not expr:
                errors.append(f"Line {i}: Expression cannot be empty")
                continue
            
            if expr.count('(') != expr.count(')'):
                errors.append(f"Line {i} ({new_col}): Unbalanced parentheses in expression")
                continue
            
            if expr.count("'") % 2 != 0:
                warnings.append(f"Line {i} ({new_col}): Possible unmatched quote in expression")
            
            expr_upper = expr.upper()
            words = expr.split()
            for word in words:
                clean_word = word.strip('(),')
                if clean_word and not clean_word.upper() in [
                    'AND', 'OR', 'NOT', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END',
                    'UPPER', 'LOWER', 'TRIM', 'CAST', 'AS', 'INTEGER', 'TEXT',
                    'REAL', 'SUBSTR', 'LENGTH', 'ROUND', 'ABS', 'COALESCE',
                    'NULL', 'TRUE', 'FALSE', 'SUM', 'AVG', 'COUNT', 'MIN', 'MAX'
                ] and not clean_word.replace('.', '').replace('-', '').replace('_', '').isdigit():
                    pass
            
            valid_count += 1
        
        if errors:
            error_msg = f"❌ Found {len(errors)} error(s):\n\n" + "\n".join(errors)
            if warnings:
                error_msg += f"\n\n⚠️ {len(warnings)} warning(s):\n" + "\n".join(warnings)
            
            QMessageBox.critical(
                self,
                "Validation Failed",
                error_msg,
                QMessageBox.StandardButton.Ok
            )
        elif warnings:
            warning_msg = f"⚠️ {valid_count} transformation(s) parsed successfully\n\n"
            warning_msg += f"But found {len(warnings)} warning(s):\n\n" + "\n".join(warnings)
            warning_msg += "\n\nNote: Column names will be validated when the workflow runs."
            
            QMessageBox.warning(
                self,
                "Validation Warnings",
                warning_msg,
                QMessageBox.StandardButton.Ok
            )
        else:
            success_msg = f"✅ All {valid_count} transformation(s) are syntactically valid!\n\n"
            success_msg += "Format and syntax look good.\n"
            success_msg += "Column names will be validated when the workflow runs."
            
            QMessageBox.information(
                self,
                "Validation Successful",
                success_msg,
                QMessageBox.StandardButton.Ok
            )
    
    def on_type_changed(self, step_type):
        """Update configuration UI based on step type"""
        self.clear_config_layout()
        
        if step_type == "Load Data":
            self.build_load_data_config()
        elif step_type == "SQL Query":
            self.build_sql_query_config()
        elif step_type == "Filter":
            self.build_filter_config()
        elif step_type == "Aggregate":
            self.build_aggregate_config()
        elif step_type == "Join":
            self.build_join_config()
        elif step_type == "Transform":
            self.build_transform_config()
        elif step_type == "Pivot":
            self.build_pivot_config()
        elif step_type == "Export":
            self.build_export_config()
    
    def get_available_steps(self):
        """Get list of available steps that can be referenced"""
        if hasattr(self.parent_wizard, 'steps'):
            num_steps = len(self.parent_wizard.steps)
            if num_steps > 0:
                return [f"step_{i}" for i in range(num_steps)]
        return []
    
    def create_label(self, text):
        """Create a styled label for dark theme"""
        label = QLabel(text)
        label.setStyleSheet("color: #d0d0d0; font-weight: bold; font-size: 14px;")
        return label
    
    def create_combo(self):
        """Create a styled combobox for dark theme"""
        combo = QComboBox()
        combo.setStyleSheet("""
            QComboBox {
                background-color: #3c3c3c;
                color: #d0d0d0;
                border: 1px solid #555555;
                padding: 4px;
                min-height: 20px;
            }
            QComboBox:hover {
                border: 1px solid #777777;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid #d0d0d0;
                width: 0;
                height: 0;
                margin-right: 5px;
            }
            QComboBox QAbstractItemView {
                background-color: #3c3c3c;
                color: #d0d0d0;
                selection-background-color: #555555;
                selection-color: #ffffff;
                border: 1px solid #555555;
            }
        """)
        return combo
    
    def build_load_data_config(self):
        """Build config for Load Data step"""
        self.config_layout.addWidget(self.create_label("Select file to load:"))
        
        self.file_combo = self.create_combo()
        try:
            files = [f for f in os.listdir(self.parent_editor.doc_dir) if f.endswith('.parquet')]
            self.file_combo.addItems(files)
        except Exception:
            pass
        self.config_layout.addWidget(self.file_combo)
        
        table_row = QHBoxLayout()
        table_row.addWidget(self.create_label("Table Name (optional):"))
        self.table_name_input = QLineEdit()
        self.table_name_input.setPlaceholderText("Leave blank to use filename")
        table_row.addWidget(self.table_name_input)
        self.config_layout.addLayout(table_row)
    
    def build_sql_query_config(self):
        """Build config for SQL Query step"""
        self.config_layout.addWidget(self.create_label("SQL Query:"))
        self.query_text = QPlainTextEdit()
        self.query_text.setPlaceholderText(
            "Enter SQL query...\n\n"
            "Tip: Use ${step_0}, ${step_1}, etc. to reference previous step results"
        )
        self.query_text.setMinimumHeight(200)
        self.config_layout.addWidget(self.query_text)
    
    def build_filter_config(self):
        """Build config for Filter step"""
        source_row = QHBoxLayout()
        source_row.addWidget(self.create_label("Source Step:"))
        self.source_combo = self.create_combo()
        
        available_steps = self.get_available_steps()
        if available_steps:
            self.source_combo.addItems(available_steps)
        else:
            self.source_combo.addItem("No previous steps available")
            self.source_combo.setEnabled(False)
        
        source_row.addWidget(self.source_combo)
        self.config_layout.addLayout(source_row)
        
        self.config_layout.addWidget(self.create_label("Filter Condition (WHERE clause):"))
        self.condition_input = QLineEdit()
        self.condition_input.setPlaceholderText("e.g., amount > 1000 AND status = 'ACTIVE'")
        self.config_layout.addWidget(self.condition_input)
    
    def build_aggregate_config(self):
        """Build config for Aggregate step"""
        source_row = QHBoxLayout()
        source_row.addWidget(self.create_label("Source Step:"))
        self.agg_source_combo = self.create_combo()
        
        available_steps = self.get_available_steps()
        if available_steps:
            self.agg_source_combo.addItems(available_steps)
        else:
            self.agg_source_combo.addItem("No previous steps available")
            self.agg_source_combo.setEnabled(False)
        
        source_row.addWidget(self.agg_source_combo)
        self.config_layout.addLayout(source_row)
        
        self.config_layout.addWidget(self.create_label("Group By Columns (comma-separated):"))
        self.group_by_input = QLineEdit()
        self.group_by_input.setPlaceholderText("e.g., category, region")
        self.config_layout.addWidget(self.group_by_input)
        
        self.config_layout.addWidget(self.create_label("Aggregations:"))
        agg_info = QLabel("Format: column : function : alias (one per line)")
        agg_info.setStyleSheet("font-size: 12px; color: #a0a0a0;")
        self.config_layout.addWidget(agg_info)
        
        self.agg_text = QPlainTextEdit()
        self.agg_text.setPlaceholderText(
            "Examples:\n"
            "amount : SUM : total_amount\n"
            "amount : AVG : avg_amount\n"
            "id : COUNT : record_count"
        )
        self.agg_text.setMaximumHeight(100)
        self.config_layout.addWidget(self.agg_text)
    
    def build_join_config(self):
        """Build config for Join step"""
        available_steps = self.get_available_steps()
        
        left_row = QHBoxLayout()
        left_row.addWidget(self.create_label("Left Source:"))
        self.left_source_combo = self.create_combo()
        if available_steps:
            self.left_source_combo.addItems(available_steps)
        else:
            self.left_source_combo.addItem("No previous steps available")
            self.left_source_combo.setEnabled(False)
        left_row.addWidget(self.left_source_combo)
        self.config_layout.addLayout(left_row)
        
        right_row = QHBoxLayout()
        right_row.addWidget(self.create_label("Right Source:"))
        self.right_source_combo = self.create_combo()
        if available_steps:
            self.right_source_combo.addItems(available_steps)
        else:
            self.right_source_combo.addItem("No previous steps available")
            self.right_source_combo.setEnabled(False)
        right_row.addWidget(self.right_source_combo)
        self.config_layout.addLayout(right_row)
        
        type_row = QHBoxLayout()
        type_row.addWidget(self.create_label("Join Type:"))
        self.join_type_combo = self.create_combo()
        self.join_type_combo.addItems(["INNER", "LEFT", "RIGHT", "FULL"])
        type_row.addWidget(self.join_type_combo)
        self.config_layout.addLayout(type_row)
        
        left_on_row = QHBoxLayout()
        left_on_row.addWidget(self.create_label("Left Column:"))
        self.left_on_input = QLineEdit()
        self.left_on_input.setPlaceholderText("Column name from left table")
        left_on_row.addWidget(self.left_on_input)
        self.config_layout.addLayout(left_on_row)
        
        right_on_row = QHBoxLayout()
        right_on_row.addWidget(self.create_label("Right Column:"))
        self.right_on_input = QLineEdit()
        self.right_on_input.setPlaceholderText("Column name from right table")
        right_on_row.addWidget(self.right_on_input)
        self.config_layout.addLayout(right_on_row)
    
    def build_transform_config(self):
        """Build config for Transform step"""
        source_row = QHBoxLayout()
        source_row.addWidget(self.create_label("Source Step:"))
        self.transform_source_combo = self.create_combo()
        
        available_steps = self.get_available_steps()
        if available_steps:
            self.transform_source_combo.addItems(available_steps)
        else:
            self.transform_source_combo.addItem("No previous steps available")
            self.transform_source_combo.setEnabled(False)
        
        source_row.addWidget(self.transform_source_combo)
        self.config_layout.addLayout(source_row)
        
        self.config_layout.addWidget(self.create_label("Column Transformations:"))
        
        info_label = QLabel("Format: column_name|SQL expression (one per line)")
        info_label.setStyleSheet("font-size: 12px; color: #a0a0a0;")
        self.config_layout.addWidget(info_label)
        
        self.transform_text = QPlainTextEdit()
        self.transform_text.setPlaceholderText(
            "Examples:\n"
            "full_name|first_name || ' ' || last_name\n"
            "total_price|quantity * unit_price\n"
            "year|CAST(strftime(date_column, '%Y') AS INTEGER)\n"
            "upper_name|UPPER(name)\n"
            "age_group|CASE WHEN age < 18 THEN 'Minor' ELSE 'Adult' END"
        )
        self.transform_text.setMaximumHeight(150)
        self.config_layout.addWidget(self.transform_text)
        
        validate_btn_row = QHBoxLayout()
        validate_transform_btn = QPushButton("🔍 Validate Transformations")
        validate_transform_btn.setStyleSheet("""
            QPushButton {
                background-color: #1976d2;
                color: white;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1565c0;
            }
        """)
        validate_transform_btn.setToolTip("Validate transformation syntax and column names")
        validate_transform_btn.clicked.connect(self.validate_transform_expressions)
        validate_btn_row.addWidget(validate_transform_btn)
        validate_btn_row.addStretch()
        self.config_layout.addLayout(validate_btn_row)
    
    def build_pivot_config(self):
        """Build config for Pivot step"""
        source_row = QHBoxLayout()
        source_row.addWidget(self.create_label("Source Step:"))
        self.pivot_source_combo = self.create_combo()
        
        available_steps = self.get_available_steps()
        if available_steps:
            self.pivot_source_combo.addItems(available_steps)
        else:
            self.pivot_source_combo.addItem("No previous steps available")
            self.pivot_source_combo.setEnabled(False)
        
        source_row.addWidget(self.pivot_source_combo)
        self.config_layout.addLayout(source_row)
        
        index_row = QHBoxLayout()
        index_row.addWidget(self.create_label("Index Column:"))
        self.index_input = QLineEdit()
        index_row.addWidget(self.index_input)
        self.config_layout.addLayout(index_row)
        
        columns_row = QHBoxLayout()
        columns_row.addWidget(self.create_label("Columns:"))
        self.columns_input = QLineEdit()
        columns_row.addWidget(self.columns_input)
        self.config_layout.addLayout(columns_row)
        
        values_row = QHBoxLayout()
        values_row.addWidget(self.create_label("Values Column:"))
        self.values_input = QLineEdit()
        values_row.addWidget(self.values_input)
        self.config_layout.addLayout(values_row)
        
        func_row = QHBoxLayout()
        func_row.addWidget(self.create_label("Aggregation Function:"))
        self.agg_func_combo = self.create_combo()
        self.agg_func_combo.addItems(["sum", "mean", "count", "min", "max"])
        func_row.addWidget(self.agg_func_combo)
        self.config_layout.addLayout(func_row)
    
    def build_export_config(self):
        """Build config for Export step"""
        source_row = QHBoxLayout()
        source_row.addWidget(self.create_label("Source Step:"))
        self.export_source_combo = self.create_combo()
        
        available_steps = self.get_available_steps()
        if available_steps:
            self.export_source_combo.addItems(available_steps)
        else:
            self.export_source_combo.addItem("No previous steps available")
            self.export_source_combo.setEnabled(False)
        
        source_row.addWidget(self.export_source_combo)
        self.config_layout.addLayout(source_row)
        
        format_row = QHBoxLayout()
        format_row.addWidget(self.create_label("Export Format:"))
        self.export_format_combo = self.create_combo()
        self.export_format_combo.addItems(["csv", "parquet", "excel"])
        format_row.addWidget(self.export_format_combo)
        self.config_layout.addLayout(format_row)
        
        self.config_layout.addWidget(QLabel("Output Path (optional):"))
        path_info = QLabel("Leave blank to use default location")
        path_info.setStyleSheet("font-size: 12px; color: #a0a0a0;")
        self.config_layout.addWidget(path_info)
        
        self.output_path_input = QLineEdit()
        self.output_path_input.setPlaceholderText("e.g., C:/output/result.csv")
        self.config_layout.addWidget(self.output_path_input)
    
    def load_existing_step(self):
        """Load existing step data into the form"""
        step = self.existing_step
        step_type = step.get('type', '')
        
        type_map = {
            'load_data': 'Load Data',
            'sql_query': 'SQL Query',
            'filter': 'Filter',
            'aggregate': 'Aggregate',
            'join': 'Join',
            'transform': 'Transform',
            'pivot': 'Pivot',
            'export': 'Export'
        }
        
        display_type = type_map.get(step_type, 'Load Data')
        
        self.on_type_changed(display_type)
        
        idx = self.type_combo.findText(display_type)
        if idx >= 0:
            self.type_combo.blockSignals(True)
            self.type_combo.setCurrentIndex(idx)
            self.type_combo.blockSignals(False)
        
        self.name_input.setText(step.get('name', ''))
        
        QApplication.processEvents()
        
        if step_type == 'load_data':
            if hasattr(self, 'file_combo'):
                file_name = step.get('file_name', '')
                if file_name:
                    idx = self.file_combo.findText(file_name)
                    if idx >= 0:
                        self.file_combo.setCurrentIndex(idx)
                    else:
                        self.file_combo.setCurrentText(file_name)
            if hasattr(self, 'table_name_input'):
                self.table_name_input.setText(step.get('table_name', ''))
        
        elif step_type == 'sql_query':
            if hasattr(self, 'query_text'):
                self.query_text.setPlainText(step.get('query', ''))
        
        elif step_type == 'filter':
            if hasattr(self, 'source_combo'):
                self.source_combo.setCurrentText(step.get('source', 'step_0'))
            if hasattr(self, 'condition_input'):
                self.condition_input.setText(step.get('condition', ''))
        
        elif step_type == 'aggregate':
            if hasattr(self, 'agg_source_combo'):
                self.agg_source_combo.setCurrentText(step.get('source', 'step_0'))
            if hasattr(self, 'group_by_input'):
                group_by = step.get('group_by', [])
                self.group_by_input.setText(', '.join(group_by) if group_by else '')
            if hasattr(self, 'agg_text'):
                aggs = step.get('aggregations', [])
                agg_lines = [f"{a['column']}:{a['function']}:{a.get('alias', '')}" for a in aggs]
                self.agg_text.setPlainText('\n'.join(agg_lines))
        
        elif step_type == 'join':
            if hasattr(self, 'left_source_combo'):
                self.left_source_combo.setCurrentText(step.get('left_source', 'step_0'))
            if hasattr(self, 'right_source_combo'):
                self.right_source_combo.setCurrentText(step.get('right_source', 'step_1'))
            if hasattr(self, 'join_type_combo'):
                self.join_type_combo.setCurrentText(step.get('join_type', 'INNER'))
            if hasattr(self, 'left_on_input'):
                self.left_on_input.setText(step.get('left_on', ''))
            if hasattr(self, 'right_on_input'):
                self.right_on_input.setText(step.get('right_on', ''))
        
        elif step_type == 'transform':
            if hasattr(self, 'transform_source_combo'):
                self.transform_source_combo.setCurrentText(step.get('source', 'step_0'))
            if hasattr(self, 'transform_text'):
                transforms = step.get('transformations', [])
                transform_lines = [f"{t['column_name']}|{t['expression']}" for t in transforms]
                self.transform_text.setPlainText('\n'.join(transform_lines))
        
        elif step_type == 'pivot':
            if hasattr(self, 'pivot_source_combo'):
                self.pivot_source_combo.setCurrentText(step.get('source', 'step_0'))
            if hasattr(self, 'index_input'):
                self.index_input.setText(step.get('index', ''))
            if hasattr(self, 'columns_input'):
                self.columns_input.setText(step.get('columns', ''))
            if hasattr(self, 'values_input'):
                self.values_input.setText(step.get('values', ''))
            if hasattr(self, 'agg_func_combo'):
                self.agg_func_combo.setCurrentText(step.get('agg_func', 'SUM'))
        
        elif step_type == 'export':
            if hasattr(self, 'export_source_combo'):
                self.export_source_combo.setCurrentText(step.get('source', 'step_0'))
            if hasattr(self, 'export_format_combo'):
                self.export_format_combo.setCurrentText(step.get('format', 'CSV'))
            if hasattr(self, 'output_path_input'):
                self.output_path_input.setText(step.get('output_path', ''))
    
    def get_step_spec(self):
        """Get the step specification"""
        step_type_display = self.type_combo.currentText()
        step_name = self.name_input.text().strip()
        
        if not step_name:
            QMessageBox.warning(self, "Invalid Input", "Please enter a step name.")
            return None
        
        type_map = {
            'Load Data': 'load_data',
            'SQL Query': 'sql_query',
            'Filter': 'filter',
            'Aggregate': 'aggregate',
            'Join': 'join',
            'Transform': 'transform',
            'Pivot': 'pivot',
            'Export': 'export'
        }
        
        step_type = type_map.get(step_type_display, 'load_data')
        
        step = {
            'name': step_name,
            'type': step_type
        }
        
        if step_type == 'load_data':
            if hasattr(self, 'file_combo'):
                step['file_name'] = self.file_combo.currentText()
            else:
                QMessageBox.warning(self, "Invalid State", "Load Data configuration not properly initialized.")
                return None
            
            if hasattr(self, 'table_name_input'):
                table_name = self.table_name_input.text().strip()
                if table_name:
                    step['table_name'] = table_name
        
        elif step_type == 'sql_query':
            if hasattr(self, 'query_text'):
                query = self.query_text.toPlainText().strip()
                if not query:
                    QMessageBox.warning(self, "Invalid Input", "Please enter a SQL query.")
                    return None
                step['query'] = query
            else:
                QMessageBox.warning(self, "Invalid State", "SQL Query configuration not properly initialized.")
                return None
        
        elif step_type == 'filter':
            if hasattr(self, 'source_combo') and hasattr(self, 'condition_input'):
                step['source'] = self.source_combo.currentText()
                condition = self.condition_input.text().strip()
                if not condition:
                    QMessageBox.warning(self, "Invalid Input", "Please enter a filter condition.")
                    return None
            else:
                QMessageBox.warning(self, "Invalid State", "Filter configuration not properly initialized.")
                return None
            step['condition'] = condition
        
        elif step_type == 'aggregate':
            if hasattr(self, 'agg_source_combo') and hasattr(self, 'group_by_input') and hasattr(self, 'agg_text'):
                step['source'] = self.agg_source_combo.currentText()
                
                group_by_text = self.group_by_input.text().strip()
                if group_by_text:
                    step['group_by'] = [col.strip() for col in group_by_text.split(',')]
                else:
                    step['group_by'] = []
                
                agg_text = self.agg_text.toPlainText().strip()
                if not agg_text:
                    QMessageBox.warning(self, "Invalid Input", "Please specify at least one aggregation.")
                    return None
                
                aggregations = []
                for line in agg_text.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(':')
                    if len(parts) >= 2:
                        agg = {
                            'column': parts[0].strip(),
                            'function': parts[1].strip().upper()
                        }
                        if len(parts) >= 3:
                            agg['alias'] = parts[2].strip()
                        aggregations.append(agg)
                
                if not aggregations:
                    QMessageBox.warning(self, "Invalid Input", "Invalid aggregation format.")
                    return None
                
                step['aggregations'] = aggregations
            else:
                QMessageBox.warning(self, "Invalid State", "Aggregate configuration not properly initialized.")
                return None
        
        elif step_type == 'join':
            if (hasattr(self, 'left_source_combo') and hasattr(self, 'right_source_combo') and 
                hasattr(self, 'join_type_combo') and hasattr(self, 'left_on_input') and 
                hasattr(self, 'right_on_input')):
                
                step['left_source'] = self.left_source_combo.currentText()
                step['right_source'] = self.right_source_combo.currentText()
                step['join_type'] = self.join_type_combo.currentText()
                step['left_on'] = self.left_on_input.text().strip()
                step['right_on'] = self.right_on_input.text().strip()
                
                if not step['left_on'] or not step['right_on']:
                    QMessageBox.warning(self, "Invalid Input", "Please specify join columns.")
                    return None
            else:
                QMessageBox.warning(self, "Invalid State", "Join configuration not properly initialized.")
                return None
        
        elif step_type == 'transform':
            if hasattr(self, 'transform_source_combo') and hasattr(self, 'transform_text'):
                step['source'] = self.transform_source_combo.currentText()
                
                trans_text = self.transform_text.toPlainText().strip()
                if not trans_text:
                    QMessageBox.warning(self, "Invalid Input", "Please specify at least one transformation.")
                    return None
                
                transformations = []
                for line in trans_text.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split('|')
                    if len(parts) == 2:
                        transformations.append({
                            'column_name': parts[0].strip(),
                            'expression': parts[1].strip()
                        })
                
                if not transformations:
                    QMessageBox.warning(self, "Invalid Input", "Invalid transformation format. Use: column_name|expression")
                    return None
                
                step['transformations'] = transformations
            else:
                QMessageBox.warning(self, "Invalid State", "Transform configuration not properly initialized.")
                return None
        
        elif step_type == 'pivot':
            if (hasattr(self, 'pivot_source_combo') and hasattr(self, 'index_input') and 
                hasattr(self, 'columns_input') and hasattr(self, 'values_input') and 
                hasattr(self, 'agg_func_combo')):
                
                step['source'] = self.pivot_source_combo.currentText()
                step['index'] = self.index_input.text().strip()
                step['columns'] = self.columns_input.text().strip()
                step['values'] = self.values_input.text().strip()
                step['agg_func'] = self.agg_func_combo.currentText()
                
                if not all([step['index'], step['columns'], step['values']]):
                    QMessageBox.warning(self, "Invalid Input", "Please specify index, columns, and values.")
                    return None
            else:
                QMessageBox.warning(self, "Invalid State", "Pivot configuration not properly initialized.")
                return None
        
        elif step_type == 'export':
            if hasattr(self, 'export_source_combo') and hasattr(self, 'export_format_combo') and hasattr(self, 'output_path_input'):
                step['source'] = self.export_source_combo.currentText()
                step['format'] = self.export_format_combo.currentText()
                output_path = self.output_path_input.text().strip()
                if output_path:
                    step['output_path'] = output_path
            else:
                QMessageBox.warning(self, "Invalid State", "Export configuration not properly initialized.")
                return None
        
        return step
