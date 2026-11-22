use crate::bridge::{BridgeError, BrowserBridge, ControlResult, PageSummary, PredictResult, ReadPageResult};
use crate::narrator::friendly_site_name;
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, LazyLock};
use tokio::sync::{mpsc, Mutex};

pub const MAX_ACTIONS: usize = 60;
pub const MAX_DECISIONS: usize = 120;

static RISKY_LABEL_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)\b(pay|buy|purchase|place\s+order|checkout|submit|send|delete|remove|confirm)\b")
        .expect("valid risky-label regex")
});

pub fn is_risky_action(kind: &str, label: &str) -> bool {
    matches!(kind, "click" | "select") && RISKY_LABEL_RE.is_match(label)
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AgentEvent {
    Ready,
    TaskAccepted { ack: String },
    PageLoaded { url: String, title: String },
    TextTyped { field: String, value: Option<String> },
    NeedsConfirmation { action: String },
    Done { url: String, title: String },
    Blocked { reason: String },
    Stopped,
    Error { code: String, message: String },
    Say { text: String, interrupt: bool },
    Silence,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TaskStatus {
    Done,
    Blocked,
    Stopped,
    NeedsConfirmation,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TaskOutcome {
    pub status: TaskStatus,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pending_action: Option<String>,
    pub steps: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub page: Option<PageSummary>,
    pub history_tail: Vec<String>,
}

#[derive(Debug, Clone)]
enum BrokerPhase {
    Idle,
    Running { narrate: bool },
    NeedsConfirmation(Box<PendingConfirmation>),
}

#[derive(Debug, Clone)]
pub struct PendingConfirmation {
    pub fingerprint: String,
    pub action_label: String,
    pub kind: String,
    pub steps: usize,
    pub decisions: usize,
    pub history_tail: Vec<String>,
    pub page: PageSummary,
    pub narrate: bool,
    pub single_step: bool,
}

fn short_click_label(label: &str) -> String {
    let trimmed = label.trim();
    if trimmed.chars().count() <= 40 {
        trimmed.to_string()
    } else {
        let mut s: String = trimmed.chars().take(37).collect();
        s.push_str("...");
        s
    }
}

pub struct Broker {
    phase: Mutex<BrokerPhase>,
    active_url: Mutex<Option<String>>,
    stop_requested: Arc<AtomicBool>,
    pipeline_running: Arc<AtomicBool>,
    background: bool,
    events: Option<mpsc::UnboundedSender<AgentEvent>>,
}

/// RAII guard keeping `Broker::is_running` true across multi-step pipelines.
pub struct PipelineGuard {
    flag: Arc<AtomicBool>,
}

impl Drop for PipelineGuard {
    fn drop(&mut self) {
        self.flag.store(false, Ordering::SeqCst);
    }
}

impl Broker {
    pub fn new(background: bool) -> Self {
        Self {
            phase: Mutex::new(BrokerPhase::Idle),
            active_url: Mutex::new(None),
            stop_requested: Arc::new(AtomicBool::new(false)),
            pipeline_running: Arc::new(AtomicBool::new(false)),
            background,
            events: None,
        }
    }

    pub fn with_events(background: bool, events: mpsc::UnboundedSender<AgentEvent>) -> Self {
        Self {
            phase: Mutex::new(BrokerPhase::Idle),
            active_url: Mutex::new(None),
            stop_requested: Arc::new(AtomicBool::new(false)),
            pipeline_running: Arc::new(AtomicBool::new(false)),
            background,
            events: Some(events),
        }
    }

    async fn record_page_url(&self, url: &str) {
        if !url.is_empty() && url != "about:blank" {
            *self.active_url.lock().await = Some(url.to_string());
        }
    }

    /// Seed initial URL discovered during browser warmup if no URL is recorded yet.
    pub async fn record_initial_url(&self, url: &str) {
        if url.is_empty() || url == "about:blank" {
            return;
        }
        let mut active = self.active_url.lock().await;
        if active.is_none() {
            *active = Some(url.to_string());
        }
    }

    /// Claim exclusive execution for a multi-step voice pipeline until the returned guard drops.
    pub fn try_start_pipeline(&self) -> Option<PipelineGuard> {
        if self
            .pipeline_running
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_ok()
        {
            Some(PipelineGuard {
                flag: self.pipeline_running.clone(),
            })
        } else {
            None
        }
    }

    pub fn emit(&self, event: AgentEvent) {
        if let Some(tx) = &self.events {
            let _ = tx.send(event);
        }
    }

    fn emit_if(&self, narrate: bool, event: AgentEvent) {
        if narrate {
            self.emit(event);
        }
    }

    pub async fn has_pending_confirmation(&self) -> bool {
        matches!(*self.phase.lock().await, BrokerPhase::NeedsConfirmation(_))
    }

    pub async fn is_running(&self) -> bool {
        self.pipeline_running.load(Ordering::SeqCst)
            || matches!(*self.phase.lock().await, BrokerPhase::Running { .. })
    }

    pub async fn is_tool_task_running(&self) -> bool {
        matches!(*self.phase.lock().await, BrokerPhase::Running { narrate: false })
    }

    /// Immediately signal any active browser task to stop at the next step boundary.
    pub fn request_stop(&self) {
        self.stop_requested.store(true, Ordering::SeqCst);
    }

    pub fn clear_stop_request(&self) {
        self.stop_requested.store(false, Ordering::SeqCst);
    }

    pub fn is_stop_requested(&self) -> bool {
        self.stop_requested.load(Ordering::SeqCst)
    }

    pub async fn start_task(
        &self,
        bridge: &dyn BrowserBridge,
        goal: String,
        url: Option<String>,
    ) -> Result<TaskOutcome, BridgeError> {
        self.start_task_with_options(bridge, goal, url, None, false, false)
            .await
    }

    pub async fn start_task_with_tab(
        &self,
        bridge: &dyn BrowserBridge,
        goal: String,
        url: Option<String>,
        new_tab: bool,
    ) -> Result<TaskOutcome, BridgeError> {
        self.start_task_with_options(bridge, goal, url, None, false, new_tab)
            .await
    }

    pub async fn start_task_with_ack(
        &self,
        bridge: &dyn BrowserBridge,
        goal: String,
        url: Option<String>,
        ack: Option<String>,
    ) -> Result<TaskOutcome, BridgeError> {
        self.start_task_with_options(bridge, goal, url, ack, true, false)
            .await
    }

    pub async fn start_task_with_ack_tab(
        &self,
        bridge: &dyn BrowserBridge,
        goal: String,
        url: Option<String>,
        ack: Option<String>,
        new_tab: bool,
    ) -> Result<TaskOutcome, BridgeError> {
        self.start_task_with_options(bridge, goal, url, ack, true, new_tab)
            .await
    }

    pub async fn open_url(
        &self,
        bridge: &dyn BrowserBridge,
        goal: String,
        url: String,
        site_name: String,
        new_tab: bool,
    ) -> Result<PageSummary, BridgeError> {
        {
            let mut phase = self.phase.lock().await;
            match &*phase {
                BrokerPhase::Running { .. } => {
                    return Err(BridgeError::new(
                        "task_busy",
                        "A browser task is already running. Say 'stop' before starting another.",
                    ));
                }
                BrokerPhase::NeedsConfirmation(pending) => {
                    return Err(BridgeError::new(
                        "confirmation_pending",
                        format!(
                            "Waiting for confirmation on '{}'. Approve or reject it first.",
                            pending.action_label
                        ),
                    ));
                }
                BrokerPhase::Idle => {
                    self.stop_requested.store(false, Ordering::SeqCst);
                    *phase = BrokerPhase::Running { narrate: true };
                }
            }
        }

        let (goal, url, site_name) = {
            let active = self.active_url.lock().await.clone();
            if let Some(active_url) = active.as_deref() {
                crate::router::contextualize_generic_search(active_url, &goal, &url, &site_name, new_tab)
                    .unwrap_or((goal, url, site_name))
            } else {
                (goal, url, site_name)
            }
        };
        let requested_url = url.clone();
        let res = bridge.open_fast(goal, url, self.background, new_tab).await;
        {
            let mut phase = self.phase.lock().await;
            if matches!(*phase, BrokerPhase::Running { .. }) {
                *phase = BrokerPhase::Idle;
            }
        }
        if self.is_stop_requested() {
            if let Ok(page) = &res {
                self.record_page_url(&page.url).await;
            }
            self.emit(AgentEvent::Stopped);
            return Err(BridgeError::new("stopped", "Stopped by user."));
        }
        match res {
            Ok(page) => {
                let recorded = if page.url.is_empty() || page.url == "https://example.test" {
                    &requested_url
                } else {
                    &page.url
                };
                self.record_page_url(recorded).await;
                self.emit(AgentEvent::Say {
                    text: format!("Opened {site_name}."),
                    interrupt: false,
                });
                Ok(page)
            }
            Err(err) => {
                self.emit(AgentEvent::Error {
                    code: err.code.clone(),
                    message: err.message.clone(),
                });
                Err(err)
            }
        }
    }

    /// Tier 0.5 universal direct click: matches any visible clickable on screen (still enforcing the
    /// risky-action yes/no confirmation gate), and falls back seamlessly to Jev if no unambiguous match is visible.
    pub async fn click_target(
        &self,
        bridge: &dyn BrowserBridge,
        target: String,
        goal: String,
    ) -> Result<TaskOutcome, BridgeError> {
        {
            let mut phase = self.phase.lock().await;
            match &*phase {
                BrokerPhase::Running { .. } => {
                    return Err(BridgeError::new(
                        "task_busy",
                        "A browser task is already running. Say 'stop' before starting another.",
                    ));
                }
                BrokerPhase::NeedsConfirmation(pending) => {
                    return Err(BridgeError::new(
                        "confirmation_pending",
                        format!(
                            "Waiting for confirmation on '{}'. Approve or reject it first.",
                            pending.action_label
                        ),
                    ));
                }
                BrokerPhase::Idle => {
                    self.stop_requested.store(false, Ordering::SeqCst);
                    *phase = BrokerPhase::Running { narrate: true };
                }
            }
        }

        let matched = match bridge.match_click(target.clone()).await {
            Ok(m) => Some(m),
            Err(err) => {
                if err.code == "invalid_request" {
                    None
                } else {
                    *self.phase.lock().await = BrokerPhase::Idle;
                    self.emit(AgentEvent::Error {
                        code: err.code.clone(),
                        message: err.message.clone(),
                    });
                    return Err(err);
                }
            }
        };

        if let Some(matched) = matched {
            if self.is_stop_requested() {
                *self.phase.lock().await = BrokerPhase::Idle;
                self.emit(AgentEvent::Stopped);
                return Ok(TaskOutcome {
                    status: TaskStatus::Stopped,
                    reason: Some("Stopped by user.".to_string()),
                    pending_action: None,
                    steps: 0,
                    page: None,
                    history_tail: Vec::new(),
                });
            }
            if matched.matched {
                if is_risky_action(&matched.kind, &matched.action_label) {
                    *self.phase.lock().await =
                        BrokerPhase::NeedsConfirmation(Box::new(PendingConfirmation {
                            fingerprint: matched.fingerprint,
                            action_label: matched.action_label.clone(),
                            kind: matched.kind,
                            steps: 0,
                            decisions: 1,
                            history_tail: Vec::new(),
                            page: matched.page.clone(),
                            narrate: true,
                            single_step: true,
                        }));
                    self.emit(AgentEvent::NeedsConfirmation {
                        action: matched.action_label.clone(),
                    });
                    return Ok(TaskOutcome {
                        status: TaskStatus::NeedsConfirmation,
                        reason: Some(format!(
                            "Needs user confirmation before {}.",
                            matched.action_label
                        )),
                        pending_action: Some(matched.action_label),
                        steps: 0,
                        page: Some(matched.page),
                        history_tail: Vec::new(),
                    });
                }

                match bridge.act(matched.fingerprint).await {
                    Ok(act) if self.is_stop_requested() => {
                        *self.phase.lock().await = BrokerPhase::Idle;
                        self.record_page_url(&act.page.url).await;
                        self.emit(AgentEvent::Stopped);
                        return Ok(TaskOutcome {
                            status: TaskStatus::Stopped,
                            reason: Some("Stopped by user.".to_string()),
                            pending_action: None,
                            steps: 1,
                            page: Some(act.page),
                            history_tail: vec![matched.action_label],
                        });
                    }
                    Ok(act) if !act.stale => {
                        *self.phase.lock().await = BrokerPhase::Idle;
                        self.record_page_url(&act.page.url).await;
                        self.emit(AgentEvent::Say {
                            text: format!("Clicked {}.", short_click_label(&matched.action_label)),
                            interrupt: false,
                        });
                        return Ok(TaskOutcome {
                            status: TaskStatus::Done,
                            reason: None,
                            pending_action: None,
                            steps: 1,
                            page: Some(act.page),
                            history_tail: vec![matched.action_label],
                        });
                    }
                    Ok(_) => {}
                    Err(err) => {
                        *self.phase.lock().await = BrokerPhase::Idle;
                        self.emit(AgentEvent::Error {
                            code: err.code.clone(),
                            message: err.message.clone(),
                        });
                        return Err(err);
                    }
                }
            }
        }

        // If "select/click <site>" missed on screen (or no real tab was open yet) and target is a known site,
        // open the site directly in ~150ms instead of running a multi-step Jev LLM loop.
        if let crate::router::RouteAction::OpenUrl {
            goal: open_goal,
            url,
            site_name,
            ..
        } = crate::router::classify(&format!("open {target}"), false, false)
        {
            let requested_url = url.clone();
            let res = bridge.open_fast(open_goal, url, self.background, false).await;
            *self.phase.lock().await = BrokerPhase::Idle;
            if self.is_stop_requested() {
                if let Ok(page) = &res {
                    self.record_page_url(&page.url).await;
                }
                self.emit(AgentEvent::Stopped);
                return Ok(TaskOutcome {
                    status: TaskStatus::Stopped,
                    reason: Some("Stopped by user.".to_string()),
                    pending_action: None,
                    steps: 1,
                    page: res.ok(),
                    history_tail: Vec::new(),
                });
            }
            return match res {
                Ok(page) => {
                    let recorded = if page.url.is_empty() || page.url == "https://example.test" {
                        &requested_url
                    } else {
                        &page.url
                    };
                    self.record_page_url(recorded).await;
                    self.emit(AgentEvent::Say {
                        text: format!("Opened {site_name}."),
                        interrupt: false,
                    });
                    Ok(TaskOutcome {
                        status: TaskStatus::Done,
                        reason: None,
                        pending_action: None,
                        steps: 1,
                        page: Some(page),
                        history_tail: vec![format!("Opened {site_name}")],
                    })
                }
                Err(err) => {
                    self.emit(AgentEvent::Error {
                        code: err.code.clone(),
                        message: err.message.clone(),
                    });
                    Err(err)
                }
            };
        }

        // Not directly matched on screen (or went stale): fall back seamlessly to autonomous Jev task
        // while keeping BrokerPhase::Running continuously (no Idle race window).
        self.run_started_task(bridge, goal, None, Some("On it.".to_string()), true, false)
            .await
    }

    async fn start_task_with_options(
        &self,
        bridge: &dyn BrowserBridge,
        goal: String,
        url: Option<String>,
        ack: Option<String>,
        narrate: bool,
        new_tab: bool,
    ) -> Result<TaskOutcome, BridgeError> {
        {
            let mut phase = self.phase.lock().await;
            match &*phase {
                BrokerPhase::Running { .. } => {
                    return Err(BridgeError::new(
                        "task_busy",
                        "A browser task is already running. Say 'stop' before starting another.",
                    ));
                }
                BrokerPhase::NeedsConfirmation(pending) => {
                    return Err(BridgeError::new(
                        "confirmation_pending",
                        format!(
                            "Waiting for confirmation on '{}'. Approve or reject it first.",
                            pending.action_label
                        ),
                    ));
                }
                BrokerPhase::Idle => {
                    self.stop_requested.store(false, Ordering::SeqCst);
                    *phase = BrokerPhase::Running { narrate };
                }
            }
        }

        self.run_started_task(bridge, goal, url, ack, narrate, new_tab)
            .await
    }

    async fn run_started_task(
        &self,
        bridge: &dyn BrowserBridge,
        goal: String,
        url: Option<String>,
        ack: Option<String>,
        narrate: bool,
        new_tab: bool,
    ) -> Result<TaskOutcome, BridgeError> {
        if let Some(text) = ack {
            self.emit_if(narrate, AgentEvent::TaskAccepted { ack: text });
        }

        let navigated = url.is_some();
        let requested_url = url.clone();
        let res = async {
            let initial_page = bridge
                .open_with_tab(goal, url, self.background, new_tab)
                .await?;
            if let Some(req_u) = requested_url.as_deref() {
                if initial_page.url.is_empty() || initial_page.url == "https://example.test" {
                    self.record_page_url(req_u).await;
                } else {
                    self.record_page_url(&initial_page.url).await;
                }
            } else {
                self.record_page_url(&initial_page.url).await;
            }
            if navigated {
                self.emit_if(
                    narrate,
                    AgentEvent::PageLoaded {
                        url: initial_page.url.clone(),
                        title: initial_page.title.clone(),
                    },
                );
            }
            self.run_loop(bridge, initial_page, 0, 0, Vec::new(), None, narrate)
                .await
        }
        .await;

        if let Err(err) = &res {
            self.emit_if(
                narrate,
                AgentEvent::Error {
                    code: err.code.clone(),
                    message: err.message.clone(),
                },
            );
            let mut phase = self.phase.lock().await;
            if matches!(*phase, BrokerPhase::Running { .. }) {
                *phase = BrokerPhase::Idle;
            }
        }
        res
    }

    pub async fn confirm_task(
        &self,
        bridge: &dyn BrowserBridge,
        approve: bool,
    ) -> Result<TaskOutcome, BridgeError> {
        self.confirm_task_with_narration(bridge, approve, false)
            .await
    }

    pub async fn confirm_task_with_narration(
        &self,
        bridge: &dyn BrowserBridge,
        approve: bool,
        narrate: bool,
    ) -> Result<TaskOutcome, BridgeError> {
        let pending = {
            let mut phase = self.phase.lock().await;
            match std::mem::replace(&mut *phase, BrokerPhase::Idle) {
                BrokerPhase::NeedsConfirmation(p) => {
                    if approve {
                        self.stop_requested.store(false, Ordering::SeqCst);
                        *phase = BrokerPhase::Running { narrate };
                    }
                    p
                }
                other => {
                    *phase = other;
                    return Err(BridgeError::new(
                        "no_pending_confirmation",
                        "There is no pending browser action waiting for confirmation.",
                    ));
                }
            }
        };

        if !approve {
            let page = bridge.cancel().await.ok().flatten().or(Some(pending.page));
            self.emit_if(narrate, AgentEvent::Stopped);
            return Ok(TaskOutcome {
                status: TaskStatus::Stopped,
                reason: Some(format!("Cancelled '{}'.", pending.action_label)),
                pending_action: None,
                steps: pending.steps,
                page,
                history_tail: pending.history_tail,
            });
        }

        let res = self
            .run_loop(
                bridge,
                pending.page.clone(),
                pending.steps,
                pending.decisions,
                pending.history_tail.clone(),
                Some(*pending),
                narrate,
            )
            .await;

        if let Err(err) = &res {
            self.emit_if(
                narrate,
                AgentEvent::Error {
                    code: err.code.clone(),
                    message: err.message.clone(),
                },
            );
            let mut phase = self.phase.lock().await;
            if matches!(*phase, BrokerPhase::Running { .. }) {
                *phase = BrokerPhase::Idle;
            }
        }
        res
    }

    #[allow(clippy::too_many_arguments)]
    async fn run_loop(
        &self,
        bridge: &dyn BrowserBridge,
        mut page: PageSummary,
        mut steps: usize,
        mut decisions: usize,
        mut history_tail: Vec<String>,
        mut pre_approved: Option<PendingConfirmation>,
        narrate: bool,
    ) -> Result<TaskOutcome, BridgeError> {
        let mut last_repeat_key: Option<(String, String)> = None;
        let mut repeat_count: usize = 0;
        // If a user-confirmed risky action hit StalePage before executing, auto-approve the exact
        // same (kind, label) once on the immediate re-prediction instead of asking "yes or no" twice.
        let mut approved_stale_retry: Option<(String, String)> = None;

        loop {
            if self.stop_requested.load(Ordering::SeqCst) {
                let _ = bridge.cancel().await;
                *self.phase.lock().await = BrokerPhase::Idle;
                self.emit_if(narrate, AgentEvent::Stopped);
                return Ok(TaskOutcome {
                    status: TaskStatus::Stopped,
                    reason: Some("Stopped by user.".to_string()),
                    pending_action: None,
                    steps,
                    page: Some(page),
                    history_tail,
                });
            }

            let (fingerprint, choice, action_label, kind, is_approved, single_step) =
                if let Some(pending) = pre_approved.take() {
                    approved_stale_retry = Some((pending.kind.clone(), pending.action_label.clone()));
                    (
                        pending.fingerprint,
                        String::new(),
                        pending.action_label,
                        pending.kind,
                        true,
                        pending.single_step,
                    )
                } else {
                    if decisions >= MAX_DECISIONS {
                        let reason = format!("Reached the {MAX_DECISIONS}-decision budget.");
                        *self.phase.lock().await = BrokerPhase::Idle;
                        self.emit_if(
                            narrate,
                            AgentEvent::Blocked {
                                reason: reason.clone(),
                            },
                        );
                        return Ok(TaskOutcome {
                            status: TaskStatus::Blocked,
                            reason: Some(reason),
                            pending_action: None,
                            steps,
                            page: Some(page),
                            history_tail,
                        });
                    }

                    let pred: PredictResult = bridge.predict().await?;
                    decisions = pred.decision_count.max(decisions + 1);
                    page = pred.page;

                    // Honor a stop requested while predict() was in flight without executing act().
                    if self.stop_requested.load(Ordering::SeqCst) {
                        let _ = bridge.cancel().await;
                        *self.phase.lock().await = BrokerPhase::Idle;
                        self.emit_if(narrate, AgentEvent::Stopped);
                        return Ok(TaskOutcome {
                            status: TaskStatus::Stopped,
                            reason: Some("Stopped by user before executing next action.".to_string()),
                            pending_action: None,
                            steps,
                            page: Some(page),
                            history_tail,
                        });
                    }

                    (
                        pred.fingerprint,
                        pred.choice,
                        pred.action_label,
                        pred.kind,
                        false,
                        false,
                    )
                };

            let is_terminal_choice = matches!(choice.as_str(), "DONE" | "BLOCKED");
            if !is_terminal_choice && steps >= MAX_ACTIONS {
                let _ = bridge.cancel().await;
                let reason = format!("Stopped at the {MAX_ACTIONS}-action budget.");
                *self.phase.lock().await = BrokerPhase::Idle;
                self.emit_if(
                    narrate,
                    AgentEvent::Blocked {
                        reason: reason.clone(),
                    },
                );
                return Ok(TaskOutcome {
                    status: TaskStatus::Blocked,
                    reason: Some(reason),
                    pending_action: None,
                    steps,
                    page: Some(page),
                    history_tail,
                });
            }

            let reuse_approved = !is_approved
                && approved_stale_retry
                    .as_ref()
                    .map(|(k, l)| k == &kind && l == &action_label)
                    .unwrap_or(false);
            if reuse_approved {
                approved_stale_retry = None;
            }
            if !is_approved && !reuse_approved && is_risky_action(&kind, &action_label) {
                *self.phase.lock().await = BrokerPhase::NeedsConfirmation(Box::new(PendingConfirmation {
                    fingerprint,
                    action_label: action_label.clone(),
                    kind,
                    steps,
                    decisions,
                    history_tail: history_tail.clone(),
                    page: page.clone(),
                    narrate,
                    single_step: false,
                }));
                self.emit_if(
                    narrate,
                    AgentEvent::NeedsConfirmation {
                        action: action_label.clone(),
                    },
                );
                return Ok(TaskOutcome {
                    status: TaskStatus::NeedsConfirmation,
                    reason: Some(format!(
                        "Needs user confirmation before {action_label}."
                    )),
                    pending_action: Some(action_label),
                    steps,
                    page: Some(page),
                    history_tail,
                });
            }

            let prev_url = page.url.clone();
            let prev_title = page.title.clone();
            let prev_fp = page.fingerprint.clone();
            let act = bridge.act(fingerprint).await?;
            page = act.page;
            decisions = act.decision_count.max(decisions);
            if !act.stale || act.executed {
                approved_stale_retry = None;
            }
            if single_step && !act.stale {
                *self.phase.lock().await = BrokerPhase::Idle;
                self.emit_if(
                    narrate,
                    AgentEvent::Say {
                        text: format!("Clicked {}.", short_click_label(&action_label)),
                        interrupt: false,
                    },
                );
                return Ok(TaskOutcome {
                    status: TaskStatus::Done,
                    reason: None,
                    pending_action: None,
                    steps: steps + 1,
                    page: Some(page),
                    history_tail: vec![action_label],
                });
            }
            if act.executed {
                steps = act.history_len.max(steps + 1);
                if let Some(last) = &act.last_action {
                    if last.kind == "fill" {
                        self.emit_if(
                            narrate,
                            AgentEvent::TextTyped {
                                field: last.action.clone(),
                                value: last.text.clone(),
                            },
                        );
                    }
                }
                let label = act
                    .last_action
                    .as_ref()
                    .map(|a| a.action.clone())
                    .filter(|s| !s.is_empty())
                    .unwrap_or_else(|| action_label.clone());
                history_tail.push(label);
                if history_tail.len() > 8 {
                    history_tail.remove(0);
                }
            }

            match act.status.as_str() {
                "done" => {
                    *self.phase.lock().await = BrokerPhase::Idle;
                    self.emit_if(
                        narrate,
                        AgentEvent::Done {
                            url: page.url.clone(),
                            title: page.title.clone(),
                        },
                    );
                    return Ok(TaskOutcome {
                        status: TaskStatus::Done,
                        reason: None,
                        pending_action: None,
                        steps,
                        page: Some(page),
                        history_tail,
                    });
                }
                "blocked" => {
                    let reason = "Agent could not make further progress on this page.".to_string();
                    *self.phase.lock().await = BrokerPhase::Idle;
                    self.emit_if(
                        narrate,
                        AgentEvent::Blocked {
                            reason: reason.clone(),
                        },
                    );
                    return Ok(TaskOutcome {
                        status: TaskStatus::Blocked,
                        reason: Some(reason),
                        pending_action: None,
                        steps,
                        page: Some(page),
                        history_tail,
                    });
                }
                _ => {
                    // Only break on identical non-wait actions when the page actually made no progress
                    // (allows legitimate repeated clicks like calendar "Next month", "+1 guest", or scrolling).
                    let no_progress = act
                        .last_action
                        .as_ref()
                        .and_then(|a| a.page_changed)
                        == Some(false)
                        || (!prev_fp.is_empty() && page.fingerprint == prev_fp);
                    if act.executed
                        && kind != "wait"
                        && !choice.is_empty()
                        && page.url == prev_url
                        && no_progress
                    {
                        let key = (choice.clone(), prev_url.clone());
                        if last_repeat_key.as_ref() == Some(&key) {
                            repeat_count += 1;
                        } else {
                            last_repeat_key = Some(key);
                            repeat_count = 1;
                        }
                        if repeat_count >= 3 {
                            let reason = "Stopped repeating the same action with no progress.".to_string();
                            *self.phase.lock().await = BrokerPhase::Idle;
                            self.emit_if(
                                narrate,
                                AgentEvent::Blocked {
                                    reason: reason.clone(),
                                },
                            );
                            return Ok(TaskOutcome {
                                status: TaskStatus::Blocked,
                                reason: Some(reason),
                                pending_action: None,
                                steps,
                                page: Some(page),
                                history_tail,
                            });
                        }
                    } else if page.url != prev_url || !no_progress {
                        last_repeat_key = None;
                        repeat_count = 0;
                    }
                    if page.url != prev_url
                        && friendly_site_name(&page.url, &page.title)
                            != friendly_site_name(&prev_url, &prev_title)
                    {
                        self.emit_if(
                            narrate,
                            AgentEvent::PageLoaded {
                                url: page.url.clone(),
                                title: page.title.clone(),
                            },
                        );
                    }
                }
            }
        }
    }

    pub async fn read_page(&self, bridge: &dyn BrowserBridge) -> Result<ReadPageResult, BridgeError> {
        {
            let phase = self.phase.lock().await;
            if matches!(*phase, BrokerPhase::Running { .. }) {
                return Err(BridgeError::new(
                    "task_busy",
                    "A browser task is currently running. Wait for it to finish or say 'stop'.",
                ));
            }
        }
        let res = bridge.read_page().await;
        if let Ok(r) = &res {
            self.record_page_url(&r.page.url).await;
        }
        res
    }

    pub async fn control(
        &self,
        bridge: &dyn BrowserBridge,
        action: &str,
    ) -> Result<ControlResult, BridgeError> {
        let normalized = action.trim().to_ascii_lowercase();
        if normalized == "stop" {
            self.request_stop();
            let pending_narrate = {
                let mut phase = self.phase.lock().await;
                match std::mem::replace(&mut *phase, BrokerPhase::Idle) {
                    BrokerPhase::NeedsConfirmation(p) => {
                        self.clear_stop_request();
                        Some(p.narrate)
                    }
                    BrokerPhase::Idle => {
                        self.clear_stop_request();
                        self.emit(AgentEvent::Silence);
                        None
                    }
                    BrokerPhase::Running { narrate } => {
                        *phase = BrokerPhase::Running { narrate };
                        // run_loop will emit Stopped (if narrate) when it observes stop_requested.
                        None
                    }
                }
            };
            let page = if let Some(narrate) = pending_narrate {
                let out = bridge.cancel().await.ok().flatten();
                self.emit_if(narrate, AgentEvent::Stopped);
                out
            } else {
                None
            };
            return Ok(ControlResult {
                action: "stop".to_string(),
                closed: false,
                page,
                message: None,
            });
        }

        let is_safe_media_control = matches!(
            normalized.as_str(),
            "pause_video"
                | "play_video"
                | "mute_video"
                | "unmute_video"
                | "volume_up"
                | "volume_down"
                | "skip_ad"
        ) || normalized.starts_with("volume:");
        let had_confirmation = {
            let mut phase = self.phase.lock().await;
            if matches!(*phase, BrokerPhase::Running { .. }) && !is_safe_media_control {
                return Err(BridgeError::new(
                    "task_busy",
                    "A browser task is running; say 'stop' before manual browser navigation.",
                ));
            }
            if matches!(*phase, BrokerPhase::NeedsConfirmation(_)) {
                *phase = BrokerPhase::Idle;
                true
            } else {
                false
            }
        };
        if had_confirmation {
            let _ = bridge.cancel().await;
        }
        let res = bridge.control(normalized).await;
        if let Ok(ctrl) = &res {
            if ctrl.closed && ctrl.page.is_none() {
                *self.active_url.lock().await = None;
            } else if let Some(p) = &ctrl.page {
                if p.url != "https://example.test" {
                    self.record_page_url(&p.url).await;
                }
            }
        }
        res
    }
}
