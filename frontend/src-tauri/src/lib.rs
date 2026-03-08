use log::{error, info, warn};
use std::sync::Mutex;
use std::time::Duration;
use tauri::Emitter;
use tauri::Manager;
use tauri_plugin_shell::ShellExt;

/// State to hold the sidecar child process for cleanup on exit.
struct SidecarState {
    child: Option<tauri_plugin_shell::process::CommandChild>,
}

/// Poll the backend /health endpoint until it responds or we time out.
async fn wait_for_backend(max_retries: u32, delay_ms: u64) -> bool {
    let client = reqwest::Client::new();
    for i in 0..max_retries {
        match client.get("http://127.0.0.1:8420/health").send().await {
            Ok(resp) if resp.status().is_success() => {
                info!("Backend health check passed on attempt {}", i + 1);
                return true;
            }
            Ok(resp) => {
                warn!("Backend returned status {} on attempt {}", resp.status(), i + 1);
            }
            Err(_) => {
                // Backend not ready yet
            }
        }
        tokio::time::sleep(Duration::from_millis(delay_ms)).await;
    }
    false
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_log::Builder::default().build())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(Mutex::new(SidecarState { child: None }))
        .setup(|app| {
            let handle = app.handle().clone();

            // Spawn the Python backend sidecar with parent PID for watchdog
            let sidecar_command = app
                .shell()
                .sidecar("rekordbot-server")
                .unwrap()
                .args(["--parent-pid", &std::process::id().to_string()]);
            let (mut rx, child) = sidecar_command.spawn().unwrap_or_else(|e| {
                panic!("Failed to spawn sidecar: {}", e);
            });

            info!("Sidecar spawned (pid: {})", child.pid());

            // Store the child process for cleanup
            let state = app.state::<Mutex<SidecarState>>();
            state.lock().unwrap().child = Some(child);

            // Forward sidecar stdout/stderr to logs
            tauri::async_runtime::spawn(async move {
                use tauri_plugin_shell::process::CommandEvent;
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            info!("[sidecar] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Stderr(line) => {
                            warn!("[sidecar] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Terminated(payload) => {
                            info!("Sidecar terminated: {:?}", payload);
                            break;
                        }
                        CommandEvent::Error(err) => {
                            error!("Sidecar error: {}", err);
                            break;
                        }
                        _ => {}
                    }
                }
            });

            // Poll health endpoint and emit event when ready
            tauri::async_runtime::spawn(async move {
                if wait_for_backend(30, 500).await {
                    info!("Backend is ready");
                    let _ = handle.emit("backend-ready", true);
                } else {
                    error!("Backend failed to start within timeout");
                    let _ = handle.emit("backend-ready", false);
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                info!("Window close requested — killing sidecar");
                let state = window.state::<Mutex<SidecarState>>();
                let mut guard = state.lock().unwrap();
                if let Some(child) = guard.child.take() {
                    let _ = child.kill();
                    info!("Sidecar kill signal sent");
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
