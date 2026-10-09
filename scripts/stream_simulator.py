"""Demo stream simulator: keeps SIMULATED equipment receiving hourly readings.

This is an ordinary API client. It logs in, and for every equipment item whose
``data_source`` is ``simulated`` it continues that item's deterministic
trajectory from ``maintenix_ml.simulator`` and POSTs the readings that are due
(one per hour, never in the future). Each POST runs inference server-side,
so predictions and alerts update exactly as they would for a real feed.

After a work order is completed with "restores health", the simulator starts a
fresh trajectory for that equipment (a repaired machine starts healthy). When a
trajectory reaches its simulated failure, the simulator stops sending readings
for that equipment until maintenance is recorded.

    python scripts/stream_simulator.py --api http://localhost:8000 --email engineer@example.com
    (password from MAINTENIX_PASSWORD)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import httpx
from maintenix_ml.equipment_types import get_spec
from maintenix_ml.simulator import simulate_unit

log = logging.getLogger("stream_simulator")
REPAIR_SEED_STEP = 7919


@lru_cache(maxsize=64)
def trajectory(equipment_type: str, seed: int):  # type: ignore[no-untyped-def]
    return simulate_unit(equipment_type, seed, "stream")


class Client:
    def __init__(self, base: str, email: str, password: str) -> None:
        self.http = httpx.Client(base_url=base.rstrip("/") + "/api/v1", timeout=30)
        self.email, self.password = email, password
        self.login()

    def login(self) -> None:
        r = self.http.post("/auth/login", json={"email": self.email, "password": self.password})
        r.raise_for_status()
        self.http.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    def get(self, path: str, **params: object) -> dict:  # type: ignore[type-arg]
        r = self.http.get(path, params=params)
        if r.status_code == 401:
            self.login()
            r = self.http.get(path, params=params)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body: dict) -> dict:  # type: ignore[type-arg]
        r = self.http.post(path, json=body)
        if r.status_code == 401:
            self.login()
            r = self.http.post(path, json=body)
        r.raise_for_status()
        return r.json()


def due_readings(c: Client, eq_id: int, max_rows: int) -> tuple[list[dict], str]:  # type: ignore[type-arg]
    d = c.get(f"/equipment/{eq_id}")
    sim, latest = d.get("simulation"), d.get("latest_reading")
    if not sim or not latest or d["status"] in ("decommissioned", "offline"):
        return [], "skipped (not streamable)"
    spec = get_spec(d["equipment_type"])
    last_t = datetime.fromisoformat(latest["recorded_at"])
    now = datetime.now(UTC)
    seed, start_idx = sim["seed"], sim["first_reading_index"]
    if d.get("last_maintenance_at"):
        restored = datetime.fromisoformat(d["last_maintenance_at"])
        since = c.get("/sensors/readings", equipment_id=eq_id, start=restored.isoformat(), page_size=1)["total"]
        seed, idx = seed + REPAIR_SEED_STEP, since
    else:
        idx = start_idx + d["reading_count"]
    traj = trajectory(spec.key, seed)
    out = []
    t = last_t + timedelta(hours=1)
    while t <= now and len(out) < max_rows:
        if idx >= len(traj):
            return out, "simulated failure reached; record maintenance that restores health to restart"
        row = traj.iloc[idx]
        out.append({"recorded_at": t.isoformat(), "operating_mode": row["operating_mode"],
                    "operating_hours": float(latest.get("operating_hours") or 0) + len(out) + 1,
                    "values": {s: float(row[s]) for s in spec.sensor_names}})
        idx += 1
        t += timedelta(hours=1)
    return out, "ok"


def run_once(c: Client, max_rows: int) -> None:
    items = c.get("/equipment", page_size=200)["items"]
    for e in items:
        if e["data_source"] != "simulated":
            continue
        rows, status = due_readings(c, e["id"], max_rows)
        if not rows:
            log.info("%s: nothing due (%s)", e["code"], status)
            continue
        rep = c.post("/sensors/readings/batch", {"equipment_id": e["id"], "readings": rows, "data_source": "simulated"})
        pred = (rep.get("predictions") or [{}])[0]
        log.info("%s: sent %d SIMULATED readings, risk=%s anomaly=%s (%s)", e["code"], rep["accepted_rows"],
                 pred.get("risk_level"), pred.get("is_anomaly"), status)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", default=os.environ.get("MAINTENIX_API", "http://localhost:8000"))
    p.add_argument("--email", default=os.environ.get("MAINTENIX_EMAIL", "engineer@example.com"))
    p.add_argument("--interval", type=int, default=300, help="seconds between checks for due readings")
    p.add_argument("--max-rows", type=int, default=500, help="cap per equipment per cycle (catch-up after downtime)")
    p.add_argument("--once", action="store_true")
    a = p.parse_args()
    password = os.environ.get("MAINTENIX_PASSWORD")
    if not password:
        print("Set MAINTENIX_PASSWORD", file=sys.stderr)
        return 2
    for _attempt in range(30):  # wait for the API to come up
        try:
            c = Client(a.api, a.email, password)
            break
        except httpx.HTTPError as exc:
            log.info("waiting for API (%s)", exc)
            time.sleep(5)
    else:
        return 1
    while True:
        try:
            run_once(c, a.max_rows)
        except httpx.HTTPError as exc:
            log.warning("cycle failed: %s", exc)
        if a.once:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
