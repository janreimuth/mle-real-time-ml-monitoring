"""Configuration, report execution and Prometheus export for the monitoring API."""

import hashlib
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pandas as pd
import yaml
from evidently import DataDefinition, Dataset, Report
from evidently.metrics import DriftedColumnsCount, ValueDrift
from prometheus_client import Gauge

logger = logging.getLogger(__name__)


def load_config(config_path: str) -> dict[str, Any]:
    with open(config_path, "rb") as file:
        return yaml.safe_load(file)


def build_data_definition(config: Mapping[str, Any]) -> DataDefinition:
    columns = config["column_mapping"]
    return DataDefinition(
        numerical_columns=columns["numerical_features"] + [columns["prediction"]],
        categorical_columns=columns["categorical_features"],
    )


def create_report(config: Mapping[str, Any]) -> Report:
    prediction = config["column_mapping"]["prediction"]
    # Pin the numeric distance and threshold so the dashboard never labels a
    # Wasserstein distance as a p-value after a sample-size-dependent test switch.
    return Report(
        metrics=[
            cast(Any, ValueDrift)(
                column=prediction, method="wasserstein", threshold=0.1
            ),
            cast(Any, DriftedColumnsCount)(),
        ]
    )


def extract_metrics_from_snapshot(snapshot: Any) -> dict[str, float]:
    """Flatten Evidently's scalar and count/share results into named gauges."""
    results: dict[str, float] = {}
    for metric in snapshot.dict()["metrics"]:
        base_name = metric["metric_name"].split("(")[0]
        column = metric["config"].get("column")
        prefix = f"{base_name}_{column}" if column else base_name
        value = metric["value"]
        if isinstance(value, dict):
            for key, number in value.items():
                results[f"{prefix}_{key}"] = float(number)
        else:
            results[prefix] = float(value)
    return results


def update_prometheus_metrics(
    metrics_dict: Mapping[str, float],
    gauge_store: dict[str, Gauge],
    dataset_name: str,
) -> None:
    for name, value in metrics_dict.items():
        if name not in gauge_store:
            gauge_store[name] = Gauge(
                f"evidently_{name.lower()}",
                f"Evidently metric {name}",
                labelnames=["dataset_name"],
            )
        gauge_store[name].labels(dataset_name=dataset_name).set(value)


def run_evidently(
    reference_data: Dataset,
    current_data: pd.DataFrame,
    data_definition: DataDefinition,
    report: Report,
    gauge_store: dict[str, Gauge],
    dataset_name: str,
    report_path: Path,
) -> None:
    current_dataset = Dataset.from_pandas(current_data, data_definition=data_definition)
    snapshot = report.run(reference_data=reference_data, current_data=current_dataset)
    # Serve only complete HTML files, even while another request reads /report.
    temporary_path = report_path.with_suffix(".tmp.html")
    snapshot.save_html(str(temporary_path))
    temporary_path.replace(report_path)
    metrics = extract_metrics_from_snapshot(snapshot)
    update_prometheus_metrics(metrics, gauge_store, dataset_name)
    logger.info("Report updated and %s metrics exported to Prometheus.", len(metrics))


def compute_hash(df: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(df).values.tobytes()).hexdigest()
