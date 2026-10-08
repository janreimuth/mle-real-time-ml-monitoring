# Train and Register the Local Model

The prediction API needs a registered MLflow model with the `production` alias. This chapter creates it from the bundled taxi reference, without repeating the earlier model-development lessons.

## Features and Reference Data

The model uses only `PULocationID`, `DOLocationID`, and `trip_distance`. The target is `duration`, measured in minutes.

Location IDs are categorical labels, not ordered quantities. The training pipeline includes a `OneHotEncoder(handle_unknown="ignore")` and `LinearRegression`, so the same encoding is applied when the saved model serves requests.

> **Note:** This is a historical replay. The [TLC data dictionary](https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_green.pdf) describes `trip_distance` as elapsed taximeter distance. These inputs are not all available at pickup, so this is not a pickup-time duration predictor.

The bundled [reference.csv](evidently_service/green_taxi_data/reference.csv) contains the first 20,000 valid rides from January 2024. Trips have durations between 1 and 60 minutes and distances between 0.1 and 100 miles. The traffic generator replays the remaining valid rides, keeping the reference slice separate.

## Start MLflow

From the repository root, run:

```bash
docker compose up -d --build --wait mlflow
```

Open MLflow at <http://127.0.0.1:5001>. Its database and artifacts are stored in the `mlflow-data` Docker volume.

## Train and Register

```bash
uv run train_and_register_model.py
```

The script:

1. trains the categorical encoding and regression pipeline on a reproducible 80/20 split,
2. logs train and holdout RMSE, the signature, and an example input, then registers `green-taxi-ride-duration@production`,
3. refreshes the reference predictions with this same model.

The holdout RMSE is measured in minutes.

Expected output includes the RMSE values, model version, alias assignment, and confirmation that the reference CSV was updated. In MLflow, inspect the run and the registered model.

To use another MLflow server instead, inspect the script's options:

```bash
uv run train_and_register_model.py --help
```

## Keep Predictions and Reference Aligned

The reference includes `duration` and `prediction`, but neither is an API input. Live events contain only the three features and the model's prediction; this lesson does not send actual durations to monitoring.

Re-running training creates a new model version and refreshes `reference.csv`. On the first run, continue to the next chapters before starting the full stack in [chapter 04](04-prometheus-grafana-docker-compose.md#start-the-stack).

**If the full stack is already running**, rebuild monitoring and restart the prediction service afterward: the reference is copied into the image, and the API caches its loaded model.

```bash
docker compose up -d --build --wait evidently_service
docker compose restart model-service
```

## Check Your Understanding

- Why should reference predictions come from the same model as live predictions?
- What does a holdout RMSE tell you that prediction drift cannot?

<details>
<summary>Show Reference Answers</summary>

- Prediction drift compares live predictions with reference predictions. If a different model produced the reference, the two could differ because the models differ, not because the data changed, and monitoring would report false drift.
- RMSE compares predictions with actual durations, so it measures accuracy in minutes. Prediction drift only shows that the predictions' distribution has shifted, not whether they are right or wrong.

</details>
