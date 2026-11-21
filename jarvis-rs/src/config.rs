use std::env;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone)]
pub struct AppPaths {
    pub workspace_root: PathBuf,
    pub jarvis_rs_dir: PathBuf,
    pub s2s_dir: PathBuf,
    pub s2s_python: PathBuf,
    pub jev_dir: PathBuf,
    pub jev_python: PathBuf,
    pub jev_bridge_script: PathBuf,
    pub python_tools_dir: PathBuf,
    pub s2s_config_yaml: PathBuf,
}

impl AppPaths {
    /// Discover workspace paths relative to an optional `--root`, `JARVIS_ROOT`, cwd, or binary path.
    pub fn discover(explicit_root: Option<&Path>) -> Result<Self, String> {
        let root = if let Some(p) = explicit_root {
            p.to_path_buf()
        } else if let Ok(p) = env::var("JARVIS_ROOT") {
            PathBuf::from(p)
        } else {
            find_workspace_root().ok_or_else(|| {
                "Could not locate workspace containing 's2s/speech-to-speech' and 'borwse harness/jev-ultrafast'. Pass --root <path>.".to_string()
            })?
        };

        let workspace_root = std::path::absolute(&root).unwrap_or(root);
        let jarvis_rs_dir = workspace_root.join("jarvis-rs");
        let s2s_dir = workspace_root.join("s2s").join("speech-to-speech");
        let jev_dir = workspace_root.join("borwse harness").join("jev-ultrafast");

        Ok(Self {
            s2s_python: venv_python(&s2s_dir),
            jev_python: venv_python(&jev_dir),
            jev_bridge_script: jarvis_rs_dir.join("python").join("jev_bridge.py"),
            python_tools_dir: jarvis_rs_dir.join("python"),
            s2s_config_yaml: jarvis_rs_dir.join("config").join("jarvis_s2s.yaml"),
            workspace_root,
            jarvis_rs_dir,
            s2s_dir,
            jev_dir,
        })
    }
}

fn venv_python(repo_dir: &Path) -> PathBuf {
    if cfg!(windows) {
        repo_dir.join(".venv").join("Scripts").join("python.exe")
    } else {
        repo_dir.join(".venv").join("bin").join("python")
    }
}

fn looks_like_workspace(dir: &Path) -> bool {
    dir.join("s2s").join("speech-to-speech").is_dir()
        && dir.join("borwse harness").join("jev-ultrafast").is_dir()
}

fn find_workspace_root() -> Option<PathBuf> {
    let mut candidates = Vec::new();
    if let Ok(cwd) = env::current_dir() {
        candidates.push(cwd);
    }
    if let Ok(exe) = env::current_exe() {
        if let Some(parent) = exe.parent() {
            candidates.push(parent.to_path_buf());
        }
    }
    for start in candidates {
        let mut cur = Some(start.as_path());
        while let Some(dir) = cur {
            if looks_like_workspace(dir) {
                return Some(dir.to_path_buf());
            }
            cur = dir.parent();
        }
    }
    None
}

/// Load `.env` files without overwriting environment variables already set in the process.
pub fn load_env_files(paths: &AppPaths) {
    for env_path in [
        paths.jarvis_rs_dir.join(".env"),
        paths.s2s_dir.join(".env"),
        paths.jev_dir.join(".env"),
    ] {
        if env_path.is_file() {
            let _ = dotenvy::from_path(&env_path);
        }
    }
}

pub fn required_env_status() -> Vec<(&'static str, bool)> {
    ["NVIDIA_API_KEY", "EXPERIENTIAL_API_KEY", "TEXT_MODEL_API_KEY"]
        .into_iter()
        .map(|name| {
            let present = env::var(name).map(|v| !v.trim().is_empty()).unwrap_or(false);
            (name, present)
        })
        .collect()
}
