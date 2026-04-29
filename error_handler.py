"""Error handling utilities."""
import json
from typing import Any


def safe_json_load(file_path: str, default: Any = None) -> Any:
    """Safely load JSON from a file.

    Args:
        file_path: Path to JSON file
        default: Default value to return on error (empty dict if None)

    Returns:
        Loaded JSON data or default value
    """
    if default is None:
        default = {}

    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        return default
    except Exception:
        return default
