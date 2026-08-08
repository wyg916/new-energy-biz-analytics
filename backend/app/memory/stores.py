from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class DeleteStore(Protocol):
    name: str
    configured: bool

    def delete(self, resource_id: str) -> bool: ...
    def absent(self, resource_id: str) -> bool: ...


@dataclass
class DisabledDeleteStore:
    name: str
    configured: bool = False

    def delete(self, resource_id: str) -> bool:
        return True

    def absent(self, resource_id: str) -> bool:
        return True


class RedisMemoryStore:
    name = "REDIS"
    configured = True

    def __init__(self, client) -> None:
        self.client = client

    @staticmethod
    def keys(resource_id: str) -> tuple[str, ...]:
        if resource_id.startswith("working-registry::"):
            return (resource_id.split("::", 1)[1],)
        return (
            f"memory:record:{resource_id}",
            f"memory:embedding:{resource_id}",
        )

    def delete(self, resource_id: str) -> bool:
        keys = self.keys(resource_id)
        if resource_id.startswith("working-registry::"):
            members = self.client.smembers(keys[0]) or ()
            normalized = tuple(
                item.decode("utf-8") if isinstance(item, bytes) else str(item)
                for item in members
            )
            keys = (*normalized, *keys)
        self.client.delete(*keys)
        return self.absent(resource_id)

    def absent(self, resource_id: str) -> bool:
        return not any(bool(self.client.exists(key)) for key in self.keys(resource_id))


class DerivedIndexStore:
    name = "VECTOR"
    configured = True

    def __init__(self, index) -> None:
        self.index = index

    def delete(self, resource_id: str) -> bool:
        return bool(self.index.delete(resource_id))

    def absent(self, resource_id: str) -> bool:
        exists = getattr(self.index, "exists", None)
        if exists is None:
            raise RuntimeError("VECTOR_DELETE_VERIFICATION_UNSUPPORTED")
        return not bool(exists(resource_id))


class ObjectMemoryStore:
    name = "OBJECT"
    configured = True

    def __init__(self, object_store) -> None:
        self.object_store = object_store

    def delete(self, resource_id: str) -> bool:
        return bool(self.object_store.delete(resource_id))

    def absent(self, resource_id: str) -> bool:
        exists = getattr(self.object_store, "exists", None)
        if exists is None:
            raise RuntimeError("OBJECT_DELETE_VERIFICATION_UNSUPPORTED")
        return not bool(exists(resource_id))


def store_registry(*, redis_client=None, derived_index=None, object_store=None) -> dict[str, DeleteStore]:
    return {
        "REDIS": RedisMemoryStore(redis_client) if redis_client is not None else DisabledDeleteStore("REDIS"),
        "VECTOR": DerivedIndexStore(derived_index) if derived_index is not None else DisabledDeleteStore("VECTOR"),
        "OBJECT": ObjectMemoryStore(object_store) if object_store is not None else DisabledDeleteStore("OBJECT"),
    }
