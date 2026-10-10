"""Bridges the file-based ML registry and the ``model_versions`` table, and caches loaded bundles."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from maintenix_ml.features import FEATURE_VERSION
from maintenix_ml.inference import LoadedModel
from maintenix_ml.registry import ModelCompatibilityError, check_compatibility, json_safe, list_metadata, load_bundle

from ..core.config import get_settings
from ..core.errors import Conflict, NotFound
from ..models import entities as m
from . import audit

log = logging.getLogger("maintenix.models")


def sync_from_disk(db: Session, models_dir: Path | None = None, auto_promote: bool = True) -> dict[str, int]:
    """Register artifacts found on disk. Promote the newest compatible version when a
    (type, task) has no production model yet. Idempotent."""
    models_dir = models_dir or get_settings().models_dir
    types = {t.key: t for t in db.scalars(select(m.EquipmentType))}
    added = skipped = promoted = 0
    for meta in list_metadata(models_dir):
        meta = json_safe(meta)
        et = types.get(meta.get("equipment_type", ""))
        if et is None:
            skipped += 1
            continue
        try:
            check_compatibility(meta)
        except ModelCompatibilityError as exc:
            log.warning("Skipping incompatible model %s/%s: %s", meta.get("name"), meta.get("version"), exc)
            skipped += 1
            continue
        exists = db.scalar(select(m.ModelVersion.id).where(
            m.ModelVersion.equipment_type_id == et.id, m.ModelVersion.task == meta["task"],
            m.ModelVersion.version == meta["version"]))
        if exists:
            continue
        metrics = meta.get("metrics", {})
        db.add(m.ModelVersion(
            equipment_type_id=et.id, task=meta["task"], name=meta["name"], version=meta["version"],
            algorithm=meta.get("algorithm", "unknown"), dataset_id=meta.get("dataset_id", "unknown")[:255],
            feature_version=meta["feature_schema"]["feature_version"], feature_names=meta["feature_schema"]["feature_names"],
            params=meta.get("params", {}), metrics=metrics,
            dataset_info={"dataset": meta.get("dataset", {}), "split": meta.get("split", {}),
                          "split_strategy": meta.get("split_strategy"), "seed": meta.get("seed"),
                          "target": meta.get("target"), "data_validation": meta.get("data_validation"),
                          "library_versions": meta.get("library_versions")},
            artifact_path=f"{meta['equipment_type']}/{meta['task']}/{meta['version']}/{meta['artifact_file']}",
            artifact_sha256=meta["artifact_sha256"], trained_at=datetime.fromisoformat(meta["trained_at"]),
        ))
        added += 1
    db.flush()
    retired = 0
    if auto_promote:
        for et in types.values():
            for task in m.MODEL_TASKS:
                prod = db.scalar(select(m.ModelVersion).where(
                    m.ModelVersion.equipment_type_id == et.id, m.ModelVersion.task == task,
                    m.ModelVersion.status == "production"))
                if prod is not None and prod.feature_version != FEATURE_VERSION:
                    # the running feature code can no longer serve this model: retire it
                    prod.status = "archived"
                    db.flush()
                    retired += 1
                    prod = None
                if prod is not None:
                    continue
                newest = db.scalars(select(m.ModelVersion).where(
                    m.ModelVersion.equipment_type_id == et.id, m.ModelVersion.task == task,
                    m.ModelVersion.feature_version == FEATURE_VERSION)
                    .order_by(m.ModelVersion.trained_at.desc()).limit(1)).first()
                if newest:
                    newest.status = "production"
                    newest.promoted_at = datetime.now(UTC)
                    promoted += 1
    db.commit()
    return {"added": added, "skipped": skipped, "promoted": promoted, "retired": retired}


def promote(db: Session, model_id: int, actor_id: int | None, ip: str | None = None) -> m.ModelVersion:
    mv = db.get(m.ModelVersion, model_id)
    if mv is None:
        raise NotFound("Model version not found")
    if mv.status == "production":
        raise Conflict("Model version is already in production")
    # verify the artifact actually loads before switching traffic to it
    try:
        load_bundle(get_settings().models_dir, mv.equipment_type.key, mv.task, mv.version)
    except (ModelCompatibilityError, FileNotFoundError) as exc:
        raise Conflict(f"Model cannot be promoted: {exc}") from exc
    previous = db.scalar(select(m.ModelVersion.id).where(
        m.ModelVersion.equipment_type_id == mv.equipment_type_id, m.ModelVersion.task == mv.task,
        m.ModelVersion.status == "production"))
    db.execute(update(m.ModelVersion).where(
        m.ModelVersion.equipment_type_id == mv.equipment_type_id, m.ModelVersion.task == mv.task,
        m.ModelVersion.status == "production").values(status="archived"))
    db.flush()
    mv.status = "production"
    mv.promoted_at = datetime.now(UTC)
    mv.promoted_by_id = actor_id
    audit.record(db, actor_id, "model.promote", "model_version", mv.id,
                 {"version": mv.version, "task": mv.task, "equipment_type": mv.equipment_type.key,
                  "previous_production_id": previous}, ip)
    db.commit()
    model_cache.clear()
    return mv


class ModelCache:
    """Loads production bundles lazily and keeps them keyed by model_version id."""

    def __init__(self) -> None:
        self._cache: dict[int, LoadedModel] = {}
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def production(self, db: Session, equipment_type_id: int) -> dict[str, tuple[m.ModelVersion, LoadedModel] | None]:
        out: dict[str, tuple[m.ModelVersion, LoadedModel] | None] = {t: None for t in m.MODEL_TASKS}
        rows = db.scalars(select(m.ModelVersion).where(
            m.ModelVersion.equipment_type_id == equipment_type_id, m.ModelVersion.status == "production")).all()
        for mv in rows:
            loaded = self._get(mv)
            if loaded is not None:
                out[mv.task] = (mv, loaded)
        return out

    def _get(self, mv: m.ModelVersion) -> LoadedModel | None:
        with self._lock:
            if mv.id in self._cache:
                return self._cache[mv.id]
        try:
            bundle, meta = load_bundle(get_settings().models_dir, mv.equipment_type.key, mv.task, mv.version)
        except (ModelCompatibilityError, FileNotFoundError, OSError) as exc:
            log.error("Cannot load model %s %s: %s", mv.name, mv.version, exc)
            return None
        loaded = LoadedModel(bundle, mv.version, meta)
        with self._lock:
            self._cache[mv.id] = loaded
        return loaded

    def loaded_count(self) -> int:
        return len(self._cache)


model_cache = ModelCache()


def production_thresholds(db: Session) -> dict[str, Any]:
    rows = db.scalars(select(m.ModelVersion).where(m.ModelVersion.status == "production", m.ModelVersion.task == "failure"))
    return {mv.equipment_type.key: mv.metrics.get("test", {}).get("threshold") for mv in rows}
