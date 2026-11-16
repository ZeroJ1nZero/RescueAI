import hashlib
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

STAGES = [f"E{i}" for i in range(6)]
EXPECTED = ["session.json", "calibration.json", "trajectory.csv", "object_observations.jsonl", "objects_final.json",
            "map_3d.ply", "map_2d.png", "map_2d.yaml", "metrics.json", "tegrastats.log", "failures.jsonl", "evidence_frames/", "report.md"]


def write_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    tmp.replace(path)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def git_info():
    def git(*args):
        p = subprocess.run(["git", *args], capture_output=True, text=True, timeout=10)
        return p.stdout.strip() if p.returncode == 0 else None
    try:
        commit = git("rev-parse", "HEAD")
        return {"commit": commit, "dirty": bool(git("status", "--porcelain")) if commit else None,
                "reason": None if commit else "not_a_git_repository_or_no_commit"}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"commit": None, "dirty": None, "reason": str(e)}


def protect_source(output, source):
    if source is not None:
        source, output = Path(source).resolve(), Path(output).resolve()
        if source.is_dir() and output.is_relative_to(source):
            raise ValueError("output must be outside the reference source directory")


class Session:
    def __init__(self, path, config, environment):
        self.path = Path(path)
        protect_source(self.path, config.get("dataset", {}).get("path"))
        self.path.mkdir(parents=True, exist_ok=False)
        self.data = {"schema_version": "1.0", "session_id": str(uuid.uuid4()),
                     "created_utc": datetime.now(timezone.utc).isoformat(), "config": config,
                     "config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True, allow_nan=False).encode()).hexdigest(),
                     "environment": environment, "git": git_info(),
                     "execution_mode": "offline", "models": {"detector": None, "gemma": None},
                     "stages": {s: {"status": "not_run", "reason": "prior_stage_not_validated"} for s in STAGES}}
        self.failures = []
        self.finish()

    def stage(self, name, status, reason=None):
        if name not in STAGES or status not in {"not_run", "failed", "passed", "running"}:
            raise ValueError("invalid stage/status")
        self.data["stages"][name] = {"status": status, "reason": reason}

    def failure(self, stage, code, detail):
        self.failures.append({"stage": stage, "code": code, "detail": str(detail),
                              "recorded_utc": datetime.now(timezone.utc).isoformat()})

    def finish(self):
        if self.failures:
            (self.path / "failures.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False, allow_nan=False) + "\n" for x in self.failures))
        self.data["artifacts"] = {f: {"status": "written" if (self.path / f).exists() else "not_generated",
                                      "reason": None if (self.path / f).exists() else "producing_stage_not_executed_or_no_measurement"}
                                   for f in EXPECTED if f not in {"session.json", "report.md"}}
        files = [p for p in self.path.rglob("*") if p.is_file() and p.name not in {"session.json", "report.md"}]
        self.data["file_sha256"] = {str(p.relative_to(self.path)): sha256(p) for p in files}
        write_json(self.path / "session.json", self.data)
        lines = ["# Experiment report", "", f"Session: {self.data['session_id']}",
                 f"Device: {self.data['environment'].get('device_kind', 'unverified')}",
                 "Execution: offline; no real-time or Orin performance claim.", "",
                 "## Stages", ""]
        lines += [f"- {k}: {v['status']} ({v['reason'] or 'checks passed'})" for k, v in self.data["stages"].items()]
        lines += ["", "## Failures", ""] + [f"- {f['stage']}/{f['code']}: {f['detail']}" for f in self.failures]
        lines += ["", "## Artifacts", "", "See session.json for hashes, configuration, versions, unavailable outputs and reasons.",
                  "E0 measurements, if present: e0_validation.json. Previews are diagnostic, not mapping results.",
                  "A passed software test suite uses synthetic fixtures and does not establish a measured-data experiment."]
        (self.path / "report.md").write_text("\n".join(lines) + "\n")


def verify_export(path):
    path = Path(path)
    data = json.loads((path / "session.json").read_text())
    errors = [name for name, digest in data["file_sha256"].items()
              if not (path / name).is_file() or sha256(path / name) != digest]
    return {"verified_files": len(data["file_sha256"]), "hash_mismatches": errors,
            "stages": data["stages"], "note": "integrity verification only, not SLAM validation"}
