"""Bootstrap the local MLflow model used by the monitoring tutorial."""

import logging
import time
from pathlib import Path

import click

DEFAULT_INPUT_PATH = Path("evidently_service/green_taxi_data/reference.csv")
DEFAULT_MODEL_NAME = "green-taxi-ride-duration"
DEFAULT_ALIAS = "production"
DEFAULT_EXPERIMENT_NAME = "green-taxi-monitoring"
DEFAULT_TRACKING_URI = "http://127.0.0.1:5001"
TEST_SIZE = 0.2
RANDOM_STATE = 42
CATEGORICAL_FEATURES = ["PULocationID", "DOLocationID"]

FEATURES = [
    "PULocationID",
    "DOLocationID",
    "trip_distance",
]
TARGET = "duration"


def wait_for_model_version(client, model_name, version, timeout_seconds):
    """Wait until the registered model version is ready to serve."""
    # Registration must finish before the API can resolve the production alias.
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        model_version = client.get_model_version(model_name, version)
        status = model_version.status
        if status == "READY":
            return model_version
        if status == "FAILED_REGISTRATION":
            raise click.ClickException(
                f"Model version {model_name} v{version} failed registration."
            )
        time.sleep(1)

    raise click.ClickException(
        f"Timed out waiting for {model_name} v{version} to become READY."
    )


@click.command()
@click.option(
    "--input",
    "input_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=DEFAULT_INPUT_PATH,
    show_default=True,
    help="CSV file used to bootstrap the local model.",
)
@click.option(
    "--tracking-uri",
    default=DEFAULT_TRACKING_URI,
    show_default=True,
    help="MLflow tracking URI used for logging and registration.",
)
@click.option(
    "--timeout-seconds",
    type=int,
    default=60,
    show_default=True,
    help="Maximum time to wait for MLflow model registration to finish.",
)
def main(input_path, tracking_uri, timeout_seconds):
    """Train and register the local demo model used by the monitoring stack."""
    import mlflow
    import pandas as pd
    from mlflow.models import infer_signature
    from mlflow.tracking import MlflowClient
    from sklearn.compose import ColumnTransformer
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import mean_squared_error
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import OneHotEncoder

    if not input_path.exists():
        raise click.ClickException(
            f"{input_path} does not exist. This repo expects the bundled reference CSV "
            "to be available before bootstrapping the local model."
        )

    # Reduce utility log noise without hiding warnings about model packaging.
    logging.getLogger("mlflow.utils").setLevel(logging.WARNING)
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(DEFAULT_EXPERIMENT_NAME)
    click.echo(f"Using MLflow tracking URI: {tracking_uri}")

    df = pd.read_csv(input_path)
    required_columns = FEATURES + [TARGET]
    missing_columns = sorted(set(required_columns) - set(df.columns))
    if missing_columns:
        raise click.ClickException(
            f"Input file is missing required columns: {', '.join(missing_columns)}"
        )

    df = df.loc[
        df[TARGET].between(1, 60) & df["trip_distance"].between(0.1, 100),
        required_columns,
    ].dropna()
    df[CATEGORICAL_FEATURES] = df[CATEGORICAL_FEATURES].astype(str)
    X = df[FEATURES]
    y = df[TARGET]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE
    )

    # Keep categorical encoding in the saved pipeline for consistent serving.
    model = make_pipeline(
        ColumnTransformer(
            [
                (
                    "locations",
                    OneHotEncoder(handle_unknown="ignore"),
                    CATEGORICAL_FEATURES,
                )
            ],
            remainder="passthrough",
        ),
        LinearRegression(),
    )
    model.fit(X_train, y_train)

    train_predictions = model.predict(X_train)
    test_predictions = model.predict(X_test)
    train_rmse = mean_squared_error(y_train, train_predictions) ** 0.5
    test_rmse = mean_squared_error(y_test, test_predictions) ** 0.5
    input_example = X_train.head(5)
    signature = infer_signature(input_example, model.predict(input_example))

    click.echo(
        f"Trained LinearRegression on {len(X_train)} rows, holdout size {len(X_test)}."
    )
    click.echo(f"Train RMSE: {train_rmse:.4f}")
    click.echo(f"Test RMSE: {test_rmse:.4f}")

    client = MlflowClient()
    with mlflow.start_run(run_name="bootstrap_real_time_monitoring_model") as run:
        mlflow.log_param("training_rows", len(X_train))
        mlflow.log_param("holdout_rows", len(X_test))
        mlflow.log_param("input_path", str(input_path))
        mlflow.log_param("model_name", DEFAULT_MODEL_NAME)
        mlflow.log_param("alias", DEFAULT_ALIAS)
        mlflow.log_metric("train_rmse", train_rmse)
        mlflow.log_metric("test_rmse", test_rmse)

        model_info = mlflow.sklearn.log_model(
            model,
            name="model",
            serialization_format="skops",
            signature=signature,
            input_example=input_example,
        )
        model_uri = model_info.model_uri

    click.echo(f"Logged run {run.info.run_id}")
    click.echo(f"Registering {model_uri} as {DEFAULT_MODEL_NAME}")

    registration = mlflow.register_model(
        model_uri=model_uri,
        name=DEFAULT_MODEL_NAME,
        await_registration_for=timeout_seconds,
    )
    model_version = wait_for_model_version(
        client=client,
        model_name=DEFAULT_MODEL_NAME,
        version=registration.version,
        timeout_seconds=timeout_seconds,
    )
    client.set_registered_model_alias(
        name=DEFAULT_MODEL_NAME, alias=DEFAULT_ALIAS, version=model_version.version
    )

    click.echo(
        f"Registered {DEFAULT_MODEL_NAME} version {model_version.version} "
        f"and assigned alias '{DEFAULT_ALIAS}'."
    )
    click.echo(
        "The FastAPI service can now resolve models:/"
        f"{DEFAULT_MODEL_NAME}@{DEFAULT_ALIAS} from your local MLflow server."
    )

    # Never compare this model's live predictions with the old model's outputs.
    reference = df[required_columns].copy()
    reference["prediction"] = model.predict(X)
    reference.to_csv(DEFAULT_INPUT_PATH, index=False)
    click.echo(f"Updated {DEFAULT_INPUT_PATH} with this model's reference predictions.")


if __name__ == "__main__":
    main()
