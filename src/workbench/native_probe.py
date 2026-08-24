from __future__ import annotations

import os
import json
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _pins() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "native" / "UPSTREAM_PINS.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("pins", {})


def _command_version(argv: list[str]) -> dict[str, Any]:
    executable = shutil.which(argv[0])
    if not executable:
        return {"present": False, "argv": argv, "output": None}
    completed = subprocess.run(
        [executable, *argv[1:]],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    output = (completed.stdout or completed.stderr).strip()
    return {
        "present": completed.returncode == 0,
        "argv": argv,
        "exit_code": completed.returncode,
        "output": output[:2048],
    }


def _pkg_config(module: str) -> dict[str, Any]:
    if not shutil.which("pkg-config"):
        return {"present": False, "module": module, "reason": "pkg-config missing"}
    result = _command_version(["pkg-config", "--modversion", module])
    return {**result, "module": module}


def probe_backend(kind: str) -> dict[str, Any]:
    pins = _pins()
    display = {
        "wayland": bool(os.environ.get("WAYLAND_DISPLAY")),
        "x11": bool(os.environ.get("DISPLAY")),
    }
    common = {
        "os": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "display": display,
    }
    if kind == "mock":
        return {**common, "backend": kind, "ready": True, "reasons": []}

    reasons: list[str] = []
    checks: dict[str, Any] = {}

    if kind in {"webkitgtk", "servo-gtk"}:
        checks["rustc"] = _command_version(["rustc", "--version", "--verbose"])
        checks["cargo"] = _command_version(["cargo", "--version"])
        checks["gtk4"] = _pkg_config("gtk4")
        if not checks["rustc"]["present"]:
            reasons.append("Rust compiler missing")
        if not checks["cargo"]["present"]:
            reasons.append("Cargo missing")
        if not checks["gtk4"]["present"]:
            reasons.append("GTK4 development package missing")
        if not any(display.values()):
            reasons.append("no Wayland or X11 display available")

    if kind == "webkitgtk":
        checks["webkitgtk_6"] = _pkg_config("webkitgtk-6.0")
        if not checks["webkitgtk_6"]["present"]:
            reasons.append("WebKitGTK 6.0 development package missing")
        else:
            expected = pins.get("webkitgtk", {}).get("release")
            observed = str(checks["webkitgtk_6"].get("output", "")).splitlines()[0]
            checks["webkitgtk_6"].update({"expected": expected, "matches_pin": observed == expected})
            if expected and observed != expected:
                reasons.append(f"WebKitGTK version {observed} does not match pin {expected}")

    if kind == "servo-gtk":
        source = os.environ.get("SERVO_GTK_SOURCE")
        checks["servo_gtk_source"] = {
            "present": bool(source and Path(source).joinpath("Cargo.toml").is_file()),
            "path": source,
        }
        if not checks["servo_gtk_source"]["present"]:
            reasons.append("SERVO_GTK_SOURCE does not point to the pinned checkout")
        else:
            revision = _command_version(["git", "-C", str(source), "rev-parse", "HEAD"])
            expected = pins.get("servo-gtk", {}).get("revision")
            observed = str(revision.get("output", "")).splitlines()[0]
            revision.update({"expected": expected, "matches_pin": observed == expected})
            checks["servo_gtk_revision"] = revision
            if not revision["present"] or observed != expected:
                reasons.append("ServoGTK checkout does not match the pinned revision")

    if kind == "playwright":
        checks["node"] = _command_version(["node", "--version"])
        node = shutil.which("node")
        if node:
            probe_script = Path(__file__).resolve().parents[2] / "oracle" / "playwright" / "probe.mjs"
            checks["playwright"] = _command_version([node, str(probe_script)])
        else:
            checks["playwright"] = {"present": False, "reason": "Node missing"}
        if not checks["node"]["present"]:
            reasons.append("Node.js missing")
        if not checks["playwright"]["present"]:
            reasons.append("@playwright/test missing")

    return {
        **common,
        "backend": kind,
        "ready": not reasons,
        "reasons": reasons,
        "checks": checks,
    }
