"""Storage: named collections of records, in local JSON files or one DynamoDB table.

A Database hands out collections ("reviews", "users", "sources", ...). Each
collection has the same small interface, so route code doesn't care where data lives.

Local:  data/<collection>.json, one file per collection.
AWS:    one DynamoDB table with partition key `collection` (String) and sort key
        `id` (String). Listing a collection is a Query, not a full-table Scan.
"""
import json
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

# Collection names used across the app.
REVIEWS = "reviews"
USERS = "users"
SETTINGS = "settings"
NOTIFICATIONS = "notifications"
DIGESTS = "digests"


class Storage(Protocol):
    def list(self) -> list[dict]: ...
    def get(self, item_id: str) -> dict | None: ...
    def put(self, item: dict) -> dict: ...
    def delete(self, item_id: str) -> None: ...


class Database(Protocol):
    def collection(self, name: str) -> Storage: ...


# --- Local ---

class LocalStorage:
    """Stores one collection in a JSON file. No AWS needed."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _read(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text() or "{}")

    def _write(self, data: dict[str, dict]) -> None:
        self.path.write_text(json.dumps(data, indent=2))

    def list(self) -> list[dict]:
        return list(self._read().values())

    def get(self, item_id: str) -> dict | None:
        return self._read().get(item_id)

    def put(self, item: dict) -> dict:
        with self._lock:
            data = self._read()
            data[item["id"]] = item
            self._write(data)
        return item

    def delete(self, item_id: str) -> None:
        with self._lock:
            data = self._read()
            data.pop(item_id, None)
            self._write(data)


class LocalDatabase:
    """One JSON file per collection inside `data_dir`."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self._collections: dict[str, LocalStorage] = {}
        self._lock = threading.Lock()

    def collection(self, name: str) -> LocalStorage:
        with self._lock:
            if name not in self._collections:
                self._collections[name] = LocalStorage(self.data_dir / f"{name}.json")
            return self._collections[name]


# --- DynamoDB ---

def _to_dynamo(value: Any) -> Any:
    """DynamoDB rejects Python floats, so store them as Decimal."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_dynamo(v) for v in value]
    return value


def _from_dynamo(value: Any) -> Any:
    """DynamoDB returns every number as Decimal; turn them back into int or float."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_dynamo(v) for v in value]
    return value


class DynamoStorage:
    """One collection inside the shared table (partition key `collection`, sort key `id`)."""

    def __init__(self, table, collection: str):
        self.table = table
        self.collection = collection

    def _key(self, item_id: str) -> dict:
        return {"collection": self.collection, "id": item_id}

    @staticmethod
    def _clean(item: dict) -> dict:
        item = _from_dynamo(item)
        item.pop("collection", None)
        return item

    def list(self) -> list[dict]:
        from boto3.dynamodb.conditions import Key

        query = {"KeyConditionExpression": Key("collection").eq(self.collection)}
        response = self.table.query(**query)
        items = response.get("Items", [])
        # A single query returns at most 1 MB, so keep going until all pages are read.
        while "LastEvaluatedKey" in response:
            response = self.table.query(**query, ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))
        return [self._clean(i) for i in items]

    def get(self, item_id: str) -> dict | None:
        item = self.table.get_item(Key=self._key(item_id)).get("Item")
        return self._clean(item) if item else None

    def put(self, item: dict) -> dict:
        if "collection" in item:
            raise ValueError("'collection' is a reserved field name")
        self.table.put_item(Item=_to_dynamo({**item, "collection": self.collection}))
        return item

    def delete(self, item_id: str) -> None:
        self.table.delete_item(Key=self._key(item_id))


class DynamoDatabase:
    """All collections share one DynamoDB table."""

    def __init__(self, table_name: str, region: str):
        import boto3  # imported lazily so local mode doesn't need boto3

        self.table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def collection(self, name: str) -> DynamoStorage:
        return DynamoStorage(self.table, name)
