use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::future::Future;
use std::path::PathBuf;
use std::pin::Pin;
use std::process::Stdio;
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader, BufWriter};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};
use tokio::sync::Mutex;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct PageSummary {
    pub url: String,
    pub title: String,
    pub text: String,
    pub fingerprint: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PredictResult {
    pub status: String,
    pub choice: String,
    pub operation: String,
    pub kind: String,
    pub action_label: String,
    #[serde(default)]
    pub role: Option<String>,
    #[serde(default)]
    pub target: Option<String>,
    pub confidence: f64,
    pub fingerprint: String,
    pub history_len: usize,
    pub decision_count: usize,
    pub page: PageSummary,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LastAction {
    #[serde(default)]
    pub action: String,
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
    pub text: Option<String>,
    #[serde(default)]
    pub page_changed: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ActResult {
    pub stale: bool,
    pub executed: bool,
    pub status: String,
    pub history_len: usize,
    pub decision_count: usize,
    pub page: PageSummary,
    #[serde(default)]
    pub last_action: Option<LastAction>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadPageResult {
    pub page: PageSummary,
    #[serde(default)]
    pub elements: Vec<Value>,
    #[serde(default)]
    pub omitted_elements: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MatchClickResult {
    pub matched: bool,
    #[serde(default)]
    pub choice: String,
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
    pub action_label: String,
    #[serde(default)]
    pub fingerprint: String,
    pub page: PageSummary,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ControlResult {
    pub action: String,
    #[serde(default)]
    pub closed: bool,
    #[serde(default)]
    pub page: Option<PageSummary>,
    #[serde(default)]
    pub message: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BridgeError {
    pub code: String,
    pub message: String,
}

impl std::fmt::Display for BridgeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl std::error::Error for BridgeError {}

impl BridgeError {
    pub fn new(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
        }
    }
}

pub type BoxFuture<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>;

pub trait BrowserBridge: Send + Sync {
    fn open(
        &self,
        goal: String,
        url: Option<String>,
        background: bool,
    ) -> BoxFuture<'_, Result<PageSummary, BridgeError>>;
    fn open_with_tab(
        &self,
        goal: String,
        url: Option<String>,
        background: bool,
        _new_tab: bool,
    ) -> BoxFuture<'_, Result<PageSummary, BridgeError>> {
        self.open(goal, url, background)
    }
    fn open_fast(
        &self,
        goal: String,
        url: String,
        background: bool,
        _new_tab: bool,
    ) -> BoxFuture<'_, Result<PageSummary, BridgeError>> {
        self.open(goal, Some(url), background)
    }
    fn predict(&self) -> BoxFuture<'_, Result<PredictResult, BridgeError>>;
    fn act(&self, fingerprint: String) -> BoxFuture<'_, Result<ActResult, BridgeError>>;
    fn cancel(&self) -> BoxFuture<'_, Result<Option<PageSummary>, BridgeError>>;
    fn read_page(&self) -> BoxFuture<'_, Result<ReadPageResult, BridgeError>>;
    fn match_click(&self, _target: String) -> BoxFuture<'_, Result<MatchClickResult, BridgeError>> {
        Box::pin(async move {
            Ok(MatchClickResult {
                matched: false,
                choice: String::new(),
                kind: String::new(),
                action_label: String::new(),
                fingerprint: String::new(),
                page: PageSummary {
                    url: String::new(),
                    title: String::new(),
                    text: String::new(),
                    fingerprint: String::new(),
                },
            })
        })
    }
    fn control(&self, action: String) -> BoxFuture<'_, Result<ControlResult, BridgeError>>;
    fn close(&self) -> BoxFuture<'_, Result<(), BridgeError>>;
}

struct ChildConn {
    child: Child,
    stdin: BufWriter<ChildStdin>,
    stdout: BufReader<ChildStdout>,
    next_id: u64,
}

pub struct StdioBridge {
    python: PathBuf,
    script: PathBuf,
    work_dir: PathBuf,
    timeout: Duration,
    conn: Mutex<Option<ChildConn>>,
}

impl StdioBridge {
    pub fn new(python: PathBuf, script: PathBuf, work_dir: PathBuf) -> Self {
        Self {
            python,
            script,
            work_dir,
            timeout: Duration::from_secs(90),
            conn: Mutex::new(None),
        }
    }

    pub fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self
    }

    fn spawn(&self) -> Result<ChildConn, BridgeError> {
        let mut cmd = Command::new(&self.python);
        if let Some(repo_root) = self.script.parent().and_then(|p| p.parent()).and_then(|p| p.parent()) {
            let mut py_paths = Vec::new();
            for crate_name in ["jev-ultrafast-rs", "python-rs"] {
                let d = repo_root.join("rust").join(crate_name).join("python");
                if d.is_dir() {
                    py_paths.push(d);
                }
            }
            if let Some(existing) = std::env::var_os("PYTHONPATH") {
                py_paths.extend(std::env::split_paths(&existing));
            }
            if !py_paths.is_empty() {
                if let Ok(joined) = std::env::join_paths(py_paths) {
                    cmd.env("PYTHONPATH", joined);
                }
            }
        }
        cmd.arg("-u")
            .arg(&self.script)
            .current_dir(&self.work_dir)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .kill_on_drop(true);

        let mut child = cmd
            .spawn()
            .map_err(|e| BridgeError::new("spawn_failed", format!("Failed to spawn jev_bridge: {e}")))?;

        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| BridgeError::new("spawn_failed", "Bridge stdin missing"))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| BridgeError::new("spawn_failed", "Bridge stdout missing"))?;

        Ok(ChildConn {
            child,
            stdin: BufWriter::new(stdin),
            stdout: BufReader::new(stdout),
            next_id: 1,
        })
    }

    async fn call_raw(&self, mut payload: Value) -> Result<Value, BridgeError> {
        let mut guard = self.conn.lock().await;
        if guard.is_none() {
            *guard = Some(self.spawn()?);
        }
        let conn = guard.as_mut().expect("spawned above");
        let req_id = conn.next_id;
        conn.next_id += 1;
        payload["id"] = json!(req_id);

        let line = serde_json::to_string(&payload)
            .map_err(|e| BridgeError::new("encode_error", e.to_string()))?;

        let io_res: Result<Value, BridgeError> = match tokio::time::timeout(self.timeout, async {
            conn.stdin
                .write_all(line.as_bytes())
                .await
                .map_err(|e| BridgeError::new("bridge_io", format!("Write to bridge failed: {e}")))?;
            conn.stdin
                .write_all(b"\n")
                .await
                .map_err(|e| BridgeError::new("bridge_io", format!("Write newline failed: {e}")))?;
            conn.stdin
                .flush()
                .await
                .map_err(|e| BridgeError::new("bridge_io", format!("Flush to bridge failed: {e}")))?;

            let mut resp_line = String::new();
            let n = conn
                .stdout
                .read_line(&mut resp_line)
                .await
                .map_err(|e| BridgeError::new("bridge_io", format!("Read from bridge failed: {e}")))?;
            if n == 0 {
                return Err(BridgeError::new(
                    "bridge_crashed",
                    "Browser bridge process exited unexpectedly",
                ));
            }
            let val: Value = serde_json::from_str(resp_line.trim()).map_err(|e| {
                BridgeError::new("invalid_response", format!("Invalid JSON from bridge: {e}"))
            })?;
            Ok(val)
        })
        .await
        {
            Ok(res) => res,
            Err(_) => Err(BridgeError::new("bridge_timeout", "Browser bridge timed out")),
        };

        let val = match io_res {
            Ok(v) => v,
            Err(err) => {
                // Drop and kill potentially desynchronized, timed-out, or dead child process.
                if let Some(mut dead) = guard.take() {
                    let _ = dead.child.start_kill();
                }
                return Err(err);
            }
        };

        if val.get("id").and_then(Value::as_u64) != Some(req_id) {
            if let Some(mut dead) = guard.take() {
                let _ = dead.child.start_kill();
            }
            return Err(BridgeError::new(
                "protocol_mismatch",
                "Bridge response id did not match request",
            ));
        }

        if val.get("ok").and_then(Value::as_bool) != Some(true) {
            let code = val
                .get("code")
                .and_then(Value::as_str)
                .unwrap_or("bridge_error");
            let msg = val
                .get("error")
                .and_then(Value::as_str)
                .unwrap_or("Unknown bridge error");
            return Err(BridgeError::new(code, msg));
        }

        Ok(val)
    }

    pub async fn ping(&self) -> Result<u64, BridgeError> {
        let val = self.call_raw(json!({"cmd": "ping"})).await?;
        Ok(val.get("pid").and_then(Value::as_u64).unwrap_or(0))
    }

    pub async fn warm_browser(&self) -> Result<Option<String>, BridgeError> {
        let val = self.call_raw(json!({"cmd": "warm_browser"})).await?;
        let url = val
            .get("url")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|s| !s.is_empty() && *s != "about:blank")
            .map(ToOwned::to_owned);
        Ok(url)
    }
}

impl BrowserBridge for StdioBridge {
    fn open(
        &self,
        goal: String,
        url: Option<String>,
        background: bool,
    ) -> BoxFuture<'_, Result<PageSummary, BridgeError>> {
        self.open_with_tab(goal, url, background, false)
    }

    fn open_with_tab(
        &self,
        goal: String,
        url: Option<String>,
        background: bool,
        new_tab: bool,
    ) -> BoxFuture<'_, Result<PageSummary, BridgeError>> {
        Box::pin(async move {
            let val = self
                .call_raw(json!({
                    "cmd": "open",
                    "goal": goal,
                    "url": url,
                    "background": background,
                    "new_tab": new_tab,
                }))
                .await?;
            serde_json::from_value(val["page"].clone())
                .map_err(|e| BridgeError::new("invalid_response", e.to_string()))
        })
    }

    fn open_fast(
        &self,
        goal: String,
        url: String,
        background: bool,
        new_tab: bool,
    ) -> BoxFuture<'_, Result<PageSummary, BridgeError>> {
        Box::pin(async move {
            let val = self
                .call_raw(json!({
                    "cmd": "open",
                    "goal": goal,
                    "url": Some(url),
                    "background": background,
                    "skip_observe": true,
                    "new_tab": new_tab,
                }))
                .await?;
            serde_json::from_value(val["page"].clone())
                .map_err(|e| BridgeError::new("invalid_response", e.to_string()))
        })
    }

    fn predict(&self) -> BoxFuture<'_, Result<PredictResult, BridgeError>> {
        Box::pin(async move {
            let val = self.call_raw(json!({"cmd": "predict"})).await?;
            serde_json::from_value(val)
                .map_err(|e| BridgeError::new("invalid_response", e.to_string()))
        })
    }

    fn act(&self, fingerprint: String) -> BoxFuture<'_, Result<ActResult, BridgeError>> {
        Box::pin(async move {
            let val = self
                .call_raw(json!({"cmd": "act", "fingerprint": fingerprint}))
                .await?;
            serde_json::from_value(val)
                .map_err(|e| BridgeError::new("invalid_response", e.to_string()))
        })
    }

    fn cancel(&self) -> BoxFuture<'_, Result<Option<PageSummary>, BridgeError>> {
        Box::pin(async move {
            let val = self.call_raw(json!({"cmd": "cancel"})).await?;
            if val["page"].is_null() {
                Ok(None)
            } else {
                serde_json::from_value(val["page"].clone())
                    .map(Some)
                    .map_err(|e| BridgeError::new("invalid_response", e.to_string()))
            }
        })
    }

    fn read_page(&self) -> BoxFuture<'_, Result<ReadPageResult, BridgeError>> {
        Box::pin(async move {
            let val = self.call_raw(json!({"cmd": "read_page"})).await?;
            serde_json::from_value(val)
                .map_err(|e| BridgeError::new("invalid_response", e.to_string()))
        })
    }

    fn match_click(&self, target: String) -> BoxFuture<'_, Result<MatchClickResult, BridgeError>> {
        Box::pin(async move {
            let val = self
                .call_raw(json!({"cmd": "match_click", "target": target}))
                .await?;
            serde_json::from_value(val)
                .map_err(|e| BridgeError::new("invalid_response", e.to_string()))
        })
    }

    fn control(&self, action: String) -> BoxFuture<'_, Result<ControlResult, BridgeError>> {
        Box::pin(async move {
            let val = self
                .call_raw(json!({"cmd": "control", "action": action}))
                .await?;
            serde_json::from_value(val)
                .map_err(|e| BridgeError::new("invalid_response", e.to_string()))
        })
    }

    fn close(&self) -> BoxFuture<'_, Result<(), BridgeError>> {
        Box::pin(async move {
            let has_child = self.conn.lock().await.is_some();
            if !has_child {
                return Ok(());
            }
            let _ = self.call_raw(json!({"cmd": "close"})).await;
            let mut guard = self.conn.lock().await;
            if let Some(mut conn) = guard.take() {
                let _ = tokio::time::timeout(Duration::from_secs(2), conn.child.wait()).await;
                let _ = conn.child.start_kill();
            }
            Ok(())
        })
    }
}
