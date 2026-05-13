"""
Thread classes for asynchronous operations in SimplSQL.

This module provides QThread-based classes for:
- Reading Parquet file schemas without loading full data
- Executing multi-step workflows asynchronously
"""

import os
import time
from PyQt6.QtCore import QThread, pyqtSignal
import pyarrow as pa
import pyarrow.parquet as pq


class ParquetSchemaThread(QThread):
    """
    Read parquet schema without loading full data.
    
    This thread reads only the schema/metadata from a Parquet file
    to determine column names and types without loading the entire dataset.
    
    Signals
    -------
    finished : pyqtSignal(object)
        Emitted with tuple of (all_columns, numeric_columns) when complete
    error : pyqtSignal(str)
        Emitted with error message if reading fails
    """
    
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, path):
        """
        Initialize the schema reader thread.
        
        Parameters
        ----------
        path : str
            Path to the Parquet file
        """
        super().__init__()
        self.path = path

    def run(self):
        """Execute the schema reading operation."""
        try:
            # Read only schema without loading data
            parquet_file = pq.ParquetFile(self.path)
            schema = parquet_file.schema_arrow
            
            # Get column names
            all_columns = schema.names
            
            # Determine numeric columns from schema
            numeric_cols = []
            for i, field in enumerate(schema):
                field_type = field.type
                # Check if the field type is numeric using pyarrow type checking
                if (pa.types.is_integer(field_type) or 
                    pa.types.is_floating(field_type) or 
                    pa.types.is_decimal(field_type)):
                    numeric_cols.append(field.name)
            
            # Return tuple of (all_columns, numeric_columns)
            self.finished.emit((all_columns, numeric_cols))
        except Exception as e:
            self.error.emit(str(e))


class WorkflowExecutionThread(QThread):
    """
    Thread for executing workflow steps asynchronously.
    
    Executes a series of data transformation steps in sequence,
    emitting progress signals after each step completion.
    
    Signals
    -------
    step_started : pyqtSignal(int, str)
        Emitted when a step begins (step_index, step_name)
    step_completed : pyqtSignal(int, object)
        Emitted when a step completes (step_index, result_df)
    step_error : pyqtSignal(int, str)
        Emitted if a step fails (step_index, error_message)
    workflow_completed : pyqtSignal(object)
        Emitted when entire workflow completes (final_result)
    workflow_error : pyqtSignal(str)
        Emitted if workflow fails (error_message)
    """
    
    step_started = pyqtSignal(int, str)  # step_index, step_name
    step_completed = pyqtSignal(int, object)  # step_index, result_df
    step_error = pyqtSignal(int, str)  # step_index, error_message
    workflow_completed = pyqtSignal(object)  # final_result
    workflow_error = pyqtSignal(str)
    
    def __init__(self, conn, workflow_steps, parent_editor, row_limit=None):
        """
        Initialize the workflow execution thread.
        
        Parameters
        ----------
        conn : duckdb.Connection
            DuckDB database connection
        workflow_steps : list
            List of step dictionaries defining the workflow
        parent_editor : QWidget
            Parent editor widget (for accessing paths, etc.)
        row_limit : int, optional
            Limit number of rows for faster testing
        """
        super().__init__()
        self.conn = conn
        self.workflow_steps = workflow_steps
        self.parent_editor = parent_editor
        self.row_limit = row_limit  # Optional row limit for faster testing
        self.is_cancelled = False
        
    def run(self):
        """Execute the workflow steps in sequence."""
        try:
            intermediate_results = {}
            final_result = None
            
            for idx, step in enumerate(self.workflow_steps):
                if self.is_cancelled:
                    self.workflow_error.emit("Workflow cancelled by user")
                    return
                    
                step_name = step.get('name', f'Step {idx + 1}')
                self.step_started.emit(idx, step_name)
                
                try:
                    result = self._execute_step(step, intermediate_results)
                    intermediate_results[f'step_{idx}'] = result
                    final_result = result
                    self.step_completed.emit(idx, result)
                except Exception as e:
                    error_msg = f"Error in {step_name}: {str(e)}"
                    self.step_error.emit(idx, error_msg)
                    self.workflow_error.emit(error_msg)
                    return
            
            self.workflow_completed.emit(final_result)
            
        except Exception as e:
            self.workflow_error.emit(f"Workflow execution error: {str(e)}")
    
    def _execute_step(self, step, intermediate_results):
        """Execute a single workflow step"""
        step_type = step.get('type')
        
        if step_type == 'load_data':
            return self._execute_load_data(step)
        elif step_type == 'transform':
            return self._execute_transform(step, intermediate_results)
        elif step_type == 'filter':
            return self._execute_filter(step, intermediate_results)
        elif step_type == 'join':
            return self._execute_join(step, intermediate_results)
        elif step_type == 'aggregate':
            return self._execute_aggregate(step, intermediate_results)
        elif step_type == 'pivot':
            return self._execute_pivot(step, intermediate_results)
        elif step_type == 'sql_query':
            return self._execute_sql_query(step, intermediate_results)
        elif step_type == 'export':
            return self._execute_export(step, intermediate_results)
        else:
            raise ValueError(f"Unknown step type: {step_type}")
    
    def _execute_load_data(self, step):
        """Load data from parquet file"""
        file_name = step.get('file_name')
        if not file_name:
            raise ValueError("No file specified for load_data step")
        
        # Get the full path
        parquet_path = os.path.join(self.parent_editor.doc_dir, file_name)
        if not os.path.exists(parquet_path):
            raise FileNotFoundError(f"File not found: {parquet_path}")
        
        # Load into DuckDB with optional row limit for faster testing
        table_name = step.get('table_name', file_name.replace('.parquet', ''))
        
        if self.row_limit:
            # Load only the specified number of rows for quick testing
            self.conn.execute(
                f"CREATE OR REPLACE TABLE {table_name} AS "
                f"SELECT * FROM read_parquet('{parquet_path}') LIMIT {self.row_limit}"
            )
        else:
            # Load all rows
            self.conn.execute(
                f"CREATE OR REPLACE TABLE {table_name} AS "
                f"SELECT * FROM read_parquet('{parquet_path}')"
            )
        
        # Return the dataframe
        return self.conn.execute(f"SELECT * FROM {table_name}").fetchdf()
    
    def _execute_sql_query(self, step, intermediate_results):
        """Execute SQL query"""
        query = step.get('query', '').strip()
        if not query:
            raise ValueError("No query specified for sql_query step")
        
        # Replace placeholders for previous step results
        for key in intermediate_results.keys():
            placeholder = f"${{{key}}}"
            if placeholder in query:
                # Create temp table from previous result
                temp_table = f"temp_{key}"
                df = intermediate_results[key]
                self.conn.register(temp_table, df)
                query = query.replace(placeholder, temp_table)
        
        return self.conn.execute(query).fetchdf()
    
    def _execute_filter(self, step, intermediate_results):
        """Apply filter to data"""
        source = step.get('source', 'step_0')
        if source not in intermediate_results:
            raise ValueError(f"Source {source} not found")
        
        df = intermediate_results[source]
        condition = step.get('condition', '')
        
        if not condition:
            raise ValueError("No filter condition specified")
        
        # Register dataframe and apply filter
        self.conn.register('temp_filter', df)
        query = f"SELECT * FROM temp_filter WHERE {condition}"
        return self.conn.execute(query).fetchdf()
    
    def _execute_aggregate(self, step, intermediate_results):
        """Perform aggregation"""
        source = step.get('source', 'step_0')
        if source not in intermediate_results:
            raise ValueError(f"Source {source} not found")
        
        df = intermediate_results[source]
        group_by = step.get('group_by', [])
        aggregations = step.get('aggregations', [])
        
        if not aggregations:
            raise ValueError("No aggregations specified")
        
        # Build aggregation query
        self.conn.register('temp_agg', df)
        
        agg_exprs = []
        for agg in aggregations:
            col = agg.get('column')
            func = agg.get('function', 'COUNT')
            alias = agg.get('alias', f"{func.lower()}_{col}")
            agg_exprs.append(f"{func}({col}) as {alias}")
        
        if group_by:
            group_clause = ', '.join(group_by)
            query = f"SELECT {group_clause}, {', '.join(agg_exprs)} FROM temp_agg GROUP BY {group_clause}"
        else:
            query = f"SELECT {', '.join(agg_exprs)} FROM temp_agg"
        
        return self.conn.execute(query).fetchdf()
    
    def _execute_join(self, step, intermediate_results):
        """Perform join operation"""
        left_source = step.get('left_source')
        right_source = step.get('right_source')
        
        if left_source not in intermediate_results or right_source not in intermediate_results:
            raise ValueError("Join sources not found")
        
        left_df = intermediate_results[left_source]
        right_df = intermediate_results[right_source]
        
        join_type = step.get('join_type', 'INNER')
        left_on = step.get('left_on')
        right_on = step.get('right_on')
        
        if not left_on or not right_on:
            raise ValueError("Join columns not specified")
        
        # Register dataframes and perform join
        self.conn.register('temp_left', left_df)
        self.conn.register('temp_right', right_df)
        
        query = f"""
            SELECT * FROM temp_left
            {join_type} JOIN temp_right
            ON temp_left.{left_on} = temp_right.{right_on}
        """
        
        return self.conn.execute(query).fetchdf()
    
    def _execute_transform(self, step, intermediate_results):
        """Execute column transformations"""
        source = step.get('source', 'step_0')
        if source not in intermediate_results:
            raise ValueError(f"Source {source} not found")
        
        df = intermediate_results[source]
        transformations = step.get('transformations', [])
        
        if not transformations:
            raise ValueError("No transformations specified")
        
        # Create temp table from source
        self.conn.execute("CREATE OR REPLACE TABLE temp_transform AS SELECT * FROM df")
        
        # Build SELECT statement with transformations
        select_parts = []
        for trans in transformations:
            col_name = trans.get('column_name')
            expression = trans.get('expression')
            if col_name and expression:
                select_parts.append(f"{expression} AS {col_name}")
        
        if not select_parts:
            raise ValueError("No valid transformations found")
        
        # Add all original columns that aren't being transformed
        transformed_cols = {trans.get('column_name') for trans in transformations}
        for col in df.columns:
            if col not in transformed_cols:
                select_parts.append(col)
        
        query = f"SELECT {', '.join(select_parts)} FROM temp_transform"
        return self.conn.execute(query).fetchdf()
    
    def _execute_pivot(self, step, intermediate_results):
        """Perform pivot operation"""
        source = step.get('source', 'step_0')
        if source not in intermediate_results:
            raise ValueError(f"Source {source} not found")
        
        df = intermediate_results[source]
        index_col = step.get('index')
        columns_col = step.get('columns')
        values_col = step.get('values')
        agg_func = step.get('agg_func', 'sum')
        
        if not all([index_col, columns_col, values_col]):
            raise ValueError("Pivot requires index, columns, and values")
        
        # Use pandas pivot_table
        result = df.pivot_table(
            index=index_col,
            columns=columns_col,
            values=values_col,
            aggfunc=agg_func,
            fill_value=0
        ).reset_index()
        
        return result
    
    def _execute_export(self, step, intermediate_results):
        """Export data to file"""
        source = step.get('source', 'step_0')
        if source not in intermediate_results:
            raise ValueError(f"Source {source} not found")
        
        df = intermediate_results[source]
        output_path = step.get('output_path')
        output_format = step.get('format', 'csv')
        
        if not output_path:
            # Use default path
            output_path = os.path.join(
                self.parent_editor.doc_dir,
                f"workflow_export_{int(time.time())}.{output_format}"
            )
        
        if output_format == 'csv':
            df.to_csv(output_path, index=False)
        elif output_format == 'parquet':
            # Use DuckDB for faster parquet export in workflows
            temp_table_name = f"temp_workflow_export_{int(time.time())}"
            try:
                self.conn.register(temp_table_name, df)
                self.conn.execute(f"""
                    COPY (SELECT * FROM {temp_table_name}) 
                    TO '{output_path}' (FORMAT 'parquet', COMPRESSION 'snappy')
                """)
                self.conn.unregister(temp_table_name)
                print(f"✅ Workflow parquet export completed: {output_path}")
            except Exception as e:
                # Fallback to pandas if DuckDB fails
                print(f"⚠️ DuckDB export failed, using pandas fallback: {e}")
                df.to_parquet(output_path, index=False)
        elif output_format == 'excel':
            df.to_excel(output_path, index=False)
        
        return df
    
    def cancel(self):
        """Cancel workflow execution"""
        self.is_cancelled = True
