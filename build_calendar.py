import re
import hashlib
import requests
from ics import Calendar, Event
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

STARTSEITE_URL = "https://www.epe.ed.tum.de/es/startseite/"
MEP_TERMINE_URL = "https://www.mep.tum.de/mep/aktuelles/termine/"
TZ = ZoneInfo("Europe/Berlin")
MONTHS = {
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

def make_uid(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20] + "@tum-les-calendar"

def clean(s):
    return re.sub(r"\s+", " ", s).strip()

def parse_german_datetime(raw):
    match = re.search(r"(\d{1,2})\.\s*([A-Za-zäöüÄÖÜ]+)\s*(\d{4})\s*um\s*(\d{1,2}):(\d{2})\s*Uhr", raw)
    if match is None:
        raise RuntimeError("could not parse seminar date and time")
    day = int(match.group(1))
    month_name = clean(match.group(2)).lower()
    month = MONTHS.get(month_name)
    if month is None:
        raise RuntimeError(f"unknown month name in seminar date: {month_name}")
    year = int(match.group(3))
    hour = int(match.group(4))
    minute = int(match.group(5))
    return datetime(year, month, day, hour, minute, tzinfo=TZ)

def parse_mep_date(day_text, month_text, year_text):
    day = int(clean(day_text))
    month_key = clean(month_text).lower().replace(".", "")[:3]
    month = MONTHS_SHORT.get(month_key)
    if month is None:
        raise RuntimeError(f"unknown month abbreviation in mep date: {month_key}")
    year = int(clean(year_text))
    return datetime(year, month, day, tzinfo=TZ).date()

def get_seminars():
    response = requests.get(STARTSEITE_URL, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text("\n")
    start_index = text.find("Seminare am Lehrstuhl für Energiesysteme")
    if start_index == -1:
        raise RuntimeError("could not find seminar block on startseite")
    end_index = text.find("Aktuelles", start_index + 1)
    if end_index == -1:
        raise RuntimeError("could not find seminar block end marker on startseite")
    block = text[start_index:end_index]
    heading_pattern = re.compile(
        r"([^\n,]+?),\s*(\d{1,2}\.\s*[A-Za-zäöüÄÖÜ]+\s*\d{4}\s*um\s*\d{1,2}:\d{2}\s*Uhr)",
        re.M,
    )
    matches = list(heading_pattern.finditer(block))
    if not matches:
        raise RuntimeError("could not parse any seminar headings from startseite")

    seminars = []
    for index, item in enumerate(matches):
        start_index = item.end()
        end_index = matches[index + 1].start() if index + 1 < len(matches) else len(block)
        details = clean(block[start_index:end_index])
        start = parse_german_datetime(item.group(2))
        end = start + timedelta(hours=1, minutes=30)
        seminars.append({
            "name": f"TUM LES Seminar: {clean(item.group(1))}",
            "begin": start,
            "end": end,
            "description": f"Details: {details}\n\nSource: {STARTSEITE_URL}",
            "location": "TUM LES, Raum 3707 / Teams",
            "all_day": False,
            "uid_seed": clean(item.group(1)) + start.isoformat() + details,
        })
    return seminars

def get_mep_upcoming_events():
    response = requests.get(MEP_TERMINE_URL, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text("\n")
    start_index = text.find("Kommende Termine")
    if start_index == -1:
        raise RuntimeError("could not find kommende termine block on mep page")
    end_index = text.find("Vergangene Termine", start_index + 1)
    if end_index == -1:
        raise RuntimeError("could not find kommende termine block end marker on mep page")
    block = text[start_index:end_index]
    lines = [clean(line) for line in block.splitlines() if clean(line)]
    events = []
    index = 0
    while index < len(lines):
        if re.fullmatch(r"\d{1,2}", lines[index]) is None:
            index += 1
            continue
        if index + 4 >= len(lines):
            raise RuntimeError("mep upcoming event block is incomplete")
        day_text = lines[index]
        month_text = lines[index + 1]
        year_text = lines[index + 2]
        marker = lines[index + 3]
        title = lines[index + 4]
        if marker.lower() != "event":
            raise RuntimeError("mep upcoming event marker is missing")
        description_parts = []
        index += 5
        while index < len(lines) and re.fullmatch(r"\d{1,2}", lines[index]) is None:
            description_parts.append(lines[index])
            index += 1
        event_date = parse_mep_date(day_text, month_text, year_text)
        details = clean(" ".join(description_parts))
        events.append({
            "name": f"TUM MEP Termin: {clean(title)}",
            "begin": event_date,
            "end": event_date + timedelta(days=1),
            "description": f"Details: {details}\n\nSource: {MEP_TERMINE_URL}",
            "location": "TUM MEP",
            "all_day": True,
            "uid_seed": clean(title) + event_date.isoformat() + details,
        })
    if not events:
        raise RuntimeError("could not parse any upcoming mep events")
    return events

def main():
    cal = Calendar()
    cal.creator = "tum-les-calendar"

    events = get_seminars() + get_mep_upcoming_events()
    events.sort(
        key=lambda item: datetime.combine(item["begin"], datetime.min.time(), tzinfo=TZ)
        if not isinstance(item["begin"], datetime)
        else item["begin"]
    )
    for item in events:
        event = Event()
        event.name = item["name"]
        event.begin = item["begin"]
        event.end = item["end"]
        event.description = item["description"]
        event.location = item["location"]
        if item["all_day"]:
            event.make_all_day()
        event.uid = make_uid(item["uid_seed"])

        cal.events.add(event)

    with open("docs/seminars.ics", "w", encoding="utf-8") as f:
        f.writelines(cal)

if __name__ == "__main__":
    main()
