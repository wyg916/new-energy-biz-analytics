from __future__ import annotations

from sqlalchemy.orm import Session

from app.data.open_source import ACN_RUN_ID, DATA_CLASSIFICATION
from app.scenarios.registry import published_charging_ops_batch


def current_data_truth(db: Session) -> dict:
    batch = published_charging_ops_batch(db)
    if batch and batch.batch_id == ACN_RUN_ID:
        return {
            "data_classification": DATA_CLASSIFICATION,
            "source": "PostgreSQL semantic layer / ACN-Data via ORNL",
            "source_name": "ACN-Data via ORNL OpenEnergyDataPortal",
            "dataset_version": "ornl-acn-discovery-2020-v1",
            "transformation_version": "data41-acn-transform-v1",
            "run_id": ACN_RUN_ID,
            "is_open_source": True,
        }
    return {
        "data_classification": "simulated",
        "source": "platform_database",
        "source_name": "fixed-seed simulated dataset",
        "dataset_version": None,
        "transformation_version": None,
        "run_id": batch.batch_id if batch else None,
        "is_open_source": False,
    }
