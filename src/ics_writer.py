import json
from datetime import datetime, timedelta

from ics import Calendar, Event
from rapidfuzz import fuzz

from src.models import NormalizedEvent
from src.utils import BERLIN_TZ, clean_text, sha_uid


def _norm_title(value: str) -> str:
    value = clean_text(value).lower()
    for token in ["prof.", "prof", "dr.", "dr", "phd", "m.sc.", "m.sc", "mr.", "ms.", "mrs."]:
        value = value.replace(token, " ")
    value = value.replace("chriss monroe", "christopher monroe")
    value = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in value)
    return clean_text(value)


def dedupe_events(events: list[NormalizedEvent]) -> list[NormalizedEvent]:
    grouped: dict[tuple[str, str, str], list[NormalizedEvent]] = {}
    for event in events:
        speaker_key = clean_text(event.speaker or "").lower()
        key = (_norm_title(event.title), event.start.date().isoformat(), speaker_key)
        grouped.setdefault(key, []).append(event)
    keys = list(grouped.keys())
    consumed = set()
    deduped: list[NormalizedEvent] = []
    for key in keys:
        if key in consumed:
            continue
        items = list(grouped[key])
        for other in keys:
            if other == key or other in consumed:
                continue
            if key[1] != other[1]:
                continue
            if fuzz.ratio(key[0], other[0]) >= 88:
                items.extend(grouped[other])
                consumed.add(other)
        items.sort(
            key=lambda item: (1 if item.event_url else 0, len(item.description or ""), 1 if not item.all_day else 0),
            reverse=True,
        )
        best = items[0]
        if len(items) > 1:
            others = ", ".join(sorted({item.source_name for item in items[1:]}))
            if others:
                suffix = " Also seen in: " + others
                best.description = clean_text((best.description or "") + suffix)
        deduped.append(best)
    deduped.sort(key=lambda item: item.start)
    return deduped


def format_title(event: NormalizedEvent) -> str:
    category = event.categories[0] if event.categories else "General High Impact"
    speaker = f" — {event.speaker}" if event.speaker else ""
    return f"[{category}] {event.title}{speaker}"


def build_event_description(event: NormalizedEvent) -> str:
    parts = [
        f"Source: {event.source_name}",
        f"Source URL: {event.source_url}",
        f"Event URL: {event.event_url or ''}",
        f"Online URL: {event.online_url or ''}",
        f"Speaker: {event.speaker or ''}",
        f"Affiliation: {event.affiliation or ''}",
        f"Location: {event.location or ''}",
        f"Score: {event.score}",
        "Score reasons: " + "; ".join(event.score_reasons),
        "Excerpt: " + clean_text(event.source_excerpt or event.description or "")[:400],
    ]
    return "\n".join(parts)


def write_ics(path: str, events: list[NormalizedEvent]) -> None:
    calendar = Calendar()
    calendar.creator = "tum-les-calendar"
    for item in events:
        event = Event()
        event.name = format_title(item)
        event.begin = item.start
        default_end = item.start + timedelta(minutes=90)
        event.end = item.end or default_end
        event.description = build_event_description(item)
        event.location = item.location
        if item.all_day:
            event.make_all_day()
        seed = item.uid_seed or f"{item.source_name}|{item.event_url or ''}|{item.title}|{item.start.isoformat()}|{item.speaker or ''}"
        event.uid = sha_uid(seed)
        calendar.events.add(event)
    with open(path, "w", encoding="utf-8") as handle:
        handle.writelines(calendar)


def write_debug_json(path: str, events: list[NormalizedEvent | dict]) -> None:
    payload = []
    for event in events:
        if isinstance(event, dict):
            payload.append(event)
            continue
        payload.append(
            {
                "title": event.title,
                "start": event.start.isoformat(),
                "end": event.end.isoformat() if event.end else None,
                "timezone": event.timezone,
                "speaker": event.speaker,
                "affiliation": event.affiliation,
                "location": event.location,
                "online_url": event.online_url,
                "source_name": event.source_name,
                "source_url": event.source_url,
                "event_url": event.event_url,
                "description": event.description,
                "categories": event.categories,
                "score": event.score,
                "score_reasons": event.score_reasons,
                "uid_seed": event.uid_seed,
                "include": event.include,
                "reject_reasons": event.reject_reasons,
            }
        )
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def write_index(path: str, included_events: list[NormalizedEvent], source_errors: list[dict], source_stats: list[dict]) -> None:
    now = datetime.now(tz=BERLIN_TZ).isoformat()
    rows = []
    for event in included_events:
        url = event.event_url or event.source_url
        rows.append(
            "<tr>"
            + f"<td>{event.start.strftime('%Y-%m-%d %H:%M')}</td>"
            + f"<td>{event.score}</td>"
            + f"<td>{event.source_name}</td>"
            + f"<td>{format_title(event)}</td>"
            + f"<td>{event.speaker or ''}</td>"
            + f"<td><a href=\"{url}\">link</a></td>"
            + "</tr>"
        )
    error_rows = []
    for error in source_errors:
        error_rows.append(
            "<tr>"
            + f"<td>{error.get('source_name','')}</td>"
            + f"<td>{error.get('source_url','')}</td>"
            + f"<td>{error.get('http_status','')}</td>"
            + f"<td>{error.get('description','')}</td>"
            + "</tr>"
        )
    stat_rows = []
    for stat in source_stats:
        stat_rows.append(
            "<tr>"
            + f"<td>{stat.get('source_name','')}</td>"
            + f"<td>{stat.get('candidates',0)}</td>"
            + f"<td>{stat.get('included',0)}</td>"
            + f"<td>{stat.get('rejected',0)}</td>"
            + f"<td>{stat.get('errors',0)}</td>"
            + "</tr>"
        )
    html = (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Curated seminars</title></head><body>"
        + "<h1>Curated seminar feed</h1>"
        + f"<p>last build: {now}</p>"
        + f"<p>included events: {len(included_events)}</p>"
        + f"<p>source failures: {len(source_errors)}</p>"
        + "<p><a href=\"seminars.ics\">seminars.ics</a> | "
        + "<a href=\"events_debug.json\">events_debug.json</a> | "
        + "<a href=\"rejected_events_debug.json\">rejected_events_debug.json</a></p>"
        + "<h2>source failures</h2>"
        + "<table border=\"1\" cellspacing=\"0\" cellpadding=\"4\">"
        + "<tr><th>source</th><th>url</th><th>status</th><th>error</th></tr>"
        + "".join(error_rows)
        + "</table>"
        + "<h2>per-source stats</h2>"
        + "<table border=\"1\" cellspacing=\"0\" cellpadding=\"4\">"
        + "<tr><th>source</th><th>candidates</th><th>included</th><th>rejected</th><th>errors</th></tr>"
        + "".join(stat_rows)
        + "</table>"
        + "<h2>included events</h2>"
        + "<table border=\"1\" cellspacing=\"0\" cellpadding=\"4\">"
        + "<tr><th>date</th><th>score</th><th>source</th><th>title</th><th>speaker</th><th>url</th></tr>"
        + "".join(rows)
        + "</table></body></html>"
    )
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(html)
