# Exception Handling Guidelines

## Goals
- Keep user-facing behavior stable while making failures diagnosable.
- Catch expected exceptions close to the operation that can fail.
- Avoid masking unrelated bugs with broad catch-all handlers.

## Rules
1. Prefer typed exceptions over catch-all blocks.
2. Use `except Exception` only at strict boundaries (top-level UI event handlers, thread boundaries), and log with context.
3. Avoid bare `except:` entirely.
4. Preserve fallback behavior where recovery is intentional (for example, CSV type fallback), but log the original failure.
5. Keep `try` blocks narrow so the caught exception maps to a single operation.

## Recommended Patterns

```python
try:
    data = json.load(f)
except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
    logger.warning("Failed to load config from %s: %s", config_path, e)
    data = default_config
```

```python
try:
    conn.unregister(temp_table)
except (duckdb.Error, RuntimeError, AttributeError):
    pass
```

```python
try:
    do_operation()
except (ValueError, TypeError) as e:
    logger.error("Validation failed: %s", e)
    raise
```

## Logging
- Use `logger.warning` for recoverable issues.
- Use `logger.error` for failed operations that impact user tasks.
- Use `logger.exception` when stack traces are needed during fallback transitions.

## File-Specific Notes
- Upload and merge paths in `Simplisql.py` should catch: `duckdb.Error`, `OSError`, `ValueError`, `TypeError`, and format-specific exceptions like `zipfile.BadZipFile`.
- View persistence paths in `ui/view_manager.py` should catch: `OSError`, `json.JSONDecodeError`, `TypeError`, `ValueError`.
