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


def _is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) == b"\x7fELF"
    except OSError:
        return False


def _browser_runtime(node: str, oracle_root: Path) -> dict[str, Any]:
    """Check that the pinned Playwright WebKit binary can resolve its libraries."""
    located = subprocess.run(
        [node, "-e", "import('@playwright/test').then(m => console.log(m.webkit.executablePath()))"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(oracle_root),
    )
    path = located.stdout.strip().splitlines()[-1] if located.stdout.strip() else ""
    if not path or not Path(path).is_file():
        return {
            "present": False,
            "reason": "the pinned Playwright WebKit browser is not installed",
            "executable": path or None,
        }
    if not shutil.which("ldd"):
        return {"present": True, "executable": path, "checked": False}
    # Playwright reports a shell wrapper as the executable, so checking that
    # path alone always looks healthy. The binaries it launches are what have
    # to resolve their libraries.
    candidates = [Path(path)] if _is_elf(Path(path)) else []
    candidates.extend(
        sorted(item for item in Path(path).parent.rglob("MiniBrowser") if _is_elf(item))
    )
    if not candidates:
        return {"present": True, "executable": path, "checked": False}
    missing: set[str] = set()
    for candidate in candidates:
        linked = subprocess.run(
            ["ldd", str(candidate)], check=False, capture_output=True, text=True, timeout=60
        )
        missing.update(
            line.split("=>")[0].strip()
            for line in linked.stdout.splitlines()
            if "not found" in line
        )
    missing = sorted(missing)
    if missing:
        return {
            "present": False,
            "reason": f"the Playwright WebKit browser cannot load: {', '.join(missing[:6])}",
            "executable": path,
            "checked_binaries": [str(item) for item in candidates],
            "missing_libraries": missing,
        }
    return {
        "present": True,
        "executable": path,
        "checked": True,
        "checked_binaries": [str(item) for item in candidates],
        "missing_libraries": [],
    }


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
        oracle_root = Path(__file__).resolve().parents[2] / "oracle" / "playwright"
        if node:
            checks["playwright"] = _command_version([node, str(oracle_root / "probe.mjs")])
        else:
            checks["playwright"] = {"present": False, "reason": "Node missing"}
        if not checks["node"]["present"]:
            reasons.append("Node.js missing")
        if not checks["playwright"]["present"]:
            reasons.append("@playwright/test missing")
        elif node:
            # The package being installed says nothing about whether its
            # bundled browser can actually start. A browser that cannot load
            # its shared libraries is a blocked environment, not a failing
            # oracle, so the prerequisite probe has to see it.
            checks["playwright_browser"] = _browser_runtime(node, oracle_root)
            if not checks["playwright_browser"]["present"]:
                reasons.append(checks["playwright_browser"]["reason"])

    return {
        **common,
        "backend": kind,
        "ready": not reasons,
        "reasons": reasons,
        "checks": checks,
    }
