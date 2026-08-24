//! WebKitGTK adapter process.
//!
//! Implements the host side of `spec/NATIVE_ADAPTER_CONTRACT_V1.md`: one
//! ordered, line-delimited JSON channel on stdin/stdout, inside a real GTK
//! application lifecycle hosting a real content view.
//!
//! The adapter reports what the engine told it and nothing more. It does not
//! normalize, coalesce, retry, or invent an event. Those are host concerns.

use std::cell::RefCell;
use std::collections::VecDeque;
use std::io::{BufRead, Write};
use std::sync::Mutex;
use std::time::Instant;

use anyhow::Result;
// Always reach glib/gio through gtk so every crate in the graph agrees.
use gtk::prelude::*;
use gtk::{gio, glib};
use serde::Serialize;
use serde_json::{Value, json};
use webkit6::prelude::*;
use webkit6::{
    LoadEvent, SnapshotOptions, SnapshotRegion, UserContentInjectedFrames, UserContentManager,
    UserScript, UserScriptInjectionTime, WebView,
};

const TRANSPORT_VERSION: u64 = 1;
const APPLICATION_ID: &str = "app.workbench.browser.WebKitGtkWorker";

/// Frames pushed by the stdin reader thread and drained on the GTK main thread.
static INBOX: Mutex<VecDeque<Inbound>> = Mutex::new(VecDeque::new());

enum Inbound {
    Line(String),
    Closed,
}

thread_local! {
    static STATE: RefCell<Option<AdapterState>> = const { RefCell::new(None) };
}

struct AdapterState {
    application: gtk::Application,
    window: Option<gtk::ApplicationWindow>,
    view: Option<WebView>,
    hold: Option<gio::ApplicationHoldGuard>,
    started: Instant,
    ordinal: u64,
    navigations: u64,
    page_generation: u64,
    shutting_down: bool,
}

impl AdapterState {
    fn monotonic_ms(&self) -> u64 {
        self.started.elapsed().as_millis() as u64
    }

    /// Every adapter line goes through here so `ordinal` stays a single
    /// contiguous sequence shared by events and replies.
    fn write_frame(&mut self, mut frame: Value) {
        self.ordinal += 1;
        frame["v"] = json!(TRANSPORT_VERSION);
        frame["ordinal"] = json!(self.ordinal);
        let line = serde_json::to_string(&frame).unwrap_or_else(|error| {
            format!(
                "{{\"v\":{TRANSPORT_VERSION},\"ordinal\":{},\"type\":\"reply\",\"ok\":false,\
                 \"error\":{{\"code\":\"internal_invariant\",\"message\":\"frame is not serializable: {error}\"}}}}",
                self.ordinal
            )
        });
        let stdout = std::io::stdout();
        let mut handle = stdout.lock();
        // A failed write means the host is gone; there is nowhere left to report it.
        let _ = writeln!(handle, "{line}");
        let _ = handle.flush();
    }

    fn emit_event(&mut self, kind: &str, payload: Value) {
        let monotonic_ms = self.monotonic_ms();
        self.write_frame(json!({
            "type": "event",
            "kind": kind,
            "monotonic_ms": monotonic_ms,
            "payload": payload,
        }));
    }

    fn reply_ok(&mut self, seq: u64, result: Value) {
        self.write_frame(json!({"type": "reply", "seq": seq, "ok": true, "result": result}));
    }

    fn reply_error(&mut self, seq: u64, code: &str, message: &str, details: Value) {
        self.write_frame(json!({
            "type": "reply",
            "seq": seq,
            "ok": false,
            "error": {"code": code, "message": message, "details": details},
        }));
    }
}

#[derive(Serialize)]
struct Identity {
    adapter: &'static str,
    adapter_version: &'static str,
    transport_version: u64,
    engine: String,
    engine_api: &'static str,
    gtk: String,
    display_backend: String,
}

fn identity() -> Identity {
    Identity {
        adapter: "browser-workbench-webkitgtk-worker",
        adapter_version: env!("CARGO_PKG_VERSION"),
        transport_version: TRANSPORT_VERSION,
        engine: format!(
            "{}.{}.{}",
            webkit6::functions::major_version(),
            webkit6::functions::minor_version(),
            webkit6::functions::micro_version()
        ),
        engine_api: "webkitgtk-6.0",
        gtk: format!(
            "{}.{}.{}",
            gtk::major_version(),
            gtk::minor_version(),
            gtk::micro_version()
        ),
        display_backend: gtk::gdk::Display::default()
            .map(|display| display.type_().name().to_string())
            .unwrap_or_else(|| "none".to_string()),
    }
}

pub fn run() -> Result<()> {
    let application = gtk::Application::builder()
        .application_id(APPLICATION_ID)
        // Non-unique: this process must never hand its session to another instance.
        .flags(gio::ApplicationFlags::NON_UNIQUE)
        .build();

    application.connect_activate(|application| {
        let hold = application.hold();
        STATE.with(|cell| {
            *cell.borrow_mut() = Some(AdapterState {
                application: application.clone(),
                window: None,
                view: None,
                hold: Some(hold),
                started: Instant::now(),
                ordinal: 0,
                navigations: 0,
                page_generation: 0,
                shutting_down: false,
            });
        });
        let identity = serde_json::to_value(identity()).unwrap_or(Value::Null);
        with_state(|state| state.write_frame(json!({"type": "ready", "identity": identity})));
        spawn_reader();
    });

    // Our own argv is the host's, not GTK's; GTK must not reinterpret it.
    let status = application.run_with_args::<&str>(&[]);
    if status != glib::ExitCode::SUCCESS {
        anyhow::bail!("GTK application exited with {status:?}");
    }
    Ok(())
}

fn with_state<T>(action: impl FnOnce(&mut AdapterState) -> T) -> Option<T> {
    STATE.with(|cell| cell.borrow_mut().as_mut().map(action))
}

/// Reads request lines off the host channel and wakes the GTK main loop.
///
/// The read runs on its own thread because the GTK main loop must stay free to
/// dispatch engine callbacks; nothing here touches GTK state.
fn spawn_reader() {
    std::thread::spawn(|| {
        let stdin = std::io::stdin();
        for line in stdin.lock().lines() {
            let message = match line {
                Ok(value) => Inbound::Line(value),
                Err(_) => Inbound::Closed,
            };
            let closed = matches!(message, Inbound::Closed);
            if let Ok(mut inbox) = INBOX.lock() {
                inbox.push_back(message);
            }
            glib::idle_add_once(drain_inbox);
            if closed {
                return;
            }
        }
        if let Ok(mut inbox) = INBOX.lock() {
            inbox.push_back(Inbound::Closed);
        }
        glib::idle_add_once(drain_inbox);
    });
}

fn drain_inbox() {
    loop {
        let next = INBOX.lock().ok().and_then(|mut inbox| inbox.pop_front());
        match next {
            Some(Inbound::Line(line)) => handle_line(&line),
            // The host vanished. Exit rather than linger holding a browser session.
            Some(Inbound::Closed) => {
                with_state(|state| {
                    state.shutting_down = true;
                    teardown(state);
                });
                return;
            }
            None => return,
        }
    }
}

fn handle_line(line: &str) {
    let trimmed = line.trim();
    if trimmed.is_empty() {
        return;
    }
    let request: Value = match serde_json::from_str(trimmed) {
        Ok(value) => value,
        Err(error) => {
            with_state(|state| {
                state.write_frame(json!({
                    "type": "reply",
                    "seq": Value::Null,
                    "ok": false,
                    "error": {
                        "code": "invalid_request",
                        "message": "request frame is not valid JSON",
                        "details": {"detail": error.to_string()},
                    },
                }));
            });
            return;
        }
    };
    let seq = request.get("seq").and_then(Value::as_u64).unwrap_or(0);
    let version = request.get("v").and_then(Value::as_u64).unwrap_or(0);
    let op = request
        .get("op")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let params = request.get("params").cloned().unwrap_or_else(|| json!({}));

    if version != TRANSPORT_VERSION {
        with_state(|state| {
            state.reply_error(
                seq,
                "protocol_mismatch",
                "unsupported transport version",
                json!({"observed": version, "expected": TRANSPORT_VERSION}),
            );
        });
        return;
    }
    dispatch(seq, &op, &params);
}

fn dispatch(seq: u64, op: &str, params: &Value) {
    match op {
        "handshake" => {
            let identity = serde_json::to_value(identity()).unwrap_or(Value::Null);
            with_state(|state| state.reply_ok(seq, json!({"identity": identity})));
        }
        "session.open" => op_session_open(seq, params),
        "page.navigate" => op_page_navigate(seq, params),
        "page.observe" => op_page_observe(seq),
        "page.evaluate" => op_page_evaluate(seq, params),
        "page.snapshot" => op_page_snapshot(seq, params),
        "shutdown" => {
            with_state(|state| {
                state.reply_ok(seq, json!({"closing": true}));
                state.shutting_down = true;
                teardown(state);
            });
        }
        other => {
            with_state(|state| {
                state.reply_error(
                    seq,
                    "capability_unsupported",
                    "operation is not implemented by this adapter",
                    json!({"op": other}),
                );
            });
        }
    }
}

fn op_session_open(seq: u64, params: &Value) {
    let width = params.get("width").and_then(Value::as_i64).unwrap_or(1280) as i32;
    let height = params.get("height").and_then(Value::as_i64).unwrap_or(800) as i32;

    let already_open = with_state(|state| state.view.is_some()).unwrap_or(false);
    if already_open {
        with_state(|state| {
            state.reply_error(
                seq,
                "backend_rejected",
                "session is already open",
                json!({}),
            );
        });
        return;
    }

    let application = match with_state(|state| state.application.clone()) {
        Some(application) => application,
        None => return,
    };

    let manager = UserContentManager::new();
    if !manager.register_script_message_handler("workbench", None) {
        with_state(|state| {
            state.reply_error(
                seq,
                "backend_failed",
                "the console bridge handler could not be registered",
                json!({}),
            );
        });
        return;
    }
    manager.connect_script_message_received(Some("workbench"), |_manager, value| {
        // Raw injected payload, reported exactly as the page sent it.
        let text = value.to_json(0).map(|json| json.to_string());
        emit(
            "script-message",
            json!({"handler": "workbench", "json": text}),
        );
    });
    manager.add_script(&UserScript::new(
        CONSOLE_BRIDGE,
        UserContentInjectedFrames::TopFrame,
        UserScriptInjectionTime::Start,
        &[],
        &[],
    ));

    let view = WebView::builder().user_content_manager(&manager).build();
    // Headless there is no window manager to honour a default window size, so
    // the declared viewport is expressed as the content view's own size
    // request. Otherwise the engine lays out at GTK's fallback size and every
    // snapshot silently disagrees with the run spec.
    view.set_size_request(width, height);
    install_engine_hooks(&view);
    let window = gtk::ApplicationWindow::builder()
        .application(&application)
        .title("Browser Workbench")
        .default_width(width)
        .default_height(height)
        .build();
    // The shell hosts the real content view; it is not a screenshot surface.
    window.set_child(Some(&view));
    window.present();

    with_state(|state| {
        state.page_generation = 1;
        state.window = Some(window);
        state.view = Some(view);
        let generation = state.page_generation;
        state.reply_ok(
            seq,
            json!({
                "page_id": "page-1",
                "generation": generation,
                "viewport": {"width": width, "height": height},
            }),
        );
    });
}

fn op_page_navigate(seq: u64, params: &Value) {
    let url = params
        .get("url")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    if url.is_empty() {
        with_state(|state| {
            state.reply_error(seq, "invalid_request", "navigate requires a url", json!({}));
        });
        return;
    }
    let view = match with_state(|state| state.view.clone()).flatten() {
        Some(view) => view,
        None => {
            with_state(|state| {
                state.reply_error(seq, "page_not_found", "no page is open", json!({}));
            });
            return;
        }
    };

    // Acceptance only. Whether the navigation succeeded is established by the
    // engine events that follow, never by this reply.
    let navigation_id = with_state(|state| {
        state.navigations += 1;
        format!("navigation-{:04}", state.navigations)
    })
    .unwrap_or_else(|| "navigation-0000".to_string());
    view.load_uri(&url);
    with_state(|state| {
        state.reply_ok(
            seq,
            json!({"accepted": true, "navigation_id": navigation_id, "url": url}),
        );
    });
}

fn op_page_observe(seq: u64) {
    let view = match with_state(|state| state.view.clone()).flatten() {
        Some(view) => view,
        None => {
            with_state(|state| {
                state.reply_error(seq, "page_not_found", "no page is open", json!({}));
            });
            return;
        }
    };
    let uri = view.uri().map(|value| value.to_string());
    let title = view.title().map(|value| value.to_string());
    let is_loading = view.is_loading();
    let progress = view.estimated_load_progress();
    let can_go_back = view.can_go_back();
    let can_go_forward = view.can_go_forward();
    with_state(|state| {
        let generation = state.page_generation;
        state.reply_ok(
            seq,
            json!({
                "page_id": "page-1",
                "generation": generation,
                "url": uri,
                "title": title,
                "is_loading": is_loading,
                "estimated_load_progress": progress,
                "can_go_back": can_go_back,
                "can_go_forward": can_go_forward,
            }),
        );
    });
}

/// Maximum base64 payload the adapter will put in one frame.
///
/// Evidence is bounded by contract. An oversized snapshot is an explicit
/// failure, never a silently downscaled or cropped image.
const MAX_INLINE_EVIDENCE_BYTES: usize = 700 * 1024;

fn current_view(seq: u64) -> Option<WebView> {
    match with_state(|state| state.view.clone()).flatten() {
        Some(view) => Some(view),
        None => {
            with_state(|state| {
                state.reply_error(seq, "page_not_found", "no page is open", json!({}));
            });
            None
        }
    }
}

/// Evaluate declared JavaScript in the page and return its JSON projection.
///
/// The reply arrives after the engine resolves, so engine events observed
/// while the script runs are emitted first and keep their place in the
/// ordinal sequence.
fn op_page_evaluate(seq: u64, params: &Value) {
    let script = params
        .get("script")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    if script.is_empty() {
        with_state(|state| {
            state.reply_error(
                seq,
                "invalid_request",
                "evaluate requires a script",
                json!({}),
            );
        });
        return;
    }
    let Some(view) = current_view(seq) else {
        return;
    };
    let future = view.evaluate_javascript_future(&script, None, None);
    glib::MainContext::default().spawn_local(async move {
        match future.await {
            Ok(value) => {
                let json = value.to_json(0).map(|value| value.to_string());
                with_state(|state| {
                    state.reply_ok(seq, json!({"json": json}));
                });
            }
            Err(error) => {
                with_state(|state| {
                    state.reply_error(
                        seq,
                        "backend_rejected",
                        "script evaluation failed",
                        json!({"detail": error.to_string()}),
                    );
                });
            }
        }
    });
}

/// Capture an engine snapshot and hand it back inline as PNG bytes.
///
/// The host is the only writer of evidence; the adapter never touches the
/// evidence tree itself.
fn op_page_snapshot(seq: u64, params: &Value) {
    let full = params
        .get("region")
        .and_then(Value::as_str)
        .unwrap_or("full-document")
        == "full-document";
    let Some(view) = current_view(seq) else {
        return;
    };
    let region = if full {
        SnapshotRegion::FullDocument
    } else {
        SnapshotRegion::Visible
    };
    let future = view.snapshot_future(region, SnapshotOptions::NONE);
    glib::MainContext::default().spawn_local(async move {
        match future.await {
            Ok(texture) => {
                let bytes = texture.save_to_png_bytes();
                let encoded = base64_encode(&bytes);
                if encoded.len() > MAX_INLINE_EVIDENCE_BYTES {
                    with_state(|state| {
                        state.reply_error(
                            seq,
                            "evidence_incomplete",
                            "snapshot exceeds the declared inline evidence bound",
                            json!({"encoded_bytes": encoded.len(), "bound": MAX_INLINE_EVIDENCE_BYTES}),
                        );
                    });
                    return;
                }
                with_state(|state| {
                    state.reply_ok(
                        seq,
                        json!({
                            "png_base64": encoded,
                            "bytes": bytes.len(),
                            "width": texture.width(),
                            "height": texture.height(),
                            "region": if full { "full-document" } else { "visible" },
                        }),
                    );
                });
            }
            Err(error) => {
                with_state(|state| {
                    state.reply_error(
                        seq,
                        "backend_rejected",
                        "snapshot failed",
                        json!({"detail": error.to_string()}),
                    );
                });
            }
        }
    });
}

fn teardown(state: &mut AdapterState) {
    if let Some(window) = state.window.take() {
        window.close();
    }
    state.view = None;
    // Dropping the hold guard lets the application loop finish.
    state.hold = None;
    state.application.quit();
}

/// Injected console bridge.
///
/// WebKitGTK 6 exposes no console signal, so console capture is necessarily
/// injected. The capability matrix declares this lane `provider: injected,
/// semantics: normalized` for exactly this reason: a page can observe and
/// defeat this wrapper, which an engine-level hook could not be.
const CONSOLE_BRIDGE: &str = r#"
(() => {
  const post = (level, args) => {
    try {
      const text = args.map((value) => {
        try { return typeof value === 'string' ? value : JSON.stringify(value); }
        catch (error) { return String(value); }
      }).join(' ');
      window.webkit.messageHandlers.workbench.postMessage(
        JSON.stringify({ kind: 'console', level: level, text: text })
      );
    } catch (error) { /* the page may have removed the bridge; stay silent */ }
  };
  for (const level of ['log', 'info', 'warn', 'error', 'debug']) {
    const original = console[level].bind(console);
    console[level] = (...args) => { post(level, args); original(...args); };
  }
  window.addEventListener('error', (event) => post('error', [String(event.message)]));
})();
"#;

const BASE64: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

/// Minimal base64 encoder. The adapter carries no dependency for this.
fn base64_encode(data: &[u8]) -> String {
    let mut out = String::with_capacity(data.len().div_ceil(3) * 4);
    for chunk in data.chunks(3) {
        let b = [
            chunk[0],
            *chunk.get(1).unwrap_or(&0),
            *chunk.get(2).unwrap_or(&0),
        ];
        let n = ((b[0] as u32) << 16) | ((b[1] as u32) << 8) | b[2] as u32;
        out.push(BASE64[(n >> 18) as usize & 63] as char);
        out.push(BASE64[(n >> 12) as usize & 63] as char);
        out.push(if chunk.len() > 1 {
            BASE64[(n >> 6) as usize & 63] as char
        } else {
            '='
        });
        out.push(if chunk.len() > 2 {
            BASE64[n as usize & 63] as char
        } else {
            '='
        });
    }
    out
}

fn install_engine_hooks(view: &WebView) {
    view.connect_load_changed(|view, phase: LoadEvent| {
        emit(
            "load-changed",
            json!({
                "phase": match phase {
                    LoadEvent::Started => "started",
                    LoadEvent::Redirected => "redirected",
                    LoadEvent::Committed => "committed",
                    LoadEvent::Finished => "finished",
                    _ => "unknown",
                },
                "url": view.uri().map(|value| value.to_string()),
                "title": view.title().map(|value| value.to_string()),
                "is_loading": view.is_loading(),
            }),
        );
    });
    view.connect_load_failed(|view, _phase, uri, error| {
        emit(
            "load-failed",
            json!({
                "url": uri,
                "error": error.to_string(),
                "current_url": view.uri().map(|value| value.to_string()),
            }),
        );
        false
    });
    view.connect_resource_load_started(|_view, resource, request| {
        // Raw request identity is captured before any host-side normalization.
        emit(
            "resource-load-started",
            json!({"url": request.uri().map(|value| value.to_string())}),
        );
        // Response status is only knowable per resource, which is why the
        // capability matrix declares this lane partial rather than exact.
        resource.connect_response_notify(|resource| {
            let response = resource.response();
            emit(
                "resource-response",
                json!({
                    "url": resource.uri().map(|value| value.to_string()),
                    "status": response.as_ref().map(|value| value.status_code()),
                    "mime_type": response
                        .as_ref()
                        .and_then(|value| value.mime_type())
                        .map(|value| value.to_string()),
                }),
            );
        });
        resource.connect_failed(|resource, error| {
            emit(
                "resource-failed",
                json!({
                    "url": resource.uri().map(|value| value.to_string()),
                    "error": error.to_string(),
                }),
            );
        });
    });
    view.connect_script_dialog(|_view, _dialog| false); // host resolves decision tokens
    view.connect_permission_request(|_view, _request| false); // default deny until declared
    view.connect_run_file_chooser(|_view, _request| false); // only declared fixture paths
    view.connect_web_process_terminated(|view, reason| {
        emit(
            "web-process-terminated",
            json!({
                "reason": format!("{reason:?}"),
                "url": view.uri().map(|value| value.to_string()),
            }),
        );
    });
    view.connect_create(|_view, _action| None); // popup becomes a host-owned tab or is rejected
    view.connect_title_notify(|view| {
        emit(
            "title-changed",
            json!({
                "title": view.title().map(|value| value.to_string()),
                "url": view.uri().map(|value| value.to_string()),
            }),
        );
    });
}

/// Pinned engine surface that is not wired yet.
///
/// `evaluate_javascript_future` and `snapshot_future` are now reachable
/// through `page.evaluate` and `page.snapshot`; they remain named here because
/// the source gate asserts the pinned boundary. `reload` and `stop_loading`
/// are genuinely unwired and must not be described as available.
#[allow(dead_code)]
fn declared_operations(view: &WebView) {
    view.reload();
    view.stop_loading();
    let javascript = view.evaluate_javascript_future("document.title", None, None);
    let screenshot = view.snapshot_future(SnapshotRegion::FullDocument, SnapshotOptions::NONE);
    glib::MainContext::default().spawn_local(async move {
        let _bounded_script_result = javascript.await;
        let _bounded_screenshot = screenshot.await;
    });
}

fn emit(kind: &str, payload: Value) {
    with_state(|state| state.emit_event(kind, payload));
}
