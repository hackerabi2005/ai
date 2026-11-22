use crate::bridge::{BridgeError, BrowserBridge, ReadPageResult};
use crate::broker::{AgentEvent, Broker, TaskStatus};
use crate::narrator::friendly_site_name;
use crate::router::{classify, is_addressed_to_jarvis, RouteAction};
use axum::extract::{Request, State};
use axum::http::{header, StatusCode};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::Deserialize;
use serde_json::json;
use std::net::{IpAddr, Ipv4Addr, SocketAddr};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::net::TcpListener;
use tokio::sync::{watch, Mutex};

const CHAT_WINDOW_DURATION: Duration = Duration::from_secs(12);

#[derive(Clone)]
pub struct ApiState {
    pub broker: Arc<Broker>,
    pub bridge: Arc<dyn BrowserBridge>,
    pub token: Arc<String>,
    pub quit_tx: Option<watch::Sender<bool>>,
    pub chat_window_until: Arc<Mutex<Option<Instant>>>,
}

pub fn validate_bind_ip(ip: IpAddr) -> Result<(), String> {
    if !ip.is_loopback() {
        return Err(format!("Refusing non-loopback bind address {ip}"));
    }
    Ok(())
}

pub async fn bind_loopback(port: u16) -> Result<(TcpListener, SocketAddr), String> {
    let ip = IpAddr::V4(Ipv4Addr::LOCALHOST);
    validate_bind_ip(ip)?;
    let addr = SocketAddr::new(ip, port);
    let listener = TcpListener::bind(addr)
        .await
        .map_err(|e| format!("Failed to bind loopback API on {addr}: {e}"))?;
    let bound = listener
        .local_addr()
        .map_err(|e| format!("Failed to read bound API address: {e}"))?;
    Ok((listener, bound))
}

fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let mut diff = 0u8;
    for (&x, &y) in a.iter().zip(b.iter()) {
        diff |= x ^ y;
    }
    diff == 0
}

async fn require_bearer_token(
    State(state): State<ApiState>,
    req: Request,
    next: Next,
) -> Response {
    let provided = req
        .headers()
        .get(header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.strip_prefix("Bearer "));
    match provided {
        Some(tok) if constant_time_eq(tok.as_bytes(), state.token.as_bytes()) => next.run(req).await,
        _ => (
            StatusCode::UNAUTHORIZED,
            Json(json!({"code": "unauthorized", "error": "Missing or invalid bearer token"})),
        )
            .into_response(),
    }
}

pub fn build_router(state: ApiState) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/task", post(post_task))
        .route("/confirm", post(post_confirm))
        .route("/control", post(post_control))
        .route("/read_page", get(get_read_page))
        .route("/utterance", post(post_utterance))
        .layer(middleware::from_fn_with_state(state.clone(), require_bearer_token))
        .with_state(state)
}

async fn health() -> impl IntoResponse {
    Json(json!({"ok": true}))
}

#[derive(Deserialize)]
struct TaskRequest {
    goal: String,
    #[serde(default)]
    url: Option<String>,
    #[serde(default)]
    new_tab: bool,
}

async fn post_task(
    State(state): State<ApiState>,
    Json(req): Json<TaskRequest>,
) -> impl IntoResponse {
    let goal = req.goal.trim().to_string();
    if goal.is_empty() || goal.len() > 2000 {
        return (
            StatusCode::BAD_REQUEST,
            Json(json!({"code": "invalid_goal", "error": "goal must be 1..2000 characters"})),
        )
            .into_response();
    }
    match state
        .broker
        .start_task_with_tab(state.bridge.as_ref(), goal, req.url, req.new_tab)
        .await
    {
        Ok(outcome) => (StatusCode::OK, Json(json!(outcome))).into_response(),
        Err(err) => map_bridge_error(err),
    }
}

#[derive(Deserialize)]
struct ConfirmRequest {
    approve: bool,
}

async fn post_confirm(
    State(state): State<ApiState>,
    Json(req): Json<ConfirmRequest>,
) -> impl IntoResponse {
    match state
        .broker
        .confirm_task(state.bridge.as_ref(), req.approve)
        .await
    {
        Ok(outcome) => (StatusCode::OK, Json(json!(outcome))).into_response(),
        Err(err) => map_bridge_error(err),
    }
}

#[derive(Deserialize)]
struct ControlRequest {
    action: String,
}

async fn post_control(
    State(state): State<ApiState>,
    Json(req): Json<ControlRequest>,
) -> impl IntoResponse {
    match state
        .broker
        .control(state.bridge.as_ref(), &req.action)
        .await
    {
        Ok(res) => (StatusCode::OK, Json(json!({"ok": true, "result": res}))).into_response(),
        Err(err) => map_bridge_error(err),
    }
}

async fn get_read_page(State(state): State<ApiState>) -> impl IntoResponse {
    match state.broker.read_page(state.bridge.as_ref()).await {
        Ok(res) => (StatusCode::OK, Json(json!({"ok": true, "result": res}))).into_response(),
        Err(err) => map_bridge_error(err),
    }
}

#[derive(Deserialize)]
struct UtteranceRequest {
    text: String,
    #[serde(default)]
    #[allow(dead_code)]
    turn_id: Option<String>,
    #[serde(default)]
    #[allow(dead_code)]
    session_id: Option<String>,
}

fn format_read_page_speech(res: &ReadPageResult) -> String {
    let site = friendly_site_name(&res.page.url, &res.page.title);
    let joined = res
        .page
        .text
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ");
    let mut body: String = joined.chars().take(460).collect();
    if joined.chars().count() > 460 {
        if let Some(pos) = body.rfind(['.', '!', '?']) {
            if pos >= 120 {
                body.truncate(pos + 1);
            }
        } else if let Some(pos) = body.rfind(' ') {
            body.truncate(pos);
        }
    }
    if body.is_empty() {
        format!("On {site}.")
    } else {
        format!("On {site}. {body}")
    }
}

fn control_narration(action: &str) -> &'static str {
    match action {
        "scroll_down" => "Scrolled down.",
        "scroll_up" => "Scrolled up.",
        "scroll_top" => "Scrolled to top.",
        "scroll_bottom" => "Scrolled to bottom.",
        "back" => "Went back.",
        "forward" => "Went forward.",
        "reload" => "Reloaded.",
        "close_tab" => "Closed the tab.",
        "press_escape" => "Dismissed.",
        _ => "Done.",
    }
}

fn is_silent_control(action: &str) -> bool {
    matches!(
        action,
        "scroll_down"
            | "scroll_up"
            | "scroll_top"
            | "scroll_bottom"
            | "play_video"
            | "pause_video"
            | "mute_video"
            | "unmute_video"
            | "volume_up"
            | "volume_down"
            | "seek_forward"
            | "seek_back"
            | "skip_ad"
            | "fullscreen"
            | "open_settings"
            | "toggle_captions"
            | "next_track"
            | "prev_track"
            | "speed_up"
            | "speed_down"
            | "press_escape"
            | "close_dialog"
            | "press_enter"
            | "press_tab"
            | "press_ctrl_k"
            | "press_ctrl_f"
    ) || action.starts_with("volume:")
        || action.starts_with("speed:")
}

/// Execute one pipeline/direct step and return true if subsequent pipeline steps may continue.
async fn execute_step(broker: &Broker, bridge: &dyn BrowserBridge, step: RouteAction) -> bool {
    match step {
        RouteAction::Control(action) => {
            let silent = is_silent_control(&action);
            match broker.control(bridge, &action).await {
                Ok(res) => {
                    if let Some(msg) = res.message.filter(|m| !m.trim().is_empty()) {
                        broker.emit(AgentEvent::Say {
                            text: msg,
                            interrupt: false,
                        });
                    } else if !silent {
                        broker.emit(AgentEvent::Say {
                            text: control_narration(&action).to_string(),
                            interrupt: false,
                        });
                    }
                    true
                }
                Err(err) => {
                    broker.emit(AgentEvent::Error {
                        code: err.code,
                        message: err.message,
                    });
                    false
                }
            }
        }
        RouteAction::ReadPage => match broker.read_page(bridge).await {
            Ok(res) => {
                broker.emit(AgentEvent::Say {
                    text: format_read_page_speech(&res),
                    interrupt: false,
                });
                true
            }
            Err(err) => {
                broker.emit(AgentEvent::Error {
                    code: err.code,
                    message: err.message,
                });
                false
            }
        },
        RouteAction::OpenUrl {
            goal,
            url,
            site_name,
            new_tab,
        } => broker
            .open_url(bridge, goal, url, site_name, new_tab)
            .await
            .is_ok(),
        RouteAction::ClickTarget { target, goal } => match broker
            .click_target(bridge, target, goal)
            .await
        {
            Ok(outcome) => outcome.status == TaskStatus::Done,
            Err(_) => false,
        },
        RouteAction::BrowserTask {
            goal,
            url,
            ack,
            new_tab,
        } => match broker
            .start_task_with_ack_tab(bridge, goal, url, Some(ack), new_tab)
            .await
        {
            Ok(outcome) => outcome.status == TaskStatus::Done,
            Err(_) => false,
        },
        _ => true,
    }
}

async fn post_utterance(
    State(state): State<ApiState>,
    Json(req): Json<UtteranceRequest>,
) -> impl IntoResponse {
    let in_confirmation = state.broker.has_pending_confirmation().await;
    let running = state.broker.is_running().await;

    match classify(&req.text, in_confirmation, running) {
        RouteAction::Ignore => Json(json!({
            "handled": true,
            "suppress_llm": true,
            "quit": false,
        }))
        .into_response(),

        RouteAction::Chat => {
            // Suppress ambient/video speech unless addressed to Jarvis or inside the active 12s chat window.
            if state.broker.is_tool_task_running().await {
                return Json(json!({
                    "handled": true,
                    "suppress_llm": true,
                    "quit": false,
                }))
                .into_response();
            }
            let now = Instant::now();
            let mut window = state.chat_window_until.lock().await;
            let active = window.map(|until| now < until).unwrap_or(false);
            let allow = is_addressed_to_jarvis(&req.text) || active;
            if allow {
                *window = Some(now + CHAT_WINDOW_DURATION);
            }
            Json(json!({
                "handled": !allow,
                "suppress_llm": !allow,
                "quit": false,
            }))
            .into_response()
        }

        RouteAction::Quit => {
            *state.chat_window_until.lock().await = None;
            state.broker.request_stop();
            state.broker.emit(AgentEvent::Say {
                text: "Goodbye.".to_string(),
                interrupt: true,
            });
            if let Some(tx) = &state.quit_tx {
                let _ = tx.send(true);
            }
            Json(json!({
                "handled": true,
                "suppress_llm": true,
                "quit": true,
            }))
            .into_response()
        }

        RouteAction::Stop => {
            *state.chat_window_until.lock().await = None;
            state.broker.request_stop();
            let broker = state.broker.clone();
            let bridge = state.bridge.clone();
            tokio::spawn(async move {
                let _ = broker.control(bridge.as_ref(), "stop").await;
            });
            Json(json!({
                "handled": true,
                "suppress_llm": true,
                "quit": false,
            }))
            .into_response()
        }

        RouteAction::Confirm(approve) => {
            let broker = state.broker.clone();
            let bridge = state.bridge.clone();
            tokio::spawn(async move {
                let _ = broker
                    .confirm_task_with_narration(bridge.as_ref(), approve, true)
                    .await;
            });
            Json(json!({
                "handled": true,
                "suppress_llm": true,
                "quit": false,
            }))
            .into_response()
        }

        RouteAction::Control(action) => {
            if action == "play_video" {
                *state.chat_window_until.lock().await = None;
            }
            let broker = state.broker.clone();
            let bridge = state.bridge.clone();
            tokio::spawn(async move {
                let _ = execute_step(&broker, bridge.as_ref(), RouteAction::Control(action)).await;
            });
            Json(json!({
                "handled": true,
                "suppress_llm": true,
                "quit": false,
            }))
            .into_response()
        }

        RouteAction::ReadPage => {
            let broker = state.broker.clone();
            let bridge = state.bridge.clone();
            tokio::spawn(async move {
                let _ = execute_step(&broker, bridge.as_ref(), RouteAction::ReadPage).await;
            });
            Json(json!({
                "handled": true,
                "suppress_llm": true,
                "quit": false,
            }))
            .into_response()
        }

        RouteAction::OpenUrl {
            goal,
            url,
            site_name,
            new_tab,
        } => {
            *state.chat_window_until.lock().await = None;
            if running || in_confirmation {
                let msg = if in_confirmation {
                    "Say yes or no first, or say stop."
                } else {
                    "Still working on the last task. Say stop to cancel."
                };
                state.broker.emit(AgentEvent::Say {
                    text: msg.to_string(),
                    interrupt: false,
                });
            } else {
                let broker = state.broker.clone();
                let bridge = state.bridge.clone();
                tokio::spawn(async move {
                    let _ = execute_step(
                        &broker,
                        bridge.as_ref(),
                        RouteAction::OpenUrl {
                            goal,
                            url,
                            site_name,
                            new_tab,
                        },
                    )
                    .await;
                });
            }
            Json(json!({
                "handled": true,
                "suppress_llm": true,
                "quit": false,
            }))
            .into_response()
        }

        RouteAction::ClickTarget { target, goal } => {
            if running || in_confirmation {
                let msg = if in_confirmation {
                    "Say yes or no first, or say stop."
                } else {
                    "Still working on the last task. Say stop to cancel."
                };
                state.broker.emit(AgentEvent::Say {
                    text: msg.to_string(),
                    interrupt: false,
                });
            } else {
                let broker = state.broker.clone();
                let bridge = state.bridge.clone();
                tokio::spawn(async move {
                    let _ = execute_step(
                        &broker,
                        bridge.as_ref(),
                        RouteAction::ClickTarget { target, goal },
                    )
                    .await;
                });
            }
            Json(json!({
                "handled": true,
                "suppress_llm": true,
                "quit": false,
            }))
            .into_response()
        }

        RouteAction::BrowserTask {
            goal,
            url,
            ack,
            new_tab,
        } => {
            if running || in_confirmation {
                let msg = if in_confirmation {
                    "Say yes or no first, or say stop."
                } else {
                    "Still working on the last task. Say stop to cancel."
                };
                state.broker.emit(AgentEvent::Say {
                    text: msg.to_string(),
                    interrupt: false,
                });
            } else {
                let broker = state.broker.clone();
                let bridge = state.bridge.clone();
                tokio::spawn(async move {
                    let _ = execute_step(
                        &broker,
                        bridge.as_ref(),
                        RouteAction::BrowserTask {
                            goal,
                            url,
                            ack,
                            new_tab,
                        },
                    )
                    .await;
                });
            }
            Json(json!({
                "handled": true,
                "suppress_llm": true,
                "quit": false,
            }))
            .into_response()
        }

        RouteAction::Pipeline(steps) => {
            *state.chat_window_until.lock().await = None;
            let guard = if running || in_confirmation {
                None
            } else {
                state.broker.try_start_pipeline()
            };
            if let Some(_pipeline_guard) = guard {
                state.broker.clear_stop_request();
                let broker = state.broker.clone();
                let bridge = state.bridge.clone();
                tokio::spawn(async move {
                    let _guard = _pipeline_guard;
                    for step in steps {
                        if broker.is_stop_requested() {
                            break;
                        }
                        if !execute_step(&broker, bridge.as_ref(), step).await {
                            break;
                        }
                    }
                });
            } else {
                let msg = if in_confirmation {
                    "Say yes or no first, or say stop."
                } else {
                    "Still working on the last task. Say stop to cancel."
                };
                state.broker.emit(AgentEvent::Say {
                    text: msg.to_string(),
                    interrupt: false,
                });
            }
            Json(json!({
                "handled": true,
                "suppress_llm": true,
                "quit": false,
            }))
            .into_response()
        }
    }
}

fn map_bridge_error(err: BridgeError) -> Response {
    let status = match err.code.as_str() {
        "task_busy" | "confirmation_pending" => StatusCode::CONFLICT,
        "invalid_request" | "no_pending_confirmation" | "no_agent" => StatusCode::BAD_REQUEST,
        _ => StatusCode::BAD_GATEWAY,
    };
    (
        status,
        Json(json!({"code": err.code, "error": err.message})),
    )
        .into_response()
}
