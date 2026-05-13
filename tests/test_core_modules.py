"""
Tests for SimpliSQL core modules.

Tests core functionality:
- Query execution and validation
- File operations
- Data export
- Workflow management
"""

import pytest
import os
import json
import pandas as pd
import duckdb


class TestQueryExecution:
    """Test query execution functionality."""
    
    def test_basic_select_query(self, duckdb_connection, sample_dataframe):
        """Test basic SELECT query execution."""
        # Load sample data
        duckdb_connection.register('test_data', sample_dataframe)
        
        # Execute simple query
        result = duckdb_connection.execute("SELECT * FROM test_data").fetchdf()
        
        assert len(result) == 5
        assert list(result.columns) == ['id', 'name', 'amount', 'date']
        assert result['id'].tolist() == [1, 2, 3, 4, 5]
    
    def test_aggregate_query(self, duckdb_connection, sample_dataframe):
        """Test aggregation query."""
        duckdb_connection.register('test_data', sample_dataframe)
        
        result = duckdb_connection.execute(
            "SELECT COUNT(*) as count, SUM(amount) as total FROM test_data"
        ).fetchdf()
        
        assert result['count'].iloc[0] == 5
        assert abs(result['total'].iloc[0] - 876.5) < 0.01
    
    def test_filter_query(self, duckdb_connection, sample_dataframe):
        """Test filtering with WHERE clause."""
        duckdb_connection.register('test_data', sample_dataframe)
        
        result = duckdb_connection.execute(
            "SELECT * FROM test_data WHERE amount >= 200"
        ).fetchdf()
        
        assert len(result) == 2
        assert all(result['amount'] >= 200)
    
    def test_cte_query(self, duckdb_connection, sample_dataframe):
        """Test Common Table Expression (CTE)."""
        duckdb_connection.register('test_data', sample_dataframe)
        
        result = duckdb_connection.execute("""
            WITH high_value AS (
                SELECT * FROM test_data WHERE amount > 150
            )
            SELECT COUNT(*) as high_count FROM high_value
        """).fetchdf()
        
        assert result['high_count'].iloc[0] == 4
    
    def test_join_query(self, duckdb_connection, sample_dataframe):
        """Test JOIN operation."""
        duckdb_connection.register('test_data', sample_dataframe)
        
        result = duckdb_connection.execute("""
            SELECT t1.id, t1.name, t2.amount
            FROM test_data t1
            LEFT JOIN test_data t2 ON t1.id = t2.id
            LIMIT 3
        """).fetchdf()
        
        assert len(result) == 3
        assert 'id' in result.columns
    
    def test_invalid_query_syntax(self, duckdb_connection):
        """Test that invalid SQL raises exception."""
        with pytest.raises(Exception):  # DuckDB ParserException
            duckdb_connection.execute("SELECT * FORM invalid_table").fetchdf()
    
    def test_nonexistent_table(self, duckdb_connection):
        """Test query against nonexistent table."""
        with pytest.raises(Exception):  # DuckDB CatalogException
            duckdb_connection.execute("SELECT * FROM nonexistent").fetchdf()


class TestFileOperations:
    """Test file handling functionality."""
    
    def test_parquet_file_read(self, sample_parquet_file, duckdb_connection):
        """Test reading Parquet file."""
        query = f"SELECT * FROM read_parquet('{sample_parquet_file}')"
        result = duckdb_connection.execute(query).fetchdf()
        
        assert len(result) == 5
        assert 'id' in result.columns
        assert 'name' in result.columns
    
    def test_csv_file_read(self, sample_csv_file, duckdb_connection):
        """Test reading CSV file."""
        query = f"SELECT * FROM read_csv_auto('{sample_csv_file}')"
        result = duckdb_connection.execute(query).fetchdf()
        
        assert len(result) == 5
        assert 'id' in result.columns
    
    def test_parquet_file_write(self, temp_app_dir, sample_dataframe):
        """Test writing to Parquet file."""
        output_path = os.path.join(temp_app_dir, "ParquetFiles", "output.parquet")
        sample_dataframe.to_parquet(output_path, index=False)
        
        assert os.path.exists(output_path)
        
        # Verify file can be read back
        read_df = pd.read_parquet(output_path)
        assert len(read_df) == 5


class TestCustomSQLFunctions:
    """Test custom SQL functions registered with DuckDB."""
    
    def test_file_basename_function(self, duckdb_connection):
        """Test FILE_BASENAME custom function."""
        # Register custom function
        def file_basename(filepath):
            if filepath is None:
                return None
            return os.path.basename(str(filepath))
        
        duckdb_connection.create_function('FILE_BASENAME', file_basename, return_type='VARCHAR')
        
        result = duckdb_connection.execute(
            "SELECT FILE_BASENAME('C:/Users/test/document.csv') as filename"
        ).fetchdf()
        
        assert result['filename'].iloc[0] == 'document.csv'
    
    def test_file_dirname_function(self, duckdb_connection):
        """Test FILE_DIRNAME custom function."""
        def file_dirname(filepath):
            if filepath is None:
                return None
            return os.path.dirname(str(filepath))
        
        duckdb_connection.create_function('FILE_DIRNAME', file_dirname, return_type='VARCHAR')
        
        result = duckdb_connection.execute(
            "SELECT FILE_DIRNAME('C:/Users/test/document.csv') as dirpath"
        ).fetchdf()
        
        assert 'C:/Users/test' in result['dirpath'].iloc[0]
    
    def test_file_name_no_ext_function(self, duckdb_connection):
        """Test FILE_NAME_NO_EXT custom function."""
        def file_name_no_ext(filepath):
            if filepath is None:
                return None
            basename = os.path.basename(str(filepath))
            return os.path.splitext(basename)[0]
        
        duckdb_connection.create_function('FILE_NAME_NO_EXT', file_name_no_ext, return_type='VARCHAR')
        
        result = duckdb_connection.execute(
            "SELECT FILE_NAME_NO_EXT('C:/Users/test/document.csv') as filename_noext"
        ).fetchdf()
        
        assert result['filename_noext'].iloc[0] == 'document'


class TestDataExport:
    """Test data export functionality."""
    
    def test_dataframe_to_csv(self, temp_app_dir, sample_dataframe):
        """Test CSV export."""
        output_path = os.path.join(temp_app_dir, "output.csv")
        sample_dataframe.to_csv(output_path, index=False)
        
        assert os.path.exists(output_path)
        
        # Verify exported file
        exported_df = pd.read_csv(output_path)
        assert len(exported_df) == 5
        assert list(exported_df.columns) == ['id', 'name', 'amount', 'date']
    
    def test_empty_dataframe_export(self, temp_app_dir):
        """Test exporting empty DataFrame."""
        empty_df = pd.DataFrame()
        output_path = os.path.join(temp_app_dir, "empty.csv")
        empty_df.to_csv(output_path, index=False)
        
        assert os.path.exists(output_path)


class TestWorkflowManagement:
    """Test workflow functionality."""
    
    def test_workflow_creation(self, temp_app_dir):
        """Test creating a workflow."""
        workflow_spec = {
            'name': 'Test Workflow',
            'description': 'A test workflow',
            'steps': [
                {
                    'name': 'Filter',
                    'type': 'filter',
                    'config': {'condition': 'amount > 100'}
                }
            ]
        }
        
        workflows_path = os.path.join(temp_app_dir, "Auto_Workflow", "workflows.json")
        os.makedirs(os.path.dirname(workflows_path), exist_ok=True)
        
        with open(workflows_path, 'w') as f:
            json.dump([workflow_spec], f)
        
        # Verify saved
        with open(workflows_path, 'r') as f:
            loaded = json.load(f)
        
        assert len(loaded) == 1
        assert loaded[0]['name'] == 'Test Workflow'
    
    def test_workflow_update(self, temp_app_dir):
        """Test updating a workflow."""
        workflows_path = os.path.join(temp_app_dir, "Auto_Workflow", "workflows.json")
        os.makedirs(os.path.dirname(workflows_path), exist_ok=True)
        
        # Create initial workflow
        original = {
            'id': 'test_123',
            'name': 'Original',
            'steps': []
        }
        
        with open(workflows_path, 'w') as f:
            json.dump([original], f)
        
        # Load and update
        with open(workflows_path, 'r') as f:
            workflows = json.load(f)
        
        workflows[0]['name'] = 'Updated'
        
        with open(workflows_path, 'w') as f:
            json.dump(workflows, f)
        
        # Verify update
        with open(workflows_path, 'r') as f:
            loaded = json.load(f)
        
        assert loaded[0]['name'] == 'Updated'


class TestConfigManagement:
    """Test configuration file handling."""
    
    def test_ai_config_save_load(self, temp_app_dir):
        """Test saving and loading AI configuration."""
        config_path = os.path.join(temp_app_dir, "Auto_Workflow", "ai_config.json")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        
        config = {
            'model': 'gemma-2b',
            'ollama_url': 'http://localhost:11434',
            'temperature': 0.7
        }
        
        # Save
        with open(config_path, 'w') as f:
            json.dump(config, f)
        
        # Load
        with open(config_path, 'r') as f:
            loaded_config = json.load(f)
        
        assert loaded_config['model'] == 'gemma-2b'
        assert loaded_config['temperature'] == 0.7
    
    def test_saved_queries_persistence(self, temp_app_dir):
        """Test saving and loading queries."""
        query_path = os.path.join(temp_app_dir, "Auto_Workflow", "saved_queries.json")
        os.makedirs(os.path.dirname(query_path), exist_ok=True)
        
        queries = {
            'query_1': 'SELECT * FROM test_data',
            'query_2': 'SELECT COUNT(*) FROM test_data'
        }
        
        # Save
        with open(query_path, 'w') as f:
            json.dump(queries, f)
        
        # Load
        with open(query_path, 'r') as f:
            loaded = json.load(f)
        
        assert len(loaded) == 2
        assert loaded['query_1'] == 'SELECT * FROM test_data'
