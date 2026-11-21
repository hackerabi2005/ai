use crate::broker::AgentEvent;
use http_body_util::{BodyExt, Full};
use hyper::body::Bytes;
use hyper::client::conn::http1::SendRequest;
use hyper::{Method, Request};
use hyper_util::rt::TokioIo;
use serde_json::json;
use std::future::Future;
use std::pin::Pin;
use std::time::{Duration, Instant};
use tokio::net::TcpStream;
use tokio::sync::{mpsc, Mutex};
use tracing::{debug, warn};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Priority {
    Normal,
    High,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NarrationLine {
    pub text: String,
    pub priority: Priority,
    pub interrupt: bool,
}

pub fn friendly_site_name(url: &str, title: &str) -> String {
    let lower = url.to_ascii_lowercase();
    if lower.contains("youtube.com/shorts") {
        return "YouTube Shorts".to_string();
    }
    if lower.contains("google.com/travel/flights") {
        return "Google Flights".to_string();
    }
    if lower.contains("maps.google.") || lower.contains("google.com/maps") {
        return "Google Maps".to_string();
    }
    if lower.contains("mail.google.com") {
        return "Gmail".to_string();
    }
    if let Some(host) = lower
        .split("://")
        .nth(1)
        .and_then(|rest| rest.split('/').next())
    {
        for (needle, name) in [
            ("youtube.com", "YouTube"),
            ("youtu.be", "YouTube"),
            ("wikipedia.org", "Wikipedia"),
            ("github.com", "GitHub"),
            ("huggingface.co", "Hugging Face"),
            ("reddit.com", "Reddit"),
            ("amazon.", "Amazon"),
            ("netflix.com", "Netflix"),
            ("spotify.com", "Spotify"),
            ("linkedin.com", "LinkedIn"),
            ("x.com", "X"),
            ("twitter.com", "X"),
            ("news.ycombinator.com", "Hacker News"),
            ("booking.com", "Booking.com"),
            ("airbnb.", "Airbnb"),
            ("expedia.", "Expedia"),
            ("kayak.", "Kayak"),
            ("skyscanner.", "Skyscanner"),
            ("tripadvisor.", "TripAdvisor"),
            ("hotels.com", "Hotels.com"),
            ("agoda.com", "Agoda"),
            ("makemytrip.com", "MakeMyTrip"),
            ("ubereats.com", "Uber Eats"),
            ("uber.com", "Uber"),
            ("opentable.com", "OpenTable"),
            ("walmart.com", "Walmart"),
            ("bestbuy.com", "Best Buy"),
            ("etsy.com", "Etsy"),
            ("ebay.", "eBay"),
            ("flipkart.com", "Flipkart"),
            ("yelp.com", "Yelp"),
            ("doordash.com", "DoorDash"),
            ("zomato.com", "Zomato"),
            ("swiggy.com", "Swiggy"),
            ("scholar.google.", "Google Scholar"),
            ("news.google.", "Google News"),
            ("translate.google.", "Google Translate"),
            ("calendar.google.", "Google Calendar"),
            ("arxiv.org", "arXiv"),
            ("stackoverflow.com", "Stack Overflow"),
            ("developer.mozilla.org", "MDN"),
            ("gemini.google.com", "Gemini"),
            ("claude.ai", "Claude"),
            ("chatgpt.com", "ChatGPT"),
            ("perplexity.ai", "Perplexity"),
            ("chat.deepseek.com", "DeepSeek"),
            ("grok.com", "Grok"),
            ("google.", "Google"),
        ] {
            if host.contains(needle) {
                return name.to_string();
            }
        }
        let clean_title = title.trim();
        if !clean_title.is_empty() {
            return truncate_chars(clean_title, 55);
        }
        return host.trim_start_matches("www.").to_string();
    }
    let clean_title = title.trim();
    if !clean_title.is_empty() {
        truncate_chars(clean_title, 55)
    } else {
        "the page".to_string()
    }
}

fn clean_spoken_title(title: &str) -> String {
    let base = title
        .trim()
        .trim_end_matches(" - YouTube")
        .split('|')
        .next()
        .unwrap_or("")
        .trim();
    let ascii: String = base
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || matches!(c, ' ' | '\'' | '-' | ',' | '.' | '&' | ':') {
                c
            } else {
                ' '
            }
        })
        .collect();
    let compact = ascii.split_whitespace().collect::<Vec<_>>().join(" ");
    let trimmed = compact.trim_matches(|c: char| !c.is_ascii_alphanumeric()).trim();
    if trimmed.len() >= 2 {
        truncate_chars(trimmed, 50)
    } else {
        String::new()
    }
}

fn truncate_chars(s: &str, max_chars: usize) -> String {
    let mut out: String = s.chars().take(max_chars).collect();
    if s.chars().count() > max_chars {
        out.push_str("...");
    }
    out
}

pub struct NarratorPolicy {
    cooldown: Duration,
    last_spoken_at: Option<Instant>,
    last_site_announced: Option<String>,
    fill_burst_announced: bool,
    pending: Option<NarrationLine>,
}

impl NarratorPolicy {
    pub fn new(cooldown: Duration) -> Self {
        Self {
            cooldown,
            last_spoken_at: None,
            last_site_announced: None,
            fill_burst_announced: false,
            pending: None,
        }
    }

    /// Convert an AgentEvent into an optional candidate line and update pending/burst state.
    pub fn push_event(&mut self, event: AgentEvent, now: Instant) -> Option<NarrationLine> {
        let candidate = match event {
            AgentEvent::Ready => Some(NarrationLine {
                text: "Jarvis ready.".to_string(),
                priority: Priority::High,
                interrupt: false,
            }),
            AgentEvent::TaskAccepted { ack } => {
                self.last_site_announced = None;
                self.fill_burst_announced = false;
                Some(NarrationLine {
                    text: ack,
                    priority: Priority::Normal,
                    interrupt: false,
                })
            }
            AgentEvent::PageLoaded { url, title } => {
                self.fill_burst_announced = false;
                let site = friendly_site_name(&url, &title);
                if self.last_site_announced.as_deref() == Some(site.as_str()) {
                    None
                } else {
                    self.last_site_announced = Some(site.clone());
                    Some(NarrationLine {
                        text: format!("Opened {site}."),
                        priority: Priority::Normal,
                        interrupt: false,
                    })
                }
            }
            AgentEvent::TextTyped { field, value } => {
                if self.fill_burst_announced {
                    None
                } else {
                    self.fill_burst_announced = true;
                    let text = match value {
                        Some(v) if !v.trim().is_empty() => {
                            format!("Typed {}.", truncate_chars(v.trim(), 32))
                        }
                        _ if !field.trim().is_empty() => {
                            format!("Filling {}.", truncate_chars(field.trim(), 32))
                        }
                        _ => "Typing.".to_string(),
                    };
                    Some(NarrationLine {
                        text,
                        priority: Priority::Normal,
                        interrupt: false,
                    })
                }
            }
            AgentEvent::NeedsConfirmation { action } => Some(NarrationLine {
                text: format!("I'm about to {action}. Say yes or no."),
                priority: Priority::High,
                interrupt: true,
            }),
            AgentEvent::Done { url, title } => {
                let site = friendly_site_name(&url, &title);
                let spoken_title = clean_spoken_title(&title);
                let text = if spoken_title.is_empty() {
                    format!("Done on {site}.")
                } else {
                    format!("Done. {spoken_title}.")
                };
                Some(NarrationLine {
                    text,
                    priority: Priority::High,
                    interrupt: false,
                })
            }
            AgentEvent::Blocked { reason } => Some(NarrationLine {
                text: format!("I couldn't continue. {reason}"),
                priority: Priority::High,
                interrupt: false,
            }),
            AgentEvent::Stopped => {
                self.pending = None;
                Some(NarrationLine {
                    text: "Stopped.".to_string(),
                    priority: Priority::High,
                    interrupt: true,
                })
            }
            AgentEvent::Error { code, message } => {
                if matches!(code.as_str(), "task_busy" | "confirmation_pending") {
                    debug!("Browser busy ({code}): {message}");
                } else {
                    warn!("Browser error ({code}): {message}");
                }
                let text = match code.as_str() {
                    "task_busy" => "Still working on the last task. Say stop to cancel.".to_string(),
                    "confirmation_pending" => "Say yes or no first, or say stop.".to_string(),
                    "chrome_not_ready" => {
                        "Chrome isn't ready. Open Chrome and allow debugging.".to_string()
                    }
                    "missing_key" => "An API key is missing.".to_string(),
                    "bridge_crashed" | "bridge_timeout" => {
                        "I lost the browser connection.".to_string()
                    }
                    _ => "Something went wrong in the browser.".to_string(),
                };
                Some(NarrationLine {
                    text,
                    priority: Priority::High,
                    interrupt: false,
                })
            }
            AgentEvent::Say { text, interrupt } => Some(NarrationLine {
                text,
                priority: Priority::High,
                interrupt,
            }),
            AgentEvent::Silence => {
                self.pending = None;
                return None;
            }
        }?;

        // Newer candidate always supersedes any unspoken queued line.
        self.pending = Some(candidate);
        self.take_ready(now)
    }

    pub fn next_deadline(&self) -> Option<Instant> {
        let line = self.pending.as_ref()?;
        if line.priority == Priority::Normal {
            if let Some(last) = self.last_spoken_at {
                return Some(last + self.cooldown);
            }
        }
        Some(Instant::now())
    }

    pub fn take_ready(&mut self, now: Instant) -> Option<NarrationLine> {
        let line = self.pending.as_ref()?;
        if line.priority == Priority::Normal {
            if let Some(last) = self.last_spoken_at {
                if now.duration_since(last) < self.cooldown {
                    return None;
                }
            }
        }
        let line = self.pending.take()?;
        self.last_spoken_at = Some(now);
        Some(line)
    }
}

pub type BoxFuture<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SayStatus {
    Spoken,
    RetryableBusy,
    Failed,
}

pub trait SaySink: Send + Sync {
    fn say(&self, text: String, interrupt: bool) -> BoxFuture<'_, bool>;
    fn say_status(&self, text: String, interrupt: bool) -> BoxFuture<'_, SayStatus> {
        Box::pin(async move {
            if self.say(text, interrupt).await {
                SayStatus::Spoken
            } else {
                SayStatus::Failed
            }
        })
    }
}

pub struct HttpSaySink {
    addr: String,
    token: String,
    conn: Mutex<Option<SendRequest<Full<Bytes>>>>,
}

impl HttpSaySink {
    pub fn new(addr: impl Into<String>, token: impl Into<String>) -> Self {
        Self {
            addr: addr.into(),
            token: token.into(),
            conn: Mutex::new(None),
        }
    }

    async fn connect(&self) -> Option<SendRequest<Full<Bytes>>> {
        let stream = match TcpStream::connect(&self.addr).await {
            Ok(s) => s,
            Err(e) => {
                debug!("s2s say connect failed ({}): {e}", self.addr);
                return None;
            }
        };
        let io = TokioIo::new(stream);
        let (sender, conn) = match hyper::client::conn::http1::handshake(io).await {
            Ok(pair) => pair,
            Err(e) => {
                debug!("s2s say handshake failed: {e}");
                return None;
            }
        };
        tokio::spawn(async move {
            let _ = conn.await;
        });
        Some(sender)
    }

    async fn post_say(&self, text: String, interrupt: bool) -> SayStatus {
        let body_bytes = Bytes::from(
            json!({"text": text, "interrupt": interrupt})
                .to_string()
                .into_bytes(),
        );
        let mut guard = self.conn.lock().await;

        for attempt in 0..2 {
            let mut reused = false;
            if let Some(sender) = guard.as_mut() {
                if !sender.is_closed() && sender.ready().await.is_ok() {
                    reused = true;
                } else {
                    *guard = None;
                }
            }
            if guard.is_none() {
                let Some(sender) = self.connect().await else {
                    return SayStatus::Failed;
                };
                *guard = Some(sender);
            }

            let req = match Request::builder()
                .method(Method::POST)
                .uri("/v1/say")
                .header("Host", &self.addr)
                .header("Content-Type", "application/json")
                .header("Authorization", format!("Bearer {}", self.token))
                .body(Full::new(body_bytes.clone()))
            {
                Ok(r) => r,
                Err(_) => return SayStatus::Failed,
            };

            let sender = guard.as_mut().expect("connected above");
            match tokio::time::timeout(Duration::from_secs(3), sender.send_request(req)).await {
                Ok(Ok(resp)) => {
                    let status = resp.status();
                    let _ = resp.into_body().collect().await;
                    if status.is_success() {
                        return SayStatus::Spoken;
                    }
                    debug!("s2s /v1/say returned {status}");
                    if matches!(status.as_u16(), 409 | 503) {
                        return SayStatus::RetryableBusy;
                    }
                    return SayStatus::Failed;
                }
                Ok(Err(e)) => {
                    *guard = None;
                    if reused && attempt == 0 {
                        continue;
                    }
                    warn!("s2s /v1/say request error: {e}");
                    return SayStatus::Failed;
                }
                Err(_) => {
                    *guard = None;
                    warn!("s2s /v1/say request timed out");
                    return SayStatus::Failed;
                }
            }
        }
        SayStatus::Failed
    }
}

impl SaySink for HttpSaySink {
    fn say(&self, text: String, interrupt: bool) -> BoxFuture<'_, bool> {
        Box::pin(async move { self.post_say(text, interrupt).await == SayStatus::Spoken })
    }

    fn say_status(&self, text: String, interrupt: bool) -> BoxFuture<'_, SayStatus> {
        Box::pin(async move { self.post_say(text, interrupt).await })
    }
}

pub async fn run_narrator(
    mut rx: mpsc::UnboundedReceiver<AgentEvent>,
    sink: std::sync::Arc<dyn SaySink>,
) {
    let mut policy = NarratorPolicy::new(Duration::from_secs(2));
    let mut queued_event: Option<AgentEvent> = None;

    loop {
        let maybe_line = if let Some(ev) = queued_event.take() {
            policy.push_event(ev, Instant::now())
        } else {
            match policy.next_deadline() {
                Some(deadline) => tokio::select! {
                    ev = rx.recv() => match ev {
                        Some(e) => policy.push_event(e, Instant::now()),
                        None => break,
                    },
                    _ = tokio::time::sleep_until(tokio::time::Instant::from_std(deadline)) => {
                        policy.take_ready(Instant::now())
                    }
                },
                None => match rx.recv().await {
                    Some(e) => policy.push_event(e, Instant::now()),
                    None => break,
                },
            }
        };

        if let Some(line) = maybe_line {
            let mut status = sink.say_status(line.text.clone(), line.interrupt).await;
            if status == SayStatus::RetryableBusy && line.priority == Priority::High {
                // Brief interruptible retry so high-priority announcements ("Done.", "Blocked.") aren't
                // silently dropped when "On it." is still finishing playback (HTTP 409).
                for _ in 0..4 {
                    tokio::select! {
                        ev = rx.recv() => {
                            match ev {
                                Some(e) => { queued_event = Some(e); break; }
                                None => return,
                            }
                        }
                        _ = tokio::time::sleep(Duration::from_millis(350)) => {}
                    }
                    status = sink.say_status(line.text.clone(), line.interrupt).await;
                    if status != SayStatus::RetryableBusy {
                        break;
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn site_mapping_and_cooldown_and_replace_stale() {
        let t0 = Instant::now();
        let mut p = NarratorPolicy::new(Duration::from_secs(2));

        // First normal line fires immediately.
        let l1 = p.push_event(
            AgentEvent::TaskAccepted {
                ack: "Opening YouTube.".into(),
            },
            t0,
        );
        assert_eq!(l1.unwrap().text, "Opening YouTube.");

        // Second normal line within 2s is deferred; third replaces second.
        let l2 = p.push_event(
            AgentEvent::PageLoaded {
                url: "https://example.com".into(),
                title: "Intermediate".into(),
            },
            t0 + Duration::from_millis(500),
        );
        assert!(l2.is_none());

        let l3 = p.push_event(
            AgentEvent::PageLoaded {
                url: "https://www.youtube.com/watch?v=1".into(),
                title: "Video - YouTube".into(),
            },
            t0 + Duration::from_millis(900),
        );
        assert!(l3.is_none());

        // After 2s cooldown expires, only the latest line ("Opened YouTube.") emits.
        assert_eq!(p.next_deadline(), Some(t0 + Duration::from_secs(2)));
        let ready = p.take_ready(t0 + Duration::from_millis(2100));
        assert_eq!(ready.unwrap().text, "Opened YouTube.");
        assert!(p.next_deadline().is_none());

        // Duplicate PageLoaded on same site is suppressed.
        let dup = p.push_event(
            AgentEvent::PageLoaded {
                url: "https://www.youtube.com/results?q=abc".into(),
                title: "Search - YouTube".into(),
            },
            t0 + Duration::from_secs(5),
        );
        assert!(dup.is_none());
    }

    #[test]
    fn fill_burst_collapses_and_stop_bypasses_cooldown_and_clears_pending() {
        let t0 = Instant::now();
        let mut p = NarratorPolicy::new(Duration::from_secs(2));

        let f1 = p.push_event(
            AgentEvent::TextTyped {
                field: "Where from".into(),
                value: Some("Zurich".into()),
            },
            t0,
        );
        assert_eq!(f1.unwrap().text, "Typed Zurich.");

        let f2 = p.push_event(
            AgentEvent::TextTyped {
                field: "Where to".into(),
                value: Some("London".into()),
            },
            t0 + Duration::from_secs(3),
        );
        assert!(f2.is_none());

        // Queue a pending page load within cooldown, then stop -> clears pending & speaks immediately.
        assert!(p
            .push_event(
                AgentEvent::PageLoaded {
                    url: "https://en.wikipedia.org".into(),
                    title: "Wikipedia".into(),
                },
                t0 + Duration::from_millis(200),
            )
            .is_none());

        let stop = p.push_event(AgentEvent::Stopped, t0 + Duration::from_millis(300));
        let stop = stop.unwrap();
        assert_eq!(stop.text, "Stopped.");
        assert!(stop.interrupt);
        assert!(p.take_ready(t0 + Duration::from_secs(10)).is_none());

        // Non-ASCII / pipe clutter in video titles is stripped cleanly for English TTS.
        let done = p
            .push_event(
                AgentEvent::Done {
                    url: "https://www.youtube.com/watch?v=abc".into(),
                    title: "Ramayana | ரூ.3000 கோடி - இந்தியாவையே - YouTube".into(),
                },
                t0 + Duration::from_secs(4),
            )
            .unwrap();
        assert_eq!(done.text, "Done. Ramayana.");

        // Routine busy / confirmation errors get helpful speech instead of "Something went wrong".
        let busy = p
            .push_event(
                AgentEvent::Error {
                    code: "task_busy".into(),
                    message: "busy".into(),
                },
                t0 + Duration::from_secs(5),
            )
            .unwrap();
        assert_eq!(busy.text, "Still working on the last task. Say stop to cancel.");
    }

    #[tokio::test]
    async fn run_narrator_retries_high_priority_on_busy_and_supersedes_on_new_event() {
        use std::sync::atomic::{AtomicUsize, Ordering};
        use std::sync::{Arc, Mutex as StdMutex};
        use tokio::sync::Notify;

        struct BusyThenOkSink {
            attempts: AtomicUsize,
            spoken: StdMutex<Vec<String>>,
            done: Arc<Notify>,
        }

        impl SaySink for BusyThenOkSink {
            fn say(&self, _text: String, _interrupt: bool) -> BoxFuture<'_, bool> {
                Box::pin(async { true })
            }
            fn say_status(&self, text: String, _interrupt: bool) -> BoxFuture<'_, SayStatus> {
                Box::pin(async move {
                    let n = self.attempts.fetch_add(1, Ordering::SeqCst);
                    if n == 0 {
                        return SayStatus::RetryableBusy;
                    }
                    self.spoken.lock().unwrap().push(text);
                    self.done.notify_one();
                    SayStatus::Spoken
                })
            }
        }

        // 1. Retries high-priority Done after transient HTTP 409 busy and delivers it.
        let done = Arc::new(Notify::new());
        let sink = Arc::new(BusyThenOkSink {
            attempts: AtomicUsize::new(0),
            spoken: StdMutex::new(Vec::new()),
            done: done.clone(),
        });
        let (tx, rx) = mpsc::unbounded_channel();
        let handle = tokio::spawn(run_narrator(rx, sink.clone()));
        tx.send(AgentEvent::Done {
            url: "https://en.wikipedia.org/wiki/Apple".into(),
            title: "Apple - Wikipedia".into(),
        })
        .unwrap();
        tokio::time::timeout(Duration::from_secs(2), done.notified())
            .await
            .expect("retry should deliver Done line");
        drop(tx);
        handle.await.unwrap();
        assert_eq!(sink.attempts.load(Ordering::SeqCst), 2);
        assert_eq!(*sink.spoken.lock().unwrap(), vec!["Done. Apple - Wikipedia."]);

        // 2. A newer event arriving during retry wait supersedes the old line immediately.
        let done2 = Arc::new(Notify::new());
        let sink2 = Arc::new(BusyThenOkSink {
            attempts: AtomicUsize::new(0),
            spoken: StdMutex::new(Vec::new()),
            done: done2.clone(),
        });
        let (tx2, rx2) = mpsc::unbounded_channel();
        let handle2 = tokio::spawn(run_narrator(rx2, sink2.clone()));
        tx2.send(AgentEvent::Done {
            url: "https://en.wikipedia.org/wiki/Apple".into(),
            title: "Apple - Wikipedia".into(),
        })
        .unwrap();
        tokio::time::sleep(Duration::from_millis(50)).await;
        tx2.send(AgentEvent::Stopped).unwrap();
        tokio::time::timeout(Duration::from_secs(2), done2.notified())
            .await
            .expect("newer Stopped event should supersede retry");
        drop(tx2);
        handle2.await.unwrap();
        assert_eq!(*sink2.spoken.lock().unwrap(), vec!["Stopped."]);
    }
}
