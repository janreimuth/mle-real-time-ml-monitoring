"""Host-side traffic generator for the local monitoring tutorial."""

import time
from pathlib import Path

import click

DEFAULT_DATA_PATH = Path("data/green_tripdata_2024-01.parquet")

# This host script uses the exposed port, not a Compose service name.
DEFAULT_URL = "http://localhost:8080/predict"

FEATURES = [
    "PULocationID",
    "DOLocationID",
    "trip_distance",
]


def prepare_features(df):
    """Clean the raw taxi data and return rows that match the API schema."""
    # Duration filters the replay, but ground truth is not part of live events.
    df["duration"] = (
        df["lpep_dropoff_datetime"] - df["lpep_pickup_datetime"]
    ).dt.total_seconds() / 60

    # Match the reference's filtering before the controlled drift experiment.
    df = df[(df["duration"] >= 1) & (df["duration"] <= 60)]
    df = df[df["trip_distance"].between(0.1, 100)]

    return df[FEATURES].dropna()


def send_rows(df, url, sleep_seconds, limit):
    """Send sampled rows to the prediction API one request at a time."""
    import requests

    headers = {"accept": "application/json", "Content-Type": "application/json"}

    sample = df.sample(frac=1, random_state=42)
    if limit is not None:
        sample = sample.head(limit)
    if sample.empty:
        raise click.ClickException(
            "No traffic rows remain after filtering and reference exclusion."
        )

    started = time.monotonic()
    for row_number, (_, row) in enumerate(sample.iterrows(), start=1):
        payload = row.to_dict()
        click.echo(f"Sending row {row_number}: {payload}")

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
        except requests.RequestException as error:
            raise click.ClickException(
                f"Stopped after {row_number - 1} successful predictions in "
                f"{time.monotonic() - started:.1f}s: {error}"
            ) from error
        click.echo(f"Response {response.status_code}: {response.text}")

        time.sleep(sleep_seconds)

    click.echo(
        f"Completed {len(sample)} successful predictions in "
        f"{time.monotonic() - started:.1f}s. "
        "Check monitoring metrics to confirm event delivery."
    )


@click.command()
@click.option(
    "--input",
    "input_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=DEFAULT_DATA_PATH,
    show_default=True,
    help="Path to the green taxi Parquet file used as live traffic.",
)
@click.option(
    "--url",
    default=DEFAULT_URL,
    show_default=True,
    help="Prediction API endpoint that receives each sampled row.",
)
@click.option(
    "--sleep",
    "sleep_seconds",
    type=click.FloatRange(min=0),
    default=1.0,
    show_default=True,
    help="Seconds to wait between requests.",
)
@click.option(
    "--limit",
    type=click.IntRange(min=1),
    default=None,
    help="Maximum number of rows to send. Omit to stream all sampled rows.",
)
def main(input_path, url, sleep_seconds, limit):
    """Send sampled taxi rows through the local monitoring stack."""
    # Lazy imports keep --help independent of data-processing dependencies.
    import pandas as pd

    if not input_path.exists():
        raise click.ClickException(
            f"{input_path} does not exist. Download it with the command in "
            "04-prometheus-grafana-docker-compose.md."
        )

    # The bundled reference uses the first 20,000 valid January 2024 rides.
    # Replay the remaining rows; another month can use all of its valid rides.
    df = pd.read_parquet(input_path)

    current_df = prepare_features(df)
    if input_path.name == DEFAULT_DATA_PATH.name:
        current_df = current_df.iloc[20000:]
    send_rows(current_df, url, sleep_seconds, limit)


if __name__ == "__main__":
    main()
