#[cfg(feature = "native")]
mod native_adapter;

#[cfg(feature = "native")]
fn main() {
    native_adapter::run();
}

#[cfg(not(feature = "native"))]
fn main() {
    eprintln!("blocked: ServoGTK is an experimental, non-gating source lane; rebuild on its pinned target host");
    std::process::exit(78);
}
