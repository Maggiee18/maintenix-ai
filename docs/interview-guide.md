# Interview Guide

Short, honest answers to the questions this project tends to raise. Numbers refer to the simulated benchmark in `ml-methodology.md`.

## 1. The 30 second pitch

Maintenix AI watches equipment sensor data, estimates the chance each machine fails in the next 48 hours, flags unusual behaviour, estimates remaining life where the data supports it, and turns that into alerts and maintenance work orders. It is a full stack: FastAPI and PostgreSQL behind a React dashboard, with a separate ML package that trains per equipment type models and a registry the API loads from. It is validated on the original NASA C-MAPSS turbofan dataset (RUL RMSE 11.80 cycles on the official test set), and the demo mixes eight real C-MAPSS engines with a clearly labelled simulated fleet of pumps, motors and compressors.

## 2. Why each technology

| Choice | Reason | What I would reconsider |
|---|---|---|
| FastAPI + Pydantic | typed request validation and OpenAPI for free; the ML stack is Python anyway | nothing at this scale |
| SQLAlchemy 2 + Alembic | typed ORM, explicit transactions, reviewed migrations | — |
| PostgreSQL | relational workflow data (work orders, users, audit) plus partial unique indexes and JSONB for bounded documents | TimescaleDB or partitioning for high frequency telemetry |
| scikit-learn + XGBoost | strong tabular baselines, fast to train and explain; compared in one pipeline | sequence models (LSTM / TCN) only if windows of raw signal beat engineered features |
| SHAP | per prediction attributions with a solid theory; exact for trees and linear models | — |
| React + TypeScript + TanStack Query | typed client, caching, loading / error states handled consistently | — |
| Recharts | declarative charts that follow the theme tokens | — |
| No Redis / Celery | inference on one window takes milliseconds, so it runs inline after ingestion | add a queue when ingestion volume or retraining jobs need it |

## 3. How the ML pipeline works

1. Readings are validated (types, plausible ranges, timezone, duplicates, unknown columns, sampling gaps).
2. Features per reading use only that unit's past: last value, 12 and 48 reading means / stds, min / max, slope, short minus long mean, operating mode.
3. Per equipment type, three tasks: failure within 48 h (classification), anomaly (unsupervised), RUL (regression, only for run to failure data).
4. Units are split 60 / 20 / 20. Candidates are compared on validation units, the winner is calibrated and gets a threshold on validation units, and the test units are scored once.
5. The artifact plus metadata (dataset fingerprint, seed, features, metrics, checksum) goes into the registry. The API mirrors it in `model_versions`, and an admin promotes versions.

## 4. How leakage is prevented

* **Temporal**: rolling windows end at the current reading; a test asserts features do not change when future rows are appended.
* **Entity**: splits by unit. A row level split would let the model see hour 300 of a pump in training and be graded on hour 301 of the same pump.
* **Selection**: model choice, calibration and threshold use validation units only; test units are untouched until the end.
* **Target**: ground truth columns from the simulator are never features. Operating hours are excluded so the model cannot learn "old means about to fail" from a counter.
* **Censoring**: compressor readings whose horizon runs past the observed data are dropped, not labelled "no failure".

## 5. Interpreting the metrics

* **Why not accuracy?** About 8 to 9 % of readings are positive. Predicting "never fails" scores over 90 % accuracy and is useless.
* **PR-AUC** is the selection metric because it focuses on the rare positive class. ROC-AUC looks flattering on imbalanced data (0.99 for the motor).
* **Threshold** maximises F2: recall counts twice as much as precision because a missed failure means unplanned downtime, possible secondary damage and safety exposure, while a false alarm costs an inspection. The confusion matrix on the Model Performance page states both costs in plain words.
* **Event level view**: all 12 test pump failures were warned about, with a median first warning 47 h ahead, at about 21 false alarm readings per 1000 healthy hours. That is closer to what a maintenance planner cares about than per reading recall.
* **Calibration**: isotonic regression on validation scores makes "30 %" mean roughly 30 %. Brier score is reported. Because isotonic output is a step function that reaches 0 and 1, the UI never displays 0 % or 100 %.
* **RUL**: MAE and RMSE in hours, reported near failure (true RUL ≤ 200 h), plus bias. The motor model is within about 19 h on average near failure. Over estimating is the dangerous direction, so every RUL model subtracts its average optimism measured on validation data (motor bias fell from +10.4 h to +4.3 h), and the UI shows the typical error next to the estimate.

## 6. Anomalies vs failures

A failure prediction is supervised: "given past failures, how likely is one soon?". Anomaly detection is unsupervised: "is this unlike healthy baseline data?". Sensor glitches, a new operating point or a transient spike are anomalies but not failures; a slow wear pattern can be a failure precursor before anything looks anomalous. So they are separate models, separate alert kinds, and anomaly alerts say explicitly they are not a confirmed failure. The detector combines Isolation Forest (multivariate patterns) with per sensor control limits (single sensor spikes the forest dilutes, and they name the sensor).

## 7. How the schema supports the workflow

Readings (narrow, configurable per type) → predictions (one row per assessment, linked to the exact model versions) → anomaly events and alerts → work orders → events and maintenance record. Key guarantees live in the database, not only in code: one production model per type and task, one active alert per equipment and kind (deduplication under concurrency), idempotent ingestion via a unique (equipment, timestamp), CHECK constraints on every status, and "completed implies a completion time".

## 8. Alert flood control

An active alert is updated, not duplicated (occurrence count, last seen, severity can only escalate). After resolution, a cooldown suppresses repeats of the same or lower severity for a configurable time; escalations always get through. Alerts are never auto-resolved when risk dips, because a person should confirm.

## 9. Error handling

Validation errors come back as 422 with row level details (an upload with 3 bad rows stores the good rows and lists the bad ones). Business rule violations are 409 (`invalid_transition` includes the allowed moves). Unexpected exceptions become a generic 500 with a request id; the stack trace is only in the JSON server log under that id. On the frontend, every data view has loading, error with retry, and empty states.

## 10. What changes for real industrial deployment

* **Data**: real historians (OPC UA, MQTT, PI) through an ingestion service, unit conversion, sensor health checks, clock sync; label quality from CMMS failure codes is the hardest part.
* **Models**: several failure modes per asset class, survival models or per mode RUL, drift monitoring (feature distributions, alert rate, precision from work-order outcomes), scheduled retraining with a human promotion gate, shadow deployment before promotion.
* **Scale**: partitioned or time series storage, a queue for ingestion and inference, shared rate limiting and caches, read replicas for dashboards.
* **Operations**: SSO / OIDC, MFA, httpOnly cookie sessions, TLS everywhere, secrets manager, backups, observability (metrics, tracing).
* **Safety**: stays advisory. Integration with control systems would need a functional safety assessment and should never act automatically on a model output.
* **Validation**: field trials comparing model alerts with maintenance outcomes before anyone relies on the numbers.

## 11. How I improved the model without cheating

* All tuning used 5-fold cross validation grouped by engine on the training engines; the official test set was read once at the end. Tuning on it would turn the test score into a training score.
* What helped: an "age" feature (cycles since the engine entered service), longer windows (15 and 90 cycles), partial windows so short records still get a prediction, a shallower XGBoost, refitting on train plus validation, and a bias correction measured on validation data. What did not: exponential smoothing, other tree ensembles, quantile and Huber losses.
* I report the trade-off: the bias correction made estimates safer (fewer late predictions, better NASA score) while the official RMSE moved slightly, within noise.

## 12. Honest limitations

* Pump, motor and compressor data come from the built-in simulator, which is cleaner than reality. A linear model winning there is a sign the simulated signal is simple.
* The real data evidence is NASA C-MAPSS FD001: RUL RMSE 11.80 cycles on all 100 official test engines. That is still a simulation benchmark from NASA, one operating condition and one fault mode, not plant data.
* The Docker images were not built in the build environment (Docker Hub was blocked); CI builds them.
