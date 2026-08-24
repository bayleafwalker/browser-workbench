use gtk::prelude::*;
use gtk::{
    Application, ApplicationWindow, Box as GtkBox, Button, Entry, HeaderBar, Label, Orientation,
    Stack, StackSwitcher,
};

pub fn run() {
    let app = Application::builder()
        .application_id("dev.browserworkbench.Shell")
        .build();
    app.connect_activate(build_window);
    app.run();
}

fn build_window(app: &Application) {
    let header = HeaderBar::new();
    let back = Button::with_label("Back");
    let forward = Button::with_label("Forward");
    let reload = Button::with_label("Reload");
    let location = Entry::builder()
        .hexpand(true)
        .placeholder_text("Address or workbench command")
        .build();
    header.pack_start(&back);
    header.pack_start(&forward);
    header.pack_start(&reload);
    header.set_title_widget(Some(&location));

    let stack = Stack::builder().hexpand(true).vexpand(true).build();
    stack.add_titled(
        &Label::new(Some("Adapter view attaches here")),
        Some("page-1"),
        "New tab",
    );
    let switcher = StackSwitcher::builder().stack(&stack).build();
    let status = Label::new(Some("No adapter connected · single-writer lease unclaimed"));
    let takeover = Button::with_label("Request takeover");
    let evidence = Button::with_label("Evidence");
    let footer = GtkBox::new(Orientation::Horizontal, 8);
    footer.append(&status);
    footer.append(&takeover);
    footer.append(&evidence);

    let root = GtkBox::new(Orientation::Vertical, 0);
    root.append(&switcher);
    root.append(&stack);
    root.append(&footer);
    let window = ApplicationWindow::builder()
        .application(app)
        .title("Browser Workbench")
        .default_width(1200)
        .default_height(800)
        .titlebar(&header)
        .child(&root)
        .build();
    window.present();
}
