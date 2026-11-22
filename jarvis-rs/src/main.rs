use clap::{Parser, Subcommand};
use jarvis::bridge::{BrowserBridge, StdioBridge};
use jarvis::broker::{Broker, TaskStatus};
use jarvis::config::{load_env_files, required_env_status, AppPaths};
use jarvis::supervisor::run_supervised;
use std::io::{self, BufRead, Write};
use std::path::PathBuf;
use std::process::{Command, ExitCode};
use tracing_subscriber::EnvFilter;

#[derive(Parser)]
#[command(name = "jarvis", about = "Voice-controlled browser agent supervisor")]
struct Cli {
    /// Workspace root containing s2s/ and borwse harness/
    #[arg(long, global = true)]
    root: Option<PathBuf>,

    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Check Python venvs, API keys, Chrome connection, and Jev bridge
    Doctor,
    /// Run one browser task headlessly through the Rust broker (no voice)
    Browse {
        #[arg(long)]
        goal: String,
        #[arg(long)]
        url: Option<String>,
        #[arg(long)]
        background: bool,
        #[arg(long)]
        keep_open: bool,
    },
    /// Run the supervised speech-to-speech + browser agent pipeline
    Run {
        #[arg(long)]
        background: bool,
    },
}

#[tokio::main]
async fn main() -> ExitCode {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .init();

    let cli = Cli::parse();
    let paths = match AppPaths::discover(cli.root.as_deref()) {
        Ok(p) => p,
        Err(msg) => {
            eprintln!("Error: {msg}");
            return ExitCode::from(2);
        }
    };
    load_env_files(&paths);

    match cli.command {
        Commands::Doctor => run_doctor(&paths).await,
        Commands::Browse {
            goal,
            url,
            background,
            keep_open,
        } => run_browse(&paths, goal, url, background, keep_open).await,
        Commands::Run { background } => match run_supervised(paths, background).await {
            Ok(()) => ExitCode::SUCCESS,
            Err(err) => {
                eprintln!("Error: {err}");
                ExitCode::FAILURE
            }
        },
    }
}

async fn run_doctor(paths: &AppPaths) -> ExitCode {
    let mut ok = true;
    println!("Workspace root: {}", paths.workspace_root.display());

    for (name, present) in required_env_status() {
        println!("env {name}: {}", if present { "set" } else { "MISSING" });
        if !present {
            ok = false;
        }
    }

    for (label, python, check_mod) in [
        ("s2s venv", &paths.s2s_python, "speech_to_speech"),
        ("jev venv", &paths.jev_python, "jev_ultrafast"),
    ] {
        if !python.is_file() {
            println!("{label}: MISSING ({})", python.display());
            ok = false;
            continue;
        }
        let status = Command::new(python)
            .args(["-c", &format!("import {check_mod}")])
            .output();
        match status {
            Ok(out) if out.status.success() => println!("{label}: ok"),
            Ok(out) => {
                println!(
                    "{label}: import {check_mod} failed: {}",
                    String::from_utf8_lossy(&out.stderr).trim()
                );
                ok = false;
            }
            Err(e) => {
                println!("{label}: failed to execute: {e}");
                ok = false;
            }
        }
    }

    if paths.s2s_python.is_file() {
        let pythonpath = jarvis::supervisor::build_pythonpath(&paths.python_tools_dir);
        let cfg_status = Command::new(&paths.s2s_python)
            .env("PYTHONPATH", &pythonpath)
            .args([
                "-c",
                "import sys; from pathlib import Path; \
                 from speech_to_speech.config import load_config, resolve_config; \
                 from speech_to_speech.VAD.vad_iterator import find_silero_onnx_path; \
                 resolve_config(load_config(Path(sys.argv[1]))); \
                 import llm_rs, tool_call_rs, stt_rs, tts_rs; \
                 onnx = find_silero_onnx_path(); \
                 print('ONNX=' + str(onnx or 'missing'))",
                &paths.s2s_config_yaml.to_string_lossy(),
            ])
            .output();
        match cfg_status {
            Ok(out) if out.status.success() => {
                let stdout = String::from_utf8_lossy(&out.stdout);
                println!("s2s config + PyO3 crates: ok ({})", stdout.trim());
            }
            Ok(out) => {
                println!(
                    "s2s config/PyO3 check FAILED: {}",
                    String::from_utf8_lossy(&out.stderr).trim()
                );
                ok = false;
            }
            Err(e) => {
                println!("s2s config/PyO3 check failed to execute: {e}");
                ok = false;
            }
        }
    }

    match std::net::TcpListener::bind("127.0.0.1:8765") {
        Ok(listener) => {
            drop(listener);
            println!("port 127.0.0.1:8765: available");
        }
        Err(e) => {
            println!("port 127.0.0.1:8765: IN USE ({e})");
            ok = false;
        }
    }

    if paths.jev_python.is_file() {
        let bh = Command::new(&paths.jev_python)
            .args(["-m", "browser_harness.run", "--doctor"])
            .current_dir(&paths.jev_dir)
            .output();
        match bh {
            Ok(out) => {
                let stdout = String::from_utf8_lossy(&out.stdout);
                let stderr = String::from_utf8_lossy(&out.stderr);
                if !stdout.trim().is_empty() {
                    println!("{}", stdout.trim());
                }
                if !stderr.trim().is_empty() {
                    println!("{}", stderr.trim());
                }
                if !out.status.success() {
                    let only_expected_offline = stdout
                        .lines()
                        .filter(|line| line.contains("[FAIL]"))
                        .all(|line| {
                            line.contains("chrome running")
                                || line.contains("daemon alive")
                                || line.contains("active browser connections")
                                || line.contains("Browser Use cloud auth")
                        });
                    if only_expected_offline && stdout.contains("[FAIL]") {
                        println!(
                            "[INFO] Chrome/daemon offline right now (jarvis run auto-launches when needed)"
                        );
                    } else {
                        ok = false;
                    }
                }
            }
            Err(e) => {
                println!("browser-harness --doctor failed: {e}");
                ok = false;
            }
        }
    }

    let bridge = StdioBridge::new(
        paths.jev_python.clone(),
        paths.jev_bridge_script.clone(),
        paths.jev_dir.clone(),
    );
    match bridge.ping().await {
        Ok(pid) => println!("jev_bridge ping: ok (pid={pid})"),
        Err(e) => {
            println!("jev_bridge ping: FAILED ({e})");
            ok = false;
        }
    }
    let _ = bridge.close().await;

    if ok {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

async fn run_browse(
    paths: &AppPaths,
    goal: String,
    url: Option<String>,
    background: bool,
    keep_open: bool,
) -> ExitCode {
    let bridge = StdioBridge::new(
        paths.jev_python.clone(),
        paths.jev_bridge_script.clone(),
        paths.jev_dir.clone(),
    );
    let broker = Broker::new(background);
    let mut outcome = match broker.start_task(&bridge, goal, url).await {
        Ok(o) => o,
        Err(e) => {
            eprintln!("Error: {e}");
            if !keep_open {
                let _ = bridge.close().await;
            }
            return ExitCode::FAILURE;
        }
    };

    while outcome.status == TaskStatus::NeedsConfirmation {
        let action = outcome
            .pending_action
            .as_deref()
            .unwrap_or("unknown action");
        print!("Confirm risky action '{action}'? [y/N]: ");
        let _ = io::stdout().flush();
        let mut line = String::new();
        let read_ok = io::stdin().lock().read_line(&mut line).is_ok();
        let approve = read_ok && matches!(line.trim().to_ascii_lowercase().as_str(), "y" | "yes");
        match broker.confirm_task(&bridge, approve).await {
            Ok(next) => outcome = next,
            Err(e) => {
                eprintln!("Error: {e}");
                if !keep_open {
                    let _ = bridge.close().await;
                }
                return ExitCode::FAILURE;
            }
        }
    }

    println!(
        "{}",
        serde_json::to_string_pretty(&outcome).unwrap_or_else(|_| format!("{outcome:?}"))
    );

    if !keep_open {
        let _ = bridge.close().await;
    }
    if outcome.status == TaskStatus::Done {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}
