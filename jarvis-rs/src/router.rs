use regex::Regex;
use std::sync::LazyLock;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RouteAction {
    Ignore,
    Quit,
    Stop,
    Confirm(bool),
    Control(String),
    ReadPage,
    OpenUrl {
        goal: String,
        url: String,
        site_name: String,
        new_tab: bool,
    },
    ClickTarget {
        target: String,
        goal: String,
    },
    BrowserTask {
        goal: String,
        url: Option<String>,
        ack: String,
        new_tab: bool,
    },
    Pipeline(Vec<RouteAction>),
    Chat,
}

#[derive(Debug, Clone, Copy)]
struct SiteEntry {
    aliases: &'static [&'static str],
    name: &'static str,
    url: &'static str,
    search_url: Option<&'static str>,
}

const SITES: &[SiteEntry] = &[
    SiteEntry {
        aliases: &["google flights", "flights"],
        name: "Google Flights",
        url: "https://www.google.com/travel/flights?hl=en",
        search_url: None,
    },
    SiteEntry {
        aliases: &["google maps", "maps"],
        name: "Google Maps",
        url: "https://maps.google.com",
        search_url: Some("https://www.google.com/maps/search/{q}"),
    },
    SiteEntry {
        aliases: &[
            "youtube shorts",
            "youtube shots",
            "you tube shorts",
            "you tube shots",
            "shorts",
        ],
        name: "YouTube Shorts",
        url: "https://www.youtube.com/shorts",
        search_url: None,
    },
    SiteEntry {
        aliases: &["youtube", "you tube", "utube", "u tube"],
        name: "YouTube",
        url: "https://www.youtube.com",
        search_url: Some("https://www.youtube.com/results?search_query={q}"),
    },
    SiteEntry {
        aliases: &["wikipedia", "wiki pedia", "wifipedia", "wifi pedia", "wiki"],
        name: "Wikipedia",
        url: "https://en.wikipedia.org",
        search_url: Some("https://en.wikipedia.org/w/index.php?search={q}"),
    },
    SiteEntry {
        aliases: &["gmail", "g mail", "gee mail"],
        name: "Gmail",
        url: "https://mail.google.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["github", "git hub"],
        name: "GitHub",
        url: "https://github.com",
        search_url: Some("https://github.com/search?q={q}"),
    },
    SiteEntry {
        aliases: &[
            "huggingface",
            "hugging face",
            "hacking face",
            "hacking phase",
            "hacking page",
        ],
        name: "Hugging Face",
        url: "https://huggingface.co",
        search_url: Some("https://huggingface.co/search/full-text?q={q}"),
    },
    SiteEntry {
        aliases: &["google scholar"],
        name: "Google Scholar",
        url: "https://scholar.google.com",
        search_url: Some("https://scholar.google.com/scholar?q={q}"),
    },
    SiteEntry {
        aliases: &["google news"],
        name: "Google News",
        url: "https://news.google.com",
        search_url: Some("https://news.google.com/search?q={q}"),
    },
    SiteEntry {
        aliases: &["google translate"],
        name: "Google Translate",
        url: "https://translate.google.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["google calendar"],
        name: "Google Calendar",
        url: "https://calendar.google.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["google", "goo gle"],
        name: "Google",
        url: "https://www.google.com",
        search_url: Some("https://www.google.com/search?q={q}"),
    },
    SiteEntry {
        aliases: &["reddit"],
        name: "Reddit",
        url: "https://www.reddit.com",
        search_url: Some("https://www.reddit.com/search/?q={q}"),
    },
    SiteEntry {
        aliases: &["amazon", "ama zon"],
        name: "Amazon",
        url: "https://www.amazon.com",
        search_url: Some("https://www.amazon.com/s?k={q}"),
    },
    SiteEntry {
        aliases: &["netflix", "net flix"],
        name: "Netflix",
        url: "https://www.netflix.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["spotify", "spot ify"],
        name: "Spotify",
        url: "https://open.spotify.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["linkedin", "linked in"],
        name: "LinkedIn",
        url: "https://www.linkedin.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["twitter", "x.com"],
        name: "X",
        url: "https://x.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["hacker news", "hackernews"],
        name: "Hacker News",
        url: "https://news.ycombinator.com",
        search_url: Some("https://hn.algolia.com/?q={q}"),
    },
    SiteEntry {
        aliases: &["twitch"],
        name: "Twitch",
        url: "https://www.twitch.tv",
        search_url: Some("https://www.twitch.tv/search?term={q}"),
    },
    SiteEntry {
        aliases: &["vimeo"],
        name: "Vimeo",
        url: "https://vimeo.com",
        search_url: Some("https://vimeo.com/search?q={q}"),
    },
    SiteEntry {
        aliases: &["soundcloud", "sound cloud"],
        name: "SoundCloud",
        url: "https://soundcloud.com",
        search_url: Some("https://soundcloud.com/search?q={q}"),
    },
    SiteEntry {
        aliases: &["stack overflow", "stackoverflow"],
        name: "Stack Overflow",
        url: "https://stackoverflow.com",
        search_url: Some("https://stackoverflow.com/search?q={q}"),
    },
    SiteEntry {
        aliases: &["imdb", "i m d b"],
        name: "IMDb",
        url: "https://www.imdb.com",
        search_url: Some("https://www.imdb.com/find/?q={q}"),
    },
    SiteEntry {
        aliases: &["ebay", "e bay"],
        name: "eBay",
        url: "https://www.ebay.com",
        search_url: Some("https://www.ebay.com/sch/i.html?_nkw={q}"),
    },
    SiteEntry {
        aliases: &["flipkart", "flip kart"],
        name: "Flipkart",
        url: "https://www.flipkart.com",
        search_url: Some("https://www.flipkart.com/search?q={q}"),
    },
    SiteEntry {
        aliases: &["duckduckgo", "duck duck go"],
        name: "DuckDuckGo",
        url: "https://duckduckgo.com",
        search_url: Some("https://duckduckgo.com/?q={q}"),
    },
    SiteEntry {
        aliases: &["mdn", "mdn web docs"],
        name: "MDN",
        url: "https://developer.mozilla.org",
        search_url: Some("https://developer.mozilla.org/en-US/search?q={q}"),
    },
    SiteEntry {
        aliases: &["medium"],
        name: "Medium",
        url: "https://medium.com",
        search_url: Some("https://medium.com/search?q={q}"),
    },
    SiteEntry {
        aliases: &["substack", "sub stack"],
        name: "Substack",
        url: "https://substack.com",
        search_url: Some("https://substack.com/search/{q}"),
    },
    SiteEntry {
        aliases: &["bbc", "bbc news"],
        name: "BBC News",
        url: "https://www.bbc.com/news",
        search_url: Some("https://www.bbc.co.uk/search?q={q}"),
    },
    SiteEntry {
        aliases: &["cnn"],
        name: "CNN",
        url: "https://www.cnn.com",
        search_url: Some("https://www.cnn.com/search?q={q}"),
    },
    SiteEntry {
        aliases: &["chatgpt", "chat gpt"],
        name: "ChatGPT",
        url: "https://chatgpt.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["claude", "claude ai", "claud", "clawed", "cloud ai"],
        name: "Claude",
        url: "https://claude.ai",
        search_url: None,
    },
    SiteEntry {
        aliases: &["gemini", "google gemini", "gemini ai"],
        name: "Gemini",
        url: "https://gemini.google.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["perplexity", "perplexity ai"],
        name: "Perplexity",
        url: "https://www.perplexity.ai",
        search_url: Some("https://www.perplexity.ai/search?q={q}"),
    },
    SiteEntry {
        aliases: &["deepseek", "deep seek"],
        name: "DeepSeek",
        url: "https://chat.deepseek.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["grok", "grok ai"],
        name: "Grok",
        url: "https://grok.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["notion"],
        name: "Notion",
        url: "https://www.notion.so",
        search_url: None,
    },
    SiteEntry {
        aliases: &["google docs", "docs"],
        name: "Google Docs",
        url: "https://docs.google.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["google drive", "drive"],
        name: "Google Drive",
        url: "https://drive.google.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["whatsapp", "whats app", "whatsapp web"],
        name: "WhatsApp",
        url: "https://web.whatsapp.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["discord"],
        name: "Discord",
        url: "https://discord.com/app",
        search_url: None,
    },
    SiteEntry {
        aliases: &["instagram", "insta gram"],
        name: "Instagram",
        url: "https://www.instagram.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["coursera"],
        name: "Coursera",
        url: "https://www.coursera.org",
        search_url: Some("https://www.coursera.org/search?query={q}"),
    },
    SiteEntry {
        aliases: &["khan academy"],
        name: "Khan Academy",
        url: "https://www.khanacademy.org",
        search_url: Some("https://www.khanacademy.org/search?page_search_query={q}"),
    },
    SiteEntry {
        aliases: &["booking.com", "booking com"],
        name: "Booking.com",
        url: "https://www.booking.com",
        search_url: Some("https://www.booking.com/searchresults.html?ss={q}"),
    },
    SiteEntry {
        aliases: &["airbnb", "air bnb"],
        name: "Airbnb",
        url: "https://www.airbnb.com",
        search_url: Some("https://www.airbnb.com/s/{q}/homes"),
    },
    SiteEntry {
        aliases: &["expedia"],
        name: "Expedia",
        url: "https://www.expedia.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["kayak"],
        name: "Kayak",
        url: "https://www.kayak.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["skyscanner", "sky scanner"],
        name: "Skyscanner",
        url: "https://www.skyscanner.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["tripadvisor", "trip advisor"],
        name: "TripAdvisor",
        url: "https://www.tripadvisor.com",
        search_url: Some("https://www.tripadvisor.com/Search?q={q}"),
    },
    SiteEntry {
        aliases: &["hotels.com", "hotels com"],
        name: "Hotels.com",
        url: "https://www.hotels.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["agoda"],
        name: "Agoda",
        url: "https://www.agoda.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["makemytrip", "make my trip"],
        name: "MakeMyTrip",
        url: "https://www.makemytrip.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["opentable", "open table"],
        name: "OpenTable",
        url: "https://www.opentable.com",
        search_url: Some("https://www.opentable.com/s?term={q}"),
    },
    SiteEntry {
        aliases: &["uber eats", "ubereats"],
        name: "Uber Eats",
        url: "https://www.ubereats.com",
        search_url: Some("https://www.ubereats.com/search?q={q}"),
    },
    SiteEntry {
        aliases: &["uber.com"],
        name: "Uber",
        url: "https://www.uber.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["walmart", "wal mart"],
        name: "Walmart",
        url: "https://www.walmart.com",
        search_url: Some("https://www.walmart.com/search?q={q}"),
    },
    SiteEntry {
        aliases: &["target.com"],
        name: "Target",
        url: "https://www.target.com",
        search_url: Some("https://www.target.com/s?searchTerm={q}"),
    },
    SiteEntry {
        aliases: &["best buy", "bestbuy"],
        name: "Best Buy",
        url: "https://www.bestbuy.com",
        search_url: Some("https://www.bestbuy.com/site/searchpage.jsp?st={q}"),
    },
    SiteEntry {
        aliases: &["etsy"],
        name: "Etsy",
        url: "https://www.etsy.com",
        search_url: Some("https://www.etsy.com/search?q={q}"),
    },
    SiteEntry {
        aliases: &["yelp"],
        name: "Yelp",
        url: "https://www.yelp.com",
        search_url: Some("https://www.yelp.com/search?find_desc={q}"),
    },
    SiteEntry {
        aliases: &["doordash", "door dash"],
        name: "DoorDash",
        url: "https://www.doordash.com",
        search_url: Some("https://www.doordash.com/search/store/{q}/"),
    },
    SiteEntry {
        aliases: &["zomato"],
        name: "Zomato",
        url: "https://www.zomato.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["swiggy"],
        name: "Swiggy",
        url: "https://www.swiggy.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["arxiv"],
        name: "arXiv",
        url: "https://arxiv.org",
        search_url: Some("https://arxiv.org/search/?query={q}&searchtype=all"),
    },
    SiteEntry {
        aliases: &["pinterest"],
        name: "Pinterest",
        url: "https://www.pinterest.com",
        search_url: Some("https://www.pinterest.com/search/pins/?q={q}"),
    },
    SiteEntry {
        aliases: &["quora"],
        name: "Quora",
        url: "https://www.quora.com",
        search_url: Some("https://www.quora.com/search?q={q}"),
    },
    SiteEntry {
        aliases: &["tiktok", "tik tok"],
        name: "TikTok",
        url: "https://www.tiktok.com",
        search_url: Some("https://www.tiktok.com/search?q={q}"),
    },
    SiteEntry {
        aliases: &["facebook", "face book"],
        name: "Facebook",
        url: "https://www.facebook.com",
        search_url: None,
    },
    SiteEntry {
        aliases: &["espn"],
        name: "ESPN",
        url: "https://www.espn.com",
        search_url: Some("https://www.espn.com/search/_/q/{q}"),
    },
    SiteEntry {
        aliases: &["new york times", "nytimes"],
        name: "New York Times",
        url: "https://www.nytimes.com",
        search_url: Some("https://www.nytimes.com/search?query={q}"),
    },
    SiteEntry {
        aliases: &["reuters"],
        name: "Reuters",
        url: "https://www.reuters.com",
        search_url: Some("https://www.reuters.com/site-search/?query={q}"),
    },
    SiteEntry {
        aliases: &["npmjs"],
        name: "npm",
        url: "https://www.npmjs.com",
        search_url: Some("https://www.npmjs.com/search?q={q}"),
    },
    SiteEntry {
        aliases: &["pypi"],
        name: "PyPI",
        url: "https://pypi.org",
        search_url: Some("https://pypi.org/search/?q={q}"),
    },
    SiteEntry {
        aliases: &["crates.io"],
        name: "crates.io",
        url: "https://crates.io",
        search_url: Some("https://crates.io/search?q={q}"),
    },
];

static QUIT_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:jarvis\s+(?:quit|exit|bye|goodbye|shut\s*down)|(?:quit|exit|shut\s*down)\s+jarvis)$")
        .unwrap()
});
static STOP_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:stop|cancel|abort|never\s*mind|stop\s+(?:browsing|that|task|it)|cancel\s+that)$")
        .unwrap()
});
static YES_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:yes|yeah|yep|go\s+ahead|confirm|approve|proceed|do\s+it|ok|okay)$").unwrap()
});
static NO_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:no|nope|don't|do\s+not|cancel|stop|reject)$").unwrap()
});
static READ_PAGE_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:read\s+(?:the\s+)?(?:page|screen|article|this)|read\s+this|(?:explain|summarize|summarise)\s+(?:this(?:\s+(?:page|article|screen))?|the\s+(?:page|article|screen))|what(?:'s|\s+is)\s+on\s+(?:the\s+)?(?:page|screen)|what\s+page\s+am\s+i\s+on|where\s+am\s+i)$")
        .unwrap()
});
static OPEN_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:open|go\s+to|navigate\s+to|visit|launch)\s+(.+)$").unwrap()
});
static SEARCH_HERE_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:search\s+(?:here|(?:on|in)\s+this\s+(?:page|site|website)|(?:this|the)\s+(?:page|site|website))\s+(?:for\s+)?(.+)|find\s+(.+?)\s+(?:here|(?:on|in)\s+this\s+(?:page|site|website))|(.+?)\s+in\s+(?:the\s+)?search(?:\s+(?:bar|box))?)$")
        .unwrap()
});
static SEARCH_SITE_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:search|look\s+up|find)\s+(?:(?:on|in)\s+)?([a-z0-9.\-\s]+?)\s+for\s+(.+)$").unwrap()
});
static SITE_SEARCH_PREFIX_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^([a-z0-9.\-\s]+?)\s+search(?:\s+for)?\s+(.+)$").unwrap()
});
static BARE_SITE_SEARCH_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:search\s+(?:on|in)\s+([a-z0-9.\-\s]+?)|([a-z0-9.\-\s]+?)\s+search)$").unwrap()
});
static SEARCH_FOR_ON_SITE_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(search|look\s+up|find|play|watch)\s+(?:(?:for|about)\s+)?(.+)\s+(?:on|in)\s+([a-z0-9.\-\s]+)$")
        .unwrap()
});
static ON_SITE_ACTION_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:on|in)\s+(?:search\s+)?([a-z0-9.\-\s]+?)\s+(select|click|open|search(?:\s+for)?|find|play|watch)\s+(.+)$")
        .unwrap()
});
static SELECT_PHRASE_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"\b(?:select|click|open|play)\s+(?:that|this|the\s+(?:first|second|third|top|next))\s+(?:video|link|result|one|item|button)\b",
    )
    .unwrap()
});
static DIRECT_CLICK_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:click|tap|press|hit|select)\s+(?:on\s+)?(?:the\s+)?(.+)$").unwrap()
});
static SEMANTIC_CLICK_HINT_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"\b(?:first|second|third|fourth|fifth|top|bottom|last|cheapest|fastest|best|closest|nearest|that|this|one|item)\b",
    )
    .unwrap()
});
static SAME_PAGE_UI_VERB_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:click|tap|press|hit|select|choose|pick|toggle|check|uncheck|expand|collapse|hover|type|enter|fill|write)\b")
        .unwrap()
});
static WAKE_WORD_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\b(?:jarvis|jarvish|jarves|jabesh)\b").unwrap());
static SEARCH_GENERIC_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:search(?:\s+the\s+web)?\s+(?:(?:for|about)\s+)?|google\s+(?:(?:for|about)\s+)?|look\s+up\s+(?:about\s+)?)(.+)$")
        .unwrap()
});
static GOAL_VERB_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:find|book|order|buy|check|uncheck|compare|play|watch|click|tap|press|hit|select|choose|pick|type|enter|fill|write|compose|reply|comment|post|submit|send|log\s*in|sign\s*in|log\s*out|sign\s*out|sign\s*up|register|pause|resume|unpause|mute|unmute|enable|disable|toggle|change|set|adjust|skip|rewind|seek|fast\s+forward|filter|sort|expand|collapse|show|hide|load|view|download|upload|share|save|bookmark|like|unlike|upvote|downvote|subscribe|unsubscribe|follow|unfollow|add|remove|delete|clear|edit|update|create|accept|reject|decline|allow|deny|next\s+page|previous\s+page)\b")
        .unwrap()
});
static LIST_TABS_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:how\s+many\s+tabs(?:\s+are\s+open)?|what\s+tabs\s+are\s+open|which\s+tabs\s+are\s+open|list\s+(?:the\s+|open\s+)?tabs)$")
        .unwrap()
});
static CLOSE_DIALOG_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^close\s+(?:(?:the|this)\s+)?(?:[a-z0-9]+\s+){0,3}(?:window|popup|modal|dialog|panel|menu|box|overlay)$")
        .unwrap()
});
static GO_TO_UI_SECTION_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:images|videos|news|shopping|forums|books|finance|ai\s+mode|all|web|home|inbox|sent|drafts|profile|account|dashboard|cart|checkout|orders|pricing|plans|documentation|models|datasets|spaces|trending|subscriptions|library|history|watch\s+later|liked\s+videos|downloads|explore|notifications|messages|menu|help|support|about|contact|login|log\s+in|sign\s+in|sign\s+up|register|filters|reviews|overview|details|specs|comments|description|transcript|chapters|page\s+\d+)$")
        .unwrap()
});
static APPEARANCE_OPTION_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"^(?:(?:text|font)\s+(?:size\s+)?(?:small|standard|large)|(?:color|colour|theme)\s+(?:light|dark|automatic|auto)|width\s+(?:standard|wide)|(?:dark|light)\s+(?:mode|theme))$",
    )
    .unwrap()
});
static MEDIA_ACTION_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"^(?:(?:turn|switch)\s+(?:on|off|up|down)\s+(?:the\s+)?(?:sound|volume|audio|mute|captions|subtitles|cc|autoplay)|(?:go|enter|exit|open)\s+(?:full\s*screen|theater(?:\s+mode)?|miniplayer|settings)|(?:add|post|write)\s+(?:a\s+)?comment\b|volume\s+(?:up|down|to\s+\d+|\d+%?)|(?:playback\s+)?speed\s+\d|captions\b|subtitles\b|full\s*screen$|theater\s*mode$)",
    )
    .unwrap()
});
static SCROLL_TOP_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:(?:scroll|go|back|jump)\s+to\s+(?:the\s+)?top|top\s+of\s+(?:the\s+)?page)$").unwrap()
});
static SCROLL_BOTTOM_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:(?:scroll|go|jump)\s+to\s+(?:the\s+)?bottom|bottom\s+of\s+(?:the\s+)?page)$").unwrap()
});
static SCROLL_UP_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"^(?:(?:more\s+)?(?:scroll|school|score)\s+(?:up|app)(?:\s+(?:more|again|two|twice|a\s+bit|please))?(?:\.?\s+(?:scroll|school|score)\s+(?:up|app))*|go\s+up|move\s+up|page\s+up)$",
    )
    .unwrap()
});
static SCROLL_DOWN_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"^(?:(?:more\s+)?(?:scroll|school|score)(?:\s+(?:down|town))?(?:\s+(?:more|again|two|twice|a\s+bit|please))?(?:\.?\s+(?:scroll|school|score)(?:\s+(?:down|town))?)*|go\s+down|move\s+down|page\s+down|keep\s+scrolling)$",
    )
    .unwrap()
});
static ZOOM_IN_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:zoom\s+in|make\s+(?:it|text|the\s+page)\s+bigger|bigger\s+text)$").unwrap()
});
static ZOOM_OUT_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:zoom\s+out|make\s+(?:it|text|the\s+page)\s+smaller|smaller\s+text)$").unwrap()
});
static ZOOM_RESET_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:reset\s+zoom|normal\s+zoom|zoom\s+(?:reset|normal|100%?))$").unwrap()
});
static SWITCH_TAB_TO_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:switch(?:\s+tab)?\s+to\s+(?:the\s+)?(.+?)(?:\s+tab)?|go\s+to\s+(?:the\s+)?(.+?)\s+tab)$")
        .unwrap()
});
static NEW_TAB_SUFFIX_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\s+(?:in|on)\s+(?:a\s+)?(?:new|another)\s+tab$").unwrap());
static NEW_TAB_PREFIX_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^(?:in|on)\s+(?:a\s+)?(?:new|another)\s+tab\s+").unwrap());
static THEN_SPLIT_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)(?:,|\.)?\s+(?:and\s+)?then\s+").unwrap());
static PAUSE_VIDEO_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:pause(?:\s+(?:(?:the|this|that)\s+)?(?:video|music|song|audio|podcast|track|movie|episode|stream|playback|it))?|stop\s+(?:(?:the|this|that)\s+)?(?:video|music|song|audio|podcast|track|movie|episode|stream|playback))$")
        .unwrap()
});
static PLAY_VIDEO_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:play|resume|unpause)(?:\s+(?:(?:the|this|that)\s+)?(?:video|music|song|audio|podcast|track|movie|episode|stream|playback|it))?$")
        .unwrap()
});
static MUTE_VIDEO_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"^(?:mute(?:\s+(?:(?:the|this|that)\s+)?(?:video|music|song|sound|audio|podcast|volume|tab|it))?|(?:turn|switch)\s+off\s+(?:(?:the|this|that)\s+)?(?:sound|volume|audio)(?:\s+(?:for|on)\s+(?:(?:the|this|that)\s+)?(?:video|music|page))?)$",
    )
    .unwrap()
});
static UNMUTE_VIDEO_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"^(?:unmute(?:\s+(?:(?:the|this|that)\s+)?(?:video|music|song|sound|audio|podcast|volume|tab|it))?|(?:turn|switch)\s+on\s+(?:(?:the|this|that)\s+)?(?:sound|volume|audio)(?:\s+(?:for|on)\s+(?:(?:the|this|that)\s+)?(?:video|music|page))?)$",
    )
    .unwrap()
});
static VOLUME_UP_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"^(?:volume\s+up|louder|(?:increase|raise)\s+(?:(?:the|this)\s+)?(?:volume|value|sound|audio)(?:\s+(?:for|on)\s+(?:(?:the|this|that)\s+)?(?:video|music|audio))?|(?:turn|bring)\s+(?:up\s+(?:(?:the|this)\s+)?(?:volume|value|sound)|(?:(?:the|this)\s+)?(?:volume|value|sound)\s+(?:up|loop))(?:\s+(?:for|on)\s+(?:(?:the|this|that)\s+)?(?:video|music|audio))?)$",
    )
    .unwrap()
});
static VOLUME_DOWN_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"^(?:volume\s+down|quieter|(?:reduce|lower|decrease)\s+(?:(?:the|this)\s+)?(?:volume|value|sound|audio)(?:\s+(?:for|on)\s+(?:(?:the|this|that)\s+)?(?:video|music|audio))?|(?:turn|bring)\s+(?:down\s+(?:(?:the|this)\s+)?(?:volume|value|sound)|(?:(?:the|this)\s+)?(?:volume|value|sound)\s+(?:down|low))(?:\s+(?:for|on)\s+(?:(?:the|this|that)\s+)?(?:video|music|audio))?)$",
    )
    .unwrap()
});
static VOLUME_SET_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:(?:set\s+)?(?:the\s+)?volume(?:\s+to)?\s+)(\d{1,3})%?$").unwrap()
});
static SPEED_SET_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:(?:set\s+)?(?:playback\s+)?speed(?:\s+to)?\s+)(\d(?:\.\d{1,2})?)x?$").unwrap()
});
static NEXT_TRACK_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:next\s+(?:video|song|track|episode)|skip\s+(?:song|track))$").unwrap()
});
static PREV_TRACK_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:previous|prev)\s+(?:video|song|track|episode)$").unwrap()
});
static SKIP_AD_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^skip\s+(?:(?:the|this|that)\s+)?(?:ads?|adds?|air|at|hat|intro|recap)|^skip\s+this$")
        .unwrap()
});
static OPEN_SETTINGS_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:(?:open|select|go\s+to|click)\s+(?:open\s+)?(?:the\s+)?settings(?:\s+in\s+this)?|settings)$")
        .unwrap()
});
static CAPTIONS_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:(?:turn|switch)\s+(?:on|off)\s+(?:the\s+)?(?:captions|subtitles|cc)|toggle\s+(?:captions|subtitles|cc)|captions|subtitles)$")
        .unwrap()
});
static SEEK_FWD_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:fast\s+forward|skip\s+(?:forward|ahead)|forward\s+10\s+seconds?)$").unwrap()
});
static SEEK_BACK_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:rewind(?:\s+10\s+seconds?)?|skip\s+back|go\s+back\s+10\s+seconds?)$").unwrap()
});
static FULLSCREEN_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:(?:go|enter|exit|toggle)\s+)?full\s*screen$").unwrap()
});
static DOMAIN_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)+$").unwrap());

const NOISE_WORDS: &[&str] = &[
    "a", "e", "i", "o", "u", "de", "he", "it", "as", "to", "in", "of", "on", "or", "so", "the",
    "and", "for", "but", "you", "uh", "um", "hm", "hmm", "mm", "ah",
];

fn percent_encode_query(q: &str) -> String {
    let mut out = String::with_capacity(q.len());
    for b in q.trim().bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char);
            }
            b' ' => out.push('+'),
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

const KNOWN_TLDS: &[&str] = &[
    "com", "org", "net", "io", "co", "edu", "gov", "tv", "ai", "dev", "app", "uk", "in", "de",
    "fr", "jp", "ca", "au", "me", "gg", "news", "info", "biz", "xyz", "tech", "site", "store",
    "shop", "wiki", "live", "fm", "to", "so", "cc", "us", "eu", "ch", "nl", "es", "it", "br",
];

/// Convert spoken domains like "bbc dot com" or "news dot ycombinator dot com" into "bbc.com".
fn normalize_spoken_domain(raw: &str) -> Option<String> {
    let trimmed = raw
        .trim()
        .trim_start_matches("https://")
        .trim_start_matches("http://")
        .trim_end_matches('/');
    if trimmed.is_empty() {
        return None;
    }
    let candidate = if trimmed.contains(" dot ") {
        trimmed
            .split(" dot ")
            .map(|seg| seg.trim().replace(' ', ""))
            .collect::<Vec<_>>()
            .join(".")
    } else {
        trimmed.to_string()
    };
    if !DOMAIN_RE.is_match(&candidate) {
        return None;
    }
    let tld = candidate.rsplit('.').next()?;
    if KNOWN_TLDS.contains(&tld) {
        Some(candidate)
    } else {
        None
    }
}

fn direct_search_url(site: &SiteEntry, query: &str) -> Option<String> {
    site.search_url
        .map(|tmpl| tmpl.replace("{q}", &percent_encode_query(query)))
}

pub fn is_addressed_to_jarvis(raw: &str) -> bool {
    let norm = normalize(raw);
    WAKE_WORD_RE.is_match(&norm)
}

fn normalize(raw: &str) -> String {
    let cleaned: String = raw
        .to_ascii_lowercase()
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '\'' || c == '.' || c == '-' || c.is_whitespace() {
                c
            } else {
                ' '
            }
        })
        .collect();
    cleaned.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn strip_polite_prefix(norm: &str) -> &str {
    let mut s = norm.trim();
    loop {
        let before = s;
        for prefix in [
            "hello jarvis ",
            "hi jarvis ",
            "yo jarvis ",
            "hey jarvis ",
            "ok jarvis ",
            "okay jarvis ",
            "jarvis ",
            "uh. ",
            "uh ",
            "um. ",
            "um ",
            "well. ",
            "well ",
            "so. ",
            "so ",
            "okay. ",
            "okay ",
            "ok. ",
            "ok ",
            "alright ",
            "all right ",
            "right ",
            "yeah ",
            "yes ",
            "hey ",
            "hi ",
            "hello ",
            "and ",
            "thank you. ",
            "thank you ",
            "thanks. ",
            "thanks ",
            "please ",
            "can you please ",
            "could you please ",
            "can you ",
            "could you ",
            "you ",
            "now ",
            "just ",
        ] {
            if let Some(rest) = s.strip_prefix(prefix) {
                s = rest.trim();
            }
        }
        if s == before {
            break;
        }
    }
    let s = s.trim_end_matches('.').trim();
    s.strip_suffix(" please").unwrap_or(s).trim()
}

fn match_site(phrase: &str) -> Option<&'static SiteEntry> {
    let p = phrase.trim().trim_start_matches("the ").trim();
    let alias_name = match p {
        "you to" | "you two" | "q two" | "q tube" => Some("YouTube"),
        "booking" => Some("Booking.com"),
        "target" => Some("Target"),
        "scholar" => Some("Google Scholar"),
        "translate" => Some("Google Translate"),
        "uber" => Some("Uber"),
        "npm" => Some("npm"),
        _ => None,
    };
    if let Some(name) = alias_name {
        return SITES.iter().find(|entry| entry.name == name);
    }
    SITES.iter().find(|entry| entry.aliases.contains(&p))
}

fn find_site_by_name_or_url(site_name: &str, url: &str) -> Option<&'static SiteEntry> {
    SITES
        .iter()
        .find(|entry| entry.name == site_name || entry.url == url)
}

fn normalize_host(url: &str) -> Option<&str> {
    let rest = url
        .strip_prefix("https://")
        .or_else(|| url.strip_prefix("http://"))?;
    let host = rest.split(['/', '?', '#']).next()?;
    let host = host
        .strip_prefix("www.")
        .or_else(|| host.strip_prefix("en."))
        .or_else(|| host.strip_prefix("m."))
        .unwrap_or(host);
    if host.is_empty() {
        None
    } else {
        Some(host)
    }
}

fn find_searchable_site_by_active_url(active_url: &str) -> Option<&'static SiteEntry> {
    let active_host = normalize_host(active_url)?;
    SITES.iter().find(|entry| {
        entry.search_url.is_some()
            && !matches!(entry.name, "Google" | "DuckDuckGo" | "Bing" | "Yahoo")
            && normalize_host(entry.url) == Some(active_host)
    })
}

/// If a generic same-tab search ("search <query>") runs while the active browser tab is already
/// on a known searchable site (e.g. YouTube, Wikipedia, GitHub, Amazon, Reddit), rewrite the
/// search to target that active site instead of overwriting the tab with Google.
pub fn contextualize_generic_search(
    active_url: &str,
    goal: &str,
    url: &str,
    site_name: &str,
    new_tab: bool,
) -> Option<(String, String, String)> {
    if new_tab || !goal.starts_with("Search Google for ") {
        return None;
    }
    let query = site_name.strip_prefix("Google search for ")?;
    if !url.starts_with("https://www.google.com/search?q=") {
        return None;
    }
    let site = find_searchable_site_by_active_url(active_url)?;
    let search_url = direct_search_url(site, query)?;
    Some((
        format!("Search {} for {}.", site.name, query),
        search_url,
        format!("{} search for {}", site.name, query),
    ))
}

fn extract_new_tab_modifier(cmd: &str) -> (String, bool) {
    if NEW_TAB_SUFFIX_RE.is_match(cmd) {
        let stripped = NEW_TAB_SUFFIX_RE.replace(cmd, "").trim().to_string();
        if !stripped.is_empty() {
            return (stripped, true);
        }
    }
    if NEW_TAB_PREFIX_RE.is_match(cmd) {
        let stripped = NEW_TAB_PREFIX_RE.replace(cmd, "").trim().to_string();
        if !stripped.is_empty() {
            return (stripped, true);
        }
    }
    (cmd.to_string(), false)
}

fn is_new_tab_phrase(target: &str) -> bool {
    matches!(
        target,
        "new tab"
            | "a new tab"
            | "another tab"
            | "another new tab"
            | "one more tab"
            | "one more new tab"
    )
}

fn route_site_search(site: &'static SiteEntry, query: &str, new_tab: bool) -> RouteAction {
    if let Some(search_url) = direct_search_url(site, query) {
        return RouteAction::OpenUrl {
            goal: format!("Search {} for {}.", site.name, query),
            url: search_url,
            site_name: format!("{} search for {}", site.name, query),
            new_tab,
        };
    }
    RouteAction::BrowserTask {
        goal: format!(
            "Search {} for {} and open or display the matching results.",
            site.name, query
        ),
        url: Some(site.url.to_string()),
        ack: format!("Searching {} for {}.", site.name, query),
        new_tab,
    }
}

/// Match "search [in|on] <site> <query>" when the user omits "for" (e.g. "search youtube rust tutorial").
fn match_search_site_without_for(cmd: &str) -> Option<(&'static SiteEntry, &str)> {
    let rest = cmd
        .strip_prefix("search in ")
        .or_else(|| cmd.strip_prefix("search on "))
        .or_else(|| cmd.strip_prefix("search "))?;
    let mut best: Option<(&'static SiteEntry, usize, &str)> = None;
    for entry in SITES {
        for &alias in entry.aliases {
            if let Some(after) = rest.strip_prefix(alias) {
                if let Some(q) = after.strip_prefix(' ').map(str::trim) {
                    if !q.is_empty() && q != "search" && best.map(|b| alias.len() > b.1).unwrap_or(true)
                    {
                        best = Some((entry, alias.len(), q));
                    }
                }
            }
        }
    }
    for (extra, name) in [
        ("booking", "Booking.com"),
        ("target", "Target"),
        ("scholar", "Google Scholar"),
        ("npm", "npm"),
    ] {
        if let Some(after) = rest.strip_prefix(extra) {
            if let Some(q) = after.strip_prefix(' ').map(str::trim) {
                if !q.is_empty() && q != "search" && best.map(|b| extra.len() > b.1).unwrap_or(true)
                {
                    if let Some(entry) = SITES.iter().find(|e| e.name == name) {
                        best = Some((entry, extra.len(), q));
                    }
                }
            }
        }
    }
    best.map(|(entry, _, q)| (entry, q))
}

/// Extract the latest unambiguous multi-word media/nav command even when speaker audio glued text around it.
fn match_embedded_media_control(norm: &str) -> Option<&'static str> {
    let mut best: Option<(usize, &'static str)> = None;
    for (needle, action) in [
        ("skip the ad", "skip_ad"),
        ("skip this ad", "skip_ad"),
        ("skip the ads", "skip_ad"),
        ("skip this ads", "skip_ad"),
        ("skip the add", "skip_ad"),
        ("skip this add", "skip_ad"),
        ("skip the adds", "skip_ad"),
        ("skip the air", "skip_ad"),
        ("skip the hat", "skip_ad"),
        ("skip this hat", "skip_ad"),
        ("pause the video", "pause_video"),
        ("pause this video", "pause_video"),
        ("stop the video", "pause_video"),
        ("stop this video", "pause_video"),
        ("play the video", "play_video"),
        ("play this video", "play_video"),
        ("resume the video", "play_video"),
        ("resume this video", "play_video"),
        ("mute the video", "mute_video"),
        ("mute this video", "mute_video"),
        ("unmute the video", "unmute_video"),
        ("unmute this video", "unmute_video"),
        ("turn the volume up", "volume_up"),
        ("turn up the volume", "volume_up"),
        ("increase the volume", "volume_up"),
        ("volume up", "volume_up"),
        ("turn the volume down", "volume_down"),
        ("turn down the volume", "volume_down"),
        ("reduce the sound", "volume_down"),
        ("reduce the volume", "volume_down"),
        ("volume down", "volume_down"),
        ("open the settings", "open_settings"),
        ("open settings", "open_settings"),
        ("select settings", "open_settings"),
        ("go to settings", "open_settings"),
        ("scroll down", "scroll_down"),
        ("scroll up", "scroll_up"),
        ("close this tab", "close_tab"),
        ("close the tab", "close_tab"),
        ("close youtube", "close_tab"),
        ("close you to", "close_tab"),
    ] {
        if let Some(pos) = norm.rfind(needle) {
            let end = pos + needle.len();
            if best.map(|(best_end, _)| end >= best_end).unwrap_or(true) {
                best = Some((end, action));
            }
        }
    }
    best.map(|(_, action)| action)
}

fn trailing_site_scope(cmd: &str) -> Option<&'static SiteEntry> {
    for sep in [" on ", " in "] {
        if let Some((_, tail)) = cmd.rsplit_once(sep) {
            if let Some(site) = match_site(tail.trim()) {
                return Some(site);
            }
        }
    }
    None
}

fn match_any_site_in_text(norm: &str) -> Option<&'static SiteEntry> {
    let bounded = format!(" {norm} ");
    for entry in SITES {
        for alias in entry.aliases {
            if bounded.contains(&format!(" {alias} ")) {
                return Some(entry);
            }
        }
    }
    None
}

fn dedupe_repeated_phrase(cmd: &str) -> String {
    let words: Vec<&str> = cmd.split_whitespace().collect();
    if words.len() >= 2 && words.len().is_multiple_of(2) {
        let mid = words.len() / 2;
        let first: Vec<&str> = words[..mid].iter().map(|w| w.trim_end_matches('.')).collect();
        let second: Vec<&str> = words[mid..].iter().map(|w| w.trim_end_matches('.')).collect();
        if first == second {
            return first.join(" ");
        }
    }
    cmd.to_string()
}

fn extract_generic_search_query(action: &RouteAction) -> Option<String> {
    match action {
        RouteAction::OpenUrl {
            site_name,
            new_tab: false,
            ..
        } => site_name
            .strip_prefix("Google search for ")
            .map(str::to_string),
        RouteAction::BrowserTask {
            goal,
            url: None,
            new_tab: false,
            ..
        } => goal
            .strip_prefix("Use the search box on this page to search for ")
            .and_then(|s| s.strip_suffix('.'))
            .map(str::to_string),
        _ => None,
    }
}

/// Collapse redundant adjacent pipeline steps (e.g. "open new tab + open site" -> 1 tab load,
/// "open youtube + search for rust" -> direct YouTube search URL) while preserving distinct pipelines.
fn optimize_pipeline(steps: Vec<RouteAction>) -> RouteAction {
    let mut out: Vec<RouteAction> = Vec::with_capacity(steps.len());
    for step in steps {
        if let Some(prev) = out.last() {
            // Rule A: blank "open a new tab" followed by an OpenUrl or BrowserTask -> set new_tab=true directly.
            if let RouteAction::OpenUrl {
                site_name,
                new_tab: true,
                ..
            } = prev
            {
                if site_name == "a new tab" {
                    match step {
                        RouteAction::OpenUrl {
                            goal,
                            url,
                            site_name,
                            ..
                        } => {
                            out.pop();
                            out.push(RouteAction::OpenUrl {
                                goal,
                                url,
                                site_name,
                                new_tab: true,
                            });
                            continue;
                        }
                        RouteAction::BrowserTask {
                            goal, url, ack, ..
                        } => {
                            out.pop();
                            out.push(RouteAction::BrowserTask {
                                goal,
                                url,
                                ack,
                                new_tab: true,
                            });
                            continue;
                        }
                        _ => {}
                    }
                }
            }

            // Rule B: "open <site>" + "search [here] for <q>" -> direct site search URL or targeted site task.
            if let RouteAction::OpenUrl {
                url: site_url,
                site_name,
                new_tab,
                ..
            } = prev
            {
                if site_name != "a new tab" && !site_name.contains(" search for ") {
                    if let Some(query) = extract_generic_search_query(&step) {
                        let nt = *new_tab;
                        if let Some(site) = find_site_by_name_or_url(site_name, site_url) {
                            out.pop();
                            out.push(route_site_search(site, &query, nt));
                            continue;
                        }
                        let su = site_url.clone();
                        let sn = site_name.clone();
                        out.pop();
                        out.push(RouteAction::BrowserTask {
                            goal: format!("Use the search box on {sn} to search for {query}."),
                            url: Some(su),
                            ack: format!("Searching {sn} for {query}."),
                            new_tab: nt,
                        });
                        continue;
                    }

                    // Rule C: "open <site>" + same-tab BrowserTask -> single targeted BrowserTask on that site.
                    if let RouteAction::BrowserTask {
                        goal,
                        url: None,
                        ack,
                        new_tab: false,
                    } = &step
                    {
                        let nt = *new_tab;
                        let su = site_url.clone();
                        let sn = site_name.clone();
                        let g_low = goal.to_ascii_lowercase();
                        let play_query = g_low
                            .strip_prefix("play ")
                            .or_else(|| g_low.strip_prefix("watch "))
                            .map(str::trim)
                            .filter(|q| !q.is_empty());
                        if let (Some(q), Some(site)) =
                            (play_query, find_site_by_name_or_url(&sn, &su))
                        {
                            if let Some(search_url) = direct_search_url(site, q) {
                                out.pop();
                                out.push(RouteAction::BrowserTask {
                                    goal: format!(
                                        "Click the top matching result for {q} on {} and make sure it plays.",
                                        site.name
                                    ),
                                    url: Some(search_url),
                                    ack: format!("Playing {q} on {}.", site.name),
                                    new_tab: nt,
                                });
                                continue;
                            }
                        }
                        let g = goal.clone();
                        let a = if ack == "On it." {
                            format!("Working on {sn} now.")
                        } else {
                            ack.clone()
                        };
                        out.pop();
                        out.push(RouteAction::BrowserTask {
                            goal: g,
                            url: Some(su),
                            ack: a,
                            new_tab: nt,
                        });
                        continue;
                    }
                }
            }
        }
        out.push(step);
    }

    match out.len() {
        0 => RouteAction::Chat,
        1 => out.into_iter().next().unwrap(),
        _ => RouteAction::Pipeline(out),
    }
}

fn can_split_and_left(left: &str) -> bool {
    let norm = normalize(left);
    let cleaned = strip_polite_prefix(&norm);
    [
        "open ",
        "go to ",
        "visit ",
        "navigate to ",
        "launch ",
        "pause",
        "play",
        "mute",
        "unmute",
        "scroll",
        "close ",
        "switch ",
    ]
    .iter()
    .any(|p| cleaned.starts_with(p))
}

fn can_split_and_right(right: &str) -> bool {
    let norm = normalize(right);
    let cleaned = strip_polite_prefix(&norm);
    [
        "open ",
        "go to ",
        "visit ",
        "navigate to ",
        "switch ",
        "close ",
        "read ",
        "scroll",
        "pause",
        "play",
        "mute",
        "unmute",
        "zoom ",
    ]
    .iter()
    .any(|p| cleaned.starts_with(p))
}

fn classify_pipeline(raw: &str, in_confirmation: bool, task_running: bool) -> Option<RouteAction> {
    if in_confirmation {
        return None;
    }
    let trimmed = raw.trim();
    // 1. Explicit sequence delimiter: "then" / "and then"
    if THEN_SPLIT_RE.is_match(trimmed) {
        let parts: Vec<&str> = THEN_SPLIT_RE
            .split(trimmed)
            .map(str::trim)
            .filter(|p| !p.is_empty())
            .take(4)
            .collect();
        if parts.len() >= 2 {
            let mut actions = Vec::with_capacity(parts.len());
            for part in parts {
                let act = classify_inner(part, false, task_running);
                if matches!(act, RouteAction::Chat | RouteAction::Ignore) {
                    return None;
                }
                actions.push(act);
            }
            return Some(optimize_pipeline(actions));
        }
    }

    // 2. Safe "and" split when either the left clause starts with a nav/control verb
    //    OR the right clause starts with an explicit browser action verb ("search youtube for rust and open a new tab").
    //    Never splits queries like "search amazon for bread and butter".
    let lower = trimmed.to_ascii_lowercase();
    if let Some(idx) = lower.find(" and ") {
        let left = trimmed[..idx].trim();
        let right = trimmed[idx + 5..].trim();
        if !left.is_empty() && !right.is_empty() && (can_split_and_left(left) || can_split_and_right(right)) {
            let a1 = classify_inner(left, false, task_running);
            let a2 = classify_inner(right, false, task_running);
            if !matches!(a1, RouteAction::Chat | RouteAction::Ignore)
                && !matches!(a2, RouteAction::Chat | RouteAction::Ignore)
            {
                return Some(optimize_pipeline(vec![a1, a2]));
            }
        }
    }
    None
}

pub fn classify(raw: &str, in_confirmation: bool, task_running: bool) -> RouteAction {
    if let Some(piped) = classify_pipeline(raw, in_confirmation, task_running) {
        return piped;
    }
    let primary = classify_inner(raw, in_confirmation, task_running);
    if matches!(primary, RouteAction::Chat) {
        if let Some((_, tail)) = raw.trim().rsplit_once(". ") {
            if let Some(piped) = classify_pipeline(tail, in_confirmation, task_running) {
                return piped;
            }
            let tail_action = classify_inner(tail, in_confirmation, task_running);
            if !matches!(tail_action, RouteAction::Chat | RouteAction::Ignore) {
                return tail_action;
            }
        }
    }
    primary
}

fn classify_inner(raw: &str, in_confirmation: bool, task_running: bool) -> RouteAction {
    let norm = normalize(raw);
    if norm.is_empty() {
        return RouteAction::Chat;
    }

    let trimmed = norm.trim_end_matches('.');
    if QUIT_RE.is_match(trimmed) {
        return RouteAction::Quit;
    }

    let deduped = dedupe_repeated_phrase(strip_polite_prefix(&norm));
    let cmd = deduped.as_str();

    if in_confirmation {
        if YES_RE.is_match(cmd) {
            return RouteAction::Confirm(true);
        }
        if NO_RE.is_match(cmd) {
            return RouteAction::Confirm(false);
        }
    }

    if NOISE_WORDS.contains(&trimmed) || NOISE_WORDS.contains(&cmd) {
        return RouteAction::Ignore;
    }

    if STOP_RE.is_match(cmd)
        || (task_running
            && (cmd.ends_with(" stop") || cmd.ends_with(" cancel") || cmd.ends_with(" abort")))
    {
        return RouteAction::Stop;
    }

    if READ_PAGE_RE.is_match(cmd) {
        return RouteAction::ReadPage;
    }

    if SCROLL_TOP_RE.is_match(cmd) {
        return RouteAction::Control("scroll_top".into());
    }
    if SCROLL_BOTTOM_RE.is_match(cmd) {
        return RouteAction::Control("scroll_bottom".into());
    }
    if SCROLL_UP_RE.is_match(cmd) {
        return RouteAction::Control("scroll_up".into());
    }
    if SCROLL_DOWN_RE.is_match(cmd) {
        return RouteAction::Control("scroll_down".into());
    }
    if ZOOM_IN_RE.is_match(cmd) {
        return RouteAction::Control("zoom_in".into());
    }
    if ZOOM_OUT_RE.is_match(cmd) {
        return RouteAction::Control("zoom_out".into());
    }
    if ZOOM_RESET_RE.is_match(cmd) {
        return RouteAction::Control("zoom_reset".into());
    }

    if PAUSE_VIDEO_RE.is_match(cmd) {
        return RouteAction::Control("pause_video".into());
    }
    if PLAY_VIDEO_RE.is_match(cmd) {
        return RouteAction::Control("play_video".into());
    }
    if MUTE_VIDEO_RE.is_match(cmd) {
        return RouteAction::Control("mute_video".into());
    }
    if UNMUTE_VIDEO_RE.is_match(cmd) {
        return RouteAction::Control("unmute_video".into());
    }
    if VOLUME_UP_RE.is_match(cmd) {
        return RouteAction::Control("volume_up".into());
    }
    if VOLUME_DOWN_RE.is_match(cmd) {
        return RouteAction::Control("volume_down".into());
    }
    if let Some(caps) = VOLUME_SET_RE.captures(cmd) {
        if let Ok(pct) = caps[1].parse::<u32>() {
            return RouteAction::Control(format!("volume:{}", pct.min(100)));
        }
    }
    if let Some(caps) = SPEED_SET_RE.captures(cmd) {
        if let Ok(rate) = caps[1].parse::<f32>() {
            return RouteAction::Control(format!("speed:{:.2}", rate.clamp(0.25, 4.0)));
        }
    }
    if NEXT_TRACK_RE.is_match(cmd) {
        return RouteAction::Control("next_track".into());
    }
    if PREV_TRACK_RE.is_match(cmd) {
        return RouteAction::Control("prev_track".into());
    }
    if SKIP_AD_RE.is_match(cmd) {
        return RouteAction::Control("skip_ad".into());
    }
    if OPEN_SETTINGS_RE.is_match(cmd) {
        return RouteAction::Control("open_settings".into());
    }
    if CAPTIONS_RE.is_match(cmd) {
        return RouteAction::Control("toggle_captions".into());
    }
    if SEEK_FWD_RE.is_match(cmd) {
        return RouteAction::Control("seek_forward".into());
    }
    if SEEK_BACK_RE.is_match(cmd) {
        return RouteAction::Control("seek_back".into());
    }
    if FULLSCREEN_RE.is_match(cmd) {
        return RouteAction::Control("fullscreen".into());
    }

    match cmd {
        "go back" | "back" => return RouteAction::Control("back".into()),
        "go forward" | "forward" => return RouteAction::Control("forward".into()),
        "reload" | "refresh" | "reload page" | "refresh page" | "reload this page"
        | "refresh this page" => return RouteAction::Control("reload".into()),
        "close tab" | "close the tab" | "close this tab" | "close current tab"
        | "close the current tab" | "close active tab" | "close this" => {
            return RouteAction::Control("close_tab".into())
        }
        "next tab" | "switch tab" | "other tab" => {
            return RouteAction::Control("switch_tab_next".into())
        }
        "previous tab" | "prev tab" | "last tab" => {
            return RouteAction::Control("switch_tab_prev".into())
        }
        "normal speed" | "reset speed" => return RouteAction::Control("speed:1".into()),
        "faster" | "speed up" | "play faster" => return RouteAction::Control("speed_up".into()),
        "slower" | "slow down" | "play slower" => return RouteAction::Control("speed_down".into()),
        "close popup" | "close the popup" | "close modal" | "dismiss popup" | "dismiss"
        | "press escape" | "hit escape" | "escape" => {
            return RouteAction::Control("press_escape".into())
        }
        "close it" | "close window" | "close the window" | "close this window" => {
            return RouteAction::Control("close_dialog".into())
        }
        "press enter" | "hit enter" | "enter" => return RouteAction::Control("press_enter".into()),
        "press tab" | "next field" => return RouteAction::Control("press_tab".into()),
        "control k" | "ctrl k" | "press control k" | "press ctrl k" | "hit control k"
        | "hit ctrl k" | "select control k" | "select ctrl k" => {
            return RouteAction::Control("press_ctrl_k".into())
        }
        "control f" | "ctrl f" | "press control f" | "press ctrl f" | "hit control f"
        | "hit ctrl f" | "select control f" | "select ctrl f" | "find on page"
        | "find in page" => return RouteAction::Control("press_ctrl_f".into()),
        _ => {}
    }

    if LIST_TABS_RE.is_match(cmd) {
        return RouteAction::Control("list_tabs".into());
    }

    if CLOSE_DIALOG_RE.is_match(cmd) {
        return RouteAction::Control("close_dialog".into());
    }

    if let Some(caps) = SWITCH_TAB_TO_RE.captures(cmd) {
        let q = caps
            .get(1)
            .or_else(|| caps.get(2))
            .map(|m| m.as_str().trim())
            .unwrap_or("");
        if matches!(q, "previous" | "prev" | "last") {
            return RouteAction::Control("switch_tab_prev".into());
        }
        if matches!(q, "next" | "other" | "another") {
            return RouteAction::Control("switch_tab_next".into());
        }
        if matches!(q, "new" | "a new" | "another new" | "one more" | "one more new") {
            return RouteAction::OpenUrl {
                goal: "Open a new tab.".to_string(),
                url: "https://www.google.com".to_string(),
                site_name: "a new tab".to_string(),
                new_tab: true,
            };
        }
        if !q.is_empty() {
            return RouteAction::Control(format!("switch_tab:{q}"));
        }
    }

    if is_new_tab_phrase(cmd) {
        return RouteAction::OpenUrl {
            goal: "Open a new tab.".to_string(),
            url: "https://www.google.com".to_string(),
            site_name: "a new tab".to_string(),
            new_tab: true,
        };
    }

    if let Some(rest) = cmd.strip_prefix("close ") {
        let count = match rest {
            "two tabs" | "2 tabs" => Some(2),
            "three tabs" | "3 tabs" => Some(3),
            "four tabs" | "4 tabs" => Some(4),
            "five tabs" | "5 tabs" => Some(5),
            _ => None,
        };
        if let Some(n) = count {
            return RouteAction::Pipeline(vec![RouteAction::Control("close_tab".into()); n]);
        }
        let site_candidate = rest
            .trim_start_matches("this ")
            .trim_start_matches("the ")
            .trim_end_matches(" tab")
            .trim();
        if match_site(site_candidate).is_some() || normalize_spoken_domain(site_candidate).is_some()
        {
            return RouteAction::Control("close_tab".into());
        }
    }

    // Never hijack questions like "what is youtube" or "how do I open a file".
    if cmd.starts_with("what ")
        || cmd.starts_with("why ")
        || cmd.starts_with("how ")
        || cmd.starts_with("who ")
        || cmd.starts_with("when ")
        || cmd.starts_with("where ")
        || cmd.starts_with("explain ")
        || cmd.starts_with("tell me ")
    {
        return RouteAction::Chat;
    }

    // Extract "in/on a new/another tab" once so search, open, and task routes all honor it cleanly.
    let (base_cmd_owned, new_tab) = extract_new_tab_modifier(cmd);
    let base_cmd = base_cmd_owned.as_str();

    if let Some(caps) = SEARCH_HERE_RE.captures(base_cmd) {
        let from_in_search = caps.get(3).is_some();
        let query = caps
            .get(1)
            .or_else(|| caps.get(2))
            .or_else(|| caps.get(3))
            .map(|m| m.as_str().trim())
            .unwrap_or("");
        if !query.is_empty() && (!from_in_search || query.split_whitespace().count() <= 6) {
            return RouteAction::BrowserTask {
                goal: format!("Use the search box on this page to search for {query}."),
                url: None,
                ack: format!("Searching this page for {query}."),
                new_tab: false,
            };
        }
    }

    if let Some(caps) = ON_SITE_ACTION_RE.captures(base_cmd) {
        let site_part = caps[1].trim();
        let verb = caps[2].trim();
        let query = caps[3].trim();
        if !query.is_empty() {
            if let Some(site) = match_site(site_part) {
                if matches!(verb, "play" | "watch") {
                    let start_url =
                        direct_search_url(site, query).unwrap_or_else(|| site.url.to_string());
                    return RouteAction::BrowserTask {
                        goal: format!(
                            "Click the top matching result for {query} on {} and make sure it plays.",
                            site.name
                        ),
                        url: Some(start_url),
                        ack: format!("Playing {query} on {}.", site.name),
                        new_tab,
                    };
                }
                return route_site_search(site, query, new_tab);
            }
            if let Some(domain) = normalize_spoken_domain(site_part) {
                let scoped = format!("site:{domain} {query}");
                return RouteAction::OpenUrl {
                    goal: format!("Search {domain} for {query}."),
                    url: format!("https://www.google.com/search?q={}", percent_encode_query(&scoped)),
                    site_name: format!("{domain} search for {query}"),
                    new_tab,
                };
            }
        }
    }

    if let Some(caps) = SEARCH_SITE_RE.captures(base_cmd) {
        let site_part = caps[1].trim();
        let query = caps[2].trim();
        if let Some(site) = match_site(site_part) {
            return route_site_search(site, query, new_tab);
        }
        if let Some(domain) = normalize_spoken_domain(site_part) {
            let scoped = format!("site:{domain} {query}");
            return RouteAction::OpenUrl {
                goal: format!("Search {domain} for {query}."),
                url: format!("https://www.google.com/search?q={}", percent_encode_query(&scoped)),
                site_name: format!("{domain} search for {query}"),
                new_tab,
            };
        }
        // Unknown brand search ("search ikea for standing desk"): strip stray "for" so Google gets "ikea standing desk".
        let stop_targets = ["me", "the", "a", "an", "this", "web", "the web", "here", "online", "all"];
        if site_part.split_whitespace().count() <= 2
            && !stop_targets.contains(&site_part)
            && !query.is_empty()
        {
            let combined = format!("{site_part} {query}");
            return RouteAction::OpenUrl {
                goal: format!("Search Google for {combined}."),
                url: format!("https://www.google.com/search?q={}", percent_encode_query(&combined)),
                site_name: format!("{site_part} search for {query}"),
                new_tab,
            };
        }
    }

    if let Some(caps) = SITE_SEARCH_PREFIX_RE.captures(base_cmd) {
        let site_part = caps[1].trim();
        let query = caps[2].trim();
        if let Some(site) = match_site(site_part) {
            return route_site_search(site, query, new_tab);
        }
        if let Some(domain) = normalize_spoken_domain(site_part) {
            let scoped = format!("site:{domain} {query}");
            return RouteAction::OpenUrl {
                goal: format!("Search {domain} for {query}."),
                url: format!("https://www.google.com/search?q={}", percent_encode_query(&scoped)),
                site_name: format!("{domain} search for {query}"),
                new_tab,
            };
        }
    }

    if let Some(caps) = SEARCH_FOR_ON_SITE_RE.captures(base_cmd) {
        let verb = caps[1].trim();
        let query = caps[2].trim();
        let site_part = caps[3].trim();
        if let Some(site) = match_site(site_part) {
            if matches!(verb, "play" | "watch") {
                let start_url = direct_search_url(site, query).unwrap_or_else(|| site.url.to_string());
                return RouteAction::BrowserTask {
                    goal: format!("Click the top matching result for {query} on {} and make sure it plays.", site.name),
                    url: Some(start_url),
                    ack: format!("Playing {query} on {}.", site.name),
                    new_tab,
                };
            }
            return route_site_search(site, query, new_tab);
        }
        if let Some(domain) = normalize_spoken_domain(site_part) {
            let scoped = format!("site:{domain} {query}");
            let start_url = format!("https://www.google.com/search?q={}", percent_encode_query(&scoped));
            if matches!(verb, "play" | "watch") {
                return RouteAction::BrowserTask {
                    goal: format!("Open the top matching result for {query} on {domain} and play it."),
                    url: Some(start_url),
                    ack: format!("Playing {query} on {domain}."),
                    new_tab,
                };
            }
            return RouteAction::OpenUrl {
                goal: format!("Search {domain} for {query}."),
                url: start_url,
                site_name: format!("{domain} search for {query}"),
                new_tab,
            };
        }
    }

    if let Some((site, query)) = match_search_site_without_for(base_cmd) {
        return route_site_search(site, query, new_tab);
    }

    if let Some(caps) = BARE_SITE_SEARCH_RE.captures(base_cmd) {
        let site_part = caps
            .get(1)
            .or_else(|| caps.get(2))
            .map(|m| m.as_str().trim())
            .unwrap_or("");
        if let Some(site) = match_site(site_part) {
            return RouteAction::OpenUrl {
                goal: format!("Open {} search.", site.name),
                url: site.url.to_string(),
                site_name: site.name.to_string(),
                new_tab,
            };
        }
        if let Some(domain) = normalize_spoken_domain(site_part) {
            return RouteAction::OpenUrl {
                goal: format!("Open {domain} search."),
                url: format!("https://{domain}"),
                site_name: domain,
                new_tab,
            };
        }
    }

    if let Some(caps) = OPEN_RE.captures(base_cmd) {
        let raw_target = caps[1].trim();
        let target = raw_target
            .strip_suffix(" search")
            .filter(|s| match_site(s.trim()).is_some() || normalize_spoken_domain(s.trim()).is_some())
            .map(str::trim)
            .unwrap_or(raw_target);
        if is_new_tab_phrase(target) {
            return RouteAction::OpenUrl {
                goal: "Open a new tab.".to_string(),
                url: "https://www.google.com".to_string(),
                site_name: "a new tab".to_string(),
                new_tab: true,
            };
        }
        if let Some(site) = match_site(target) {
            return RouteAction::OpenUrl {
                goal: format!("Open {} and make sure the page is loaded.", site.name),
                url: site.url.to_string(),
                site_name: site.name.to_string(),
                new_tab,
            };
        }
        if let Some(domain) = normalize_spoken_domain(target) {
            return RouteAction::OpenUrl {
                goal: format!("Open {domain} and make sure the page is loaded."),
                url: format!("https://{domain}"),
                site_name: domain,
                new_tab,
            };
        }
        if let Some(site_label) = target
            .strip_suffix(" website")
            .or_else(|| target.strip_suffix(" site"))
            .map(str::trim)
            .filter(|s| !s.is_empty())
        {
            return RouteAction::BrowserTask {
                goal: format!("Open the official website for {site_label} from the search results."),
                url: Some(format!(
                    "https://www.google.com/search?q={}",
                    percent_encode_query(site_label)
                )),
                ack: format!("Finding {site_label}."),
                new_tab,
            };
        }
        // Direct same-page section navigation ("go to images", "open images", "go to news", "open comments").
        if !new_tab && (base_cmd.starts_with("go to ") || base_cmd.starts_with("open ")) {
            let section = target.trim_start_matches("the ").trim();
            if GO_TO_UI_SECTION_RE.is_match(section) {
                return RouteAction::ClickTarget {
                    target: section.to_string(),
                    goal: format!("Click {section} on this page."),
                };
            }
        }
        // Only treat "open <target>" (not stray "go to head") as a same-tab Jev task for unknown targets.
        if base_cmd.starts_with("open ") && !target.starts_with("ended") && target.split_whitespace().count() <= 5 {
            return RouteAction::BrowserTask {
                goal: format!("Open {target}."),
                url: None,
                ack: format!("Opening {target}."),
                new_tab,
            };
        }
    }

    if let Some(caps) = SEARCH_GENERIC_RE.captures(base_cmd) {
        let query = caps[1].trim();
        if !query.is_empty() {
            let explicit_google =
                base_cmd.starts_with("google ") || base_cmd.starts_with("search the web ");
            return RouteAction::OpenUrl {
                goal: if explicit_google {
                    format!("Search Google web for {query}.")
                } else {
                    format!("Search Google for {query}.")
                },
                url: format!("https://www.google.com/search?q={}", percent_encode_query(query)),
                site_name: format!("Google search for {query}"),
                new_tab,
            };
        }
    }

    if let Some(action) = match_embedded_media_control(&norm) {
        return RouteAction::Control(action.into());
    }

    // Direct click on any visible clickable by label (falls back seamlessly to Jev if not matched on screen).
    if !new_tab {
        if APPEARANCE_OPTION_RE.is_match(base_cmd) {
            return RouteAction::ClickTarget {
                target: base_cmd.to_string(),
                goal: format!("Select {base_cmd} on this page."),
            };
        }
        if let Some(caps) = DIRECT_CLICK_RE.captures(base_cmd) {
            let target = caps[1].trim();
            let has_explicit_site_scope = target
                .rsplit_once(" on ")
                .map(|(_, s)| match_site(s.trim()).is_some() || normalize_spoken_domain(s.trim()).is_some())
                .unwrap_or(false);
            if !target.is_empty()
                && !has_explicit_site_scope
                && !SEMANTIC_CLICK_HINT_RE.is_match(target)
                && !SELECT_PHRASE_RE.is_match(base_cmd)
                && target.split_whitespace().count() <= 8
            {
                return RouteAction::ClickTarget {
                    target: target.to_string(),
                    goal: raw.trim().to_string(),
                };
            }
        }
    }

    // Require at least 2 words for GOAL_VERB_RE so a stray single word like "Select" doesn't spawn Jev.
    if (GOAL_VERB_RE.is_match(base_cmd) && base_cmd.contains(' '))
        || MEDIA_ACTION_RE.is_match(base_cmd)
        || SELECT_PHRASE_RE.is_match(base_cmd)
    {
        // Typing/writing verbs always stay on the active tab (never hijack ChatGPT prompts mentioning a site);
        // other same-page UI verbs only navigate if the utterance explicitly ends with "on/in <known site>".
        let is_typing_verb = base_cmd.starts_with("type ")
            || base_cmd.starts_with("enter ")
            || base_cmd.starts_with("fill ")
            || base_cmd.starts_with("write ");
        let inferred_site = if is_typing_verb {
            None
        } else if SAME_PAGE_UI_VERB_RE.is_match(base_cmd) {
            trailing_site_scope(base_cmd)
        } else {
            match_any_site_in_text(base_cmd)
        };
        let url = inferred_site.map(|s| s.url.to_string());
        let ack = match inferred_site {
            Some(s) => format!("Working on {} now.", s.name),
            None => "On it.".to_string(),
        };
        return RouteAction::BrowserTask {
            goal: raw.trim().to_string(),
            url,
            ack,
            new_tab,
        };
    }

    RouteAction::Chat
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn routes_known_sites_and_stt_variants() {
        for phrase in [
            "open youtube",
            "Jarvis, open YouTube!",
            "please open you tube",
            "go to utube",
        ] {
            match classify(phrase, false, false) {
                RouteAction::OpenUrl { url, site_name, .. } => {
                    assert_eq!(url, "https://www.youtube.com", "{phrase}");
                    assert_eq!(site_name, "YouTube");
                }
                other => panic!("unexpected for {phrase}: {other:?}"),
            }
        }

        for phrase in ["open wikipedia", "open wifipedia", "visit wiki pedia"] {
            match classify(phrase, false, false) {
                RouteAction::OpenUrl { url, site_name, .. } => {
                    assert_eq!(url, "https://en.wikipedia.org", "{phrase}");
                    assert_eq!(site_name, "Wikipedia");
                }
                other => panic!("unexpected for {phrase}: {other:?}"),
            }
        }
    }

    #[test]
    fn routes_searches_and_complex_goals() {
        match classify("search Wikipedia for Alan Turing", false, false) {
            RouteAction::OpenUrl { url, site_name, .. } => {
                assert_eq!(url, "https://en.wikipedia.org/w/index.php?search=alan+turing");
                assert_eq!(site_name, "Wikipedia search for alan turing");
            }
            other => panic!("{other:?}"),
        }

        match classify("play lo-fi beats on youtube", false, false) {
            RouteAction::BrowserTask { url, .. } => {
                assert_eq!(
                    url.as_deref(),
                    Some("https://www.youtube.com/results?search_query=lo-fi+beats")
                );
            }
            other => panic!("{other:?}"),
        }

        match classify(
            "Find one-way flights from Zurich to London on December 20, 2026",
            false,
            false,
        ) {
            RouteAction::BrowserTask { url, .. } => {
                assert_eq!(
                    url.as_deref(),
                    Some("https://www.google.com/travel/flights?hl=en")
                );
            }
            other => panic!("{other:?}"),
        }

        match classify("search for rust async traits", false, false) {
            RouteAction::OpenUrl { url, site_name, .. } => {
                assert_eq!(url, "https://www.google.com/search?q=rust+async+traits");
                assert_eq!(site_name, "Google search for rust async traits");
            }
            other => panic!("{other:?}"),
        }

        match classify("Blackberry Evolve X2 Select that video.", false, false) {
            RouteAction::BrowserTask { url, goal, .. } => {
                assert_eq!(url, None);
                assert!(goal.contains("Blackberry Evolve X2"));
            }
            other => panic!("{other:?}"),
        }

        assert!(is_addressed_to_jarvis("Hey Jarvis, what is gravity?"));
        assert!(is_addressed_to_jarvis("Jarvish explain this"));
        assert!(!is_addressed_to_jarvis("Our final prediction is regression probability"));

        match classify("open example.com", false, false) {
            RouteAction::OpenUrl { url, site_name, .. } => {
                assert_eq!(url, "https://example.com");
                assert_eq!(site_name, "example.com");
            }
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn routes_controls_confirmations_stop_and_quit() {
        assert_eq!(
            classify("scroll down", false, false),
            RouteAction::Control("scroll_down".into())
        );
        for phrase in [
            "Go down",
            "Scroll down Two",
            "More Scroll more",
            "keep scrolling",
            "scroll more",
        ] {
            assert_eq!(
                classify(phrase, false, false),
                RouteAction::Control("scroll_down".into()),
                "{phrase}"
            );
        }
        assert_eq!(
            classify("go up", false, false),
            RouteAction::Control("scroll_up".into())
        );
        match classify("You open Youtube shots.", false, false) {
            RouteAction::OpenUrl { url, site_name, .. } => {
                assert_eq!(url, "https://www.youtube.com/shorts");
                assert_eq!(site_name, "YouTube Shorts");
            }
            other => panic!("expected YouTube Shorts open url, got {other:?}"),
        }
        match classify("open shorts", false, false) {
            RouteAction::OpenUrl { url, .. } => {
                assert_eq!(url, "https://www.youtube.com/shorts");
            }
            other => panic!("expected YouTube Shorts open url, got {other:?}"),
        }
        assert_eq!(
            classify("go back", false, false),
            RouteAction::Control("back".into())
        );
        assert_eq!(
            classify("refresh", false, false),
            RouteAction::Control("reload".into())
        );
        assert_eq!(classify("read the page", false, false), RouteAction::ReadPage);
        assert_eq!(classify("stop", false, true), RouteAction::Stop);
        assert_eq!(classify("Jarvis quit", false, false), RouteAction::Quit);
        assert_eq!(classify("yes", true, false), RouteAction::Confirm(true));
        assert_eq!(classify("no", true, false), RouteAction::Confirm(false));
        assert_eq!(classify("yes", false, false), RouteAction::Chat);
    }

    #[test]
    fn negatives_stay_on_chat() {
        for chat in [
            "tell me a joke",
            "what is the capital of France",
            "what is youtube",
            "explain how photosynthesis works",
            "how do I open a file in Python",
            "open ended question about life",
            "who are you",
            "hello jarvis",
            "why is the sky blue",
            "when was Alan Turing born",
            "where is Zurich",
            "what's the weather like today",
            "explain quantum entanglement simply",
            "can you tell me a story",
            "good morning",
            "thank you",
            "who invented the internet",
            "summarize what we talked about",
        ] {
            assert_eq!(classify(chat, false, false), RouteAction::Chat, "{chat}");
        }
    }

    #[test]
    fn expanded_browser_phrase_matrix() {
        let mut count = 0;
        for (phrase, expected_url) in [
            ("open google", "https://www.google.com"),
            ("open gmail", "https://mail.google.com"),
            ("open g mail", "https://mail.google.com"),
            ("open github", "https://github.com"),
            ("open git hub", "https://github.com"),
            ("open reddit", "https://www.reddit.com"),
            ("open amazon", "https://www.amazon.com"),
            ("open netflix", "https://www.netflix.com"),
            ("open spotify", "https://open.spotify.com"),
            ("open linkedin", "https://www.linkedin.com"),
            ("open hacker news", "https://news.ycombinator.com"),
            ("open google maps", "https://maps.google.com"),
            ("visit bbc.com", "https://bbc.com"),
            ("search youtube for rust", "https://www.youtube.com/results?search_query=rust"),
            ("search amazon for usb cable", "https://www.amazon.com/s?k=usb+cable"),
            ("find wireless headphones on amazon", "https://www.amazon.com/s?k=wireless+headphones"),
            ("look up tokio on github", "https://github.com/search?q=tokio"),
            ("google weather in zurich", "https://www.google.com/search?q=weather+in+zurich"),
        ] {
            match classify(phrase, false, false) {
                RouteAction::OpenUrl { url, .. } => {
                    assert_eq!(url, expected_url, "{phrase}");
                    count += 1;
                }
                other => panic!("expected OpenUrl for {phrase}, got {other:?}"),
            }
        }
        for (phrase, expected_url) in [
            ("book a hotel in london", None),
            ("change quality to 1080p", None),
            ("add a comment", None),
            ("seek to 1:30", None),
            ("click the first video", None),
        ] {
            match classify(phrase, false, false) {
                RouteAction::BrowserTask { url, .. } => {
                    assert_eq!(url.as_deref(), expected_url, "{phrase}");
                    count += 1;
                }
                other => panic!("expected BrowserTask for {phrase}, got {other:?}"),
            }
        }
        assert_eq!(count, 23);

        // Universal direct voice clicks (including labels that match site names like "Docs", "Flights", "Maps", "GitHub").
        for (phrase, expected_target) in [
            ("click sign in", "sign in"),
            ("click on Accept all", "accept all"),
            ("tap the Free cancellation checkbox", "free cancellation checkbox"),
            ("click docs", "docs"),
            ("click flights", "flights"),
            ("click maps", "maps"),
            ("click github", "github"),
            ("select Price low to high", "price low to high"),
        ] {
            match classify(phrase, false, false) {
                RouteAction::ClickTarget { target, .. } => {
                    assert_eq!(target, expected_target, "{phrase}");
                }
                other => panic!("expected ClickTarget for {phrase:?}, got {other:?}"),
            }
        }

        for (phrase, expected_ctrl) in [
            ("pause the video", "pause_video"),
            ("play the video", "play_video"),
            ("turn off the volume", "mute_video"),
            ("mute", "mute_video"),
            ("unmute", "unmute_video"),
            ("turn the volume up for the video", "volume_up"),
            ("increase the volume", "volume_up"),
            ("volume down", "volume_down"),
            ("reduce the sound", "volume_down"),
            ("volume 35%", "volume:35"),
            ("skip the ad", "skip_ad"),
            ("skip the air", "skip_ad"),
            ("open settings", "open_settings"),
            ("open the settings", "open_settings"),
            ("select settings", "open_settings"),
            ("go to settings", "open_settings"),
            ("turn on captions", "toggle_captions"),
            ("go fullscreen", "fullscreen"),
            ("rewind 10 seconds", "seek_back"),
            ("fast forward", "seek_forward"),
            ("refresh this page", "reload"),
            ("scroll down. Scroll down.", "scroll_down"),
            ("close youtube", "close_tab"),
            ("close you to", "close_tab"),
            ("close Q two", "close_tab"),
            ("close this", "close_tab"),
            ("There's a smarter way Skip the ad.", "skip_ad"),
            ("The Pause the video.", "pause_video"),
            ("Okay, so pause the video, please take it.", "pause_video"),
            ("Volume, volume up I mean.", "volume_up"),
            ("Turn the value low.", "volume_down"),
        ] {
            assert_eq!(
                classify(phrase, false, false),
                RouteAction::Control(expected_ctrl.into()),
                "{phrase}"
            );
        }
        assert_eq!(classify("Select", false, false), RouteAction::Chat);
        assert_eq!(classify("Go to head", false, false), RouteAction::Chat);
        assert!(is_addressed_to_jarvis("Hello, Jabesh."));

        match classify("open another tab", false, false) {
            RouteAction::OpenUrl { new_tab, .. } => assert!(new_tab),
            other => panic!("expected OpenUrl new_tab for open another tab, got {other:?}"),
        }
        match classify("Uh. Open another tab.", false, false) {
            RouteAction::OpenUrl { new_tab, .. } => assert!(new_tab),
            other => panic!("expected OpenUrl new_tab for Uh. Open another tab., got {other:?}"),
        }
        match classify("Hello Jarvis, open Youtube.", false, false) {
            RouteAction::OpenUrl { url, new_tab, .. } => {
                assert_eq!(url, "https://www.youtube.com");
                assert!(!new_tab);
            }
            other => panic!("expected OpenUrl for Hello Jarvis open Youtube, got {other:?}"),
        }
        match classify("open youtube on another tab", false, false) {
            RouteAction::OpenUrl { url, new_tab, .. } => {
                assert_eq!(url, "https://www.youtube.com");
                assert!(new_tab);
            }
            other => panic!("expected OpenUrl new_tab for open youtube on another tab, got {other:?}"),
        }
        match classify("Open Youtube Open Youtube", false, false) {
            RouteAction::OpenUrl { url, new_tab, .. } => {
                assert_eq!(url, "https://www.youtube.com");
                assert!(!new_tab);
            }
            other => panic!("expected deduped YouTube OpenUrl, got {other:?}"),
        }
        for phrase in [
            "Open another new tab.",
            "Open another tab. Open a new tab",
        ] {
            match classify(phrase, false, false) {
                RouteAction::OpenUrl { new_tab, .. } => assert!(new_tab, "{phrase}"),
                other => panic!("expected OpenUrl new_tab for {phrase:?}, got {other:?}"),
            }
        }
        assert_eq!(
            classify("Open another new tab. Close this tab.", false, false),
            RouteAction::Control("close_tab".into())
        );
        assert_eq!(
            classify("open a new tab close this tab", false, false),
            RouteAction::Control("close_tab".into())
        );

        match classify("open huggingface in new tab", false, false) {
            RouteAction::OpenUrl {
                url,
                site_name,
                new_tab,
                ..
            } => {
                assert_eq!(url, "https://huggingface.co");
                assert_eq!(site_name, "Hugging Face");
                assert!(new_tab);
            }
            other => panic!("expected OpenUrl new_tab for HuggingFace, got {other:?}"),
        }
        match classify("open hacking page in new tab", false, false) {
            RouteAction::OpenUrl { url, new_tab, .. } => {
                assert_eq!(url, "https://huggingface.co");
                assert!(new_tab);
            }
            other => panic!("expected OpenUrl new_tab for hacking page, got {other:?}"),
        }
        match classify("open you to", false, false) {
            RouteAction::OpenUrl { url, new_tab, .. } => {
                assert_eq!(url, "https://www.youtube.com");
                assert!(!new_tab);
            }
            other => panic!("expected OpenUrl for open you to, got {other:?}"),
        }
        for noise in ["a", "e", "de", "He", "it", "the", "as"] {
            assert_eq!(classify(noise, false, false), RouteAction::Ignore, "{noise}");
        }
    }

    #[test]
    fn routes_universal_web_and_accessibility_commands() {
        for (phrase, expected_ctrl) in [
            ("scroll to top", "scroll_top"),
            ("go to bottom", "scroll_bottom"),
            ("zoom in", "zoom_in"),
            ("make text smaller", "zoom_out"),
            ("reset zoom", "zoom_reset"),
            ("next tab", "switch_tab_next"),
            ("previous tab", "switch_tab_prev"),
            ("switch to wikipedia", "switch_tab:wikipedia"),
            ("go to github tab", "switch_tab:github"),
            ("close popup", "press_escape"),
            ("dismiss", "press_escape"),
            ("press enter", "press_enter"),
            ("next field", "press_tab"),
            ("pause the music", "pause_video"),
            ("play the podcast", "play_video"),
            ("mute audio", "mute_video"),
            ("speed 1.5", "speed:1.50"),
            ("normal speed", "speed:1"),
            ("play faster", "speed_up"),
            ("slow down", "speed_down"),
            ("next song", "next_track"),
            ("previous episode", "prev_track"),
            ("skip intro", "skip_ad"),
        ] {
            assert_eq!(
                classify(phrase, false, false),
                RouteAction::Control(expected_ctrl.into()),
                "{phrase}"
            );
        }

        // Spoken domains work for ANY website on earth without hardcoding.
        match classify("open bbc dot co dot uk", false, false) {
            RouteAction::OpenUrl { url, new_tab, .. } => {
                assert_eq!(url, "https://bbc.co.uk");
                assert!(!new_tab);
            }
            other => panic!("expected spoken domain OpenUrl, got {other:?}"),
        }
        match classify("visit arxiv dot org in new tab", false, false) {
            RouteAction::OpenUrl { url, new_tab, .. } => {
                assert_eq!(url, "https://arxiv.org");
                assert!(new_tab);
            }
            other => panic!("expected spoken domain new_tab OpenUrl, got {other:?}"),
        }
        match classify("search rust-lang dot org for borrow checker", false, false) {
            RouteAction::OpenUrl { url, .. } => {
                assert!(url.contains("site%3Arust-lang.org"), "{url}");
                assert!(url.contains("borrow+checker"), "{url}");
            }
            other => panic!("expected domain-scoped search OpenUrl, got {other:?}"),
        }
        match classify("search here for headphones", false, false) {
            RouteAction::BrowserTask { url, goal, .. } => {
                assert!(url.is_none());
                assert!(goal.contains("headphones"));
            }
            other => panic!("expected same-page BrowserTask, got {other:?}"),
        }
        match classify("open khan academy", false, false) {
            RouteAction::OpenUrl { url, .. } => assert_eq!(url, "https://www.khanacademy.org"),
            other => panic!("expected Khan Academy OpenUrl, got {other:?}"),
        }
        match classify("open stripe website", false, false) {
            RouteAction::BrowserTask { url, .. } => {
                assert_eq!(url.as_deref(), Some("https://www.google.com/search?q=stripe"));
            }
            other => panic!("expected generic brand website lookup, got {other:?}"),
        }
        assert_eq!(classify("read this", false, false), RouteAction::ReadPage);
        assert_eq!(classify("what page am i on", false, false), RouteAction::ReadPage);

        for phrase in [
            "accept cookies",
            "reject cookies",
            "show more",
            "load more results",
            "add to cart",
            "choose the second option",
            "sort by lowest price",
            "like this post",
            "subscribe to channel",
            "next page",
        ] {
            match classify(phrase, false, false) {
                RouteAction::BrowserTask { url, .. } => assert!(url.is_none(), "{phrase}"),
                other => panic!("expected same-tab BrowserTask for {phrase:?}, got {other:?}"),
            }
        }
        // Single stray words must still NOT trigger Jev.
        for stray in ["Accept", "Like", "Show", "Add", "Select"] {
            assert_eq!(classify(stray, false, false), RouteAction::Chat, "{stray}");
        }
    }

    #[test]
    fn routes_differentiated_website_pipelines_from_booking_to_surfing() {
        // 1. "search in youtube ... then go to new tab" -> 2-step Pipeline (search first, then new tab).
        match classify("search in youtube for lo-fi then go to new tab", false, false) {
            RouteAction::Pipeline(steps) => {
                assert_eq!(steps.len(), 2);
                assert!(matches!(
                    &steps[0],
                    RouteAction::OpenUrl { url, new_tab: false, .. }
                        if url == "https://www.youtube.com/results?search_query=lo-fi"
                ));
                assert!(matches!(
                    &steps[1],
                    RouteAction::OpenUrl { site_name, new_tab: true, .. }
                        if site_name == "a new tab"
                ));
            }
            other => panic!("expected 2-step Pipeline, got {other:?}"),
        }

        // Bare "search in youtube then go to new tab" must NOT Google "in youtube" and NOT switch_tab:new.
        match classify("search in youtube then go to new tab", false, false) {
            RouteAction::Pipeline(steps) => {
                assert_eq!(steps.len(), 2);
                assert!(matches!(
                    &steps[0],
                    RouteAction::OpenUrl { url, new_tab: false, .. } if url == "https://www.youtube.com"
                ));
                assert!(matches!(
                    &steps[1],
                    RouteAction::OpenUrl { new_tab: true, .. }
                ));
            }
            other => panic!("expected YouTube -> new tab Pipeline, got {other:?}"),
        }

        // 2. Smart collapsing: "open a new tab and search youtube for rust" -> 1 direct OpenUrl(new_tab=true).
        match classify("open a new tab and search youtube for rust", false, false) {
            RouteAction::OpenUrl { url, new_tab, .. } => {
                assert_eq!(url, "https://www.youtube.com/results?search_query=rust");
                assert!(new_tab);
            }
            other => panic!("expected collapsed new_tab YouTube search, got {other:?}"),
        }

        // 3. Smart collapsing: "open youtube and search for rust" -> 1 direct YouTube search URL.
        match classify("open youtube and search for rust", false, false) {
            RouteAction::OpenUrl { url, new_tab, .. } => {
                assert_eq!(url, "https://www.youtube.com/results?search_query=rust");
                assert!(!new_tab);
            }
            other => panic!("expected collapsed YouTube search, got {other:?}"),
        }

        // 4. Smart collapsing on site without search_url: "open netflix and search for inception" -> BrowserTask on Netflix.
        match classify("open netflix and search for inception", false, false) {
            RouteAction::BrowserTask { url, goal, new_tab, .. } => {
                assert_eq!(url.as_deref(), Some("https://www.netflix.com"));
                assert!(goal.contains("inception"));
                assert!(!new_tab);
            }
            other => panic!("expected Netflix BrowserTask, got {other:?}"),
        }

        // 5. Booking & travel pipelines: direct search URLs, collapsed tasks, and new-tab booking tasks.
        match classify("search booking for paris hotels", false, false) {
            RouteAction::OpenUrl { url, new_tab, .. } => {
                assert_eq!(url, "https://www.booking.com/searchresults.html?ss=paris+hotels");
                assert!(!new_tab);
            }
            other => panic!("expected Booking search OpenUrl, got {other:?}"),
        }
        match classify("open booking.com and find hotels in paris", false, false) {
            RouteAction::BrowserTask { url, goal, new_tab, .. } => {
                assert_eq!(url.as_deref(), Some("https://www.booking.com"));
                assert!(goal.contains("hotels in paris"));
                assert!(!new_tab);
            }
            other => panic!("expected collapsed Booking BrowserTask, got {other:?}"),
        }
        match classify("open a new tab and book flights from zurich to london", false, false) {
            RouteAction::BrowserTask { url, new_tab, .. } => {
                assert_eq!(url.as_deref(), Some("https://www.google.com/travel/flights?hl=en"));
                assert!(new_tab);
            }
            other => panic!("expected collapsed new-tab Flights BrowserTask, got {other:?}"),
        }

        // 6. Universal new_tab suffix/prefix works on searches & play tasks without leaking into the query.
        for phrase in [
            "search youtube for rust in a new tab",
            "search in youtube for rust in a new tab",
            "search rust on youtube in a new tab",
            "youtube search rust in a new tab",
            "in a new tab search youtube for rust",
        ] {
            match classify(phrase, false, false) {
                RouteAction::OpenUrl { url, new_tab, .. } => {
                    assert_eq!(url, "https://www.youtube.com/results?search_query=rust", "{phrase}");
                    assert!(new_tab, "{phrase}");
                }
                other => panic!("expected new_tab YouTube search for {phrase:?}, got {other:?}"),
            }
        }
        match classify("play lofi beats on youtube in a new tab", false, false) {
            RouteAction::BrowserTask { url, new_tab, .. } => {
                assert_eq!(
                    url.as_deref(),
                    Some("https://www.youtube.com/results?search_query=lofi+beats")
                );
                assert!(new_tab);
            }
            other => panic!("expected new_tab play BrowserTask, got {other:?}"),
        }

        // 7. Search without "for" and "and" inside a search query must stay intact.
        match classify("search youtube rust tutorial", false, false) {
            RouteAction::OpenUrl { url, .. } => {
                assert_eq!(url, "https://www.youtube.com/results?search_query=rust+tutorial");
            }
            other => panic!("expected YouTube search without 'for', got {other:?}"),
        }
        match classify("search amazon for bread and butter", false, false) {
            RouteAction::OpenUrl { url, .. } => {
                assert_eq!(url, "https://www.amazon.com/s?k=bread+and+butter");
            }
            other => panic!("expected intact 'bread and butter' Amazon search, got {other:?}"),
        }

        // 8. Non-collapsible pipeline: open wikipedia and read the page.
        match classify("open wikipedia and read the page", false, false) {
            RouteAction::Pipeline(steps) => {
                assert_eq!(steps.len(), 2);
                assert!(matches!(&steps[0], RouteAction::OpenUrl { url, .. } if url == "https://en.wikipedia.org"));
                assert_eq!(steps[1], RouteAction::ReadPage);
            }
            other => panic!("expected OpenUrl + ReadPage pipeline, got {other:?}"),
        }

        // 9. "go to new tab" opens a new tab instead of switch_tab:new.
        match classify("go to new tab", false, false) {
            RouteAction::OpenUrl { new_tab, site_name, .. } => {
                assert!(new_tab);
                assert_eq!(site_name, "a new tab");
            }
            other => panic!("expected new tab OpenUrl, got {other:?}"),
        }

        // 10. Unpunctuated fillers ("okay open youtube"), STT scroll variants, and rightmost command in merged speech.
        match classify("okay open youtube", false, false) {
            RouteAction::OpenUrl { url, new_tab, .. } => {
                assert_eq!(url, "https://www.youtube.com");
                assert!(!new_tab);
            }
            other => panic!("expected instant YouTube OpenUrl for 'okay open youtube', got {other:?}"),
        }
        assert_eq!(
            classify("school down", false, false),
            RouteAction::Control("scroll_down".into())
        );
        assert_eq!(
            classify(
                "He Scroll down Pause the video. Play the video. Scroll up Close Youtube",
                false,
                false
            ),
            RouteAction::Control("close_tab".into())
        );

        // 11. Greedy search-with-in/on, unknown brand search, google for X, search+and+action, and titled video clicks.
        match classify("find hotels in paris on booking.com", false, false) {
            RouteAction::OpenUrl { url, .. } => {
                assert_eq!(url, "https://www.booking.com/searchresults.html?ss=hotels+in+paris");
            }
            other => panic!("expected Booking search for 'hotels in paris', got {other:?}"),
        }
        match classify("play songs in hindi on youtube", false, false) {
            RouteAction::BrowserTask { url, .. } => {
                assert_eq!(
                    url.as_deref(),
                    Some("https://www.youtube.com/results?search_query=songs+in+hindi")
                );
            }
            other => panic!("expected YouTube play search for 'songs in hindi', got {other:?}"),
        }
        match classify("google for rust async", false, false) {
            RouteAction::OpenUrl { url, .. } => {
                assert_eq!(url, "https://www.google.com/search?q=rust+async");
            }
            other => panic!("expected clean Google search without 'for', got {other:?}"),
        }
        match classify("search ikea for standing desk", false, false) {
            RouteAction::OpenUrl { url, .. } => {
                assert_eq!(url, "https://www.google.com/search?q=ikea+standing+desk");
            }
            other => panic!("expected clean brand search without 'for', got {other:?}"),
        }
        match classify("search youtube for lo-fi and open a new tab", false, false) {
            RouteAction::Pipeline(steps) => {
                assert_eq!(steps.len(), 2);
                assert!(matches!(
                    &steps[0],
                    RouteAction::OpenUrl { url, .. } if url == "https://www.youtube.com/results?search_query=lo-fi"
                ));
                assert!(matches!(&steps[1], RouteAction::OpenUrl { new_tab: true, .. }));
            }
            other => panic!("expected 2-step search + new tab pipeline, got {other:?}"),
        }
        match classify("select the ramayana video", false, false) {
            RouteAction::ClickTarget { target, .. } => assert_eq!(target, "ramayana video"),
            other => panic!("expected fast ClickTarget for titled video, got {other:?}"),
        }
        match classify("type github", false, false) {
            RouteAction::BrowserTask { url, .. } => assert!(url.is_none()),
            other => panic!("expected same-tab BrowserTask for 'type github', got {other:?}"),
        }
        match classify("find pricing here", false, false) {
            RouteAction::BrowserTask { url, goal, .. } => {
                assert!(url.is_none());
                assert!(goal.contains("pricing"));
            }
            other => panic!("expected same-page search for 'find pricing here', got {other:?}"),
        }

        // 12. Bare enter, Ctrl+K/Ctrl+F shortcuts, hands-free explain/summarize page, and 'on search <site> ...'.
        assert_eq!(classify("enter", false, false), RouteAction::Control("press_enter".into()));
        assert_eq!(
            classify("select control k", false, false),
            RouteAction::Control("press_ctrl_k".into())
        );
        assert_eq!(
            classify("control f", false, false),
            RouteAction::Control("press_ctrl_f".into())
        );
        assert_eq!(classify("school up", false, false), RouteAction::Control("scroll_up".into()));
        assert_eq!(classify("explain this", false, false), RouteAction::ReadPage);
        assert_eq!(classify("summarize the page", false, false), RouteAction::ReadPage);
        assert_eq!(classify("explain quantum physics", false, false), RouteAction::Chat);
        match classify("on search wikipedia select apple", false, false) {
            RouteAction::OpenUrl { url, .. } => {
                assert_eq!(url, "https://en.wikipedia.org/w/index.php?search=apple");
            }
            other => panic!("expected Wikipedia search for 'apple', got {other:?}"),
        }

        // 13. Relative tab switching, same-page section nav, dialog closing, ad-CTA bleed guard, STT skip/pause, tab count.
        assert_eq!(
            classify("switch to previous tab", false, false),
            RouteAction::Control("switch_tab_prev".into())
        );
        assert_eq!(
            classify("switch to next tab", false, false),
            RouteAction::Control("switch_tab_next".into())
        );
        assert_eq!(
            classify("go to the another tab", false, false),
            RouteAction::Control("switch_tab_next".into())
        );
        assert_eq!(
            classify("how many tabs are open", false, false),
            RouteAction::Control("list_tabs".into())
        );
        for phrase in ["close the window", "close the help window", "close this help window", "close it"] {
            assert_eq!(
                classify(phrase, false, false),
                RouteAction::Control("close_dialog".into()),
                "{phrase}"
            );
        }
        for (phrase, expected) in [
            ("go to images", "images"),
            ("go to AI mode", "ai mode"),
            ("go to news", "news"),
            ("go to videos", "videos"),
            ("go to forums", "forums"),
        ] {
            match classify(phrase, false, false) {
                RouteAction::ClickTarget { target, .. } => assert_eq!(target, expected, "{phrase}"),
                other => panic!("expected ClickTarget for {phrase:?}, got {other:?}"),
            }
        }
        assert_eq!(classify("skip the add", false, false), RouteAction::Control("skip_ad".into()));
        assert_eq!(classify("skip the hat", false, false), RouteAction::Control("skip_ad".into()));
        assert_eq!(classify("stop the video", false, false), RouteAction::Control("pause_video".into()));
        assert_eq!(classify("start building today", false, false), RouteAction::Chat);

        // 14. 'this'/'that' media controls, '<query> in search', and glued trailing stop only while task_running.
        assert_eq!(classify("pause this video", false, false), RouteAction::Control("pause_video".into()));
        assert_eq!(classify("play this video", false, false), RouteAction::Control("play_video".into()));
        assert_eq!(classify("mute this video", false, false), RouteAction::Control("mute_video".into()));
        assert_eq!(classify("skip this ad", false, false), RouteAction::Control("skip_ad".into()));
        assert_eq!(classify("skip this", false, false), RouteAction::Control("skip_ad".into()));
        assert_eq!(
            classify("this tab skip this this skip this ad", false, false),
            RouteAction::Control("skip_ad".into())
        );
        match classify("perfect in search", false, false) {
            RouteAction::BrowserTask { url, goal, .. } => {
                assert!(url.is_none());
                assert!(goal.contains("perfect"));
            }
            other => panic!("expected same-page search for 'perfect in search', got {other:?}"),
        }
        assert_eq!(classify("i love y'all bro stop", false, true), RouteAction::Stop);
        assert_eq!(classify("i love y'all bro stop", false, false), RouteAction::Chat);
        match classify("open images", false, false) {
            RouteAction::ClickTarget { target, .. } => assert_eq!(target, "images"),
            other => panic!("expected ClickTarget for 'open images', got {other:?}"),
        }
        assert_eq!(
            classify("close current tab", false, false),
            RouteAction::Control("close_tab".into())
        );

        // 15. Typing prompts mentioning sites stay on active tab; AI apps (Gemini/Claude/Perplexity/DeepSeek) route directly.
        match classify("type s on a HuggingFace letter", false, false) {
            RouteAction::BrowserTask { url, .. } => assert!(url.is_none()),
            other => panic!("expected same-tab BrowserTask for typing prompt mentioning HuggingFace, got {other:?}"),
        }
        match classify("write an essay on youtube", false, false) {
            RouteAction::BrowserTask { url, .. } => assert!(url.is_none()),
            other => panic!("expected same-tab BrowserTask for write prompt mentioning YouTube, got {other:?}"),
        }
        match classify("click sign in on github", false, false) {
            RouteAction::BrowserTask { url, .. } => assert_eq!(url.as_deref(), Some("https://github.com")),
            other => panic!("expected GitHub-scoped BrowserTask, got {other:?}"),
        }
        for (phrase, expected) in [
            ("open gemini", "https://gemini.google.com"),
            ("open claude", "https://claude.ai"),
            ("open claude ai", "https://claude.ai"),
            ("open perplexity", "https://www.perplexity.ai"),
            ("open deepseek", "https://chat.deepseek.com"),
        ] {
            match classify(phrase, false, false) {
                RouteAction::OpenUrl { url, .. } => assert_eq!(url, expected, "{phrase}"),
                other => panic!("expected OpenUrl for {phrase:?}, got {other:?}"),
            }
        }

        // 16. Close site variants, multi-tab close with gratitude prefix, bare appearance options, and active-site search.
        for phrase in [
            "close this wikipedia",
            "close the youtube tab",
            "close this github tab",
        ] {
            assert_eq!(
                classify(phrase, false, false),
                RouteAction::Control("close_tab".into()),
                "{phrase}"
            );
        }
        assert_eq!(
            classify("Okay, thank you. Close three tabs.", false, false),
            RouteAction::Pipeline(vec![
                RouteAction::Control("close_tab".into()),
                RouteAction::Control("close_tab".into()),
                RouteAction::Control("close_tab".into()),
            ])
        );
        for (phrase, expected_target) in [
            ("text large", "text large"),
            ("text small", "text small"),
            ("text standard", "text standard"),
            ("color dark", "color dark"),
            ("color light", "color light"),
            ("color automatic", "color automatic"),
            ("width wide", "width wide"),
            ("width standard", "width standard"),
            ("dark mode", "dark mode"),
        ] {
            match classify(phrase, false, false) {
                RouteAction::ClickTarget { target, .. } => assert_eq!(target, expected_target, "{phrase}"),
                other => panic!("expected ClickTarget for {phrase:?}, got {other:?}"),
            }
        }
        assert_eq!(
            contextualize_generic_search(
                "https://www.youtube.com/",
                "Search Google for mrbeast.",
                "https://www.google.com/search?q=mrbeast",
                "Google search for mrbeast",
                false,
            ),
            Some((
                "Search YouTube for mrbeast.".into(),
                "https://www.youtube.com/results?search_query=mrbeast".into(),
                "YouTube search for mrbeast".into(),
            ))
        );
        assert_eq!(
            contextualize_generic_search(
                "https://en.wikipedia.org/wiki/Main_Page",
                "Search Google for apple.",
                "https://www.google.com/search?q=apple",
                "Google search for apple",
                false,
            ),
            Some((
                "Search Wikipedia for apple.".into(),
                "https://en.wikipedia.org/w/index.php?search=apple".into(),
                "Wikipedia search for apple".into(),
            ))
        );
        // Explicit "google <query>" must stay on Google even when on Wikipedia.
        assert_eq!(
            contextualize_generic_search(
                "https://en.wikipedia.org/wiki/Main_Page",
                "Search Google web for apple.",
                "https://www.google.com/search?q=apple",
                "Google search for apple",
                false,
            ),
            None
        );
    }
}
