from __future__ import annotations

from typing import Any

from botocore.config import Config


def make_ddb_client_config(*, max_pool_connections: int = 25) -> Config:
    """Return a botocore Config sized for our concurrent workloads."""
    return Config(
        max_pool_connections=max_pool_connections,
        retries={"mode": "standard", "max_attempts": 3},
    )


def unmarshal_dynamodb_value(value: dict[str, Any]) -> Any:
    """Convert one DynamoDB attribute-value dict to a plain Python value."""
    if "NULL" in value:
        return None
    if "BOOL" in value:
        return value["BOOL"]
    if "S" in value:
        return value["S"]
    if "N" in value:
        text = value["N"]
        return int(text) if "." not in text else float(text)
    if "L" in value:
        return [unmarshal_dynamodb_value(v) for v in value["L"]]
    if "M" in value:
        return {k: unmarshal_dynamodb_value(v) for k, v in value["M"].items()}
    return None


def unmarshal_image(image: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Convert a full DynamoDB image (e.g. NewImage) to a plain dict."""
    return {k: unmarshal_dynamodb_value(v) for k, v in image.items()}


__all__ = [
    "make_ddb_client_config",
    "unmarshal_dynamodb_value",
    "unmarshal_image",
]
