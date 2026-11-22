use axum::body::Body;
use axum::http::{header, Request, StatusCode};
use jarvis::api::{build_router, validate_bind_ip, ApiState};
use jarvis::bridge::{
    ActResult, BoxFuture, BridgeError, BrowserBridge, ControlResult, MatchClickResult, PageSummary,
    PredictResult, ReadPageResult, StdioBridge,
};
use jarvis::broker::{is_risky_action, AgentEvent, Broker, TaskStatus, MAX_ACTIONS, MAX_DECISIONS};
use jarvis::narrator::{HttpSaySink, SaySink};
use serde_json::{json, Value};
use std::collections::VecDeque;
use std::net::{IpAddr, Ipv4Addr};
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use tokio::sync::Notify;
use tower::ServiceExt;

fn fake_page(url: &str, fp: &str) -> PageSummary {
    PageSummary {
        url: url.to_string(),
        title: "Test Page".to_string(),
        text: "Visible body text".to_string(),
        fingerprint: fp.to_string(),
    }
}

struct FakeBridge {
    predicts: Mutex<VecDeque<PredictResult>>,
    acts: Mutex<VecDeque<ActResult>>,
    act_calls: AtomicUsize,
    cancel_calls: AtomicUsize,
    predict_started: Option<Arc<Notify>>,
    release_predict: Option<Arc<Notify>>,
}

impl FakeBridge {
    fn new(predicts: Vec<PredictResult>, acts: Vec<ActResult>) -> Self {
        Self {
            predicts: Mutex::new(predicts.into()),
            acts: Mutex::new(acts.into()),
            act_calls: AtomicUsize::new(0),
            cancel_calls: AtomicUsize::new(0),
            predict_started: None,
            release_predict: None,
        }
    }
}

impl BrowserBridge for FakeBridge {
    fn open(
        &self,
        _goal: String,
        url: Option<String>,
        _background: bool,
    ) -> BoxFuture<'_, Result<PageSummary, BridgeError>> {
        Box::pin(async move { Ok(fake_page(url.as_deref().unwrap_or("https://example.test"), "fp0")) })
    }

    fn predict(&self) -> BoxFuture<'_, Result<PredictResult, BridgeError>> {
        Box::pin(async move {
            if let Some(n) = &self.predict_started {
                n.notify_one();
            }
            if let Some(rel) = &self.release_predict {
                rel.notified().await;
            }
            let item = self
                .predicts
                .lock()
                .unwrap()
                .pop_front()
                .ok_or_else(|| BridgeError::new("test_empty", "No more fake predicts"))?;
            Ok(item)
        })
    }

    fn act(&self, _fingerprint: String) -> BoxFuture<'_, Result<ActResult, BridgeError>> {
        Box::pin(async move {
            self.act_calls.fetch_add(1, Ordering::SeqCst);
            let item = self
                .acts
                .lock()
                .unwrap()
                .pop_front()
                .ok_or_else(|| BridgeError::new("test_empty", "No more fake acts"))?;
            Ok(item)
        })
    }

    fn cancel(&self) -> BoxFuture<'_, Result<Option<PageSummary>, BridgeError>> {
        Box::pin(async move {
            self.cancel_calls.fetch_add(1, Ordering::SeqCst);
            Ok(Some(fake_page("https://example.test", "fp0")))
        })
    }

    fn read_page(&self) -> BoxFuture<'_, Result<ReadPageResult, BridgeError>> {
        Box::pin(async move {
            Ok(ReadPageResult {
                page: fake_page("https://example.test", "fp0"),
                elements: vec![json!({"index": "1", "label": "Search"})],
                omitted_elements: 0,
            })
        })
    }

    fn control(&self, action: String) -> BoxFuture<'_, Result<ControlResult, BridgeError>> {
        Box::pin(async move {
            Ok(ControlResult {
                action,
                closed: false,
                page: Some(fake_page("https://example.test", "fp0")),
                message: None,
            })
        })
    }

    fn close(&self) -> BoxFuture<'_, Result<(), BridgeError>> {
        Box::pin(async move { Ok(()) })
    }
}

fn pred(kind: &str, label: &str, choice: &str, fp: &str, decisions: usize) -> PredictResult {
    PredictResult {
        status: "predicted".into(),
        choice: choice.into(),
        operation: if kind == "fill" { "TYPE_TEXT" } else { "CLICK" }.into(),
        kind: kind.into(),
        action_label: label.into(),
        role: Some("button".into()),
        target: Some("1".into()),
        confidence: 0.99,
        fingerprint: fp.into(),
        history_len: decisions.saturating_sub(1),
        decision_count: decisions,
        page: fake_page("https://example.test", fp),
    }
}

fn act_res(status: &str, executed: bool, steps: usize, decisions: usize, fp: &str) -> ActResult {
    ActResult {
        stale: false,
        executed,
        status: status.into(),
        history_len: steps,
        decision_count: decisions,
        page: fake_page("https://example.test/done", fp),
        last_action: None,
    }
}

#[test]
fn risky_label_policy_only_flags_clicks_and_selects() {
    assert!(is_risky_action("click", "Place order"));
    assert!(is_risky_action("click", "Pay $199 now"));
    assert!(is_risky_action("select", "Confirm purchase"));
    assert!(is_risky_action("click", "Delete account"));
    assert!(!is_risky_action("fill", "Submit query"));
    assert!(!is_risky_action("click", "Search flights"));
}

#[test]
fn non_loopback_bind_is_refused() {
    assert!(validate_bind_ip(IpAddr::V4(Ipv4Addr::LOCALHOST)).is_ok());
    assert!(validate_bind_ip(IpAddr::V4(Ipv4Addr::UNSPECIFIED)).is_err());
    assert!(validate_bind_ip(IpAddr::V4(Ipv4Addr::new(192, 168, 1, 10))).is_err());
}

#[tokio::test]
async fn confirmation_gate_pauses_and_resumes_on_approve_or_reject() {
    let bridge = FakeBridge::new(
        vec![
            pred("click", "Search", "e1", "fp1", 1),
            pred("click", "Place order", "e2", "fp2", 2),
            pred("done", "DONE", "DONE", "fp3", 3),
        ],
        vec![
            act_res("ready", true, 1, 1, "fp2"),
            act_res("ready", true, 2, 2, "fp3"),
            act_res("done", false, 2, 3, "fp3"),
        ],
    );
    let broker = Broker::new(false);
    let paused = broker
        .start_task(&bridge, "Buy ticket".into(), None)
        .await
        .unwrap();
    assert_eq!(paused.status, TaskStatus::NeedsConfirmation);
    assert_eq!(paused.pending_action.as_deref(), Some("Place order"));
    assert_eq!(bridge.act_calls.load(Ordering::SeqCst), 1);

    let done = broker.confirm_task(&bridge, true).await.unwrap();
    assert_eq!(done.status, TaskStatus::Done);
    assert_eq!(bridge.act_calls.load(Ordering::SeqCst), 3);

    // Reject path cancels without executing act().
    let bridge2 = FakeBridge::new(
        vec![pred("click", "Delete item", "e1", "fp1", 1)],
        vec![],
    );
    let broker2 = Broker::new(false);
    let paused2 = broker2
        .start_task(&bridge2, "Delete".into(), None)
        .await
        .unwrap();
    assert_eq!(paused2.status, TaskStatus::NeedsConfirmation);
    let cancelled = broker2.confirm_task(&bridge2, false).await.unwrap();
    assert_eq!(cancelled.status, TaskStatus::Stopped);
    assert_eq!(bridge2.act_calls.load(Ordering::SeqCst), 0);
    assert_eq!(bridge2.cancel_calls.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn stop_during_predict_prevents_next_act() {
    let predict_started = Arc::new(Notify::new());
    let release_predict = Arc::new(Notify::new());
    let bridge = Arc::new(FakeBridge {
        predicts: Mutex::new(vec![pred("click", "Next", "e1", "fp1", 1)].into()),
        acts: Mutex::new(vec![act_res("ready", true, 1, 1, "fp2")].into()),
        act_calls: AtomicUsize::new(0),
        cancel_calls: AtomicUsize::new(0),
        predict_started: Some(predict_started.clone()),
        release_predict: Some(release_predict.clone()),
    });
    let broker = Arc::new(Broker::new(false));

    let b = broker.clone();
    let br = bridge.clone();
    let handle = tokio::spawn(async move {
        b.start_task(br.as_ref(), "Browse".into(), None).await
    });

    predict_started.notified().await;
    let ctrl = broker.control(bridge.as_ref(), "stop").await.unwrap();
    assert_eq!(ctrl.action, "stop");
    release_predict.notify_one();

    let outcome = handle.await.unwrap().unwrap();
    assert_eq!(outcome.status, TaskStatus::Stopped);
    assert_eq!(bridge.act_calls.load(Ordering::SeqCst), 0);
    assert_eq!(bridge.cancel_calls.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn budgets_enforce_max_actions_and_max_decisions() {
    let mut predicts = Vec::new();
    let mut acts = Vec::new();
    for i in 1..=(MAX_ACTIONS + 2) {
        predicts.push(pred("click", "Next", "e1", "fp", i));
        acts.push(act_res("ready", true, i, i, "fp"));
    }
    let bridge = FakeBridge::new(predicts, acts);
    let broker = Broker::new(false);
    let out = broker.start_task(&bridge, "Loop".into(), None).await.unwrap();
    assert_eq!(out.status, TaskStatus::Blocked);
    assert_eq!(out.steps, MAX_ACTIONS);

    // Decision budget when acts stay stale / non-mutating.
    let mut stale_preds = Vec::new();
    let mut stale_acts = Vec::new();
    for i in 1..=(MAX_DECISIONS + 1) {
        stale_preds.push(pred("click", "Next", "e1", "fp", i));
        stale_acts.push(act_res("ready", false, 0, i, "fp"));
    }
    let bridge2 = FakeBridge::new(stale_preds, stale_acts);
    let out2 = Broker::new(false)
        .start_task(&bridge2, "Loop".into(), None)
        .await
        .unwrap();
    assert_eq!(out2.status, TaskStatus::Blocked);
}

#[tokio::test]
async fn api_rejects_missing_or_bad_token_and_serves_authenticated_requests() {
    let bridge: Arc<dyn BrowserBridge> = Arc::new(FakeBridge::new(
        vec![pred("done", "DONE", "DONE", "fp1", 1)],
        vec![act_res("done", false, 0, 1, "fp1")],
    ));
    let state = ApiState {
        broker: Arc::new(Broker::new(false)),
        bridge,
        token: Arc::new("secret-token".into()),
        quit_tx: None,
        chat_window_until: Arc::new(tokio::sync::Mutex::new(None)),
    };
    let app = build_router(state);

    // Missing token -> 401
    let resp = app
        .clone()
        .oneshot(
            Request::builder()
                .uri("/health")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);

    // Bad token -> 401
    let resp_bad = app
        .clone()
        .oneshot(
            Request::builder()
                .uri("/read_page")
                .header(header::AUTHORIZATION, "Bearer wrong")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(resp_bad.status(), StatusCode::UNAUTHORIZED);

    // Valid token -> 200 and executes task
    let resp_ok = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/task")
                .header(header::AUTHORIZATION, "Bearer secret-token")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(r#"{"goal":"Test goal"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(resp_ok.status(), StatusCode::OK);
    let body = axum::body::to_bytes(resp_ok.into_body(), usize::MAX)
        .await
        .unwrap();
    let parsed: Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(parsed["status"], "done");
}

#[tokio::test]
async fn stdio_bridge_handles_fake_python_child_crash_gracefully() {
    // Use Python directly to simulate a child process that crashes on second command.
    let script = std::env::temp_dir().join(format!("jarvis_fake_crash_{}.py", std::process::id()));
    std::fs::write(
        &script,
        "import json, sys\nfor line in sys.stdin:\n  req = json.loads(line)\n  if req['cmd'] == 'ping':\n    print(json.dumps({'id': req['id'], 'ok': True, 'pid': 1}), flush=True)\n  else:\n    sys.exit(1)\n",
    )
    .unwrap();

    let python = if cfg!(windows) {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .join("borwse harness")
            .join("jev-ultrafast")
            .join(".venv")
            .join("Scripts")
            .join("python.exe")
    } else {
        PathBuf::from("python3")
    };

    if python.is_file() {
        let bridge = StdioBridge::new(
            python,
            script.clone(),
            PathBuf::from(env!("CARGO_MANIFEST_DIR")),
        );
        assert_eq!(bridge.ping().await.unwrap(), 1);
        let err = bridge.read_page().await.unwrap_err();
        assert_eq!(err.code, "bridge_crashed");
        // After crash, bridge respawns cleanly on next ping.
        assert_eq!(bridge.ping().await.unwrap(), 1);
        let _ = bridge.close().await;
    }
    let _ = std::fs::remove_file(script);
}

#[tokio::test]
async fn jarvis_tools_python_talks_to_live_rust_loopback_server() {
    let s2s_python = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("s2s")
        .join("speech-to-speech")
        .join(".venv")
        .join(if cfg!(windows) {
            "Scripts\\python.exe"
        } else {
            "bin/python"
        });
    if !s2s_python.is_file() {
        return;
    }

    let bridge: Arc<dyn BrowserBridge> = Arc::new(FakeBridge::new(
        vec![
            pred("click", "Buy now", "e1", "fp1", 1),
            pred("done", "DONE", "DONE", "fp2", 2),
        ],
        vec![
            act_res("ready", true, 1, 1, "fp2"),
            act_res("done", false, 1, 2, "fp2"),
        ],
    ));
    let token = "live-loopback-tok";
    let (listener, addr) = jarvis::api::bind_loopback(0).await.unwrap();
    let app = build_router(ApiState {
        broker: Arc::new(Broker::new(false)),
        bridge,
        token: Arc::new(token.into()),
        quit_tx: None,
        chat_window_until: Arc::new(tokio::sync::Mutex::new(None)),
    });
    let (tx, rx) = tokio::sync::oneshot::channel::<()>();
    let srv = tokio::spawn(async move {
        let _ = axum::serve(listener, app)
            .with_graceful_shutdown(async move {
                let _ = rx.await;
            })
            .await;
    });

    let tools_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("python");
    let py_code = r#"
import asyncio, json, sys
sys.path.insert(0, sys.argv[1])
import jarvis_tools

async def run():
    r1 = await jarvis_tools.execute_tool("browser_task", {"goal": "Buy item", "url": None})
    r2 = await jarvis_tools.execute_tool("browser_confirm", {"approve": True})
    print(json.dumps({"r1": r1.output, "r2": r2.output}))

asyncio.run(run())
"#;

    let out = tokio::process::Command::new(&s2s_python)
        .args(["-c", py_code, tools_dir.to_str().unwrap()])
        .env("JARVIS_API_URL", format!("http://{addr}"))
        .env("JARVIS_API_TOKEN", token)
        .output()
        .await
        .unwrap();

    let _ = tx.send(());
    let _ = srv.await;

    assert!(
        out.status.success(),
        "python stderr: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    let parsed: Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(parsed["r1"]["status"], "needs_confirmation");
    assert_eq!(parsed["r1"]["pending_action"], "Buy now");
    assert_eq!(parsed["r2"]["status"], "done");
}

#[tokio::test]
async fn bridge_error_mid_task_resets_broker_to_idle_for_next_task() {
    let broker = Broker::new(false);
    // First task fails during predict() because FakeBridge has no predicts queued.
    let failing = FakeBridge::new(vec![], vec![]);
    let err = broker
        .start_task(&failing, "Fail mid step".into(), None)
        .await
        .unwrap_err();
    assert_eq!(err.code, "test_empty");

    // Next task must succeed immediately rather than getting stuck in Running.
    let working = FakeBridge::new(
        vec![pred("done", "DONE", "DONE", "fp1", 1)],
        vec![act_res("done", false, 0, 1, "fp1")],
    );
    let ok = broker
        .start_task(&working, "Recover cleanly".into(), None)
        .await
        .unwrap();
    assert_eq!(ok.status, TaskStatus::Done);
}

#[tokio::test]
async fn utterance_endpoint_routes_browser_commands_chat_and_quit_and_emits_events() {
    let (events_tx, mut events_rx) = tokio::sync::mpsc::unbounded_channel();
    let (quit_tx, quit_rx) = tokio::sync::watch::channel(false);

    let bridge: Arc<dyn BrowserBridge> = Arc::new(FakeBridge::new(
        vec![pred("done", "DONE", "DONE", "fp1", 1)],
        vec![act_res("done", false, 0, 1, "fp1")],
    ));
    let app = build_router(ApiState {
        broker: Arc::new(Broker::with_events(false, events_tx)),
        bridge,
        token: Arc::new("utt-tok".into()),
        quit_tx: Some(quit_tx),
        chat_window_until: Arc::new(tokio::sync::Mutex::new(None)),
    });

    // 1a. Unaddressed ambient speech -> suppressed (stops YouTube speaker bleed).
    let ambient_resp = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/utterance")
                .header(header::AUTHORIZATION, "Bearer utt-tok")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(r#"{"text":"tell me a joke"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    let ambient_json: Value = serde_json::from_slice(
        &axum::body::to_bytes(ambient_resp.into_body(), usize::MAX)
            .await
            .unwrap(),
    )
    .unwrap();
    assert_eq!(ambient_json["suppress_llm"], true);

    // 1b. Addressed "Jarvis, tell me a joke" -> passes to LLM & opens 12s follow-up window.
    let chat_resp = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/utterance")
                .header(header::AUTHORIZATION, "Bearer utt-tok")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(r#"{"text":"Jarvis, tell me a joke"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(chat_resp.status(), StatusCode::OK);
    let chat_json: Value = serde_json::from_slice(
        &axum::body::to_bytes(chat_resp.into_body(), usize::MAX)
            .await
            .unwrap(),
    )
    .unwrap();
    assert_eq!(chat_json["handled"], false);
    assert_eq!(chat_json["suppress_llm"], false);

    // 1c. Immediate follow-up within 12s window passes without repeating "Jarvis".
    let followup_resp = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/utterance")
                .header(header::AUTHORIZATION, "Bearer utt-tok")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(r#"{"text":"tell me another one"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    let followup_json: Value = serde_json::from_slice(
        &axum::body::to_bytes(followup_resp.into_body(), usize::MAX)
            .await
            .unwrap(),
    )
    .unwrap();
    assert_eq!(followup_json["suppress_llm"], false);

    // 2. Direct "open youtube" -> fast OpenUrl path speaks "Opened YouTube." without calling predict/act!
    let open_resp = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/utterance")
                .header(header::AUTHORIZATION, "Bearer utt-tok")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(r#"{"text":"open youtube"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(open_resp.status(), StatusCode::OK);
    let open_json: Value = serde_json::from_slice(
        &axum::body::to_bytes(open_resp.into_body(), usize::MAX)
            .await
            .unwrap(),
    )
    .unwrap();
    assert_eq!(open_json["handled"], true);
    assert_eq!(open_json["suppress_llm"], true);
    assert_eq!(open_json["quit"], false);

    let opened_ev = tokio::time::timeout(std::time::Duration::from_secs(2), events_rx.recv())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        opened_ev,
        AgentEvent::Say {
            text: "Opened YouTube.".into(),
            interrupt: false,
        }
    );

    // 2b. Multi-step play command -> uses Jev predict/act starting on YouTube search results.
    let search_resp = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/utterance")
                .header(header::AUTHORIZATION, "Bearer utt-tok")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(r#"{"text":"play rust on youtube"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(search_resp.status(), StatusCode::OK);
    let mut seen = Vec::new();
    for _ in 0..3 {
        let ev = tokio::time::timeout(std::time::Duration::from_secs(2), events_rx.recv())
            .await
            .unwrap()
            .unwrap();
        seen.push(ev);
    }
    assert!(matches!(&seen[0], AgentEvent::TaskAccepted { ack } if ack == "Playing rust on YouTube."));
    assert!(matches!(&seen[1], AgentEvent::PageLoaded { .. }));
    assert!(matches!(&seen[2], AgentEvent::Done { .. }));

    // 2c. Scroll down runs silently (no TTS cooldown lock), while reload still speaks.
    let scroll_resp = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/utterance")
                .header(header::AUTHORIZATION, "Bearer utt-tok")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(r#"{"text":"scroll down"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(scroll_resp.status(), StatusCode::OK);
    tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    assert!(events_rx.try_recv().is_err());

    let reload_resp = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/utterance")
                .header(header::AUTHORIZATION, "Bearer utt-tok")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(r#"{"text":"reload"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(reload_resp.status(), StatusCode::OK);
    let reload_ev = tokio::time::timeout(std::time::Duration::from_secs(2), events_rx.recv())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        reload_ev,
        AgentEvent::Say {
            text: "Reloaded.".into(),
            interrupt: false,
        }
    );

    // 3. Voice quit -> triggers quit_tx and emits Goodbye.
    let quit_resp = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/utterance")
                .header(header::AUTHORIZATION, "Bearer utt-tok")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(r#"{"text":"Jarvis quit"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(quit_resp.status(), StatusCode::OK);
    let quit_json: Value = serde_json::from_slice(
        &axum::body::to_bytes(quit_resp.into_body(), usize::MAX)
            .await
            .unwrap(),
    )
    .unwrap();
    assert_eq!(quit_json["quit"], true);
    assert!(*quit_rx.borrow());
    let bye = events_rx.recv().await.unwrap();
    assert_eq!(
        bye,
        AgentEvent::Say {
            text: "Goodbye.".into(),
            interrupt: true
        }
    );
}

#[tokio::test]
async fn http_say_sink_posts_bearer_auth_json_to_s2s_say_endpoint() {
    use axum::routing::post;
    use axum::{Json, Router};

    type SayLog = Arc<Mutex<Vec<(Option<String>, Value)>>>;
    let seen: SayLog = Arc::new(Mutex::new(Vec::new()));
    let seen_srv = seen.clone();
    let app = Router::new().route(
        "/v1/say",
        post(
            move |headers: axum::http::HeaderMap, Json(body): Json<Value>| {
                let seen_srv = seen_srv.clone();
                async move {
                    let auth = headers
                        .get(header::AUTHORIZATION)
                        .and_then(|v| v.to_str().ok())
                        .map(str::to_string);
                    seen_srv.lock().unwrap().push((auth, body));
                    Json(json!({"ok": true}))
                }
            },
        ),
    );
    let (listener, addr) = jarvis::api::bind_loopback(0).await.unwrap();
    let (tx, rx) = tokio::sync::oneshot::channel::<()>();
    let srv = tokio::spawn(async move {
        let _ = axum::serve(listener, app)
            .with_graceful_shutdown(async move {
                let _ = rx.await;
            })
            .await;
    });

    let sink = HttpSaySink::new(addr.to_string(), "say-tok");
    assert!(sink.say("Opened YouTube.".into(), false).await);
    assert!(sink.say("Done.".into(), true).await);

    let _ = tx.send(());
    let _ = srv.await;

    let recorded = seen.lock().unwrap();
    assert_eq!(recorded.len(), 2);
    assert_eq!(recorded[0].0.as_deref(), Some("Bearer say-tok"));
    assert_eq!(recorded[0].1["text"], "Opened YouTube.");
    assert_eq!(recorded[0].1["interrupt"], false);
    assert_eq!(recorded[1].1["text"], "Done.");
    assert_eq!(recorded[1].1["interrupt"], true);
}

#[tokio::test]
async fn llm_tool_driven_task_does_not_emit_narrator_events() {
    let (events_tx, mut events_rx) = tokio::sync::mpsc::unbounded_channel();
    let bridge: Arc<dyn BrowserBridge> = Arc::new(FakeBridge::new(
        vec![pred("done", "DONE", "DONE", "fp1", 1)],
        vec![act_res("done", false, 0, 1, "fp1")],
    ));
    let app = build_router(ApiState {
        broker: Arc::new(Broker::with_events(false, events_tx)),
        bridge,
        token: Arc::new("tool-tok".into()),
        quit_tx: None,
        chat_window_until: Arc::new(tokio::sync::Mutex::new(None)),
    });

    let resp = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/task")
                .header(header::AUTHORIZATION, "Bearer tool-tok")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(r#"{"goal":"Check flights"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    assert!(events_rx.try_recv().is_err());
}

#[tokio::test]
async fn same_tab_task_skips_initial_page_loaded_and_suppresses_chat_during_tool_call() {
    // 1. Same-tab router task (url=None) should NOT emit a redundant PageLoaded ("Opened YouTube.").
    let (events_tx, mut events_rx) = tokio::sync::mpsc::unbounded_channel();
    let bridge = FakeBridge::new(
        vec![pred("done", "DONE", "DONE", "fp1", 1)],
        vec![act_res("done", false, 0, 1, "fp1")],
    );
    let broker = Broker::with_events(false, events_tx);
    broker
        .start_task_with_ack(&bridge, "Open settings".into(), None, Some("On it.".into()))
        .await
        .unwrap();
    let mut events = Vec::new();
    while let Ok(ev) = events_rx.try_recv() {
        events.push(ev);
    }
    assert!(!events.iter().any(|e| matches!(e, AgentEvent::PageLoaded { .. })));

    // 2. While a tool-driven /task is in flight, stray Chat utterances get suppress_llm=true.
    let predict_started = Arc::new(Notify::new());
    let release_predict = Arc::new(Notify::new());
    let slow_bridge = Arc::new(FakeBridge {
        predicts: Mutex::new(vec![pred("done", "DONE", "DONE", "fp1", 1)].into()),
        acts: Mutex::new(vec![act_res("done", false, 0, 1, "fp1")].into()),
        act_calls: AtomicUsize::new(0),
        cancel_calls: AtomicUsize::new(0),
        predict_started: Some(predict_started.clone()),
        release_predict: Some(release_predict.clone()),
    });
    let tool_broker = Arc::new(Broker::new(false));
    let app = build_router(ApiState {
        broker: tool_broker.clone(),
        bridge: slow_bridge.clone(),
        token: Arc::new("t".into()),
        quit_tx: None,
        chat_window_until: Arc::new(tokio::sync::Mutex::new(None)),
    });

    let b = tool_broker.clone();
    let br = slow_bridge.clone();
    let task_handle = tokio::spawn(async move { b.start_task(br.as_ref(), "Browse".into(), None).await });
    predict_started.notified().await;

    let resp = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/utterance")
                .header(header::AUTHORIZATION, "Bearer t")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(r#"{"text":"Jarvis, tell me a joke"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    let body: Value = serde_json::from_slice(&axum::body::to_bytes(resp.into_body(), usize::MAX).await.unwrap()).unwrap();
    assert_eq!(body["suppress_llm"], true);

    release_predict.notify_one();
    let _ = task_handle.await;

    // 3. Anti-loop breaker stops after 3 identical non-wait actions with NO page progress,
    //    while allowing legitimate repeated clicks (e.g. "Next month", scrolling) when the page changes.
    let loop_bridge = FakeBridge::new(
        vec![
            pred("click", "Play", "e1", "fp1", 1),
            pred("click", "Play", "e1", "fp1", 2),
            pred("click", "Play", "e1", "fp1", 3),
        ],
        vec![
            ActResult {
                stale: false,
                executed: true,
                status: "ready".into(),
                history_len: 1,
                decision_count: 1,
                page: fake_page("https://example.test", "fp1"),
                last_action: None,
            },
            ActResult {
                stale: false,
                executed: true,
                status: "ready".into(),
                history_len: 2,
                decision_count: 2,
                page: fake_page("https://example.test", "fp1"),
                last_action: None,
            },
            ActResult {
                stale: false,
                executed: true,
                status: "ready".into(),
                history_len: 3,
                decision_count: 3,
                page: fake_page("https://example.test", "fp1"),
                last_action: None,
            },
        ],
    );
    let stuck = Broker::new(false)
        .start_task(&loop_bridge, "Stuck loop".into(), None)
        .await
        .unwrap();
    assert_eq!(stuck.status, TaskStatus::Blocked);
    assert_eq!(stuck.steps, 3);

    // Legitimate repeated clicks on same URL that DO change the page (calendar "Next month") succeed.
    let calendar_bridge = FakeBridge::new(
        vec![
            pred("click", "Next month", "e5", "fp1", 1),
            pred("click", "Next month", "e5", "fp2", 2),
            pred("click", "Next month", "e5", "fp3", 3),
            pred("click", "Next month", "e5", "fp4", 4),
            pred("done", "DONE", "DONE", "fp5", 5),
        ],
        vec![
            ActResult {
                stale: false,
                executed: true,
                status: "ready".into(),
                history_len: 1,
                decision_count: 1,
                page: fake_page("https://booking.test", "fp2"),
                last_action: None,
            },
            ActResult {
                stale: false,
                executed: true,
                status: "ready".into(),
                history_len: 2,
                decision_count: 2,
                page: fake_page("https://booking.test", "fp3"),
                last_action: None,
            },
            ActResult {
                stale: false,
                executed: true,
                status: "ready".into(),
                history_len: 3,
                decision_count: 3,
                page: fake_page("https://booking.test", "fp4"),
                last_action: None,
            },
            ActResult {
                stale: false,
                executed: true,
                status: "ready".into(),
                history_len: 4,
                decision_count: 4,
                page: fake_page("https://booking.test", "fp5"),
                last_action: None,
            },
            act_res("done", false, 4, 5, "fp5"),
        ],
    );
    let ok_cal = Broker::new(false)
        .start_task(&calendar_bridge, "Navigate to April".into(), None)
        .await
        .unwrap();
    assert_eq!(ok_cal.status, TaskStatus::Done);
    assert_eq!(ok_cal.steps, 4);
}

#[tokio::test]
async fn utterance_pipeline_executes_multi_step_sequence_in_order() {
    let (events_tx, mut events_rx) = tokio::sync::mpsc::unbounded_channel();
    let bridge: Arc<dyn BrowserBridge> = Arc::new(FakeBridge::new(vec![], vec![]));
    let app = build_router(ApiState {
        broker: Arc::new(Broker::with_events(false, events_tx)),
        bridge,
        token: Arc::new("pipe-tok".into()),
        quit_tx: None,
        chat_window_until: Arc::new(tokio::sync::Mutex::new(None)),
    });

    let resp = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/utterance")
                .header(header::AUTHORIZATION, "Bearer pipe-tok")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(r#"{"text":"search in youtube for rust then go to new tab"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(resp.status(), StatusCode::OK);

    let ev1 = tokio::time::timeout(std::time::Duration::from_secs(2), events_rx.recv())
        .await
        .unwrap()
        .unwrap();
    let ev2 = tokio::time::timeout(std::time::Duration::from_secs(2), events_rx.recv())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        ev1,
        AgentEvent::Say {
            text: "Opened YouTube search for rust.".into(),
            interrupt: false,
        }
    );
    assert_eq!(
        ev2,
        AgentEvent::Say {
            text: "Opened a new tab.".into(),
            interrupt: false,
        }
    );
}

#[tokio::test]
async fn direct_click_target_clicks_safe_gates_risky_and_falls_back_on_miss() {
    struct ClickBridge {
        match_res: Mutex<VecDeque<MatchClickResult>>,
        inner: FakeBridge,
    }

    impl BrowserBridge for ClickBridge {
        fn open(&self, g: String, u: Option<String>, b: bool) -> BoxFuture<'_, Result<PageSummary, BridgeError>> {
            self.inner.open(g, u, b)
        }
        fn predict(&self) -> BoxFuture<'_, Result<PredictResult, BridgeError>> {
            self.inner.predict()
        }
        fn act(&self, fp: String) -> BoxFuture<'_, Result<ActResult, BridgeError>> {
            self.inner.act(fp)
        }
        fn cancel(&self) -> BoxFuture<'_, Result<Option<PageSummary>, BridgeError>> {
            self.inner.cancel()
        }
        fn read_page(&self) -> BoxFuture<'_, Result<ReadPageResult, BridgeError>> {
            self.inner.read_page()
        }
        fn match_click(&self, _target: String) -> BoxFuture<'_, Result<MatchClickResult, BridgeError>> {
            Box::pin(async move {
                Ok(self.match_res.lock().unwrap().pop_front().unwrap())
            })
        }
        fn control(&self, a: String) -> BoxFuture<'_, Result<ControlResult, BridgeError>> {
            self.inner.control(a)
        }
        fn close(&self) -> BoxFuture<'_, Result<(), BridgeError>> {
            self.inner.close()
        }
    }

    let (events_tx, mut events_rx) = tokio::sync::mpsc::unbounded_channel();
    let bridge = ClickBridge {
        match_res: Mutex::new(
            vec![
                // 1. Safe match -> clicks directly with 0 predict calls
                MatchClickResult {
                    matched: true,
                    choice: "e1".into(),
                    kind: "click".into(),
                    action_label: "Accept Cookies".into(),
                    fingerprint: "fp1".into(),
                    page: fake_page("https://site.test", "fp1"),
                },
                // 2. Risky match -> pauses for confirmation before clicking
                MatchClickResult {
                    matched: true,
                    choice: "e2".into(),
                    kind: "click".into(),
                    action_label: "Buy now".into(),
                    fingerprint: "fp2".into(),
                    page: fake_page("https://site.test", "fp2"),
                },
                // 3. Miss -> falls back seamlessly to Jev predict/act
                MatchClickResult {
                    matched: false,
                    choice: String::new(),
                    kind: String::new(),
                    action_label: String::new(),
                    fingerprint: String::new(),
                    page: fake_page("https://site.test", "fp3"),
                },
            ]
            .into(),
        ),
        inner: FakeBridge::new(
            vec![pred("done", "DONE", "DONE", "fp3", 1)],
            vec![
                act_res("ready", true, 1, 1, "fp2"),
                act_res("ready", true, 1, 1, "fp3"),
                act_res("done", false, 0, 1, "fp3"),
            ],
        ),
    };

    let broker = Broker::with_events(false, events_tx);

    // 1. Safe direct click
    let r1 = broker
        .click_target(&bridge, "Accept Cookies".into(), "click Accept Cookies".into())
        .await
        .unwrap();
    assert_eq!(r1.status, TaskStatus::Done);
    assert_eq!(
        events_rx.try_recv().unwrap(),
        AgentEvent::Say {
            text: "Clicked Accept Cookies.".into(),
            interrupt: false,
        }
    );

    // 2. Risky direct click pauses for confirmation, then executes 1 step on approve without extra predict()
    let r2 = broker
        .click_target(&bridge, "Buy now".into(), "click Buy now".into())
        .await
        .unwrap();
    assert_eq!(r2.status, TaskStatus::NeedsConfirmation);
    assert_eq!(r2.pending_action.as_deref(), Some("Buy now"));
    assert_eq!(
        events_rx.try_recv().unwrap(),
        AgentEvent::NeedsConfirmation {
            action: "Buy now".into(),
        }
    );
    let r2_done = broker.confirm_task_with_narration(&bridge, true, true).await.unwrap();
    assert_eq!(r2_done.status, TaskStatus::Done);
    assert_eq!(
        events_rx.try_recv().unwrap(),
        AgentEvent::Say {
            text: "Clicked Buy now.".into(),
            interrupt: false,
        }
    );

    // 3. Miss falls back seamlessly to Jev BrowserTask
    let r3 = broker
        .click_target(&bridge, "Offscreen link".into(), "click Offscreen link".into())
        .await
        .unwrap();
    assert_eq!(r3.status, TaskStatus::Done);
}

#[tokio::test]
async fn idle_stop_does_not_block_next_pipeline_and_read_page_does_not_lock_phase() {
    struct SlowReadBridge {
        read_started: Arc<Notify>,
        release_read: Arc<Notify>,
        inner: FakeBridge,
    }

    impl BrowserBridge for SlowReadBridge {
        fn open(&self, g: String, u: Option<String>, b: bool) -> BoxFuture<'_, Result<PageSummary, BridgeError>> {
            self.inner.open(g, u, b)
        }
        fn predict(&self) -> BoxFuture<'_, Result<PredictResult, BridgeError>> {
            self.inner.predict()
        }
        fn act(&self, fp: String) -> BoxFuture<'_, Result<ActResult, BridgeError>> {
            self.inner.act(fp)
        }
        fn cancel(&self) -> BoxFuture<'_, Result<Option<PageSummary>, BridgeError>> {
            self.inner.cancel()
        }
        fn read_page(&self) -> BoxFuture<'_, Result<ReadPageResult, BridgeError>> {
            Box::pin(async move {
                self.read_started.notify_one();
                self.release_read.notified().await;
                self.inner.read_page().await
            })
        }
        fn control(&self, a: String) -> BoxFuture<'_, Result<ControlResult, BridgeError>> {
            self.inner.control(a)
        }
        fn close(&self) -> BoxFuture<'_, Result<(), BridgeError>> {
            self.inner.close()
        }
    }

    // 1. read_page must not hold broker.phase locked while awaiting bridge I/O.
    let read_started = Arc::new(Notify::new());
    let release_read = Arc::new(Notify::new());
    let slow = Arc::new(SlowReadBridge {
        read_started: read_started.clone(),
        release_read: release_read.clone(),
        inner: FakeBridge::new(vec![], vec![]),
    });
    let (events_tx, mut events_rx) = tokio::sync::mpsc::unbounded_channel();
    let broker = Arc::new(Broker::with_events(false, events_tx));

    let b_read = broker.clone();
    let s_read = slow.clone();
    let read_task = tokio::spawn(async move { b_read.read_page(s_read.as_ref()).await });
    read_started.notified().await;

    // Must complete immediately (never deadlock waiting for read_page).
    let running = tokio::time::timeout(std::time::Duration::from_millis(200), broker.is_running())
        .await
        .expect("is_running should not block during read_page");
    assert!(!running);
    release_read.notify_one();
    assert!(read_task.await.unwrap().is_ok());

    // 2. Idle "stop" followed by a Pipeline utterance must execute the full pipeline cleanly.
    let app = build_router(ApiState {
        broker: broker.clone(),
        bridge: slow,
        token: Arc::new("stop-pipe-tok".into()),
        quit_tx: None,
        chat_window_until: Arc::new(tokio::sync::Mutex::new(None)),
    });
    let stop_resp = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/utterance")
                .header(header::AUTHORIZATION, "Bearer stop-pipe-tok")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(r#"{"text":"stop"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(stop_resp.status(), StatusCode::OK);
    // Drain Silence event emitted by idle stop.
    let ev0 = tokio::time::timeout(std::time::Duration::from_secs(1), events_rx.recv())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(ev0, AgentEvent::Silence);

    let pipe_resp = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/utterance")
                .header(header::AUTHORIZATION, "Bearer stop-pipe-tok")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(r#"{"text":"search youtube for rust then go to new tab"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(pipe_resp.status(), StatusCode::OK);
    let ev1 = tokio::time::timeout(std::time::Duration::from_secs(2), events_rx.recv())
        .await
        .unwrap()
        .unwrap();
    let ev2 = tokio::time::timeout(std::time::Duration::from_secs(2), events_rx.recv())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        ev1,
        AgentEvent::Say {
            text: "Opened YouTube search for rust.".into(),
            interrupt: false,
        }
    );
    assert_eq!(
        ev2,
        AgentEvent::Say {
            text: "Opened a new tab.".into(),
            interrupt: false,
        }
    );
}

#[tokio::test]
async fn stdio_bridge_timeout_kills_desynced_child_so_next_call_succeeds() {
    let dir = std::env::temp_dir().join(format!("jarvis_timeout_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let script = dir.join("flaky_timeout_bridge.py");
    let marker = dir.join("saw_first.flag");
    let _ = std::fs::remove_file(&marker);
    std::fs::write(
        &script,
        format!(
            "import json, os, sys, time\nflag = r'{}'\nfor line in sys.stdin:\n    req = json.loads(line)\n    if not os.path.exists(flag):\n        open(flag, 'w').write('1')\n        time.sleep(1.5)\n    sys.stdout.write(json.dumps({{'id': req['id'], 'ok': True, 'pid': os.getpid()}}) + '\\n')\n    sys.stdout.flush()\n",
            marker.display()
        ),
    )
    .unwrap();

    let python = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("borwse harness")
        .join("jev-ultrafast")
        .join(".venv")
        .join(if cfg!(windows) { "Scripts\\python.exe" } else { "bin/python" });
    let bridge = StdioBridge::new(python, script.clone(), dir.clone())
        .with_timeout(std::time::Duration::from_millis(250));

    let err = bridge.ping().await.unwrap_err();
    assert_eq!(err.code, "bridge_timeout");
    // Child was killed & dropped on timeout, so the next ping spawns a clean child and succeeds.
    let pid = bridge.ping().await.expect("second ping after timeout should recover");
    assert!(pid > 0);
    let _ = bridge.close().await;
    let _ = std::fs::remove_dir_all(&dir);
}

#[tokio::test]
async fn approved_risky_action_stale_retry_does_not_reprompt_and_media_control_runs_while_busy() {
    // 1. User confirms "Send message", act() hits stale=true, next predict() picks "Send message" again
    // -> executes without re-asking confirmation, then finishes Done.
    let bridge = FakeBridge::new(
        vec![
            pred("click", "Send message", "e1", "fp1", 1),
            pred("click", "Send message", "e1", "fp2", 2),
            pred("done", "DONE", "DONE", "fp3", 3),
        ],
        vec![
            ActResult {
                stale: true,
                executed: false,
                status: "ready".into(),
                history_len: 0,
                decision_count: 1,
                page: fake_page("https://chatgpt.com", "fp2"),
                last_action: None,
            },
            act_res("ready", true, 1, 2, "fp3"),
            act_res("done", false, 1, 3, "fp3"),
        ],
    );
    let broker = Broker::new(false);
    let paused = broker
        .start_task(&bridge, "Send message".into(), None)
        .await
        .unwrap();
    assert_eq!(paused.status, TaskStatus::NeedsConfirmation);
    let done = broker.confirm_task(&bridge, true).await.unwrap();
    assert_eq!(done.status, TaskStatus::Done);
    assert_eq!(bridge.act_calls.load(Ordering::SeqCst), 3);

    // 2. While a task is running, safe media controls ("pause_video") execute immediately, while navigation ("back") gets task_busy.
    let predict_started = Arc::new(Notify::new());
    let release_predict = Arc::new(Notify::new());
    let running_bridge = Arc::new(FakeBridge {
        predicts: Mutex::new(vec![pred("done", "DONE", "DONE", "fp1", 1)].into()),
        acts: Mutex::new(vec![act_res("done", false, 0, 1, "fp1")].into()),
        act_calls: AtomicUsize::new(0),
        cancel_calls: AtomicUsize::new(0),
        predict_started: Some(predict_started.clone()),
        release_predict: Some(release_predict.clone()),
    });
    let broker2 = Arc::new(Broker::new(false));
    let b2 = broker2.clone();
    let br2 = running_bridge.clone();
    let task = tokio::spawn(async move { b2.start_task(br2.as_ref(), "Watch video".into(), None).await });
    predict_started.notified().await;

    let pause_ok = broker2.control(running_bridge.as_ref(), "pause_video").await;
    assert!(pause_ok.is_ok(), "pause_video should work while a task is running");
    let back_err = broker2.control(running_bridge.as_ref(), "back").await.unwrap_err();
    assert_eq!(back_err.code, "task_busy");

    release_predict.notify_one();
    assert_eq!(task.await.unwrap().unwrap().status, TaskStatus::Done);
}

#[tokio::test]
async fn generic_search_uses_active_searchable_site_after_open() {
    let (events_tx, mut events_rx) = tokio::sync::mpsc::unbounded_channel();
    let bridge: Arc<dyn BrowserBridge> = Arc::new(FakeBridge::new(vec![], vec![]));
    let app = build_router(ApiState {
        broker: Arc::new(Broker::with_events(false, events_tx)),
        bridge,
        token: Arc::new("ctx-tok".into()),
        quit_tx: None,
        chat_window_until: Arc::new(tokio::sync::Mutex::new(None)),
    });

    // 1. Open YouTube
    let r1 = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/utterance")
                .header(header::AUTHORIZATION, "Bearer ctx-tok")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(r#"{"text":"open youtube"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(r1.status(), StatusCode::OK);
    let ev1 = tokio::time::timeout(std::time::Duration::from_secs(2), events_rx.recv())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        ev1,
        AgentEvent::Say {
            text: "Opened YouTube.".into(),
            interrupt: false,
        }
    );

    // 2. Generic "search mrbeast" while on YouTube searches YouTube instead of Google!
    let r2 = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/utterance")
                .header(header::AUTHORIZATION, "Bearer ctx-tok")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(r#"{"text":"search mrbeast"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(r2.status(), StatusCode::OK);
    let ev2 = tokio::time::timeout(std::time::Duration::from_secs(2), events_rx.recv())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        ev2,
        AgentEvent::Say {
            text: "Opened YouTube search for mrbeast.".into(),
            interrupt: false,
        }
    );

    // 3. Explicit "google mrbeast" still searches Google even when on YouTube.
    let r3 = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/utterance")
                .header(header::AUTHORIZATION, "Bearer ctx-tok")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(r#"{"text":"google mrbeast"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(r3.status(), StatusCode::OK);
    let ev3 = tokio::time::timeout(std::time::Duration::from_secs(2), events_rx.recv())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        ev3,
        AgentEvent::Say {
            text: "Opened Google search for mrbeast.".into(),
            interrupt: false,
        }
    );
}

#[tokio::test]
async fn pipeline_guard_blocks_concurrent_utterances_and_stop_aborts_open_url() {
    struct DelayedOpenBridge {
        started: Arc<Notify>,
        release: Arc<Notify>,
    }

    impl BrowserBridge for DelayedOpenBridge {
        fn open(
            &self,
            _goal: String,
            url: Option<String>,
            _background: bool,
        ) -> BoxFuture<'_, Result<PageSummary, BridgeError>> {
            let started = self.started.clone();
            let release = self.release.clone();
            Box::pin(async move {
                started.notify_one();
                release.notified().await;
                Ok(fake_page(
                    url.as_deref().unwrap_or("https://www.google.com"),
                    "fp0",
                ))
            })
        }
        fn predict(&self) -> BoxFuture<'_, Result<PredictResult, BridgeError>> {
            Box::pin(async { Err(BridgeError::new("unused", "unused")) })
        }
        fn act(&self, _fingerprint: String) -> BoxFuture<'_, Result<ActResult, BridgeError>> {
            Box::pin(async { Err(BridgeError::new("unused", "unused")) })
        }
        fn cancel(&self) -> BoxFuture<'_, Result<Option<PageSummary>, BridgeError>> {
            Box::pin(async { Ok(None) })
        }
        fn read_page(&self) -> BoxFuture<'_, Result<ReadPageResult, BridgeError>> {
            Box::pin(async { Err(BridgeError::new("unused", "unused")) })
        }
        fn control(&self, action: String) -> BoxFuture<'_, Result<ControlResult, BridgeError>> {
            Box::pin(async move {
                Ok(ControlResult {
                    action,
                    closed: false,
                    page: None,
                    message: None,
                })
            })
        }
        fn close(&self) -> BoxFuture<'_, Result<(), BridgeError>> {
            Box::pin(async { Ok(()) })
        }
    }

    let (events_tx, mut events_rx) = tokio::sync::mpsc::unbounded_channel();
    let started = Arc::new(Notify::new());
    let release = Arc::new(Notify::new());
    let broker = Arc::new(Broker::with_events(false, events_tx));
    let bridge: Arc<dyn BrowserBridge> = Arc::new(DelayedOpenBridge {
        started: started.clone(),
        release: release.clone(),
    });

    // 1. Holding a PipelineGuard blocks concurrent utterances even when BrokerPhase is Idle.
    let guard = broker.try_start_pipeline().expect("acquire pipeline guard");
    assert!(broker.is_running().await);
    let app = build_router(ApiState {
        broker: broker.clone(),
        bridge: bridge.clone(),
        token: Arc::new("pipe-tok".into()),
        quit_tx: None,
        chat_window_until: Arc::new(tokio::sync::Mutex::new(None)),
    });
    let resp = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/utterance")
                .header(header::AUTHORIZATION, "Bearer pipe-tok")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(r#"{"text":"open youtube"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let busy_ev = events_rx.recv().await.unwrap();
    assert_eq!(
        busy_ev,
        AgentEvent::Say {
            text: "Still working on the last task. Say stop to cancel.".into(),
            interrupt: false,
        }
    );
    drop(guard);
    assert!(!broker.is_running().await);

    // 2. Requesting stop while open_url is awaiting emits AgentEvent::Stopped instead of Opened.
    let b = broker.clone();
    let br = bridge.clone();
    let handle = tokio::spawn(async move {
        b.open_url(
            br.as_ref(),
            "Open Google".into(),
            "https://www.google.com".into(),
            "Google".into(),
            false,
        )
        .await
    });
    started.notified().await;
    broker.request_stop();
    release.notify_one();
    let err = handle.await.unwrap().unwrap_err();
    assert_eq!(err.code, "stopped");
    let stop_ev = events_rx.recv().await.unwrap();
    assert_eq!(stop_ev, AgentEvent::Stopped);
}

