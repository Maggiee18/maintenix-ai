"""File-based model registry.

Layout::

    models/<equipment_type>/<task>/<version>/model.joblib
    models/<equipment_type>/<task>/<version>/metadata.json

``metadata.json`` records the dataset identifier, feature schema, training
parameters, metrics, library versions and the SHA-256 of the artifact. The
backend mirrors this metadata in its ``model_versions`` table and stores the
deployment status there.

Safety: artifacts are joblib (pickle) files, which can execute code when
loaded. ``load_bundle`` therefore only reads from the configured models
directory, rejects path traversal, verifies the SHA-256 recorded at training
time and checks the feature schema against the running code. There is no API to
upload model files.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib

from .equipment_types import get_spec
from .features import FEATURE_VERSION, anomaly_feature_names, feature_names

TASKS = ("failure", "anomaly", "rul")
_SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")


class ModelCompatibilityError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def expected_features(equipment_type: str, task: str) -> list[str]:
    spec = get_spec(equipment_type)
    return anomaly_feature_names(spec) if task == "anomaly" else feature_names(spec)


def save_bundle(models_dir: Path, equipment_type: str, task: str, bundle: Any, metadata: dict[str, Any]) -> Path:
    if task not in TASKS:
        raise ValueError(task)
    version = datetime.now(UTC).strftime("v%Y%m%dT%H%M%SZ")
    root = Path(models_dir) / equipment_type / task
    out = root / version
    n = 1
    while out.exists():
        out = root / f"{version}-{n}"
        n += 1
    out.mkdir(parents=True)
    artifact = out / "model.joblib"
    joblib.dump(bundle, artifact, compress=3)
    import sklearn
    import xgboost

    meta = {
        **metadata,
        "name": f"{equipment_type}-{task}",
        "equipment_type": equipment_type,
        "task": task,
        "version": out.name,
        "trained_at": datetime.now(UTC).isoformat(),
        "feature_schema": {"feature_version": FEATURE_VERSION, "feature_names": expected_features(equipment_type, task)},
        "artifact_file": artifact.name,
        "artifact_sha256": _sha256(artifact),
        "library_versions": {"scikit-learn": sklearn.__version__, "xgboost": xgboost.__version__},
    }
    (out / "metadata.json").write_text(json.dumps(json_safe(meta), indent=2, allow_nan=False))
    return out


def json_safe(o: Any) -> Any:
    """Recursively convert numpy types and replace NaN/inf with None (strict JSON)."""
    import math

    if isinstance(o, dict):
        return {str(k): json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [json_safe(v) for v in o]
    if isinstance(o, (str, bool)) or o is None:
        return o
    if isinstance(o, int):
        return o
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    try:
        return json_safe(_json_default(o))
    except TypeError:
        return str(o)


def _json_default(o: Any) -> Any:
    import numpy as np

    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


def list_metadata(models_dir: Path) -> list[dict[str, Any]]:
    out = []
    for meta_path in sorted(Path(models_dir).glob("*/*/*/metadata.json")):
        try:
            out.append(json.loads(meta_path.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def read_metadata(models_dir: Path, equipment_type: str, task: str, version: str) -> dict[str, Any]:
    return json.loads((_version_dir(models_dir, equipment_type, task, version) / "metadata.json").read_text())


def _version_dir(models_dir: Path, equipment_type: str, task: str, version: str) -> Path:
    for part in (equipment_type, task, version):
        if not _SAFE.match(part):
            raise ModelCompatibilityError("Invalid model identifier")
    base = Path(models_dir).resolve()
    path = (base / equipment_type / task / version).resolve()
    if base not in path.parents:
        raise ModelCompatibilityError("Model path escapes the models directory")
    return path


def check_compatibility(meta: dict[str, Any]) -> None:
    schema = meta.get("feature_schema", {})
    if schema.get("feature_version") != FEATURE_VERSION:
        raise ModelCompatibilityError(
            f"Feature version mismatch: model {schema.get('feature_version')} vs code {FEATURE_VERSION}")
    if schema.get("feature_names") != expected_features(meta["equipment_type"], meta["task"]):
        raise ModelCompatibilityError("Feature names differ from the running feature pipeline")


def load_bundle(models_dir: Path, equipment_type: str, task: str, version: str) -> tuple[Any, dict[str, Any]]:
    vdir = _version_dir(models_dir, equipment_type, task, version)
    meta = json.loads((vdir / "metadata.json").read_text())
    check_compatibility(meta)
    artifact = vdir / meta["artifact_file"]
    if artifact.parent != vdir or _sha256(artifact) != meta["artifact_sha256"]:
        raise ModelCompatibilityError("Artifact checksum mismatch; refusing to load")
    return joblib.load(artifact), meta
