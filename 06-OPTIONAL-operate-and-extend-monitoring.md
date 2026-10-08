# Optional: Operate and Extend Monitoring

Go through this chapter after the core monitoring loop works. Use the troubleshooting table below as a reference for when something breaks.

| Symptom | First check | Possible fix |
|---|---|---|
| Prediction returns 503 | `docker compose logs --tail 30 model-service` | Check MLflow health, the registered model, and its `production` alias. |
| Prediction returns 422 | Request body and <http://localhost:8080/docs> | Send only the three features with valid values. |
| Predictions work, but buffer stays empty | `docker compose logs --tail 30 model-service` | Check delivery warnings, `MONITORING_URL`, and monitoring container health. |
| Report returns 404 | <http://localhost:8085/> | Fill the current window; a container restart resets it. |
| Report exists, but metrics are missing | <http://localhost:8085/metrics> and monitoring logs | Check report calculation/export before changing dashboards. |
| Prometheus target is `DOWN` | <http://localhost:9090/targets> | Check service names, ports, and the Compose network. |
| Prometheus has values, Grafana is empty | Dashboard query, data source, and time range | Confirm the `prometheus` data source and include recent samples. |

To recreate a missing model, follow [chapter 01's training steps](01-train-and-register-local-model.md#start-mlflow), including the [alignment steps for a running stack](01-train-and-register-local-model.md#keep-predictions-and-reference-aligned).

## Experiment 1: Tune the Window

In [config.yaml](evidently_service/config.yaml), try `window_size: 50` while keeping `calculation_period_sec: 10`.

```bash
docker compose up -d --build --wait evidently_service
uv run send_data.py --limit 60 --sleep 0.2
```

Configuration is copied into the image, so a restart alone will not apply the edit. A smaller window fills sooner but its drift estimates can be noisier. Compare it with the normal-traffic baseline you recorded in chapter 05, then restore the original setting and rebuild.

## Experiment 2: Add One Useful Metric

In `create_report` in [utils.py](evidently_service/utils.py), add this metric to the report's `metrics` list, separated from the existing entries by a comma:

```python
cast(Any, ValueDrift)(column="trip_distance", method="wasserstein", threshold=0.1)
```

Rebuild monitoring, fill the window and inspect:

```bash
curl --fail http://localhost:8085/metrics
```

The exporter creates `evidently_valuedrift_trip_distance`. Query it in Prometheus before adding a Grafana panel. The threshold here is a teaching default; calibrate it against normal variation rather than assuming 0.1 is universally meaningful.

Changes made through Grafana's UI are stored in its volume, not in the repository's dashboard JSON. Export a dashboard deliberately if you want to retain its configuration in Git.

## Experiment 3: Test a Monitoring Outage

Stop only the monitoring service:

```bash
docker compose stop evidently_service
```

Send the valid prediction request from chapter 05. The API should still return its prediction, log a delivery warning and increment `monitoring_delivery_failures_total`. Check **Monitoring Delivery Failures** in Grafana after the next scrape. The synchronous delivery described in [chapter 02](02-API-set-up.md#forwarding-to-monitoring) can delay the response.

Restore monitoring:

```bash
docker compose up -d --wait evidently_service
```

The in-memory buffer is empty again. Lost events are not retried. Refill it and inspect the new report.

## Recognize the Demo's Limits

| Current behavior | Production direction |
|---|---|
| One Uvicorn worker and one in-memory window, protected by a lock | Persist events and calculate reports over durable batches. Multiple workers would otherwise have independent windows. |
| Synchronous monitoring delivery in the prediction request | Use a queue and retry delivery outside the serving path. |
| Drift metrics keep their last value while traffic is idle; freshness is shown separately | Define freshness alerts appropriate to the expected traffic pattern. |
| Only inputs and predictions arrive | Join delayed outcomes to monitor error, not only distributions. |
| One cached model and a reference copied into the image | Release the model and matching reference together, with explicit version tracking. |
| Local services and default credentials | Add authentication, access controls, secret handling and resource limits before any public deployment. |

See [chapter 04](04-prometheus-grafana-docker-compose.md#prometheus-scraping) for the `InstanceDown` rule's limits. An `UP` target does not guarantee fresh reports.

## Cleanup

Stop the stack while preserving model artifacts, dashboards, and metrics:

```bash
docker compose down
```

> **Warning:** `docker compose down -v` also deletes the MLflow registry and artifacts, Grafana changes, and Prometheus history in this project's volumes. Only use it when you intend a complete reset. You must train and register the model again afterward.

## Check Your Understanding

- Why is a valid prediction response insufficient evidence that monitoring works?
- What happens to the window when monitoring restarts?
- Why would adding Uvicorn workers break the shared-window assumption?
- Why must the reference predictions change when the model changes?
- What distinguishes prediction drift from measured model degradation?

<details>
<summary>Show Reference Answers</summary>

- A prediction is returned even when delivery to monitoring fails: the API only logs a warning and increments `monitoring_delivery_failures_total`. Check the buffer, report, and metrics to confirm events arrive.
- It starts empty. The window lives in memory, so buffered events and the previous report are lost, and the window must be refilled before the next report.
- Each worker is a separate process with its own in-memory window, so events are split between them and no single window sees all traffic.
- Drift compares live predictions with reference predictions. If the reference came from the old model, the difference would reflect the model change, not a change in the data.
- Prediction drift only shows that the distribution of predictions has shifted. Measuring degradation requires actual outcomes, such as real trip durations, to compute errors like RMSE.

</details>
