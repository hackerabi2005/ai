use crate::api::{bind_loopback, build_router, ApiState};
use crate::bridge::{BrowserBridge, StdioBridge};
use crate::broker::{AgentEvent, Broker};
use crate::config::{required_env_status, AppPaths};
use crate::narrator::{run_narrator, HttpSaySink};
use http_body_util::{BodyExt, Empty};
use hyper::body::Bytes;
use hyper::{Method, Request};
use hyper_util::rt::TokioIo;
use serde_json::Value;
use std::env;
use std::ffi::OsString;
use std::path::Path;
use std::process::Stdio;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::net::TcpStream;
use tokio::process::Command;
use tokio::sync::{mpsc, oneshot, watch};
use tracing::{error, info, warn};
use uuid::Uuid;

const MAX_S2S_RESTARTS: usize = 3;
const S2S_ADDR: &str = "127.0.0.1:8765";

pub fn build_pythonpath(tools_dir: &Path) -> OsString {
    let mut paths = vec![tools_dir.to_path_buf()];
    if let Some(repo_root) = tools_dir.parent().and_then(|p| p.parent()) {
        for crate_name in [
            "jev-ultrafast-rs",
            "python-rs",
            "tool-call-rs",
            "utils-rs",
            "stt-rs",
            "llm-rs",
            "tts-rs",
            "pipeline-rs",
            "speech-languages-rs",
        ] {
            let py_dir = repo_root.join("rust").join(crate_name).join("python");
            if py_dir.is_dir() {
                paths.push(py_dir);
            }
        }
    }
    if let Some(existing) = env::var_os("PYTHONPATH") {
        paths.extend(env::split_paths(&existing));
    }
    env::join_paths(paths).unwrap_or_else(|_| tools_dir.as_os_str().to_os_string())
}

pub fn preflight_check(paths: &AppPaths) -> Result<(), String> {
    let mut missing = Vec::new();
    for (name, present) in required_env_status() {
        if !present {
            missing.push(name);
        }
    }
    if !missing.is_empty() {
        return Err(format!(
            "Missing required API key environment variable(s): {}. Put them in jarvis-rs/.env or the repo .env files.",
            missing.join(", ")
        ));
    }
    for (label, path) in [
        ("s2s Python venv", &paths.s2s_python),
        ("jev Python venv", &paths.jev_python),
        ("jev_bridge.py", &paths.jev_bridge_script),
        ("jarvis_tools.py", &paths.python_tools_dir.join("jarvis_tools.py")),
        ("jarvis_s2s.yaml", &paths.s2s_config_yaml),
    ] {
        if !path.is_file() {
            return Err(format!("Missing {label} at {}", path.display()));
        }
    }
    Ok(())
}

async fn s2s_session_active(addr: &str) -> bool {
    let Ok(stream) = TcpStream::connect(addr).await else {
        return false;
    };
    let io = TokioIo::new(stream);
    let Ok((mut sender, conn)) = hyper::client::conn::http1::handshake(io).await else {
        return false;
    };
    tokio::spawn(async move {
        let _ = conn.await;
    });
    let Ok(req) = Request::builder()
        .method(Method::GET)
        .uri("/v1/pool")
        .header("Host", addr)
        .body(Empty::<Bytes>::new())
    else {
        return false;
    };
    let Ok(Ok(resp)) = tokio::time::timeout(Duration::from_secs(2), sender.send_request(req)).await
    else {
        return false;
    };
    if !resp.status().is_success() {
        return false;
    }
    let Ok(bytes) = resp.into_body().collect().await else {
        return false;
    };
    let Ok(val) = serde_json::from_slice::<Value>(&bytes.to_bytes()) else {
        return false;
    };
    val.get("in_use").and_then(Value::as_u64).unwrap_or(0) >= 1
}

async fn announce_when_ready(
    addr: String,
    events_tx: mpsc::UnboundedSender<AgentEvent>,
    mut quit_rx: watch::Receiver<bool>,
) {
    for _ in 0..600 {
        if *quit_rx.borrow() {
            return;
        }
        if s2s_session_active(&addr).await {
            // Brief grace for WASAPI audio stream startup before speaking Ready.
            tokio::time::sleep(Duration::from_millis(250)).await;
            if !*quit_rx.borrow() {
                let _ = events_tx.send(AgentEvent::Ready);
            }
            return;
        }
        tokio::select! {
            _ = tokio::time::sleep(Duration::from_millis(100)) => {}
            _ = quit_rx.changed() => {
                if *quit_rx.borrow() {
                    return;
                }
            }
        }
    }
}

async fn wait_for_quit(quit_rx: &mut watch::Receiver<bool>) {
    while !*quit_rx.borrow() {
        if quit_rx.changed().await.is_err() {
            std::future::pending::<()>().await;
        }
    }
}

pub async fn run_supervised(paths: AppPaths, background: bool) -> Result<(), String> {
    preflight_check(&paths)?;

    if matches!(
        tokio::time::timeout(Duration::from_millis(300), TcpStream::connect(S2S_ADDR)).await,
        Ok(Ok(_))
    ) {
        return Err(format!(
            "Port {S2S_ADDR} is already in use; stop any running s2s or jarvis instance first."
        ));
    }

    let token = Arc::new(Uuid::new_v4().to_string());
    let (listener, addr) = bind_loopback(0).await?;
    let api_url = format!("http://{addr}");

    let (events_tx, events_rx) = mpsc::unbounded_channel();
    let (quit_tx, mut quit_rx) = watch::channel(false);

    let bridge = Arc::new(StdioBridge::new(
        paths.jev_python.clone(),
        paths.jev_bridge_script.clone(),
        paths.jev_dir.clone(),
    ));
    let broker = Arc::new(Broker::with_events(background, events_tx.clone()));

    let state = ApiState {
        broker: broker.clone(),
        bridge: bridge.clone(),
        token: token.clone(),
        quit_tx: Some(quit_tx),
        chat_window_until: Arc::new(tokio::sync::Mutex::new(None)),
    };
    let app = build_router(state);

    let (shutdown_tx, shutdown_rx) = oneshot::channel::<()>();
    let server_handle = tokio::spawn(async move {
        let server = axum::serve(listener, app).with_graceful_shutdown(async move {
            let _ = shutdown_rx.await;
        });
        if let Err(err) = server.await {
            error!("Loopback API server error: {err}");
        }
    });

    let narrator_handle = tokio::spawn(run_narrator(
        events_rx,
        Arc::new(HttpSaySink::new(S2S_ADDR, token.as_str())),
    ));

    info!("Jarvis loopback tool API listening on {api_url}");

    // Ping the browser bridge eagerly so a missing jev dependency fails early.
    if let Err(err) = bridge.ping().await {
        drop(events_tx);
        let _ = narrator_handle.await;
        let _ = shutdown_tx.send(());
        let _ = server_handle.await;
        return Err(format!("Browser bridge failed startup check: {err}"));
    }

    // Pre-connect browser-harness daemon in the background so voice starts immediately
    // without blocking on Chrome's "Allow remote debugging?" prompt.
    let warm_bridge = bridge.clone();
    let warm_broker = broker.clone();
    tokio::spawn(async move {
        info!("Checking Chrome remote debugging connection...");
        match warm_bridge.warm_browser().await {
            Ok(url) => {
                if let Some(ref u) = url {
                    warm_broker.record_initial_url(u).await;
                    info!("Chrome remote debugging connected (active tab: {u}).");
                } else {
                    info!("Chrome remote debugging connected.");
                }
            }
            Err(err) => {
                warn!("Chrome is not connected yet ({err}); voice chat still works, open Chrome before browsing.");
            }
        }
    });

    let pythonpath = build_pythonpath(&paths.python_tools_dir);
    let mut restarts = 0usize;

    loop {
        let started = Instant::now();
        info!("Starting speech-to-speech voice pipeline...");
        let mut child = Command::new(&paths.s2s_python)
            .arg("-m")
            .arg("speech_to_speech.cli")
            .arg("local")
            .arg("-f")
            .arg(&paths.s2s_config_yaml)
            .current_dir(&paths.s2s_dir)
            .env("JARVIS_API_URL", &api_url)
            .env("JARVIS_API_TOKEN", token.as_str())
            .env("JARVIS_BROWSER_BACKGROUND", if background { "1" } else { "0" })
            .env("PYTHONPATH", &pythonpath)
            .stdin(Stdio::inherit())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .kill_on_drop(true)
            .spawn()
            .map_err(|e| format!("Failed to spawn speech-to-speech: {e}"))?;

        let ready_handle = tokio::spawn(announce_when_ready(
            S2S_ADDR.to_string(),
            events_tx.clone(),
            quit_rx.clone(),
        ));

        enum StopTrigger {
            ChildExited(std::io::Result<std::process::ExitStatus>),
            CtrlC,
            VoiceQuit,
        }

        let trigger = tokio::select! {
            status = child.wait() => StopTrigger::ChildExited(status),
            _ = tokio::signal::ctrl_c() => StopTrigger::CtrlC,
            _ = wait_for_quit(&mut quit_rx) => StopTrigger::VoiceQuit,
        };
        ready_handle.abort();

        match trigger {
            StopTrigger::CtrlC => {
                info!("Ctrl+C received, shutting down Jarvis...");
                broker.request_stop();
                let _ = child.start_kill();
                let _ = tokio::time::timeout(Duration::from_secs(3), child.wait()).await;
                break;
            }
            StopTrigger::VoiceQuit => {
                info!("Voice quit requested, waiting briefly for Goodbye audio...");
                tokio::time::sleep(Duration::from_millis(1400)).await;
                let _ = child.start_kill();
                let _ = tokio::time::timeout(Duration::from_secs(3), child.wait()).await;
                break;
            }
            StopTrigger::ChildExited(Ok(status)) if status.success() => {
                info!("speech-to-speech exited cleanly.");
                break;
            }
            StopTrigger::ChildExited(Ok(status)) => {
                let code = status.code().unwrap_or(-1);
                if code == 2 {
                    let _ = bridge.close().await;
                    let _ = shutdown_tx.send(());
                    let _ = server_handle.await;
                    drop(events_tx);
                    let _ = narrator_handle.await;
                    return Err(
                        "speech-to-speech exited with configuration error (code 2).".to_string(),
                    );
                }
                if started.elapsed() > Duration::from_secs(60) {
                    restarts = 0;
                }
                restarts += 1;
                if restarts > MAX_S2S_RESTARTS {
                    let _ = bridge.close().await;
                    let _ = shutdown_tx.send(());
                    let _ = server_handle.await;
                    drop(events_tx);
                    let _ = narrator_handle.await;
                    return Err(format!(
                        "speech-to-speech crashed repeatedly (last exit code {code}); giving up."
                    ));
                }
                warn!("speech-to-speech exited with code {code}; restarting ({restarts}/{MAX_S2S_RESTARTS})...");
                tokio::time::sleep(Duration::from_secs(2)).await;
            }
            StopTrigger::ChildExited(Err(err)) => {
                error!("Failed waiting on speech-to-speech: {err}");
                break;
            }
        }
    }

    let _ = bridge.close().await;
    let _ = shutdown_tx.send(());
    let _ = server_handle.await;
    drop(events_tx);
    let _ = tokio::time::timeout(Duration::from_secs(2), narrator_handle).await;
    Ok(())
}
