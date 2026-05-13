# SimpliSQL Architecture Guide

## Overview

SimpliSQL is built using a **modular, mixin-based architecture** that separates concerns across functional domains:

```
User Interface (PyQt6)
    ↓
Main Application (DuckDBQueryEditor)
    ↓
Mixins (Modular Functionality)
    ├── QueryManager (SQL execution)
    ├── FileUtilities (File operations)
    ├── FileUpload (Import data)
    ├── QueryHelpers (Validation & templates)
    ├── WorkflowManager (Automation)
    ├── ExportUtils (Data export)
    ├── UIBuilder (UI construction)
    ├── ViewManager (Saved views)
    └── DataOperationDialogs (Filtering UI)
    ↓
Core Libraries
    ├── DuckDB (SQL engine)
    ├── Pandas (Data processing)
    └── PyArrow (File I/O)
```

## Module Structure

### `simplsql_modules/core/` - Business Logic

#### `query_manager.py`
**Responsibility**: SQL query execution and result handling

Key Classes:
- `QueryManager` - Mixin for query execution methods
- `QueryExecutionThread` - QThread for non-blocking execution

Key Methods:
- `execute_query()` - Parse and execute SQL with auto-fixes
- `execute_query_background()` - Background execution with progress
- `execute_query_to_store()` - Store results to Parquet
- `load_data_advanced()` - Load data with filtering UI

Features:
- Automatic table name substitution
- CTE (Common Table Expression) support
- Query result display in tree view
- Execution timing and profiling

#### `file_upload.py`
**Responsibility**: Multi-format file import and data loading

Supported Formats:
- CSV/TXT (with custom delimiters)
- Excel (.xlsx, .xls)
- JSON
- XML
- ZIP archives

Key Methods:
- `upload_files()` - Main orchestrator
- `_process_csv_files()` - CSV batch processing
- `_process_excel_files()` - Excel sheet handling
- `_duckdb_parquet_conversion()` - File conversion

Features:
- Batch merge options
- Progress tracking
- ZIP file extraction
- Type inference and fixing

#### `file_utilities.py`
**Responsibility**: File management and Parquet operations

Key Methods:
- `load_existing_parquet_files()` - Scan for existing files
- `display_existing_files()` - Update UI dropdown
- `delete_parquet()` - Remove files with confirmation
- `refresh_parquet_files()` - Reload file list

#### `query_helpers.py`
**Responsibility**: SQL validation and query assistance

Key Methods:
- `validate_sql()` - Syntax validation using EXPLAIN
- `show_query_templates()` - Display template library
- `show_syntax_helper()` - Interactive syntax guide

Templates Include:
- Basic SELECT statements
- Aggregation functions
- JOINs (INNER, LEFT, FULL)
- Window functions
- CTEs

#### `workflow_manager.py`
**Responsibility**: Multi-step workflow creation and execution

Key Methods:
- `create_workflow_wizard()` - Launch workflow builder
- `manage_workflows()` - View, edit, delete workflows
- `execute_workflow()` - Run with progress tracking

Workflow Steps Supported:
- Filter (WHERE clause)
- Group By (Aggregation)
- Join (INNER, LEFT, FULL)
- Sort (ORDER BY)
- Limit (LIMIT clause)
- Rename Columns

#### `export_utils.py`
**Responsibility**: Data export to various formats

Key Methods:
- `export_to_csv()` - CSV export with DuckDB optimization
- `export_to_excel()` - Excel export via Pandas
- `generate_audit_pdf()` - PDF report generation

### `simplsql_modules/ui/` - User Interface

#### `ui_builder.py`
**Responsibility**: UI initialization and theming

Key Methods:
- `build_grouped_action_bar()` - Create compact toolbar
- `init_ui()` - Main UI construction
- `apply_theme()` - Apply color scheme

Components:
- Action bar with grouped buttons
- SQL editor pane
- Results display (tree view or table)
- Progress dialogs

#### `view_manager.py`
**Responsibility**: Manage saved data views

Features:
- Save current view with filters
- Restore views from storage
- View versioning
- Share view definitions

#### `dialogs.py`
**Responsibility**: Dialog windows for user interaction

Classes:
- `WorkflowWizard` - Multi-step workflow builder
- `StepEditorDialog` - Individual step configuration

#### `data_dialogs.py`
**Responsibility**: Data-centric dialog windows

Features:
- Column picker
- Filter builder
- Join configurator
- Visualization options

#### `widgets.py`
**Responsibility**: Custom PyQt6 widgets

Classes:
- `CustomPlainTextEdit` - Enhanced SQL editor
- `LineChartDialog` - Line chart configuration

### `simplsql_modules/utils/` - Utilities

#### `paths.py`
PyInstaller-compatible path resolution:
- `get_app_dir()` - App data directory
- `get_resource_path()` - Bundle resource paths

#### `threads.py`
Background thread classes:
- `ParquetSchemaThread` - Async schema loading
- `WorkflowExecutionThread` - Async workflow execution

#### `models.py`
Qt model classes:
- `PandasModel` - Display DataFrames in tables
- `DataFrameFilterProxy` - Filterable proxy model

### `simplsql_modules/ai/` - AI Integration

#### `ai_assistant.py`
**Responsibility**: AI chat interface and integration

Features:
- Multi-provider support (OpenAI, Anthropic, Gemini)
- Local Ollama/Gemma integration
- Chat history persistence
- Configuration management

## Data Flow

### Query Execution Flow

```
User writes SQL
        ↓
    [execute_query()]
        ↓
Auto-fix queries:
├── Replace backslashes
├── Replace double quotes
└── Substitute table names
        ↓
    [conn.execute()]
        ↓
DuckDB Engine
        ↓
[populate_treeview()]
        ↓
Display results
```

### File Upload Flow

```
User selects files
        ↓
    [upload_files()]
        ↓
Group by type:
├── CSV/TXT
├── Excel
├── JSON
├── XML
└── ZIP
        ↓
For each group:
├── [_process_<type>_files()]
├── Merge/concatenate options
└── Type fixing
        ↓
    [_duckdb_parquet_conversion()]
        ↓
Save as Parquet
        ↓
Update file dropdown
```

### Workflow Execution Flow

```
User creates workflow
        ↓
Store in workflows.json
        ↓
User executes workflow
        ↓
[execute_workflow()]
        ↓
[WorkflowExecutionThread]
        ↓
For each step:
├── Build SQL from step config
├── Execute query
└── Pass result to next step
        ↓
Display final results
```

## Design Patterns

### 1. Mixin Pattern
Multiple inheritance to compose functionality:
```python
class DuckDBQueryEditor(
    DataOperationDialogs,
    ViewManager,
    QueryManager,      # Adds query execution
    FileUtilities,     # Adds file management
    FileUpload,        # Adds import capability
    UIBuilder,         # Adds UI construction
    QueryHelpers,      # Adds validation
    WorkflowManager,   # Adds workflows
    ExportUtils,       # Adds export
    QWidget
):
    pass
```

**Advantages**:
- Clean separation of concerns
- Easy to test individual mixins
- Avoids deep inheritance hierarchies
- DRY principle

### 2. Configuration Persistence
JSON-based configuration storage:
```python
config_path = app_dir / "Auto_Workflow" / "config.json"
with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)
```

### 3. Background Threading
Long operations run in QThread to prevent UI freezing:
```python
class QueryExecutionThread(QThread):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    
    def run(self):
        try:
            result = self.conn.execute(query).fetchdf()
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
```

### 4. Circular Import Prevention
Methods import dependencies locally to avoid circular imports:
```python
def show_message(self):
    # Import MainWindow here, not at top
    from simplsql_modules.Simplisql import MainWindow
    MainWindow.show_styled_message_box(...)
```

## State Management

### Persistent State
Stored in `Auto_Workflow/` directory:
- `saved_queries.json` - User query library
- `workflows.json` - Workflow definitions
- `views.json` - Saved data views
- `ai_config.json` - AI settings
- `ai_chat_history.json` - Chat history
- `theme_settings.json` - Theme preferences

### Runtime State
Held in `DuckDBQueryEditor` instance:
- `self.conn` - DuckDB connection
- `self.uploaded_files` - Loaded file paths
- `self.uploaded_display_names` - File display names
- `self.workflows` - Workflow list
- `self.saved_queries` - Query library
- `self.current_theme` - Active theme

## Integration Points

### DuckDB Integration
- In-memory database for fast operations
- Parquet native support (direct file format)
- Custom SQL functions (FILE_BASENAME, etc.)
- Advanced SQL features (CTEs, Window functions)

### PyQt6 Integration
- Event-driven UI
- Stylesheet-based theming
- Signal/slot for cross-component communication
- Threading with QThread

### Ollama/Local AI Integration
- HTTP REST API to localhost:11434
- Streaming responses
- Local model execution
- Zero cloud dependencies

## Error Handling Strategy

### Three-Level Approach

**Level 1: Prevention**
- Input validation before execution
- SQL syntax validation with EXPLAIN
- File format detection

**Level 2: Detection**
- Try-except blocks around critical operations
- DuckDB-specific exception handling
- Thread exception signals

**Level 3: User Notification**
- Styled message boxes
- Error messages with copy button
- Detailed error logs

## Performance Considerations

### Optimization Techniques

1. **Lazy Loading**
   - Load parquet schemas on demand
   - Defer table creation until needed

2. **Streaming**
   - Use fetchdf() for result streaming
   - Progress dialogs for long operations

3. **Caching**
   - Cache loaded workflows
   - Store file list in memory

4. **Batch Operations**
   - Merge multiple CSV files
   - Bulk insert to Parquet

### Scaling Limits

- **Row Limit**: Configure for preview queries
- **Column Count**: DuckDB handles 1000+ columns
- **File Size**: Limited by available RAM (in-memory operations)
- **Concurrent Operations**: Single-threaded, operations queue implicitly

## Testing Strategy

### Unit Tests (70% coverage)
- Core module functionality
- Custom SQL functions
- Configuration persistence
- Data export

### Integration Tests (20% coverage)
- File upload + query execution
- Workflow creation + execution
- AI assistant integration

### Manual Tests (10% coverage)
- UI interactions
- Theme switching
- Large dataset handling

See `tests/` directory for implementation.

## Future Architecture Improvements

1. **Dependency Injection**
   - Replace circular imports with injection
   - Better testability

2. **Event Bus**
   - Replace direct method calls
   - Loose coupling

3. **Database Abstraction**
   - Support PostgreSQL, MySQL
   - Abstract DuckDB-specific code

4. **Plugin System**
   - Allow custom data sources
   - Custom visualization providers

5. **Logging Framework**
   - Replace print() with logging module
   - Structured logs

---

**Architecture Version**: 2.0  
**Last Updated**: April 2024  
**Maintainers**: SimpliSQL Team
