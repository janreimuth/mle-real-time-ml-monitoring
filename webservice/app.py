"""Prediction API with monitoring delivery and Prometheus service metrics."""

import logging
import os

import requests
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from prometheus_client import Counter
from prometheus_fastapi_instrumentator import Instrumentator

from webservice.data_model import TaxiRide, TaxiRidePrediction
from webservice.predict import ModelUnavailableError, predict
from webservice.validation import validation_error_handler

# Compose supplies the monitoring service's internal URL.
MONITORING_URL = os.getenv(
    "MONITORING_URL", "http://evidently_service:8085/iterate/green_taxi_data"
)

app = FastAPI()
app.add_exception_handler(RequestValidationError, validation_error_handler)
logger = logging.getLogger(__name__)
monitoring_delivery_failures = Counter(
    "monitoring_delivery_failures_total",
    "Failed attempts to deliver prediction events to monitoring",
)

Instrumentator().instrument(app).expose(app)


@app.get("/")
def index():
    # Liveness only; the prediction route checks model availability.
    return {"message": "NYC Taxi Ride Duration Prediction"}


@app.post("/predict", response_model=TaxiRidePrediction)
def predict_duration(data: TaxiRide):
    try:
        prediction = predict("green-taxi-ride-duration", data)
    except ModelUnavailableError as error:
        logger.warning("Model unavailable: %s", error)
        raise HTTPException(
            status_code=503,
            detail="Model unavailable. Check MLFLOW_TRACKING_URI, start MLflow and "
            "run 'uv run train_and_register_model.py', then retry.",
        ) from error
    try:
        monitoring_payload = TaxiRidePrediction(
            **data.model_dump(), prediction=prediction
        ).model_dump()

        # Synchronous delivery failure must not fail a valid prediction.
        response = requests.post(
            MONITORING_URL,
            json=monitoring_payload,
            timeout=5,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as error:
        monitoring_delivery_failures.inc()
        logger.warning("Monitoring delivery failed: %s", error)

    return TaxiRidePrediction(**data.model_dump(), prediction=prediction)
