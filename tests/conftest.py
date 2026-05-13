"""
Pytest configuration and fixtures for SimpliSQL tests.
"""

import os
import pytest
import tempfile
import json
import duckdb
import pandas as pd
from pathlib import Path


@pytest.fixture
def temp_app_dir():
    """Create a temporary application directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create required subdirectories
        os.makedirs(os.path.join(tmpdir, "ParquetFiles"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "Auto_Workflow"), exist_ok=True)
        yield tmpdir


@pytest.fixture
def duckdb_connection():
    """Create an in-memory DuckDB connection for testing."""
    conn = duckdb.connect(database=":memory:", read_only=False)
    yield conn
    conn.close()


@pytest.fixture
def sample_dataframe():
    """Create a sample DataFrame for testing."""
    return pd.DataFrame({
        'id': [1, 2, 3, 4, 5],
        'name': ['Alice', 'Bob', 'Charlie', 'David', 'Eve'],
        'amount': [100.0, 250.5, 150.75, 200.0, 175.25],
        'date': pd.date_range('2024-01-01', periods=5)
    })


@pytest.fixture
def sample_parquet_file(temp_app_dir, sample_dataframe):
    """Create a sample Parquet file for testing."""
    parquet_path = os.path.join(temp_app_dir, "ParquetFiles", "test_data.parquet")
    sample_dataframe.to_parquet(parquet_path, index=False)
    return parquet_path


@pytest.fixture
def sample_csv_file(temp_app_dir, sample_dataframe):
    """Create a sample CSV file for testing."""
    csv_path = os.path.join(temp_app_dir, "test_data.csv")
    sample_dataframe.to_csv(csv_path, index=False)
    return csv_path
