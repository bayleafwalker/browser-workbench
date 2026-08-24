//! WebKitGTK adapter process.
//!
//! Implements the adapter side of `spec/NATIVE_ADAPTER_CONTRACT_V1.md`: one
//! ordered, line-delimited JSON channel on stdin/stdout, inside a real GTK
//! application lifecycle hosting real content views.
//!
//! The adapter reports what the engine told it and nothing more. It does not
//! normalize, coalesce, retry, or invent an event, and it holds no protocol
//! state of its own: sessions, generations, leases, and evidence all belong to
//! the host.

use std::cell::RefCell;
use std::collections::{HashMap, VecDeque};
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
    Download, FileChooserRequest, LoadEvent, PermissionRequest, ScriptDialog, ScriptDialogType,
    SnapshotOptions, SnapshotRegion, UserContentInjectedFrames, UserContentManager, UserScript,
    UserScriptInjectionTime, WebView,
};

const TRANSPORT_VERSION: u64 = 1;
const APPLICATION_ID: &str = "app.workbench.browser.WebKitGtkWorker";

/// Maximum base64 payload the adapter will put in one frame.
///
/// Evidence is bounded by contract. An oversized snapshot is an explicit
/// failure, never a silently downscaled or cropped image.
const MAX_INLINE_EVIDENCE_BYTES: usize = 700 * 1024;

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
    stack: Option<gtk::Stack>,
    pages: HashMap<String, WebView>,
    page_order: Vec<String>,
    active_page: Option<String>,
    dialogs: HashMap<String, ScriptDialog>,
    permissions: HashMap<String, PermissionRequest>,
    file_choosers: HashMap<String, FileChooserRequest>,
    downloads: HashMap<String, Download>,
    hold: Option<gio::ApplicationHoldGuard>,
    started: Instant,
    ordinal: u64,
    navigations: u64,
    page_counter: u64,
    token_counter: u64,
    viewport: (i32, i32),
    quarantine: Option<String>,
    downloads_connected: bool,
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

    fn emit_event(&mut self, page_id: Option<&str>, kind: &str, payload: Value) {
        let monotonic_ms = self.monotonic_ms();
        self.write_frame(json!({
            "type": "event",
            "kind": kind,
            "page_id": page_id,
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

    fn next_token(&mut self, prefix: &str) -> String {
        self.token_counter += 1;
        format!("{prefix}-{:04}", self.token_counter)
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
                stack: None,
                pages: HashMap::new(),
                page_order: Vec::new(),
                active_page: None,
                dialogs: HashMap::new(),
                permissions: HashMap::new(),
                file_choosers: HashMap::new(),
                downloads: HashMap::new(),
                hold: Some(hold),
                started: Instant::now(),
                ordinal: 0,
                navigations: 0,
                page_counter: 0,
                token_counter: 0,
                viewport: (1280, 800),
                quarantine: None,
                downloads_connected: false,
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
                with_state(teardown);
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
        "page.new" => op_page_new(seq),
        "page.list" => op_page_list(seq),
        "page.close" => op_page_close(seq, params),
        "page.navigate" => op_page_navigate(seq, params),
        "page.observe" => op_page_observe(seq, params),
        "page.evaluate" => op_page_evaluate(seq, params),
        "page.snapshot" => op_page_snapshot(seq, params),
        "page.terminate" => op_page_terminate(seq, params),
        "page.decide" => op_page_decide(seq, params),
        "shutdown" => {
            with_state(|state| {
                state.reply_ok(seq, json!({"closing": true}));
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

// -- page lifecycle -------------------------------------------------------

fn op_session_open(seq: u64, params: &Value) {
    let width = params.get("width").and_then(Value::as_i64).unwrap_or(1280) as i32;
    let height = params.get("height").and_then(Value::as_i64).unwrap_or(800) as i32;

    if with_state(|state| state.window.is_some()).unwrap_or(false) {
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
    let Some(application) = with_state(|state| state.application.clone()) else {
        return;
    };

    let stack = gtk::Stack::new();
    let window = gtk::ApplicationWindow::builder()
        .application(&application)
        .title("Browser Workbench")
        .default_width(width)
        .default_height(height)
        .build();
    window.set_child(Some(&stack));
    window.present();
    let quarantine = params
        .get("quarantine_dir")
        .and_then(Value::as_str)
        .map(str::to_string);
    with_state(|state| {
        state.viewport = (width, height);
        state.window = Some(window);
        state.stack = Some(stack);
        state.quarantine = quarantine;
    });

    match create_page() {
        Some(page_id) => with_state(|state| {
            state.reply_ok(
                seq,
                json!({"page_id": page_id, "viewport": {"width": width, "height": height}}),
            );
        }),
        None => with_state(|state| {
            state.reply_error(
                seq,
                "backend_failed",
                "page could not be created",
                json!({}),
            )
        }),
    };
}

/// Builds one content view, wires its engine hooks, and puts it on screen.
fn create_page() -> Option<String> {
    let (stack, viewport, page_counter) =
        with_state(|state| (state.stack.clone(), state.viewport, state.page_counter))?;
    let stack = stack?;
    let page_id = format!("page-{}", page_counter + 1);

    let manager = UserContentManager::new();
    if !manager.register_script_message_handler("workbench", None) {
        return None;
    }
    let handler_page = page_id.clone();
    manager.connect_script_message_received(Some("workbench"), move |_manager, value| {
        // Raw injected payload, reported exactly as the page sent it.
        let text = value.to_json(0).map(|json| json.to_string());
        emit(
            Some(&handler_page),
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
    view.set_size_request(viewport.0, viewport.1);
    install_engine_hooks(&view, &page_id);
    install_download_hooks(&view);
    stack.add_named(&view, Some(&page_id));
    stack.set_visible_child(&view);

    with_state(|state| {
        state.page_counter += 1;
        state.pages.insert(page_id.clone(), view);
        state.page_order.push(page_id.clone());
        state.active_page = Some(page_id.clone());
    });
    Some(page_id)
}

fn op_page_new(seq: u64) {
    if with_state(|state| state.stack.is_none()).unwrap_or(true) {
        with_state(|state| {
            state.reply_error(seq, "backend_rejected", "no session is open", json!({}));
        });
        return;
    }
    match create_page() {
        Some(page_id) => {
            with_state(|state| state.reply_ok(seq, json!({"page_id": page_id})));
        }
        None => {
            with_state(|state| {
                state.reply_error(
                    seq,
                    "backend_failed",
                    "page could not be created",
                    json!({}),
                )
            });
        }
    }
}

fn op_page_list(seq: u64) {
    let pages = with_state(|state| {
        let active = state.active_page.clone();
        state
            .page_order
            .iter()
            .filter_map(|page_id| {
                state.pages.get(page_id).map(|view| {
                    json!({
                        "page_id": page_id,
                        "url": view.uri().map(|value| value.to_string()),
                        "title": view.title().map(|value| value.to_string()),
                        "active": Some(page_id.clone()) == active,
                    })
                })
            })
            .collect::<Vec<_>>()
    })
    .unwrap_or_default();
    with_state(|state| state.reply_ok(seq, json!({"pages": pages})));
}

fn op_page_close(seq: u64, params: &Value) {
    let Some(page_id) = page_param(seq, params) else {
        return;
    };
    let removed = with_state(|state| {
        let view = state.pages.remove(&page_id);
        state.page_order.retain(|item| item != &page_id);
        if state.active_page.as_deref() == Some(page_id.as_str()) {
            state.active_page = state.page_order.last().cloned();
        }
        (view, state.stack.clone())
    });
    match removed {
        Some((Some(view), Some(stack))) => {
            stack.remove(&view);
            with_state(|state| state.reply_ok(seq, json!({"closed": page_id})));
        }
        _ => {
            with_state(|state| {
                state.reply_error(seq, "page_not_found", "page does not exist", json!({}))
            });
        }
    }
}

/// Resolves the `page_id` parameter to a live view, replying with an error if
/// it names nothing.
fn page_view(seq: u64, params: &Value) -> Option<(String, WebView)> {
    let page_id = params
        .get("page_id")
        .and_then(Value::as_str)
        .map(str::to_string)
        .or_else(|| with_state(|state| state.active_page.clone()).flatten())?;
    match with_state(|state| state.pages.get(&page_id).cloned()).flatten() {
        Some(view) => Some((page_id, view)),
        None => {
            with_state(|state| {
                state.reply_error(
                    seq,
                    "page_not_found",
                    "page does not exist",
                    json!({"page_id": page_id}),
                );
            });
            None
        }
    }
}

fn page_param(seq: u64, params: &Value) -> Option<String> {
    page_view(seq, params).map(|(page_id, _)| page_id)
}

// -- page operations ------------------------------------------------------

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
    let Some((_page_id, view)) = page_view(seq, params) else {
        return;
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

fn op_page_observe(seq: u64, params: &Value) {
    let Some((page_id, view)) = page_view(seq, params) else {
        return;
    };
    let uri = view.uri().map(|value| value.to_string());
    let title = view.title().map(|value| value.to_string());
    let is_loading = view.is_loading();
    let progress = view.estimated_load_progress();
    let can_go_back = view.can_go_back();
    let can_go_forward = view.can_go_forward();
    with_state(|state| {
        state.reply_ok(
            seq,
            json!({
                "page_id": page_id,
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

fn op_page_terminate(seq: u64, params: &Value) {
    let Some((_page_id, view)) = page_view(seq, params) else {
        return;
    };
    // A real web process kill, not a simulated lifecycle flag.
    view.terminate_web_process();
    with_state(|state| state.reply_ok(seq, json!({"terminated": true})));
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
    let Some((_page_id, view)) = page_view(seq, params) else {
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
    let Some((_page_id, view)) = page_view(seq, params) else {
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

// -- browser-owned decisions ---------------------------------------------

/// Applies one host decision to a pending browser-owned request.
///
/// Dialogs, permissions, file choosers, and downloads are all held open until
/// the host decides. The adapter never answers on the host's behalf and never
/// answers the same request twice: the token is consumed on use.
fn op_page_decide(seq: u64, params: &Value) {
    let token = params
        .get("token")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let decision = params
        .get("decision")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();

    if let Some(dialog) = with_state(|state| state.dialogs.remove(&token)).flatten() {
        match decision.as_str() {
            "accept" => {
                dialog.confirm_set_confirmed(true);
                if dialog.dialog_type() == ScriptDialogType::Prompt {
                    dialog
                        .prompt_set_text(params.get("value").and_then(Value::as_str).unwrap_or(""));
                }
            }
            _ => dialog.confirm_set_confirmed(false),
        }
        dialog.close();
        with_state(|state| {
            state.reply_ok(
                seq,
                json!({"token": token, "decision": decision, "kind": "dialog"}),
            );
        });
        return;
    }

    if let Some(request) = with_state(|state| state.permissions.remove(&token)).flatten() {
        if decision == "allow" {
            request.allow();
        } else {
            request.deny();
        }
        with_state(|state| {
            state.reply_ok(
                seq,
                json!({"token": token, "decision": decision, "kind": "permission"}),
            );
        });
        return;
    }

    if let Some(request) = with_state(|state| state.file_choosers.remove(&token)).flatten() {
        if decision == "select" {
            let files: Vec<String> = params
                .get("files")
                .and_then(Value::as_array)
                .map(|items| {
                    items
                        .iter()
                        .filter_map(Value::as_str)
                        .map(str::to_string)
                        .collect()
                })
                .unwrap_or_default();
            let borrowed: Vec<&str> = files.iter().map(String::as_str).collect();
            request.select_files(&borrowed);
            with_state(|state| {
                state.reply_ok(
                    seq,
                    json!({"token": token, "decision": decision, "kind": "file-chooser", "files": files}),
                );
            });
        } else {
            request.cancel();
            with_state(|state| {
                state.reply_ok(
                    seq,
                    json!({"token": token, "decision": "cancel", "kind": "file-chooser"}),
                );
            });
        }
        return;
    }

    if let Some(download) = with_state(|state| state.downloads.get(&token).cloned()).flatten() {
        if decision == "cancel" {
            download.cancel();
        }
        with_state(|state| {
            state.reply_ok(
                seq,
                json!({
                    "token": token,
                    "decision": decision,
                    "kind": "download",
                    "destination": download.destination().map(|value| value.to_string()),
                }),
            );
        });
        return;
    }

    with_state(|state| {
        state.reply_error(
            seq,
            "precondition_failed",
            "decision token is unknown or already consumed",
            json!({"token": token}),
        );
    });
}

// -- engine hooks ---------------------------------------------------------

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

fn install_engine_hooks(view: &WebView, page_id: &str) {
    let page = page_id.to_string();
    view.connect_load_changed(move |view, phase: LoadEvent| {
        emit(
            Some(&page),
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
    let page = page_id.to_string();
    view.connect_load_failed(move |view, _phase, uri, error| {
        emit(
            Some(&page),
            "load-failed",
            json!({
                "url": uri,
                "error": error.to_string(),
                "current_url": view.uri().map(|value| value.to_string()),
            }),
        );
        false
    });
    let page = page_id.to_string();
    view.connect_resource_load_started(move |_view, resource, request| {
        // Raw request identity is captured before any host-side normalization.
        emit(
            Some(&page),
            "resource-load-started",
            json!({"url": request.uri().map(|value| value.to_string())}),
        );
        // Response status is only knowable per resource, which is why the
        // capability matrix declares this lane partial rather than exact.
        let response_page = page.clone();
        resource.connect_response_notify(move |resource| {
            let response = resource.response();
            emit(
                Some(&response_page),
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
        let failed_page = page.clone();
        resource.connect_failed(move |resource, error| {
            emit(
                Some(&failed_page),
                "resource-failed",
                json!({
                    "url": resource.uri().map(|value| value.to_string()),
                    "error": error.to_string(),
                }),
            );
        });
    });

    // Browser-owned decisions are held open, never answered by the adapter.
    let page = page_id.to_string();
    view.connect_script_dialog(move |_view, dialog| {
        let token = with_state(|state| {
            let token = state.next_token("dialog");
            state.dialogs.insert(token.clone(), dialog.clone());
            token
        });
        let Some(token) = token else {
            return false;
        };
        emit(
            Some(&page),
            "script-dialog",
            json!({
                "token": token,
                "dialog_type": format!("{:?}", dialog.dialog_type()),
                "message": dialog.message().map(|value| value.to_string()),
                "default_text": dialog.prompt_get_default_text().map(|value| value.to_string()),
                "default_decision": "deny",
            }),
        );
        // Handled: the dialog stays open until the host decides.
        true
    });
    let page = page_id.to_string();
    view.connect_permission_request(move |_view, request| {
        let token = with_state(|state| {
            let token = state.next_token("permission");
            state.permissions.insert(token.clone(), request.clone());
            token
        });
        let Some(token) = token else {
            return false;
        };
        emit(
            Some(&page),
            "permission-request",
            json!({
                "token": token,
                "request_type": request.type_().name(),
                "default_decision": "deny",
            }),
        );
        true
    });
    let page = page_id.to_string();
    view.connect_run_file_chooser(move |_view, request| {
        let token = with_state(|state| {
            let token = state.next_token("filechooser");
            state.file_choosers.insert(token.clone(), request.clone());
            token
        });
        let Some(token) = token else {
            return false;
        };
        emit(
            Some(&page),
            "file-chooser",
            json!({
                "token": token,
                "selects_multiple": request.selects_multiple(),
                "mime_types": request.mime_types().iter().map(|value| value.to_string()).collect::<Vec<_>>(),
                "default_decision": "cancel",
            }),
        );
        true
    });

    let page = page_id.to_string();
    view.connect_web_process_terminated(move |view, reason| {
        emit(
            Some(&page),
            "web-process-terminated",
            json!({
                "reason": format!("{reason:?}"),
                "url": view.uri().map(|value| value.to_string()),
            }),
        );
    });
    view.connect_create(|_view, _action| None); // popup becomes a host-owned tab or is rejected
    let page = page_id.to_string();
    view.connect_title_notify(move |view| {
        emit(
            Some(&page),
            "title-changed",
            json!({
                "title": view.title().map(|value| value.to_string()),
                "url": view.uri().map(|value| value.to_string()),
            }),
        );
    });
}

/// Downloads are session-scoped, so they are wired once per session.
fn install_download_hooks(view: &WebView) {
    if with_state(|state| state.downloads_connected).unwrap_or(true) {
        return;
    }
    let Some(session) = view.network_session() else {
        return;
    };
    session.connect_download_started(|_session, download| {
        let token = with_state(|state| {
            let token = state.next_token("download");
            state.downloads.insert(token.clone(), download.clone());
            token
        });
        let Some(token) = token else {
            return;
        };
        emit(
            None,
            "download-started",
            json!({
                "token": token,
                "url": download
                    .request()
                    .and_then(|request| request.uri())
                    .map(|value| value.to_string()),
            }),
        );
        // Every download lands in the host-declared quarantine directory.
        // Without this the engine picks its own destination and the file
        // escapes the evidence boundary before the host ever sees it.
        download.connect_decide_destination(move |download, suggested| {
            let Some(quarantine) = with_state(|state| state.quarantine.clone()).flatten() else {
                download.cancel();
                return true;
            };
            let name = if suggested.is_empty() {
                "download.bin"
            } else {
                suggested
            };
            let destination = format!("{quarantine}/{name}");
            download.set_allow_overwrite(true);
            download.set_destination(&destination);
            emit(
                None,
                "download-destination",
                json!({"suggested": suggested, "destination": destination}),
            );
            true
        });
        let finished_token = token.clone();
        download.connect_finished(move |download| {
            emit(
                None,
                "download-finished",
                json!({
                    "token": finished_token,
                    "destination": download.destination().map(|value| value.to_string()),
                    "received_bytes": download.received_data_length(),
                }),
            );
        });
        let failed_token = token.clone();
        download.connect_failed(move |_download, error| {
            emit(
                None,
                "download-failed",
                json!({"token": failed_token, "error": error.to_string()}),
            );
        });
    });
    with_state(|state| state.downloads_connected = true);
}

fn teardown(state: &mut AdapterState) {
    for (_page_id, view) in state.pages.drain() {
        view.try_close();
    }
    state.page_order.clear();
    state.active_page = None;
    if let Some(window) = state.window.take() {
        window.close();
    }
    state.stack = None;
    // Dropping the hold guard lets the application loop finish.
    state.hold = None;
    state.application.quit();
}

/// Pinned engine surface that is not wired yet.
///
/// `reload` and `stop_loading` are genuinely unwired and must not be described
/// as available; they are named here because the source gate asserts the
/// pinned boundary.
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

fn emit(page_id: Option<&str>, kind: &str, payload: Value) {
    with_state(|state| state.emit_event(page_id, kind, payload));
}
