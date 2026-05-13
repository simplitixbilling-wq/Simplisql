"""
Workflow Manager Module

Provides workflow orchestration and execution functionality:
- Create multi-step data transformation workflows
- Manage existing workflows (view, edit, delete)
- Execute workflows with progress tracking
- Row-limited testing for large datasets

This module separates workflow management logic from core editor functionality,
enabling reusable, automated data processing pipelines.

Dependencies:
    - self attributes: conn, workflows, doc_dir
    - External methods: apply_dark_dialog_styling, apply_progress_dialog_styling, populate_treeview, create_input_popup, add_workflow, delete_workflow
    - PyQt6: Dialog widgets, progress dialogs
    - DuckDB: Query execution
    - WorkflowWizard: UI for creating/editing workflows
    - WorkflowExecutionThread: Background workflow execution
    - MainWindow: Styled message boxes

Author: Refactored from Simplsql.py Phase 12B
"""

import os
import time
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QPushButton, QTextEdit, QMessageBox, QProgressDialog, QInputDialog,
    QApplication
)
from PyQt6.QtCore import Qt
from ui import WorkflowWizard
from utils import WorkflowExecutionThread


class WorkflowManager:
    """Mixin class providing workflow management and execution functionality"""
    
    def create_workflow_wizard(self):
        """
        Launch wizard to create a multi-step workflow.
        
        Opens the WorkflowWizard dialog which guides users through creating
        a new workflow by adding transformation steps (filter, aggregate, join, etc.).
        Once completed, the workflow is saved to the workflows list.
        
        Called by: Create Workflow button/menu
        """
        # Import MainWindow here to avoid circular import
        from Simplisql import MainWindow
        
        wizard = WorkflowWizard(self)
        if wizard.exec() == QDialog.DialogCode.Accepted:
            workflow_spec = wizard.get_workflow_spec()
            if workflow_spec:
                self.add_workflow(workflow_spec)
                MainWindow.show_styled_message_box(
                    self,
                    "Success",
                    f"Workflow '{workflow_spec['name']}' created successfully!",
                    icon=QMessageBox.Icon.Information
                )

    def manage_workflows(self):
        """
        Show dialog to manage existing workflows.
        
        Displays a comprehensive workflow management interface:
        - List all saved workflows with step counts
        - Preview workflow steps
        - Run workflows with row limit options
        - Edit workflows using WorkflowWizard
        - Delete workflows with confirmation
        
        Features:
        - Visual workflow preview
        - Quick run with configurable row limits
        - In-place editing with WorkflowWizard
        - Safe deletion with confirmation
        
        Called by: Manage Workflows button/menu
        """
        # Import MainWindow here to avoid circular import
        from Simplisql import MainWindow
        
        if not self.workflows:
            MainWindow.show_styled_message_box(
                self,
                "No Workflows",
                "No workflows have been created yet.",
                icon=QMessageBox.Icon.Information
            )
            return

        dlg = QDialog(self)
        self.apply_dark_dialog_styling(dlg)
        dlg.setWindowTitle("Manage Workflows")
        dlg.setMinimumSize(700, 500)
        layout = QVBoxLayout(dlg)

        info_label = QLabel("Select a workflow to view, edit, or delete:")
        info_label.setStyleSheet("color: #d0d0d0; font-weight: bold; font-size: 15px;")
        layout.addWidget(info_label)

        # List widget to show workflows
        workflow_list = QListWidget()
        workflow_list.setStyleSheet("""
            QListWidget {
                background-color: #3c3f41;
                color: #ffffff;
                border: 2px solid #555555;
                padding: 4px;
                font-size: 14px;
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

        for wf in self.workflows:
            name = wf.get('name', 'Unnamed')
            desc = wf.get('description', '')
            steps = wf.get('steps', [])
            item_text = f"{name} ({len(steps)} steps)"
            if desc:
                item_text += f" - {desc}"
            workflow_list.addItem(item_text)

        layout.addWidget(workflow_list)

        # Preview area
        preview_label = QLabel("Workflow Steps:")
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
                font-size: 10px;
            }
        """)
        layout.addWidget(preview_text)

        # Update preview when selection changes
        def update_preview():
            idx = workflow_list.currentRow()
            if idx >= 0:
                wf = self.workflows[idx]
                steps_text = []
                for i, step in enumerate(wf.get('steps', []), 1):
                    step_name = step.get('name', f'Step {i}')
                    step_type = step.get('type', 'unknown')
                    steps_text.append(f"{i}. {step_name} ({step_type})")
                preview_text.setText('\n'.join(steps_text))

        workflow_list.currentItemChanged.connect(update_preview)

        # Buttons
        btn_row = QHBoxLayout()
        run_btn = QPushButton("▶️ Run")
        run_btn.setStyleSheet("QPushButton { background-color: #2e7d32; color: white; padding: 6px 12px; }")
        edit_btn = QPushButton("✏️ Edit")
        edit_btn.setStyleSheet("QPushButton { background-color: #1976d2; color: white; padding: 6px 12px; }")
        delete_btn = QPushButton("🗑️ Delete")
        delete_btn.setStyleSheet("QPushButton { background-color: #c62828; color: white; padding: 6px 12px; }")
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("QPushButton { padding: 6px 12px; }")

        def on_run():
            idx = workflow_list.currentRow()
            if idx < 0:
                MainWindow.show_styled_message_box(self, "Select", "Please select a workflow.", icon=QMessageBox.Icon.Warning)
                return
            wf = self.workflows[idx]
            dlg.accept()
            
            # Ask for row limit before executing
            row_limit = self.create_input_popup(
                "Row Limit",
                "Enter number of rows to process (leave blank for ALL rows):\n\n"
                "💡 Tip: Use small numbers (e.g., 1000) for quick testing"
            )
            
            if row_limit is None:
                return  # User cancelled
            
            # Parse row limit
            limit_value = None
            if row_limit and row_limit.strip():
                try:
                    limit_value = int(row_limit.strip())
                    if limit_value <= 0:
                        MainWindow.show_styled_message_box(
                            self,
                            "Invalid Input",
                            "Row limit must be a positive number.",
                            icon=QMessageBox.Icon.Warning
                        )
                        return
                except ValueError:
                    MainWindow.show_styled_message_box(
                        self,
                        "Invalid Input",
                        "Please enter a valid number for row limit.",
                        icon=QMessageBox.Icon.Warning
                    )
                    return
            
            self.execute_workflow(wf, row_limit=limit_value)

        def on_edit():
            idx = workflow_list.currentRow()
            if idx < 0:
                MainWindow.show_styled_message_box(self, "Select", "Please select a workflow.", icon=QMessageBox.Icon.Warning)
                return
            wf = self.workflows[idx]
            wizard = WorkflowWizard(self, existing_workflow=wf)
            if wizard.exec() == QDialog.DialogCode.Accepted:
                # Refresh the workflow list to show any changes
                workflow_list.clear()
                for updated_wf in self.workflows:
                    name = updated_wf.get('name', 'Unnamed')
                    desc = updated_wf.get('description', '')
                    steps = updated_wf.get('steps', [])
                    item_text = f"{name} ({len(steps)} steps)"
                    if desc:
                        item_text += f" - {desc}"
                    workflow_list.addItem(item_text)
                # Re-select the edited workflow
                workflow_list.setCurrentRow(idx)
                update_preview()

        def on_delete():
            idx = workflow_list.currentRow()
            if idx < 0:
                return
            wf = self.workflows[idx]
            reply = QMessageBox.question(
                self,
                "Confirm Delete",
                f"Are you sure you want to delete workflow '{wf.get('name', 'Unnamed')}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.delete_workflow(wf['id'])
                workflow_list.takeItem(idx)
                preview_text.clear()

        run_btn.clicked.connect(on_run)
        edit_btn.clicked.connect(on_edit)
        delete_btn.clicked.connect(on_delete)
        close_btn.clicked.connect(dlg.reject)

        btn_row.addStretch()
        btn_row.addWidget(run_btn)
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(delete_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        # Select first item by default
        if workflow_list.count() > 0:
            workflow_list.setCurrentRow(0)

        dlg.exec()

    def run_workflow_dialog(self):
        """
        Quick dialog to select and run a workflow.
        
        Provides a streamlined interface for executing workflows:
        - Simple dropdown selection of saved workflows
        - Optional row limit for testing
        - Direct execution without entering management dialog
        
        This is a faster alternative to manage_workflows() when you just
        want to run a workflow without viewing/editing.
        
        Called by: Run Workflow button/menu
        """
        # Import MainWindow here to avoid circular import
        from Simplisql import MainWindow
        
        if not self.workflows:
            MainWindow.show_styled_message_box(
                self,
                "No Workflows",
                "No workflows have been created yet.",
                icon=QMessageBox.Icon.Information
            )
            return

        workflow_names = [wf.get('name', 'Unnamed') for wf in self.workflows]
        name, ok = QInputDialog.getItem(
            self,
            "Run Workflow",
            "Select workflow to run:",
            workflow_names,
            0,
            False
        )

        if ok and name:
            # Ask for row limit to speed up testing
            row_limit = self.create_input_popup(
                "Row Limit",
                "Enter number of rows to process (leave blank for ALL rows):\n\n"
                "💡 Tip: Use small numbers (e.g., 1000) for quick testing"
            )
            
            if row_limit is None:
                return  # User cancelled
            
            # Parse row limit
            limit_value = None
            if row_limit and row_limit.strip():
                try:
                    limit_value = int(row_limit.strip())
                    if limit_value <= 0:
                        MainWindow.show_styled_message_box(
                            self,
                            "Invalid Input",
                            "Row limit must be a positive number.",
                            icon=QMessageBox.Icon.Warning
                        )
                        return
                except ValueError:
                    MainWindow.show_styled_message_box(
                        self,
                        "Invalid Input",
                        "Please enter a valid number for row limit.",
                        icon=QMessageBox.Icon.Warning
                    )
                    return
            
            idx = workflow_names.index(name)
            wf = self.workflows[idx]
            self.execute_workflow(wf, row_limit=limit_value)

    def execute_workflow(self, workflow_spec, row_limit=None):
        """
        Execute a workflow asynchronously with progress tracking.
        
        Runs a multi-step workflow in a background thread, providing:
        - Progress updates for each step
        - Row limit support for faster testing
        - Error handling with detailed messages
        - Cancellation support
        - Result visualization in main table
        
        Args:
            workflow_spec: Workflow specification dictionary with 'steps' list
            row_limit: Optional integer to limit rows processed (e.g., 1000 for testing)
        
        Workflow execution:
        1. Validates workflow has steps
        2. Shows progress dialog with step tracking
        3. Creates WorkflowExecutionThread
        4. Connects signals for progress updates
        5. Handles completion, errors, and cancellation
        6. Displays final results in table
        
        Called by: manage_workflows, run_workflow_dialog
        """
        # Import MainWindow here to avoid circular import
        from Simplisql import MainWindow
        
        steps = workflow_spec.get('steps', [])
        if not steps:
            MainWindow.show_styled_message_box(
                self,
                "Empty Workflow",
                "This workflow has no steps to execute.",
                icon=QMessageBox.Icon.Warning
            )
            return

        # Show progress dialog with row limit info
        workflow_name = workflow_spec.get('name', 'Unnamed')
        limit_info = f" (Limited to {row_limit:,} rows)" if row_limit else " (Processing ALL rows)"
        progress = QProgressDialog(
            f"Executing workflow: {workflow_name}{limit_info}...",
            "Cancel",
            0,
            len(steps),
            self
        )
        progress.setWindowTitle("Workflow Execution")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        self.apply_progress_dialog_styling(progress, "#9C27B0")  # Purple for workflows
        progress.setValue(0)
        progress.show()
        QApplication.processEvents()

        # Create and start workflow thread with row limit
        self.workflow_thread = WorkflowExecutionThread(self.conn, steps, self, row_limit=row_limit)

        def on_step_started(idx, step_name):
            progress.setLabelText(f"Step {idx + 1}/{len(steps)}: {step_name}")
            progress.setValue(idx)
            QApplication.processEvents()

        def on_step_completed(idx, result_df):
            print(f"✓ Step {idx + 1} completed: {result_df.shape if result_df is not None else 'No result'}")

        def on_step_error(idx, error_msg):
            progress.close()
            # Get workflow and step details for better error context
            workflow_name = workflow_spec.get('name', 'Unnamed')
            step_name = steps[idx].get('name', f'Step {idx + 1}') if idx < len(steps) else 'Unknown'
            detailed_error = f"Workflow: {workflow_name}\nStep: {step_name} (Index: {idx})\nError: {error_msg}\nTimestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            
            MainWindow.show_error_message_box_with_copy(
                self,
                "Workflow Step Error",
                f"Step {idx + 1} failed: {error_msg}",
                detailed_text=detailed_error
            )

        def on_workflow_completed(final_result):
            progress.setValue(len(steps))
            progress.close()
            
            if final_result is not None and not final_result.empty:
                self.populate_treeview(final_result, set_full=True, skip_large_prompt=True)
                MainWindow.show_styled_message_box(
                    self,
                    "Success",
                    f"Workflow '{workflow_spec.get('name', 'Unnamed')}' completed successfully!\n\n"
                    f"Final result: {final_result.shape[0]} rows × {final_result.shape[1]} columns",
                    icon=QMessageBox.Icon.Information
                )
            else:
                MainWindow.show_styled_message_box(
                    self,
                    "Completed",
                    f"Workflow '{workflow_spec.get('name', 'Unnamed')}' completed successfully!",
                    icon=QMessageBox.Icon.Information
                )

        def on_workflow_error(error_msg):
            progress.close()
            workflow_name = workflow_spec.get('name', 'Unnamed')
            detailed_error = f"Workflow: {workflow_name}\nTotal Steps: {len(steps)}\nError: {error_msg}\nTimestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            
            MainWindow.show_error_message_box_with_copy(
                self,
                "Workflow Execution Error",
                error_msg,
                detailed_text=detailed_error
            )

        # Connect signals
        self.workflow_thread.step_started.connect(on_step_started)
        self.workflow_thread.step_completed.connect(on_step_completed)
        self.workflow_thread.step_error.connect(on_step_error)
        self.workflow_thread.workflow_completed.connect(on_workflow_completed)
        self.workflow_thread.workflow_error.connect(on_workflow_error)

        # Handle cancellation
        def on_cancel():
            if hasattr(self, 'workflow_thread'):
                self.workflow_thread.cancel()

        progress.canceled.connect(on_cancel)

        # Start execution
        self.workflow_thread.start()
