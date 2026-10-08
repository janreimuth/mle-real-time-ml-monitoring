"""Helpers for loading the registered MLflow model and serving predictions."""

import os
from functools import lru_cache

import mlflow
import pandas as pd
from dotenv import load_dotenv
from mlflow.exceptions import MlflowException


class ModelUnavailableError(RuntimeError):
    """The registered model cannot be loaded for inference."""


# Restart the API to clear this cache after changing the production alias.
@lru_cache(maxsize=1)
def load_model(model_name):
    alias = "production"
    model_uri = f"models:/{model_name}@{alias}"

    try:
        model = mlflow.pyfunc.load_model(model_uri)
    except (MlflowException, OSError) as error:
        raise ModelUnavailableError("Could not load the production model.") from error
    return model


def predict(model_name, data):
    # Compose injects this variable; local runs can read it from .env.
    load_dotenv()
    MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI")
    if not MLFLOW_TRACKING_URI:
        raise ModelUnavailableError("MLFLOW_TRACKING_URI is not set.")

    # MLflow needs the tracking URI before resolving models:/ URIs.
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

    # MLflow expects tabular inputs with categorical location IDs.
    model_input = pd.DataFrame([data.model_dump()])
    model_input[["PULocationID", "DOLocationID"]] = model_input[
        ["PULocationID", "DOLocationID"]
    ].astype(str)

    model = load_model(model_name)
    prediction = model.predict(model_input)
    return float(prediction[0])
