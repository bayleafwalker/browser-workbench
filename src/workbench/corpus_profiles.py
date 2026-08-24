from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import WorkbenchError
from .evidence import ArtifactStore
from .mock_backend import MockBackend
from .util import repo_root


class Profile:
    """Backend-specific bindings for the frozen scenario corpus.

    The corpus is frozen: twelve scenarios and their assertion texts do not
    change. How a given backend *reaches* each assertion does change, because
    a deterministic mock and a real browser engine are not the same machine.
    Everything that legitimately differs lives here, and every difference is
    declared in `semantics()` so a native corpus result can never be mistaken
    for the mock denominator.
    """

    name = "mock"
    backend_kind = "mock"
    variant = "denominator"

    def __init__(self) -> None:
        self._backends: list[Any] = []

    def make_backend(self, store: ArtifactStore) -> Any:
        backend = MockBackend(store, variant=self.variant)
        self._backends.append(backend)
        return backend

    def open_start_page(self, backend: Any, page_id: str) -> None:
        """Bring the page to a state where targets and scripts are meaningful.

        The mock's synthetic page object is already populated; a real engine
        starts on about:blank and has to load something first.
        """
        return None

    def url(self, name: str) -> str:
        return f"https://fixture.invalid/{name}"

    def settle(self, backend: Any, page_id: str) -> dict[str, Any]:
        return backend.page_await(
            {
                "page_id": page_id,
                "conditions": [{"kind": "load_state", "equals": "idle"}],
                "deadline_ms": 50,
            }
        )

    # -- semantics that genuinely differ between backends ------------------

    def clock_is_deterministic(self, awaited: dict[str, Any]) -> bool:
        """The mock owns a virtual clock, so the value itself is asserted."""
        return awaited["monotonic_ms"] == 10

    def javascript_provider(self) -> str:
        return "injected"

    def set_title_intent(self) -> dict[str, Any]:
        return {"kind": "javascript", "value": "set-title:Declared"}

    def read_title_intent(self) -> dict[str, Any]:
        return {"kind": "javascript", "value": "return-title"}

    def correlates_requests(self, network: list[dict[str, Any]]) -> bool:
        requests = {
            event["payload"].get("request_id")
            for event in network
            if event["kind"] == "network.request"
        }
        responses = {
            event["payload"].get("request_id")
            for event in network
            if event["kind"] == "network.response"
        }
        return bool(requests & responses)

    def act_on_fresh_target(self, backend: Any, page_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return (target, receipt) for one act against a live target."""
        target = backend.page_observe({"page_id": page_id, "projection": "targets"})["data"][
            "targets"
        ][0]
        receipt = backend.page_act(
            {
                "page_id": page_id,
                "client_id": "writer-a",
                "target": target,
                "intent": {"kind": "click"},
            }
        )
        return target, receipt

    def advance_generation(self, backend: Any, page_id: str) -> None:
        backend.page_navigate(
            {
                "page_id": page_id,
                "url": self.url("next"),
                "client_id": "writer-a",
                "wait": "commit",
            }
        )

    def prepare_prompts(self, backend: Any, page_id: str) -> None:
        backend.page_navigate(
            {"page_id": page_id, "url": self.url("prompts"), "client_id": "writer-a"}
        )
        self.settle(backend, page_id)

    def upload_act(self, backend: Any, page_id: str, path: Path) -> dict[str, Any]:
        return backend.page_act(
            {
                "page_id": page_id,
                "client_id": "writer-a",
                "intent": {"kind": "upload", "path": str(path)},
            }
        )

    def download_act(self, backend: Any, page_id: str) -> dict[str, Any]:
        return backend.page_act(
            {
                "page_id": page_id,
                "client_id": "writer-a",
                "intent": {"kind": "download.accept", "download_id": "fixture"},
            }
        )

    def crash(self, backend: Any, page_id: str) -> None:
        backend.page_act(
            {"page_id": page_id, "client_id": "writer-a", "intent": {"kind": "test.crash"}}
        )

    def semantics(self) -> dict[str, str]:
        return {}

    def close_all(self) -> list[dict[str, Any]]:
        """Tear down every backend this profile created for one repetition."""
        deviations: list[dict[str, Any]] = []
        for backend in self._backends:
            close = getattr(backend, "close", None)
            if close:
                try:
                    close()
                except WorkbenchError as error:
                    deviations.append({"kind": "corpus-teardown-error", "error": error.as_dict()})
            deviations.extend(getattr(backend, "deviations", []))
        self._backends = []
        return deviations


class WebKitGtkProfile(Profile):
    """Bindings for the real WebKitGTK backend against the loopback fixture."""

    name = "webkitgtk"
    backend_kind = "webkitgtk"

    def __init__(self, base_url: str, variant: str = "stable-ephemeral") -> None:
        super().__init__()
        self.base_url = base_url
        self.variant = variant

    def make_backend(self, store: ArtifactStore) -> Any:
        from .webkitgtk_backend import WebKitGtkBackend

        backend = WebKitGtkBackend(store, variant=self.variant)
        backend.connect()
        self._backends.append(backend)
        return backend

    def open_start_page(self, backend: Any, page_id: str) -> None:
        backend.page_navigate(
            {"page_id": page_id, "url": self.url("index"), "client_id": "writer-a"}
        )
        self.settle(backend, page_id)

    def url(self, name: str) -> str:
        return f"{self.base_url}{name}.html"

    def settle(self, backend: Any, page_id: str) -> dict[str, Any]:
        awaited = backend.page_await(
            {
                "page_id": page_id,
                "conditions": [{"kind": "load_state", "equals": "idle"}],
                "deadline_ms": 30000,
            }
        )
        # An idle load state is not yet a quiet engine.
        backend.quiesce()
        return awaited

    def clock_is_deterministic(self, awaited: dict[str, Any]) -> bool:
        """A real engine has no virtual clock.

        What is actually assertable is that the wait was satisfied by observed
        events rather than by sleeping: the event cursor advanced, and the
        monotonic reading came from engine event timestamps.
        """
        return awaited["satisfied"] is True and awaited["event_cursor"] > 0

    def javascript_provider(self) -> str:
        # Real script evaluation through the engine's own API.
        return "engine"

    def set_title_intent(self) -> dict[str, Any]:
        return {"kind": "javascript", "value": "document.title = 'Declared';"}

    def read_title_intent(self) -> dict[str, Any]:
        return {"kind": "javascript", "value": "document.title"}

    def correlates_requests(self, network: list[dict[str, Any]]) -> bool:
        # WebKitGTK identifies a resource by its URI, not by a request id.
        requests = {
            event["payload"].get("url")
            for event in network
            if event["kind"] == "network.request"
        }
        responses = {
            event["payload"].get("url")
            for event in network
            if event["kind"] == "network.response"
        }
        return bool(requests & responses)

    def act_on_fresh_target(self, backend: Any, page_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        targets = backend.page_observe({"page_id": page_id, "projection": "targets"})["data"][
            "targets"
        ]
        link = next(item for item in targets if item["role"] == "link")
        receipt = backend.page_act(
            {
                "page_id": page_id,
                "client_id": "writer-a",
                "target": link,
                "intent": {"kind": "click"},
            }
        )
        return link, receipt

    def advance_generation(self, backend: Any, page_id: str) -> None:
        # The click already navigated; settling commits the new generation.
        self.settle(backend, page_id)

    def prepare_prompts(self, backend: Any, page_id: str) -> None:
        backend.page_navigate(
            {"page_id": page_id, "url": self.url("prompts"), "client_id": "writer-a"}
        )
        self.settle(backend, page_id)
        # The fixture raises both prompts after load; wait for the engine to
        # actually hand them over rather than assuming they are already here.
        backend.await_pending(dialogs=1, permissions=1, deadline_ms=15000)

    def upload_act(self, backend: Any, page_id: str, path: Path) -> dict[str, Any]:
        backend.page_navigate(
            {"page_id": page_id, "url": self.url("upload"), "client_id": "writer-a"}
        )
        self.settle(backend, page_id)
        targets = backend.page_observe({"page_id": page_id, "projection": "targets"})["data"][
            "targets"
        ]
        chooser = next(item for item in targets if item["role"] == "file")
        return backend.page_act(
            {
                "page_id": page_id,
                "client_id": "writer-a",
                "target": chooser,
                "intent": {"kind": "upload", "path": str(path)},
            }
        )

    def download_act(self, backend: Any, page_id: str) -> dict[str, Any]:
        targets = backend.page_observe({"page_id": page_id, "projection": "targets"})["data"][
            "targets"
        ]
        link = next(item for item in targets if item["name"] == "Download")
        backend.page_act(
            {
                "page_id": page_id,
                "client_id": "writer-a",
                "target": link,
                "intent": {"kind": "click"},
            }
        )
        token = backend.await_download(deadline_ms=30000)
        return backend.page_act(
            {
                "page_id": page_id,
                "client_id": "writer-a",
                "intent": {"kind": "download.accept", "download_id": token},
            }
        )

    def crash(self, backend: Any, page_id: str) -> None:
        # A page that never loaded has no web process to kill, so the crash
        # would be a no-op. The checkpoint under test was already taken, so
        # loading here does not disturb the state being restored.
        self.open_start_page(backend, page_id)
        backend.page_act(
            {"page_id": page_id, "client_id": "writer-a", "intent": {"kind": "test.crash"}}
        )

    def semantics(self) -> dict[str, str]:
        return {
            "crash is visible": (
                "a real web process is started and then terminated; a page that never "
                "loaded has no process to kill"
            ),
            "virtual clock is deterministic": (
                "no virtual clock on a real engine; asserted as event-driven satisfaction "
                "with an advanced event cursor"
            ),
            "provider class is recorded": (
                "javascript runs through the engine API, so the provider is engine rather "
                "than the mock's injected"
            ),
            "network request and response correlate": (
                "WebKitGTK identifies a resource by URI; correlation is by URI, not request_id"
            ),
            "fresh target executes": (
                "targets are discovered by injected script because the engine exposes no "
                "host-side target API"
            ),
        }



def profile_for(kind: str, *, base_url: str | None = None, variant: str | None = None) -> Profile:
    if kind == "mock":
        return Profile()
    if kind == "webkitgtk":
        if not base_url:
            raise WorkbenchError("invalid_request", "the webkitgtk profile needs a fixture base URL")
        return WebKitGtkProfile(base_url, variant or "stable-ephemeral")
    raise WorkbenchError("invalid_request", f"no corpus profile for backend: {kind}")


def fixture_path() -> Path:
    return repo_root() / "examples" / "fixtures" / "upload.txt"


def load_corpus() -> dict[str, Any]:
    return json.loads(
        (repo_root() / "spec" / "WORKBENCH_CORPUS_V1.json").read_text(encoding="utf-8")
    )
