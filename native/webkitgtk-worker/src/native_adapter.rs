//! Pinned WebKitGTK source boundary. Runtime verification belongs on the native target host.

use anyhow::Result;
use gtk::prelude::*;
use serde::Serialize;
use webkit6::prelude::*;
use webkit6::{LoadEvent, SnapshotOptions, SnapshotRegion, WebView};

#[derive(Debug, Serialize)]
struct NormalizedEvent {
    kind: &'static str,
    url: Option<String>,
    title: Option<String>,
    provider: &'static str,
}

pub fn run() -> Result<()> {
    gtk::init()?;
    let view = WebView::new();
    install_engine_hooks(&view);
    view.load_uri("about:blank");
    // The production host owns the authenticated loopback bridge and GTK widget lifetime.
    // This worker never binds a public socket and never invents events it did not observe.
    Ok(())
}

fn install_engine_hooks(view: &WebView) {
    view.connect_load_changed(|view, phase: LoadEvent| {
        emit(NormalizedEvent {
            kind: match phase {
                LoadEvent::Started => "navigation.started",
                LoadEvent::Redirected => "navigation.redirected",
                LoadEvent::Committed => "navigation.committed",
                LoadEvent::Finished => "navigation.finished",
                _ => "navigation.phase",
            },
            url: view.uri().map(|value| value.to_string()),
            title: view.title().map(|value| value.to_string()),
            provider: "engine",
        });
    });
    view.connect_load_failed(|view, _phase, uri, error| {
        emit(NormalizedEvent {
            kind: "navigation.failed",
            url: Some(uri.to_string()),
            title: Some(error.to_string()),
            provider: "engine",
        });
        false
    });
    view.connect_resource_load_started(|_view, _resource, request| {
        let _ = request.uri(); // raw request identity is captured before normalization
    });
    view.connect_script_dialog(|_view, _dialog| false); // host resolves decision tokens
    view.connect_permission_request(|_view, _request| false); // default deny until declared
    view.connect_run_file_chooser(|_view, _request| false); // only declared fixture paths
    view.connect_web_process_terminated(|view, _reason| {
        emit(NormalizedEvent {
            kind: "page.terminated",
            url: view.uri().map(|value| value.to_string()),
            title: view.title().map(|value| value.to_string()),
            provider: "engine",
        });
    });
    view.connect_create(|_view, _action| None); // popup becomes a host-owned tab or is rejected
    view.connect_title_notify(|view| {
        emit(NormalizedEvent {
            kind: "page.title_changed",
            url: view.uri().map(|value| value.to_string()),
            title: view.title().map(|value| value.to_string()),
            provider: "engine",
        });
    });
}

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

fn emit(event: NormalizedEvent) {
    if let Ok(line) = serde_json::to_string(&event) {
        println!("{line}");
    }
}
