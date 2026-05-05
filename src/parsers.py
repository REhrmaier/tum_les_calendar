import re
from datetime import datetime, timedelta
from urllib.parse import urljoin

from dateparser import parse as dateparse

from src.fetchers import discover_feed_links, fetch_html, parse_ics_feed, parse_rss_feed
from src.models import NormalizedEvent
from src.utils import BERLIN_TZ, clean_text


MONTHS_DE = {
    "januar": 1,
    "februar": 2,
    "maerz": 3,
    "märz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
}

MONTHS_SHORT = {
    "jan": 1,
    "feb": 2,
    "mär": 3,
    "mae": 3,
    "mar": 3,
    "apr": 4,
    "mai": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "okt": 10,
    "nov": 11,
    "dez": 12,
}

def _bad_line_title(value: str) -> bool:
    lower = value.lower().strip()
    if not lower:
        return True
    if lower in {"location", "part of", "events", "upcoming events"}:
        return True
    if "javascript must be enabled" in lower:
        return True
    if "america/new_york" in lower:
        return True
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", lower):
        return True
    if re.fullmatch(r"\d{1,2}:\d{2}", lower):
        return True
    return False


def _clean_event_title(raw: str) -> str:
    title = clean_text(raw)
    markers = [
        "For the Zoom passcode",
        "Abstract:",
        "Bio:",
        "Speaker:",
        "Location:",
        "Part Of",
        "---Date:",
    ]
    for marker in markers:
        if marker.lower() in title.lower():
            pattern = re.compile(re.escape(marker), re.I)
            match = pattern.search(title)
            if match:
                title = clean_text(title[:match.start()])
    if len(title) > 180:
        for sep in [". ", " — ", " - ", " | ", ": "]:
            if sep in title:
                title = clean_text(title.split(sep)[0])
                break
    return title


def parse_german_datetime(raw: str) -> datetime | None:
    match = re.search(r"(\d{1,2})\.\s*([A-Za-zäöüÄÖÜ]+)\s*(\d{4})\s*um\s*(\d{1,2}):(\d{2})\s*Uhr", raw)
    if match is None:
        return None
    month_name = clean_text(match.group(2)).lower()
    month = MONTHS_DE.get(month_name)
    if month is None:
        return None
    return datetime(
        int(match.group(3)),
        month,
        int(match.group(1)),
        int(match.group(4)),
        int(match.group(5)),
        tzinfo=BERLIN_TZ,
    )


def parse_german_date(raw: str, default_year: int | None = None) -> datetime | None:
    parsed = dateparse(
        raw,
        languages=["de", "en"],
        settings={"TIMEZONE": "Europe/Berlin", "RETURN_AS_TIMEZONE_AWARE": True},
    )
    if parsed is None:
        return None
    if default_year is not None and re.search(r"\d{4}", raw) is None:
        parsed = parsed.replace(year=default_year)
    return parsed


def parse_les(session, source: dict) -> list[NormalizedEvent]:
    soup = fetch_html(session, source["url"])
    text = soup.get_text("\n")
    start_index = text.find("Seminare am Lehrstuhl für Energiesysteme")
    end_index = text.find("Aktuelles", start_index + 1) if start_index != -1 else -1
    if start_index == -1 or end_index == -1:
        raise RuntimeError("could not find les seminar section")
    block = text[start_index:end_index]
    heading_pattern = re.compile(
        r"([^\n,]+?),\s*(\d{1,2}\.\s*[A-Za-zäöüÄÖÜ]+\s*\d{4}\s*um\s*\d{1,2}:\d{2}\s*Uhr)",
        re.M,
    )
    matches = list(heading_pattern.finditer(block))
    events: list[NormalizedEvent] = []
    for index, match in enumerate(matches):
        parsed_start = parse_german_datetime(match.group(2))
        if parsed_start is None:
            continue
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(block)
        details = clean_text(block[match.end():next_start])
        events.append(
            NormalizedEvent(
                title=clean_text(match.group(1)),
                start=parsed_start,
                end=parsed_start + timedelta(minutes=90),
                timezone="Europe/Berlin",
                speaker=None,
                affiliation=None,
                location="TUM LES, Raum 3707 / Teams",
                online_url=None,
                source_name=source["name"],
                source_url=source["url"],
                event_url=source["url"],
                description=details,
                uid_seed=f"{source['name']}|{match.group(1)}|{parsed_start.isoformat()}|{details}",
                source_excerpt=details[:240],
            )
        )
    return events


def parse_mep(session, source: dict) -> list[NormalizedEvent]:
    soup = fetch_html(session, source["url"])
    text = soup.get_text("\n")
    start_index = text.find("Kommende Termine")
    end_index = text.find("Vergangene Termine", start_index + 1) if start_index != -1 else -1
    if start_index == -1 or end_index == -1:
        raise RuntimeError("could not find mep upcoming section")
    lines = [clean_text(line) for line in text[start_index:end_index].splitlines() if clean_text(line)]
    events = []
    pointer = 0
    while pointer < len(lines):
        if re.fullmatch(r"\d{1,2}", lines[pointer]) is None:
            pointer += 1
            continue
        if pointer + 4 >= len(lines):
            break
        day = int(lines[pointer])
        month_key = lines[pointer + 1].lower().replace(".", "")[:3]
        month = MONTHS_SHORT.get(month_key)
        year = int(lines[pointer + 2])
        marker = lines[pointer + 3].lower()
        title = lines[pointer + 4]
        if month is None or marker != "event":
            pointer += 1
            continue
        pointer += 5
        desc_lines = []
        while pointer < len(lines) and re.fullmatch(r"\d{1,2}", lines[pointer]) is None:
            desc_lines.append(lines[pointer])
            pointer += 1
        start = datetime(year, month, day, 0, 0, tzinfo=BERLIN_TZ)
        description = clean_text(" ".join(desc_lines))
        events.append(
            NormalizedEvent(
                title=clean_text(title),
                start=start,
                end=start + timedelta(days=1),
                timezone="Europe/Berlin",
                speaker=None,
                affiliation=None,
                location="TUM MEP",
                online_url=None,
                source_name=source["name"],
                source_url=source["url"],
                event_url=source["url"],
                description=description,
                uid_seed=f"{source['name']}|{title}|{start.isoformat()}",
                all_day=True,
                source_excerpt=description[:240],
            )
        )
    return events


def parse_ias_coffee(session, source: dict) -> list[NormalizedEvent]:
    soup = fetch_html(session, source["url"])
    lines = [clean_text(line) for line in soup.get_text("\n").splitlines() if clean_text(line)]
    events = []
    for idx, line in enumerate(lines):
        if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", line) is None:
            continue
        if idx + 1 >= len(lines):
            continue
        raw_title = lines[idx + 1]
        if "coffee talk" not in raw_title.lower():
            continue
        start = datetime.strptime(line, "%d.%m.%Y").replace(hour=13, minute=0, tzinfo=BERLIN_TZ)
        speaker = None
        speaker_match = re.search(r"\bby\s+(.+?)\s+on\s+", raw_title, re.I)
        if speaker_match:
            speaker = clean_text(speaker_match.group(1))
        title = raw_title
        talk_match = re.search(r"on\s+[\"“](.+?)[\"”]", raw_title, re.I)
        if talk_match:
            title = clean_text(talk_match.group(1))
        events.append(
            NormalizedEvent(
                title=title,
                start=start,
                end=start + timedelta(minutes=60),
                timezone="Europe/Berlin",
                speaker=speaker,
                affiliation=None,
                location="Online",
                online_url=source["url"],
                source_name=source["name"],
                source_url=source["url"],
                event_url=source["url"],
                description=raw_title,
                uid_seed=f"{source['name']}|{line}|{title}|{speaker or ''}",
                source_excerpt=raw_title[:240],
            )
        )
    return events


def parse_mibe(session, source: dict) -> list[NormalizedEvent]:
    feed_events = parse_rss_feed(source["name"], source["url"], "https://www.bioengineering.tum.de/events/feed.rss")
    html = fetch_html(session, source["url"])
    cards = html.select("article, .news-list-item, li, div")
    html_events = []
    for card in cards:
        title_node = card.find(["h2", "h3"])
        if title_node is None:
            continue
        title = clean_text(title_node.get_text(" ", strip=True))
        if len(title) < 8:
            continue
        card_text = clean_text(card.get_text("\n", strip=True))
        if "seminar" not in title.lower() and "talk" not in title.lower():
            continue
        list_date_match = re.search(r"(\d{2}\.\d{2}\.\d{4})", card_text)
        detail_date_match = re.search(r"Datum und (?:Uhrzeit|Zeit):\s*([^\n]+)", card_text, re.I)
        start = None
        if detail_date_match:
            default_year = None
            if list_date_match:
                default_year = int(list_date_match.group(1).split(".")[-1])
            start = parse_german_date(detail_date_match.group(1), default_year=default_year)
        if start is None and list_date_match:
            start = datetime.strptime(list_date_match.group(1), "%d.%m.%Y").replace(tzinfo=BERLIN_TZ)
        if start is None:
            continue
        speaker = None
        speaker_match = re.search(r"Sprecher:\s*([^\n]+)", card_text, re.I)
        if speaker_match:
            speaker = clean_text(speaker_match.group(1))
        location = None
        location_match = re.search(r"Ort:\s*([^\n]+)", card_text, re.I)
        if location_match:
            location = clean_text(location_match.group(1))
        event_url = source["url"]
        link = title_node.find("a")
        if link and link.get("href"):
            event_url = urljoin(source["url"], link.get("href"))
        html_events.append(
            NormalizedEvent(
                title=title,
                start=start,
                end=None,
                timezone="Europe/Berlin",
                speaker=speaker,
                affiliation=None,
                location=location,
                online_url=None,
                source_name=source["name"],
                source_url=source["url"],
                event_url=event_url,
                description=card_text,
                uid_seed=f"{source['name']}|{event_url}|{title}|{start.isoformat()}",
                source_excerpt=card_text[:240],
            )
        )
    return html_events if html_events else feed_events


def parse_event_cards_generic(session, source: dict) -> list[NormalizedEvent]:
    soup = fetch_html(session, source["url"])
    events: list[NormalizedEvent] = []
    for container in soup.find_all(["article", "li", "div", "section"]):
        title_tag = container.find(["h1", "h2", "h3", "h4"])
        if title_tag is None:
            continue
        title = clean_text(title_tag.get_text(" ", strip=True))
        if len(title) < 10:
            continue
        link_tag = title_tag.find("a") or container.find("a")
        if link_tag is None:
            continue
        container_text = clean_text(container.get_text("\n", strip=True))
        parsed = dateparse(
            container_text,
            settings={"PREFER_DATES_FROM": "future", "TIMEZONE": "Europe/Berlin", "RETURN_AS_TIMEZONE_AWARE": True},
        )
        if parsed is None:
            continue
        url = urljoin(source["url"], link_tag.get("href") or source["url"])
        speaker = None
        speaker_match = re.search(r"(Speaker|Speakers?|Vortragende|By):\s*([^\n|]+)", container_text, re.I)
        if speaker_match:
            speaker = clean_text(speaker_match.group(2))
        location = None
        location_match = re.search(r"(Location|Ort):\s*([^\n|]+)", container_text, re.I)
        if location_match:
            location = clean_text(location_match.group(2))
        online_url = None
        if re.search(r"zoom|online|webcast|livestream|hybrid|webinar|youtube", container_text, re.I):
            online_url = url
        events.append(
            NormalizedEvent(
                title=title,
                start=parsed if parsed.tzinfo else parsed.replace(tzinfo=BERLIN_TZ),
                end=None,
                timezone="Europe/Berlin",
                speaker=speaker,
                affiliation=None,
                location=location,
                online_url=online_url,
                source_name=source["name"],
                source_url=source["url"],
                event_url=url,
                description=container_text,
                uid_seed=f"{source['name']}|{url}|{title}|{parsed.isoformat()}",
                source_excerpt=container_text[:240],
            )
        )
    deduped = []
    seen = set()
    for event in events:
        key = (event.title.lower(), event.start.date())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)
    return deduped


def parse_via_discovery(session, source: dict) -> list[NormalizedEvent]:
    feed_links = discover_feed_links(session, source["url"])
    for feed_link in feed_links:
        lower = feed_link.lower()
        try:
            if lower.endswith(".ics") or "ical" in lower:
                parsed = parse_ics_feed(session, source["name"], source["url"], feed_link)
                if parsed:
                    return parsed
            if "rss" in lower or "feed" in lower or "atom" in lower:
                parsed = parse_rss_feed(source["name"], source["url"], feed_link)
                if parsed:
                    return parsed
        except Exception:
            continue
    return parse_event_cards_generic(session, source)


def parse_seem(session, source: dict) -> list[NormalizedEvent]:
    soup = fetch_html(session, source["url"])
    text = soup.get_text("\n")
    start = text.find("Upcoming")
    end = text.find("Winter semester", start + 1) if start != -1 else -1
    scoped = text[start:end] if start != -1 and end != -1 else text
    lines = [clean_text(line) for line in scoped.splitlines() if clean_text(line)]
    events = []
    for idx, line in enumerate(lines):
        parsed = dateparse(line, settings={"PREFER_DATES_FROM": "future", "TIMEZONE": "Europe/Berlin", "RETURN_AS_TIMEZONE_AWARE": True})
        if parsed is None:
            continue
        if idx + 3 >= len(lines):
            continue
        speaker = lines[idx + 1]
        affiliation = lines[idx + 2]
        title = lines[idx + 3]
        if len(title) < 8 or title.lower() == "tba" or _bad_line_title(title):
            continue
        location = lines[idx + 4] if idx + 4 < len(lines) else ""
        desc = "Speaker: " + speaker + ". Affiliation: " + affiliation + ". " + location
        events.append(
            NormalizedEvent(
                title=title,
                start=parsed if parsed.tzinfo else parsed.replace(tzinfo=BERLIN_TZ),
                end=None,
                timezone="Europe/Berlin",
                speaker=speaker,
                affiliation=affiliation,
                location=location or "TUM + ifo",
                online_url=source["url"] if "online" in desc.lower() or "zoom" in desc.lower() else None,
                source_name=source["name"],
                source_url=source["url"],
                event_url=source["url"],
                description=desc,
                uid_seed=f"{source['name']}|{title}|{parsed.isoformat()}",
                source_excerpt=desc[:240],
            )
        )
    return events


def parse_mcml(session, source: dict) -> list[NormalizedEvent]:
    parsed = parse_rss_feed(source["name"], source["url"], "https://mcml.ai/events/index.xml")
    return parsed


def parse_hai(session, source: dict) -> list[NormalizedEvent]:
    soup = fetch_html(session, source["url"])
    lines = [clean_text(line) for line in soup.get_text("\n").splitlines() if clean_text(line)]
    events = []
    for idx, line in enumerate(lines):
        parsed = dateparse(
            line,
            settings={"PREFER_DATES_FROM": "future", "TIMEZONE": "America/Los_Angeles", "RETURN_AS_TIMEZONE_AWARE": True},
        )
        if parsed is None:
            continue
        if idx + 1 >= len(lines):
            continue
        title = lines[idx - 1] if idx > 0 else lines[idx + 1]
        title = _clean_event_title(title)
        if _bad_line_title(title):
            continue
        if len(title.split()) < 4:
            continue
        location = lines[idx + 1] if idx + 1 < len(lines) else None
        online_url = source["url"] if location and "stream available" in location.lower() else None
        events.append(
            NormalizedEvent(
                title=title,
                start=parsed,
                end=None,
                timezone=str(parsed.tzinfo),
                speaker=None,
                affiliation=None,
                location=location,
                online_url=online_url,
                source_name=source["name"],
                source_url=source["url"],
                event_url=source["url"],
                description=" ".join(lines[max(0, idx - 2):idx + 6]),
                uid_seed=f"{source['name']}|{title}|{parsed.isoformat()}",
                source_excerpt=" ".join(lines[max(0, idx - 2):idx + 6])[:240],
            )
        )
    return events


def parse_csail(session, source: dict) -> list[NormalizedEvent]:
    soup = fetch_html(session, source["url"])
    text = clean_text(soup.get_text("\n"))
    pattern = re.compile(
        r"Add to Calendar\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+([A-Za-z_\/]+)\s+(.+?)(?=Add to Calendar|\Z)"
    )
    events = []
    for start_raw, end_raw, timezone, blob in pattern.findall(text):
        start = datetime.strptime(start_raw, "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(end_raw, "%Y-%m-%d %H:%M:%S")
        start = dateparse(start.isoformat(), settings={"TIMEZONE": timezone, "RETURN_AS_TIMEZONE_AWARE": True}) or start.replace(tzinfo=BERLIN_TZ)
        end = dateparse(end.isoformat(), settings={"TIMEZONE": timezone, "RETURN_AS_TIMEZONE_AWARE": True}) or end.replace(tzinfo=BERLIN_TZ)
        title = _clean_event_title(blob.split(" Part Of ")[0].split(" Location ")[0])
        if _bad_line_title(title):
            continue
        if len(title.split()) < 4:
            continue
        detail = clean_text(blob)
        events.append(
            NormalizedEvent(
                title=title,
                start=start,
                end=end,
                timezone=timezone,
                speaker=None,
                affiliation=None,
                location=None,
                online_url=source["url"] if "zoom" in detail.lower() or "virtual" in detail.lower() else None,
                source_name=source["name"],
                source_url=source["url"],
                event_url=source["url"],
                description=detail,
                uid_seed=f"{source['name']}|{title}|{start.isoformat()}",
                source_excerpt=detail[:240],
            )
        )
    return events


def parse_mcqst(session, source: dict) -> list[NormalizedEvent]:
    ics_url = "https://www.mcqst.de/tech/ICS-Events-subscribe.ics"
    try:
        parsed = parse_ics_feed(session, source["name"], source["url"], ics_url)
        if parsed:
            return parsed
    except Exception:
        pass
    return _line_scan_date_title_events(session, source)


def parse_stanford_energy(session, source: dict) -> list[NormalizedEvent]:
    soup = fetch_html(session, source["url"])
    lines = [clean_text(line) for line in soup.get_text("\n").splitlines() if clean_text(line)]
    events = []
    for idx, line in enumerate(lines):
        if "|" not in line and "Seminar:" not in line:
            continue
        date_line = lines[idx + 1] if idx + 1 < len(lines) else ""
        parsed = dateparse(date_line, settings={"PREFER_DATES_FROM": "future", "TIMEZONE": "America/Los_Angeles", "RETURN_AS_TIMEZONE_AWARE": True})
        if parsed is None:
            continue
        title = line
        speaker = None
        if "|" in line:
            parts = [clean_text(part) for part in line.split("|")]
            if len(parts) >= 2:
                title = parts[1]
            if len(parts) >= 3:
                speaker = parts[2]
        elif " - " in line:
            left, right = line.rsplit(" - ", 1)
            title = left
            speaker = right
        events.append(
            NormalizedEvent(
                title=title,
                start=parsed,
                end=None,
                timezone=str(parsed.tzinfo),
                speaker=speaker,
                affiliation=None,
                location=lines[idx + 2] if idx + 2 < len(lines) else None,
                online_url=source["url"] if "online" in " ".join(lines[idx:idx + 5]).lower() else None,
                source_name=source["name"],
                source_url=source["url"],
                event_url=source["url"],
                description=" ".join(lines[idx:idx + 6]),
                uid_seed=f"{source['name']}|{title}|{parsed.isoformat()}",
                source_excerpt=" ".join(lines[idx:idx + 6])[:240],
            )
        )
    return events


def parse_mit_sloan_finance(session, source: dict) -> list[NormalizedEvent]:
    soup = fetch_html(session, source["url"])
    lines = [clean_text(line) for line in soup.get_text("\n").splitlines() if clean_text(line)]
    events = []
    for idx, line in enumerate(lines):
        parsed = dateparse(line, settings={"PREFER_DATES_FROM": "future", "TIMEZONE": "America/New_York", "RETURN_AS_TIMEZONE_AWARE": True})
        if parsed is None:
            continue
        speaker = lines[idx + 1] if idx + 1 < len(lines) else None
        title = f"MIT Sloan Finance Seminar — {speaker}" if speaker else "MIT Sloan Finance Seminar"
        events.append(
            NormalizedEvent(
                title=title,
                start=parsed.replace(hour=0, minute=0, second=0, microsecond=0),
                end=None,
                timezone=str(parsed.tzinfo),
                speaker=speaker,
                affiliation=None,
                location=None,
                online_url=None,
                source_name=source["name"],
                source_url=source["url"],
                event_url=source["url"],
                description="time not published",
                uid_seed=f"{source['name']}|{title}|{parsed.date().isoformat()}",
                source_excerpt=line,
                all_day=True,
            )
        )
    return events


def parse_harvard_seas(session, source: dict) -> list[NormalizedEvent]:
    feed_links = discover_feed_links(session, source["url"])
    for link in feed_links:
        lower = link.lower()
        if lower.endswith(".ics") or "calendar/1.ics" in lower:
            return parse_ics_feed(session, source["name"], source["url"], link)
        if lower.endswith(".xml") or "rss" in lower:
            return parse_rss_feed(source["name"], source["url"], link)
    return []


def parse_emt(session, source: dict) -> list[NormalizedEvent]:
    soup = fetch_html(session, source["url"])
    text = clean_text(soup.get_text("\n"))
    if "join our research seminar" in text.lower():
        return []
    return []


def _line_scan_date_title_events(session, source: dict) -> list[NormalizedEvent]:
    soup = fetch_html(session, source["url"])
    lines = [clean_text(line) for line in soup.get_text("\n").splitlines() if clean_text(line)]
    events = []
    for idx, line in enumerate(lines):
        parsed = dateparse(line, settings={"PREFER_DATES_FROM": "future", "TIMEZONE": "Europe/Berlin", "RETURN_AS_TIMEZONE_AWARE": True})
        if parsed is None:
            continue
        title = ""
        for candidate in lines[idx + 1:idx + 8]:
            lower = candidate.lower()
            if lower in {"may", "june", "july", "events", "upcoming events"}:
                continue
            if re.fullmatch(r"\d{4}", candidate):
                continue
            if len(candidate) < 8:
                continue
            if _bad_line_title(candidate):
                continue
            title = candidate
            break
        if not title:
            continue
        events.append(
            NormalizedEvent(
                title=title,
                start=parsed if parsed.tzinfo else parsed.replace(tzinfo=BERLIN_TZ),
                end=None,
                timezone="Europe/Berlin",
                speaker=None,
                affiliation=None,
                location=None,
                online_url=source["url"] if "online" in " ".join(lines[idx:idx + 8]).lower() else None,
                source_name=source["name"],
                source_url=source["url"],
                event_url=source["url"],
                description=" ".join(lines[idx:idx + 10]),
                uid_seed=f"{source['name']}|{title}|{parsed.isoformat()}",
                source_excerpt=" ".join(lines[idx:idx + 10])[:240],
            )
        )
    return events


def parse_source(session, source: dict) -> list[NormalizedEvent]:
    parser = source.get("parser", "discover")
    if parser == "les":
        return parse_les(session, source)
    if parser == "mep":
        return parse_mep(session, source)
    if parser == "discover":
        return parse_via_discovery(session, source)
    if parser == "seem":
        return parse_seem(session, source)
    if parser == "ias_coffee":
        return parse_ias_coffee(session, source)
    if parser == "mibe":
        return parse_mibe(session, source)
    if parser == "mcml":
        return parse_mcml(session, source)
    if parser == "emt":
        return parse_emt(session, source)
    if parser == "mcqst":
        return parse_mcqst(session, source)
    if parser == "hai":
        return parse_hai(session, source)
    if parser == "stanford_energy":
        return parse_stanford_energy(session, source)
    if parser == "csail":
        return parse_csail(session, source)
    if parser == "mit_sloan_finance":
        return parse_mit_sloan_finance(session, source)
    if parser == "harvard_seas":
        return parse_harvard_seas(session, source)
    raise RuntimeError(f"unknown parser: {parser}")
