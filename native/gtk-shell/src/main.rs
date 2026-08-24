#[cfg(feature = "native")]
mod native_shell;

#[cfg(feature = "native")]
fn main() {
    native_shell::run();
}

#[cfg(not(feature = "native"))]
fn main() {
    eprintln!("blocked: rebuild with --features native on a GTK4 target host");
    std::process::exit(78);
}
