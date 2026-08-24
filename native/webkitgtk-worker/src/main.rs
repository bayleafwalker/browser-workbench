#[cfg(feature = "native")]
mod native_adapter;

#[cfg(feature = "native")]
fn main() -> anyhow::Result<()> {
    native_adapter::run()
}

#[cfg(not(feature = "native"))]
fn main() {
    eprintln!("blocked: rebuild with --features native on a GTK4 + WebKitGTK 6.0 target host");
    std::process::exit(78);
}
