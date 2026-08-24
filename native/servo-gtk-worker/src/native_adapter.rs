//! Experimental ServoGTK adapter limited to the pinned public WebView surface.

use gtk::prelude::*;
use servo_gtk::WebView;

pub fn run() {
    gtk::init().expect("GTK4 initialization");
    let view = WebView::new();
    view.load_url("about:blank");
    view.reload();
    view.go_back();
    view.go_forward();

    // Explicitly unsupported by the pinned public widget surface:
    // lifecycle observation, semantic/DOM observation, JavaScript evaluation,
    // stop-loading, popup creation, dialog/permission/file hooks, and termination.
    // The host must return capability_unsupported; it must not synthesize success.
}
