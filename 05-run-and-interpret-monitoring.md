# Run and Interpret the Monitoring Loop

This step shows how to drive traffic through the services, confirm that each layer is working, and interpret what the monitoring outputs are telling you. The model must have a `production` alias and all five Compose services must be running.

## Check the Services

```bash
curl --fail http://localhost:8080/
curl --fail http://localhost:8085/
```

The API should return `{"message": "NYC Taxi Ride Duration Prediction"}`. The monitoring service should return `"status": "ok"` along with `buffered_rows` (events collected so far) and `window_size` (250). If either service is not ready, `--fail` makes `curl` print an error instead.

Before 250 events have arrived, <http://localhost:8085/report> returns HTTP 404 with `Report not generated yet`. That is expected, not a startup failure.

## Send One Prediction Request

```bash
curl --fail -X POST http://localhost:8080/predict \
  -H "Content-Type: application/json" \
  -d '{"PULocationID": 42, "DOLocationID": 41, "trip_distance": 1.5}'
```

The response contains these three fields and a `prediction` in minutes. The API loads the registered pipeline, makes a prediction, and forwards the event to monitoring before returning.

Try adding `fare_amount` to the payload. The API should reject it with HTTP 422, as the serving contract accepts only the three model inputs.

## Fill the Monitoring Window

With the January Parquet file downloaded in chapter 04, replay a short batch:

```bash
uv run send_data.py --limit 300 --sleep 0.05
```

The generator filters and excludes the reference slice [described in chapter 01](01-train-and-register-local-model.md#features-and-reference-data), then shuffles the remaining rides with a fixed seed. Only the three features are posted, not actual duration.

It reports the number of successful predictions and elapsed time, and stops with a clear error if no replay rows remain. This summary confirms API responses, not monitoring delivery.

Useful options:

| Option | Purpose |
|---|---|
| `--limit 300` | Stop after 300 rows. |
| `--sleep 0.05` | Pause 0.05 seconds between requests. |
| `--input path/to/file.parquet` | Replay a different file, such as another month. |
| `--url http://localhost:8080/predict` | Change the prediction endpoint. |

Inspect the logs. Health checks and Prometheus scrapes add an access-log line every few seconds, so filter for the monitoring messages:

```bash
docker compose logs evidently_service | grep -E "Buffered|Report updated"
```

Expect `Buffered .../250 rows` lines, and at least one `Report updated and 3 metrics exported to Prometheus.` once the window is full.

Reports follow the [window and refresh rules in chapter 03](03-evidently-set-up.md#window-and-refresh-period). No new requests means no new analysis. Use the freshness panels to distinguish recent reports from retained gauge values.

## Follow the Results

1. Open <http://localhost:8085/report>. Inspect the distributions for the three inputs and the prediction.
2. Open <http://localhost:9090/targets>. The Prometheus, model-service, and Evidently targets should all be `UP`.
3. Query `evidently_valuedrift_prediction{dataset_name="green_taxi_data"}` in Prometheus to see the latest prediction drift score.
4. Open **Evidently Data Drift Dashboard** in Grafana to follow drift and freshness over time.
5. Open **Model Service Dashboard** to compare request volume and mean response time.

Prometheus scrapes every 30 seconds. Allow one scrape after the first report, then refresh Grafana and make sure its time range includes your replay. The request rate and response time panels need at least two scrapes, so they can take about 30 seconds longer to fill than the drift panels.

### Interpret the Panels

| Panel | Meaning |
|---|---|
| **Prediction Drift** | Normalized Wasserstein distance. Larger means a bigger distribution shift. The demo threshold is `0.1`. |
| **Drifted Columns** | Count across three input columns plus prediction, between 0 and 4. |
| **Time Since Last Event / Report** | Seconds since the last event or report. The value keeps rising while no traffic arrives; before the first event or report, the panel shows a waiting message. |
| **Mean Response Time** | Mean request duration in seconds, including synchronous monitoring delivery. |
| **Calls per Minute** | Estimated request count over a rolling minute, grouped by route and method. |
| **Monitoring Delivery Failures** | Failed delivery attempts since the API process started, including timeouts. A timeout does not prove the event was lost. |

The normal replay can already flag drift: the reference is a different slice of rides, the current window is small, and thresholds are teaching defaults. Record these baseline values before the synthetic experiment. Do not expect every normal window to score zero.

## Try a Controlled Drift Experiment

Replace normal traffic with repeated longer trips and fixed locations:

```bash
for _ in {1..300}; do
  curl --fail --silent --show-error -X POST http://localhost:8080/predict \
    -H "Content-Type: application/json" \
    -d '{"PULocationID": 42, "DOLocationID": 41, "trip_distance": 25.0}' \
    > /dev/null
  sleep 0.05
done
```

This is deliberately artificial, not representative production traffic. It changes both input and prediction distributions. Wait 10 seconds and send one more identical request so a report includes the fully replaced window, then allow the next Prometheus scrape.

Compare the baseline and shifted reports:

- Which columns are flagged as drifting?
- Does the prediction distance cross 0.1?
- What further evidence would you need before retraining?

## Debug from the API Outward

If a panel is empty, check the prediction response, monitoring buffer and report, Prometheus target health, then the Grafana query and time range. A reachable Grafana page alone does not prove that events reached monitoring.

## Cleanup

Follow the [cleanup instructions](06-OPTIONAL-operate-and-extend-monitoring.md#cleanup) if you are done for the day, or continue with the [optional chapter](06-OPTIONAL-operate-and-extend-monitoring.md) for tuning, failure recovery, and production considerations.
