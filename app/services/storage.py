"""Item storage: a local JSON file, or DynamoDB."""
import json
import threading
from pathlib import Path
from typing import Protocol


class Storage(Protocol):
    def list(self) -> list[dict]: ...
    def get(self, item_id: str) -> dict | None: ...
    def put(self, item: dict) -> dict: ...
    def delete(self, item_id: str) -> None: ...


class LocalStorage:
    """Stores items in a JSON file. No AWS needed."""

    def __init__(self, path: str):
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


class DynamoStorage:
    """Stores items in a DynamoDB table with partition key `id` (string)."""

    def __init__(self, table_name: str, region: str):
        import boto3  # imported lazily so local mode doesn't need boto3

        self.table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def list(self) -> list[dict]:
        # A single scan returns at most 1 MB, so keep going until all pages are read.
        response = self.table.scan()
        items = response.get("Items", [])
        while "LastEvaluatedKey" in response:
            response = self.table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))
        return items

    def get(self, item_id: str) -> dict | None:
        return self.table.get_item(Key={"id": item_id}).get("Item")

    def put(self, item: dict) -> dict:
        self.table.put_item(Item=item)
        return item

    def delete(self, item_id: str) -> None:
        self.table.delete_item(Key={"id": item_id})
