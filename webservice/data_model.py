"""Pydantic request and response models for the prediction API."""

from pydantic import BaseModel, ConfigDict, Field


class TaxiRide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    PULocationID: int = Field(ge=1)
    DOLocationID: int = Field(ge=1)
    trip_distance: float = Field(gt=0, allow_inf_nan=False)


# Prediction responses and monitoring events share this schema.
class TaxiRidePrediction(TaxiRide):
    prediction: float = Field(allow_inf_nan=False)
