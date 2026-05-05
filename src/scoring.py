from datetime import datetime, timedelta
import re

from src.models import NormalizedEvent
from src.utils import BERLIN_TZ


CATEGORY_MAP = [
    ("TUM Must", ["speakers series", "tum speakers"]),
    ("Energy", ["energy", "power system", "renewable", "smart grid", "district heating", "heat pump", "sector coupling"]),
    ("Buildings", ["building", "hvac", "building control", "building automation", "energy management"]),
    ("Finance", ["finance", "economics", "market", "asset pricing", "climate finance", "carbon pricing"]),
    ("AI", ["artificial intelligence", "machine learning", "foundation model", "llm", "deep learning", "ai "]),
    ("Quantum", ["quantum", "mcqst", "munich quantum"]),
    ("Physics", ["physics", "cosmology", "particle", "condensed matter"]),
    ("Math", ["mathematics", "theorem", "geometry", "topology", "number theory", "tcs"]),
    ("Medicine", ["medicine", "clinical", "health ai"]),
    ("Bioengineering", ["bioengineering", "biomedical", "genomics", "protein"]),
    ("Neuroscience", ["neuro", "neuroscience", "brain"]),
]


TOPIC_BONUSES = [
    (35, ["energy system", "building energy", "hvac", "model predictive control", "mpc", "smart grid", "renewable", "energy management", "optimization"]),
    (30, ["finance", "asset pricing", "energy markets", "econometrics", "climate finance", "carbon pricing"]),
    (30, ["artificial intelligence", "machine learning", "foundation model", "llm", "ai safety", "deep learning"]),
    (30, ["quantum", "theoretical computer science", "cryptography", "particle physics", "mathematics"]),
    (25, ["medicine", "biomedical", "bioengineering", "neuroscience", "drug discovery"]),
]


HIGH_IMPACT = ["nobel", "fields medal", "turing award", "abel prize", "keynote", "plenary", "distinguished lecturer", "chief scientist", "founder", "ceo", "cto"]
INSTITUTION_SIGNAL = ["mit", "stanford", "harvard", "princeton", "ias", "berkeley", "oxford", "cambridge", "caltech", "eth", "epfl", "max planck", "deepmind", "openai", "anthropic"]
ONLINE_SIGNAL = ["zoom", "online", "livestream", "stream", "webcast", "youtube", "remote", "hybrid", "webinar"]
LOCAL_SIGNAL = ["tum", "munich", "garching", "ifo", "lmu", "max planck munich"]
PENALTIES = [
    (-30, ["application deadline", "deadline"]),
    (-30, ["student only"]),
    (-25, ["internal only"]),
    (-25, ["exam", "course", "training"]),
    (-20, ["career fair", "job fair"]),
    (-20, ["registration deadline"]),
    (-15, ["networking"]),
]
GENERIC_TITLES = {
    "events",
    "calendar",
    "seminar",
    "astrophysics seminar",
    "physics events",
    "upcoming events",
}
BAD_TITLE_PHRASES = [
    "add to calendar",
    "refreshments at",
    "javascript must be enabled",
    "departments",
    "part of",
    "hewlett",
    "kirsch auditorium",
    "zoom registration required",
    "i forgot my password",
    "log in",
    "share ",
    "sunet",
    "tbd",
    "munich center for quantum science and technology",
    "munich quantum center",
]
LOW_VALUE_PATTERNS = [
    "phd café",
    "phd caf",
    "open studios",
    "summer school",
    "onboarding",
    "welcome day",
    "career fair",
    "job fair",
    "info session",
    "application deadline",
    "registration deadline",
    "social",
    "reception",
    "performing arts",
    "project showcase",
    "tour",
    "training",
    "student group",
    "community-only",
    "cohort",
]
GENERIC_SERIES_PATTERNS = [
    "astrophysics seminar",
    "physics events",
    "events",
    "upcoming events",
    "seminar",
    "colloquium",
    "institute for advanced study astrophysics seminar",
]
PROSE_TITLE_PREFIXES = [
    "the ai index, currently",
    "strategic stability exists when",
]


def _contains_any(text: str, phrases: list[str]) -> bool:
    return any(phrase in text for phrase in phrases)


def score_event(event: NormalizedEvent, source_weight: int) -> NormalizedEvent:
    text = " ".join(
        [
            event.title or "",
            event.description or "",
            event.source_name or "",
            event.location or "",
            event.affiliation or "",
        ]
    ).lower()
    score = source_weight
    reasons = [f"source_weight:{source_weight}"]

    for bonus, phrases in TOPIC_BONUSES:
        if _contains_any(text, phrases):
            score += bonus
            reasons.append(f"topic_bonus:+{bonus}:{phrases[0]}")

    if _contains_any(text, HIGH_IMPACT):
        score += 50
        reasons.append("high_impact:+50")
    if _contains_any(text, INSTITUTION_SIGNAL):
        score += 20
        reasons.append("institution_signal:+20")
    if _contains_any(text, ONLINE_SIGNAL) or event.online_url:
        score += 20
        reasons.append("online_bonus:+20")
    if _contains_any(text, LOCAL_SIGNAL):
        score += 15
        reasons.append("local_bonus:+15")

    for penalty, phrases in PENALTIES:
        if _contains_any(text, phrases):
            score += penalty
            reasons.append(f"penalty:{penalty}:{phrases[0]}")

    if not event.speaker and len(event.title.split()) < 4:
        score -= 15
        reasons.append("penalty:-15:weak_title_no_speaker")

    categories = []
    for category, tokens in CATEGORY_MAP:
        if _contains_any(text, tokens):
            categories.append(category)
    if not categories:
        categories.append("General High Impact")
    event.categories = categories
    event.score = max(0, min(100, score))
    event.score_reasons = reasons
    return event


def should_include(event: NormalizedEvent, source_group: str) -> tuple[bool, list[str]]:
    now = datetime.now(tz=BERLIN_TZ)
    reasons = []
    if event.start is None:
        reasons.append("missing_real_date")
    elif event.start < now:
        reasons.append("past_event")
    if event.start is not None and event.start > now + timedelta(days=365) and event.score < 90:
        reasons.append("too_far_future")
    if event.title.strip().lower() == "page updated":
        reasons.append("placeholder_title")
    normalized_title = " ".join(event.title.strip().lower().split())
    if normalized_title in GENERIC_TITLES:
        reasons.append("generic_title")
    reduced = normalized_title.replace("upcoming", "").replace("events", "").replace("seminar", "").replace("calendar", "").replace("physics", "").replace("astrophysics", "").strip()
    if not reduced:
        reasons.append("generic_title")
    if normalized_title.startswith("tba speakers"):
        reasons.append("generic_title")
    if "javascript must be enabled" in normalized_title or normalized_title in {"location", "america/new_york"}:
        reasons.append("generic_title")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", normalized_title):
        reasons.append("generic_title")
    if re.fullmatch(r"\d{1,2}\s+[a-zäöü]+\s+\d{4}", normalized_title):
        reasons.append("date_only_title")
    if any(phrase in normalized_title for phrase in BAD_TITLE_PHRASES):
        reasons.append("generic_title")
    if re.fullmatch(r"\d{1,2}:\d{2}\s*(am|pm)\s*-\s*\d{1,2}:\d{2}\s*(am|pm)", normalized_title):
        reasons.append("generic_title")
    if len(normalized_title.split()) > 18:
        reasons.append("generic_title")
    if any(pattern in normalized_title for pattern in LOW_VALUE_PATTERNS):
        reasons.append("low_value_event_type")
    if any(pattern in normalized_title for pattern in GENERIC_SERIES_PATTERNS):
        reasons.append("generic_series_without_talk_title")
    if "institute for advanced study" in normalized_title and "seminar" in normalized_title:
        reasons.append("generic_series_without_talk_title")
    if normalized_title == "institute for advanced study multi-scale initiative":
        reasons.append("generic_series_without_talk_title")
    if any(normalized_title.startswith(prefix) for prefix in PROSE_TITLE_PREFIXES):
        reasons.append("title_too_long_or_description")
    if len(event.title or "") > 180:
        reasons.append("title_too_long_or_description")
    words = normalized_title.split()
    if len(words) > 25 and ":" not in normalized_title and " - " not in normalized_title and "|" not in normalized_title:
        reasons.append("title_too_long_or_description")
    if len(words) > 12 and ":" not in normalized_title and " - " not in normalized_title and "|" not in normalized_title:
        reasons.append("title_too_long_or_description")
    low_value_text = " ".join([event.title or "", event.description or "", event.location or ""]).lower()
    if any(pattern in low_value_text for pattern in ["internal", "student group", "community", "cohort only"]):
        reasons.append("internal_or_student_community")
    if not event.title.strip():
        reasons.append("empty_title")
    if event.start is None:
        reasons.append("missing_start")
    if "date_only_title" in reasons:
        reasons.append("generic_title")
    if "low_value_event_type" in reasons and event.score < 95:
        reasons.append("score_below_threshold")
    if "title_too_long_or_description" in reasons:
        reasons.append("score_below_threshold")
    if source_group == "tum_must" and not reasons:
        return True, []
    if event.score >= 70 and not reasons:
        return True, []
    is_online = event.online_url is not None or "online_bonus:+20" in event.score_reasons
    if event.score >= 60 and is_online and not reasons:
        return True, []
    if source_group in {"les", "mep", "emt"} and event.score >= 45 and not reasons:
        return True, []
    if source_group == "tum_ias" and event.online_url and event.start is not None and event.title:
        if "generic_title" not in reasons and "generic_series_without_talk_title" not in reasons and "missing_real_date" not in reasons:
            return True, []
    reasons.append("score_below_threshold")
    return False, reasons
