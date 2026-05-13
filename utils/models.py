"""
Data model classes for Qt table views in SimplSQL.

This module provides:
- PandasModel: QAbstractTableModel for displaying pandas DataFrames
- DataFrameFilterProxy: QSortFilterProxyModel for filtering and sorting tables
"""

import pandas as pd
from PyQt6.QtCore import Qt, QAbstractTableModel, QSortFilterProxyModel


class PandasModel(QAbstractTableModel):
    """
    Qt table model for displaying pandas DataFrames.
    
    This model allows pandas DataFrames to be displayed in Qt table views
    with proper type handling for sorting and display.
    
    Parameters
    ----------
    df : pd.DataFrame, optional
        The DataFrame to display
    parent : QObject, optional
        The parent object
    """
    
    def __init__(self, df: pd.DataFrame = None, parent=None):
        super().__init__(parent)
        self._df = df if df is not None else pd.DataFrame()

    def setDataFrame(self, df: pd.DataFrame):
        """
        Set a new DataFrame for the model.
        
        Parameters
        ----------
        df : pd.DataFrame
            The DataFrame to display
        """
        self.beginResetModel()
        self._df = df.copy()
        self.endResetModel()

    def rowCount(self, parent=None):
        """Return the number of rows."""
        return len(self._df.index)

    def columnCount(self, parent=None):
        """Return the number of columns."""
        return len(self._df.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        """
        Return data for the given index and role.
        
        Parameters
        ----------
        index : QModelIndex
            The model index
        role : Qt.ItemDataRole
            The data role
            
        Returns
        -------
        str or float or None
            The data value for display or sorting
        """
        if not index.isValid():
            return None
        
        val = self._df.iat[index.row(), index.column()]
        
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return '' if pd.isna(val) else str(val)
        elif role == Qt.ItemDataRole.UserRole:
            # Return raw value for sorting - preserve numeric types
            if pd.isna(val):
                return None
            
            # Check if the column itself is numeric
            col_idx = index.column()
            col_name = self._df.columns[col_idx]
            
            try:
                # If the column is numeric type, return as float for proper sorting
                if pd.api.types.is_numeric_dtype(self._df[col_name]):
                    return float(val)
                # If column is object type, try to convert individual value to float
                elif isinstance(val, (int, float)):
                    return float(val)
                # Try parsing string numbers
                elif isinstance(val, str) and val.replace('.', '').replace('-', '').replace('+', '').replace('e', '').replace('E', '').isdigit():
                    return float(val)
                else:
                    # Return as lowercase string for case-insensitive text sorting
                    return str(val).lower()
            except (ValueError, TypeError):
                # If conversion fails, treat as string
                return str(val).lower()
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        """
        Return header data for columns and rows.
        
        Parameters
        ----------
        section : int
            The section number (column or row index)
        orientation : Qt.Orientation
            Horizontal or vertical
        role : Qt.ItemDataRole
            The data role
            
        Returns
        -------
        str or None
            The header text
        """
        if orientation == Qt.Orientation.Horizontal:
            col = self._df.columns[section]
            # Sanitize header text to avoid invisible/control characters that may render oddly
            header_text = str(col)
            if role == Qt.ItemDataRole.DisplayRole:
                try:
                    return header_text.strip().rstrip('\r\n\x00')
                except Exception:
                    return header_text
            if role == Qt.ItemDataRole.ToolTipRole:
                try:
                    return str(self._df[col].dtype)
                except Exception:
                    return ''
        else:
            if role == Qt.ItemDataRole.DisplayRole:
                return str(self._df.index[section])
        return None

    def flags(self, index):
        """Return the item flags for the given index."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable


class DataFrameFilterProxy(QSortFilterProxyModel):
    """
    Proxy model for filtering and sorting DataFrame tables.
    
    Provides advanced filtering with multiple operators:
    - contains, not_contains
    - equals, not_equals
    - starts_with, ends_with
    - greater_than, less_than
    
    Also provides proper sorting for numeric and text columns.
    
    Parameters
    ----------
    parent : QObject, optional
        The parent object
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_text = ''
        self._filter_column = None
        self._filter_operator = 'contains'  # Default operator

    def setFilterText(self, text: str):
        """
        Set the filter text for global filtering.
        
        Parameters
        ----------
        text : str
            The text to filter by
        """
        self._filter_text = (text or '').strip().lower()
        self.invalidateFilter()

    def setFilter(self, column: int, text: str, operator: str = 'contains'):
        """
        Set a column-specific filter with operator.
        
        Parameters
        ----------
        column : int or None
            The column index to filter, or None for global filter
        text : str
            The filter text
        operator : str, optional
            The filter operator (default: 'contains')
            
        Notes
        -----
        If column is None, treats the filter text as global across all columns.
        """
        self._filter_column = column
        self._filter_text = (text or '').strip().lower()
        self._filter_operator = operator or 'contains'
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        """
        Determine if a row passes the filter.
        
        Parameters
        ----------
        source_row : int
            The source model row index
        source_parent : QModelIndex
            The parent index
            
        Returns
        -------
        bool
            True if the row should be displayed
        """
        if not self._filter_text:
            return True
        model = self.sourceModel()
        if model is None:
            return True
        
        # If a specific column is set, only check that column
        if self._filter_column is not None:
            try:
                idx = model.index(source_row, self._filter_column)
                data = model.data(idx, Qt.ItemDataRole.DisplayRole)
                return self._apply_filter_operator(data)
            except Exception:
                return True

        # Global filter across all columns (legacy mode)
        cols = model.columnCount()
        for c in range(cols):
            idx = model.index(source_row, c)
            data = model.data(idx, Qt.ItemDataRole.DisplayRole)
            if self._apply_filter_operator(data):
                return True
        return False
    
    def _apply_filter_operator(self, data):
        """Apply the filter operator to the data."""
        if not data:
            return False
        
        data_str = str(data).lower()
        filter_text = self._filter_text
        
        # Handle multiple values separated by commas (OR logic)
        if ',' in filter_text:
            filter_values = [val.strip() for val in filter_text.split(',') if val.strip()]
            if not filter_values:
                return True
            
            # Apply the operator to each filter value (OR logic)
            for filter_val in filter_values:
                if self._single_value_filter(data_str, filter_val):
                    return True
            return False
        else:
            # Single value filter
            return self._single_value_filter(data_str, filter_text)
    
    def _single_value_filter(self, data_str, filter_val):
        """Apply filter operator to a single filter value."""
        if self._filter_operator == 'contains':
            return filter_val in data_str
        elif self._filter_operator == 'not_contains':
            return filter_val not in data_str
        elif self._filter_operator == 'equals':
            return filter_val == data_str
        elif self._filter_operator == 'not_equals':
            return filter_val != data_str
        elif self._filter_operator == 'starts_with':
            return data_str.startswith(filter_val)
        elif self._filter_operator == 'ends_with':
            return data_str.endswith(filter_val)
        elif self._filter_operator == 'greater_than':
            try:
                return float(data_str) > float(filter_val)
            except (ValueError, TypeError):
                return False
        elif self._filter_operator == 'less_than':
            try:
                return float(data_str) < float(filter_val)
            except (ValueError, TypeError):
                return False
        else:
            # Default to contains
            return filter_val in data_str

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        """
        Return sequential 1-based row numbers for the vertical header.
        
        The proxy's sections correspond to visible rows after filtering/sorting,
        so this yields natural serial numbers for displayed rows.
        
        Parameters
        ----------
        section : int
            The section number
        orientation : Qt.Orientation
            Horizontal or vertical
        role : Qt.ItemDataRole
            The data role
            
        Returns
        -------
        str or None
            The header text
        """
        if orientation == Qt.Orientation.Vertical and role == Qt.ItemDataRole.DisplayRole:
            try:
                return str(section + 1)
            except Exception:
                return str(section)
        # Fallback to default behavior for horizontal headers and other roles
        return super().headerData(section, orientation, role)
    
    def lessThan(self, source_left, source_right):
        """
        Custom sorting comparison to handle numeric vs string data properly.
        
        Parameters
        ----------
        source_left : QModelIndex
            Left item index
        source_right : QModelIndex
            Right item index
            
        Returns
        -------
        bool
            True if left < right
        """
        try:
            # Get the raw values for comparison (UserRole preserves data types)
            left_data = self.sourceModel().data(source_left, Qt.ItemDataRole.UserRole)
            right_data = self.sourceModel().data(source_right, Qt.ItemDataRole.UserRole)
            
            # Handle None/null values - put them at the end
            if left_data is None and right_data is None:
                return False
            if left_data is None:
                return False  # None is "greater than" any value (goes to end)
            if right_data is None:
                return True   # Any value is "less than" None
            
            # Both values exist, compare them directly
            # Since UserRole now returns proper types (float for numbers, str for strings)
            # Python's < operator will handle the comparison correctly
            return left_data < right_data
            
        except Exception:
            # Fallback to default comparison if anything goes wrong
            return super().lessThan(source_left, source_right)
