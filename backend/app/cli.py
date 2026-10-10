"""Operational commands.

    python -m app.cli bootstrap            # equipment types, models, thresholds, first admin
    python -m app.cli seed-demo            # SIMULATED demo fleet, users and history (not in production)
    python -m app.cli create-user EMAIL NAME ROLE   # password read from MAINTENIX_NEW_PASSWORD or prompt
    python -m app.cli run-fleet            # run predictions for every active equipment
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import sys
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from maintenix_ml.simulator import demo_segment

from .core.config import get_settings
from .core.logging import configure_logging
from .core.security import hash_password, password_problems
from .db.session import get_sessionmaker
from .models import entities as m
from .services import inference, telemetry
from .services.bootstrap import bootstrap

log = logging.getLogger("maintenix.cli")

DEMO_FLEET = [
    # code, name, type, location, stage, seed, criticality
    ("PMP-101", "Cooling water pump A", "centrifugal_pump", "Utilities / Bay 1", "healthy", 1101, "high"),
    ("PMP-102", "Cooling water pump B", "centrifugal_pump", "Utilities / Bay 1", "healthy", 1102, "high"),
    ("PMP-103", "Process feed pump", "centrifugal_pump", "Line 2 / Feed", "elevated", 1103, "medium"),
    ("PMP-104", "Condensate return pump", "centrifugal_pump", "Boiler house", "critical", 1104, "high"),
    ("MTR-201", "Conveyor drive motor 1", "electric_motor", "Line 1 / Conveyor", "healthy", 2201, "medium"),
    ("MTR-202", "Conveyor drive motor 2", "electric_motor", "Line 1 / Conveyor", "degrading", 2202, "medium"),
    ("MTR-203", "Mixer motor", "electric_motor", "Line 3 / Mixing", "healthy", 2203, "low"),
    ("MTR-204", "Extruder main motor", "electric_motor", "Line 3 / Extrusion", "critical", 2204, "high"),
    ("CMP-301", "Instrument air compressor 1", "air_compressor", "Compressor room", "healthy", 3301, "high"),
    ("CMP-302", "Instrument air compressor 2", "air_compressor", "Compressor room", "healthy", 3302, "high"),
    ("CMP-303", "Plant air compressor", "air_compressor", "Compressor room", "elevated", 3303, "medium"),
    ("CMP-304", "Packaging air compressor", "air_compressor", "Packaging hall", "critical", 3304, "medium"),
]
DEMO_USERS = [
    ("engineer@example.com", "Priya Raman", "engineer"),
    ("technician@example.com", "Arjun Mehta", "technician"),
    ("technician2@example.com", "Sara Thomas", "technician"),
    ("viewer@example.com", "Vikram Rao", "viewer"),
]
HISTORY_HOURS = 24 * 14


def cmd_bootstrap(_: argparse.Namespace) -> int:
    with get_sessionmaker()() as db:
        print(json.dumps(bootstrap(db), default=str))
    return 0


def cmd_seed_demo(a: argparse.Namespace) -> int:
    s = get_settings()
    if s.environment == "production" and not a.force:
        print("Refusing to seed SIMULATED demo data in production (use --force if you really mean it).", file=sys.stderr)
        return 2
    password = os.environ.get("DEMO_USER_PASSWORD", "")
    if password_problems(password):
        print("Set DEMO_USER_PASSWORD (10+ chars, mixed case, a digit) to create demo users.", file=sys.stderr)
        return 2
    with get_sessionmaker()() as db:
        bootstrap(db)
        if db.scalar(select(func.count()).select_from(m.Equipment)) and not a.force:
            print("Equipment already exists; demo seed skipped.")
            return 0
        roles = {r.name: r for r in db.scalars(select(m.Role))}
        users = {}
        for email, name, role in DEMO_USERS:
            u = db.scalar(select(m.User).where(m.User.email == email))
            if u is None:
                u = m.User(email=email, full_name=name, role=roles[role], password_hash=hash_password(password))
                db.add(u)
            users[role if role not in users else role + "2"] = u
        db.commit()

        types = {t.key: t for t in db.scalars(select(m.EquipmentType))}
        end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        created: list[m.Equipment] = []
        for code, name, etype, loc, stage, seed, crit in DEMO_FLEET:
            if db.scalar(select(m.Equipment.id).where(m.Equipment.code == code)):
                continue
            seg, end_idx = demo_segment(etype, seed, stage, end, HISTORY_HOURS)
            eq = m.Equipment(code=code, name=name, equipment_type_id=types[etype].id, location=loc, criticality=crit,
                             manufacturer="Simulated Co.", model_number=f"SIM-{etype[:3].upper()}", serial_number=f"SIM{seed}",
                             install_date=date(2021, 3, 1), data_source="simulated", simulation_seed=seed,
                             simulation_offset=end_idx - len(seg) + 1, status="operational")
            db.add(eq)
            db.commit()
            frame = seg[["timestamp", "operating_hours", "operating_mode", *[s.name for s in types[etype].sensors]]].copy()
            frame.insert(0, "unit_id", code)
            telemetry.ingest_frame(db, eq, frame, "simulated", assume_utc=True)
            # backfill a prediction history every 6 h over the last 7 days (alerts only for the latest)
            for h in range(7 * 24, 0, -6):
                inference.run_for_equipment(db, eq, as_of=end - timedelta(hours=h), triggered_by="backfill", raise_alerts=False)
            inference.run_for_equipment(db, eq, triggered_by="backfill")
            created.append(eq)
            log.info("seeded %s (%s, %s)", code, etype, stage)

        _demo_work_orders(db, users)
        print(json.dumps({"equipment_created": len(created), "demo_users": [u[0] for u in DEMO_USERS]}))
    return 0


def _demo_work_orders(db, users) -> None:  # type: ignore[no-untyped-def]
    """A small, realistic maintenance history created through the real state machine."""
    from .api.deps import CurrentUser
    from .schemas.maintenance import CompletionRequest, WorkOrderCreate
    from .services import workorders

    if db.scalar(select(func.count()).select_from(m.WorkOrder)):
        return
    eng = CurrentUser(users["engineer"], "seed", 0)
    tech = CurrentUser(users["technician"], "seed", 0)
    eq = {e.code: e for e in db.scalars(select(m.Equipment))}
    wo = workorders.create(db, WorkOrderCreate(equipment_id=eq["PMP-101"].id, title="Quarterly bearing lubrication",
                                               description="Routine lubrication per maintenance plan.", priority="low",
                                               assigned_to_id=users["technician"].id), eng, None)
    workorders.transition(db, wo.id, "in_progress", tech, "Started", None)
    workorders.complete(db, wo.id, CompletionRequest(action_taken="lubrication", summary="Bearings greased, no abnormal noise.",
                                                     downtime_hours=0.5, restores_health=False), tech, None)
    wo = workorders.create(db, WorkOrderCreate(equipment_id=eq["MTR-202"].id, title="Inspect motor winding temperature trend",
                                               description="Temperature trending up over the last week.", priority="medium",
                                               due_date=date.today() + timedelta(days=5),
                                               assigned_to_id=users["technician2"].id if "technician2" in users else users["technician"].id),
                           eng, None)


def cmd_import_cmapss(a: argparse.Namespace) -> int:
    """Load engines from the official NASA C-MAPSS FD001 *test* set as real (imported) equipment.

    Test engines were never used for training. Cycle k of an engine is stored at
    (now - n_cycles + k) hours, so the latest cycle is "current". Ground-truth RUL
    from RUL_FD001.txt is printed next to the model's estimate for comparison.
    """
    from pathlib import Path

    import numpy as np
    import pandas as pd

    from maintenix_ml.adapters.cmapss import read_raw, to_canonical

    data_dir = Path(a.data_dir)
    raw = read_raw(data_dir / "test_FD001.txt")
    truth = pd.read_csv(data_dir / "RUL_FD001.txt", header=None, sep=r"\s+").iloc[:, 0].to_numpy()
    lengths = raw.groupby("unit")["cycle"].max()
    eligible = [u for u in lengths.index if lengths[u] >= 60]
    # spread the selection over the range of true remaining life (sorted, evenly spaced)
    by_rul = sorted(eligible, key=lambda u: truth[u - 1])
    picks = [by_rul[int(i)] for i in np.linspace(0, len(by_rul) - 1, a.engines)]
    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    rows = []
    with get_sessionmaker()() as db:
        bootstrap(db)
        et = db.scalar(select(m.EquipmentType).where(m.EquipmentType.key == "turbofan_engine"))
        if et is None:
            print("turbofan_engine type missing; run bootstrap first", file=sys.stderr)
            return 2
        for u in sorted(picks):
            code = f"TF-{u:03d}"
            if db.scalar(select(m.Equipment.id).where(m.Equipment.code == code)):
                continue
            eng = to_canonical(raw[raw["unit"] == u], prefix="FD001")
            n = len(eng)
            eng["timestamp"] = [end - timedelta(hours=n - 1 - k) for k in range(n)]
            eng["unit_id"] = code
            eq = m.Equipment(code=code, name=f"Turbofan engine {u} (C-MAPSS FD001 test)", equipment_type_id=et.id,
                             location="NASA C-MAPSS FD001 test set", manufacturer="NASA C-MAPSS (simulation benchmark)",
                             model_number="FD001", serial_number=f"FD001-test-{u}", data_source="imported",
                             criticality="high", status="operational")
            db.add(eq)
            db.commit()
            telemetry.ingest_frame(db, eq, eng.drop(columns=["data_source"]), "imported", assume_utc=True)
            for h in range(min(40, n - 48), 0, -5):
                inference.run_for_equipment(db, eq, as_of=end - timedelta(hours=h), triggered_by="backfill", raise_alerts=False)
            pred = inference.run_for_equipment(db, eq, triggered_by="backfill")
            rows.append({"code": code, "cycles": n, "true_rul": int(truth[u - 1]),
                         "predicted_rul": round(pred.rul_hours, 1) if pred and pred.rul_hours is not None else None,
                         "failure_probability": round(pred.failure_probability, 3) if pred and pred.failure_probability is not None else None})
    print(json.dumps({"imported": rows, "note": "true_rul from RUL_FD001.txt; model clips RUL at 125 cycles"}, indent=2))
    return 0


def cmd_create_user(a: argparse.Namespace) -> int:
    password = os.environ.get("MAINTENIX_NEW_PASSWORD") or getpass.getpass("Password: ")
    if password_problems(password):
        print("Password needs: " + ", ".join(password_problems(password)), file=sys.stderr)
        return 2
    with get_sessionmaker()() as db:
        role = db.scalar(select(m.Role).where(m.Role.name == a.role))
        if role is None:
            print(f"Unknown role {a.role}", file=sys.stderr)
            return 2
        db.add(m.User(email=a.email.lower(), full_name=a.name, role=role, password_hash=hash_password(password)))
        db.commit()
    print(f"Created {a.email} ({a.role})")
    return 0


def cmd_promote_latest(_: argparse.Namespace) -> int:
    """Register new artifacts and promote the newest compatible version of every (type, task)."""
    from .services.models_registry import promote, sync_from_disk

    with get_sessionmaker()() as db:
        sync_from_disk(db)
        promoted = []
        for et in db.scalars(select(m.EquipmentType)):
            for task in m.MODEL_TASKS:
                newest = db.scalars(select(m.ModelVersion).where(
                    m.ModelVersion.equipment_type_id == et.id, m.ModelVersion.task == task,
                    m.ModelVersion.status != "archived").order_by(m.ModelVersion.trained_at.desc()).limit(1)).first()
                if newest is not None and newest.status != "production":
                    promote(db, newest.id, actor_id=None, ip="cli")  # audited; verifies the artifact loads first
                    promoted.append(f"{et.key}/{task}/{newest.version}")
    print(json.dumps({"promoted": promoted}))
    return 0


def cmd_run_fleet(_: argparse.Namespace) -> int:
    with get_sessionmaker()() as db:
        print(json.dumps(inference.run_fleet(db, triggered_by="scheduled")))
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging(get_settings().log_level)
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("bootstrap").set_defaults(fn=cmd_bootstrap)
    sd = sub.add_parser("seed-demo")
    sd.add_argument("--force", action="store_true")
    sd.set_defaults(fn=cmd_seed_demo)
    cu = sub.add_parser("create-user")
    cu.add_argument("email")
    cu.add_argument("name")
    cu.add_argument("role", choices=["admin", "engineer", "technician", "viewer"])
    cu.set_defaults(fn=cmd_create_user)
    sub.add_parser("run-fleet").set_defaults(fn=cmd_run_fleet)
    sub.add_parser("promote-latest", help="promote the newest model version of every type and task").set_defaults(fn=cmd_promote_latest)
    ic = sub.add_parser("import-cmapss", help="load real NASA C-MAPSS FD001 test engines as equipment")
    ic.add_argument("--data-dir", default="../datasets/raw/cmapss")
    ic.add_argument("--engines", type=int, default=8)
    ic.set_defaults(fn=cmd_import_cmapss)
    a = p.parse_args(argv)
    return int(a.fn(a))


if __name__ == "__main__":
    sys.exit(main())
