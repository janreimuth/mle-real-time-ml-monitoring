# Prometheus, Grafana, and Docker Compose

[Docker Compose](docker-compose.yaml) provides the local services. MLflow has already been started in chapter 01; now bring up the prediction API, Evidently, Prometheus, and Grafana.

## Service Addresses

| Service | From your computer | Within Compose |
|---|---|---|
| MLflow | `http://127.0.0.1:5001` | `http://mlflow:5000` |
| Prediction API | `http://localhost:8080` | `http://model-service:8080` |
| Evidently | `http://localhost:8085` | `http://evidently_service:8085` |
| Prometheus | `http://localhost:9090` | `http://prometheus:9090` |
| Grafana | `http://localhost:3000` | `http://grafana:3000` |

Use the host URLs in your browser or terminal and service names inside Compose. `localhost` inside a container refers to that container, not your computer.

Both Python services use the repository's single `pyproject.toml` and `uv.lock`. Docker builds from the repository root and installs the locked dependencies.

## Start the Stack

After training and registration:

```bash
docker compose up -d --build --wait
docker compose ps
```

Use logs when a service fails its readiness check:

```bash
docker compose logs --tail 50 model-service evidently_service mlflow
```

## Test the API

Open the API docs at <http://localhost:8080/docs> or send a request from the terminal:

```bash
curl --fail -X POST http://localhost:8080/predict \
  -H "Content-Type: application/json" \
  -d '{"PULocationID": 42, "DOLocationID": 41, "trip_distance": 1.5}'
```

## Inspect Monitoring Endpoints

| Endpoint | URL | What it shows |
|---|---|---|
| Service health | <http://localhost:8085/> | Buffered row count and window size. |
| API docs | <http://localhost:8085/docs> | Monitoring event schema. |
| Latest report | <http://localhost:8085/report> | HTTP 404 until the first complete window. |
| Metrics | <http://localhost:8085/metrics> | Raw Prometheus exposition. |

## Prometheus Scraping

Inspect [prometheus/prometheus.yaml](prometheus/prometheus.yaml). Every 30 seconds, Prometheus scrapes `/metrics` on the prediction API, Evidently, and itself.

The Prometheus Targets page at <http://localhost:9090/targets> should show all three targets as healthy. Evidently's drift gauges appear only after its first report; its ordinary process metrics and reference hash are available earlier.

[alert.yaml](prometheus/alert.yaml) defines an `InstanceDown` rule after a target has been down for five minutes. This repo has no Alertmanager or notification channel, so no email or Slack messages are sent.

## Grafana Provisioning

Grafana loads its Prometheus data source and two dashboards from [grafana/provisioning](grafana/provisioning/) and [grafana/dashboards](grafana/dashboards/):

- **Evidently Data Drift Dashboard**: prediction drift, drifted-column count, and event/report freshness.
- **Model Service Dashboard**: average request duration, request counts, and monitoring delivery failures.

Open Grafana at <http://localhost:3000> using `admin` / `admin`. You can skip the initial password-change prompt in this disposable local environment.

The data source uses `http://prometheus:9090`, not `localhost`. Drift gauges are filtered to `green_taxi_data`. They are not duplicated by an additional unconfigured dataset query.

## Download Replay Data

The training reference is bundled. The larger traffic file is downloaded once:

```bash
curl --fail --location https://d37ci6vzurychx.cloudfront.net/trip-data/green_tripdata_2024-01.parquet -o data/green_tripdata_2024-01.parquet
```

The dashboards stay mostly empty until traffic arrives. In the next chapter you will replay rides from this file as prediction requests to fill them.
