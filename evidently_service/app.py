"""Receive prediction events and expose an Evidently report and metrics."""

import logging
import time
from pathlib import Path
from threading import Lock

import pandas as pd
from evidently import Dataset
from fastapi import FastAPI, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest

from evidently_service.utils import (
    build_data_definition,
    compute_hash,
    create_report,
    load_config,
    run_evidently,
)
from webservice.data_model import TaxiRidePrediction
from webservice.validation import validation_error_handler

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
REPORT_PATH = BASE_DIR / "latest_report.html"
# A restarted process has an empty window; do not serve the previous report.
REPORT_PATH.unlink(missing_ok=True)
DATASET_NAME = "green_taxi_data"

config = load_config(str(BASE_DIR / "config.yaml"))
data_definition = build_data_definition(config)
categorical_features = config["column_mapping"]["categorical_features"]
reference_df = pd.read_csv(
    BASE_DIR / config["service"]["reference_path"],
    dtype=dict.fromkeys(categorical_features, str),
)
reference_data = Dataset.from_pandas(reference_df, data_definition=data_definition)
report = create_report(config)
window_size = config["service"]["window_size"]
calculation_period = config["service"]["calculation_period_sec"]
if window_size < 2 or calculation_period <= 0:
    raise ValueError(
        "window_size must be at least 2 and calculation_period_sec positive."
    )

reference_hash = Gauge(
    "evidently_reference_dataset_hash",
    "Hash of the reference dataset used for monitoring",
    labelnames=["hash"],
)
reference_hash.labels(hash=compute_hash(reference_df)).set(1)
last_event_timestamp = Gauge(
    "evidently_last_event_timestamp_seconds",
    "Unix timestamp of the last accepted prediction event; zero before any event",
    ["dataset_name"],
).labels(dataset_name=DATASET_NAME)
last_report_timestamp = Gauge(
    "evidently_last_report_timestamp_seconds",
    "Unix timestamp of the last successful report; zero before any report",
    ["dataset_name"],
).labels(dataset_name=DATASET_NAME)
logger.info(
    "Loaded %s reference rows; live window size is %s", len(reference_df), window_size
)

app = FastAPI(title="Taxi Prediction Monitoring")
app.add_exception_handler(RequestValidationError, validation_error_handler)
current_data = pd.DataFrame()
gauge_store: dict[str, Gauge] = {}
last_calculation = 0.0
# FastAPI runs synchronous handlers in threads. Protect this single shared window.
buffer_lock = Lock()


@app.get("/")
def health():
    with buffer_lock:
        return {
            "status": "ok",
            "buffered_rows": len(current_data),
            "window_size": window_size,
        }


@app.post("/iterate/{dataset}")
def iterate(dataset: str, data: TaxiRidePrediction):
    global current_data, last_calculation

    if dataset != DATASET_NAME:
        raise HTTPException(status_code=404, detail="Unknown dataset")

    row = data.model_dump()
    for column in categorical_features:
        row[column] = str(row[column])
    incoming_df = pd.DataFrame([row])

    with buffer_lock:
        current_data = (
            (
                incoming_df
                if current_data.empty
                else pd.concat([current_data, incoming_df], ignore_index=True)
            )
            .tail(window_size)
            .reset_index(drop=True)
        )
        last_event_timestamp.set(time.time())
        logger.info("Buffered %s/%s rows", len(current_data), window_size)

        if len(current_data) < window_size:
            return {"status": "buffering", "buffered_rows": len(current_data)}

        # Refresh on incoming traffic, at most once per configured period.
        # The first full window always produces a report immediately.
        if (
            last_calculation == 0
            or time.monotonic() - last_calculation >= calculation_period
        ):
            run_evidently(
                reference_data,
                current_data,
                data_definition,
                report,
                gauge_store,
                dataset_name=dataset,
                report_path=REPORT_PATH,
            )
            last_calculation = time.monotonic()
            last_report_timestamp.set(time.time())

        return {"status": "ok", "buffered_rows": len(current_data)}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})


@app.get("/report")
def view_report():
    if not REPORT_PATH.exists():
        raise HTTPException(status_code=404, detail="Report not generated yet")
    return FileResponse(REPORT_PATH, media_type="text/html")
