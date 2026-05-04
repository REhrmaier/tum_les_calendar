import re
import hashlib
import requests
from ics import Calendar, Event
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pypdf import PdfReader
from io import BytesIO

PDF_URL = "https://www.epe.ed.tum.de/fileadmin/w00bzo/es/pdf/programm_vdi-ak_et_vortragsankuendigung_2025_26.pdf"
TZ = ZoneInfo("Europe/Berlin")

def make_uid(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20] + "@tum-les-calendar"

def clean(s):
    return re.sub(r"\s+", " ", s).strip()

def main():
    pdf = requests.get(PDF_URL, timeout=30)
    pdf.raise_for_status()

    reader = PdfReader(BytesIO(pdf.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    pattern = re.compile(
        r"•\s*(\d{2}\.\d{2}\.\d{4})\s+„(.+?)“\s+(.+?)(?=\n\s*•|\nDie Webinare|\Z)",
        re.S,
    )

    cal = Calendar()
    cal.creator = "tum-les-calendar"

    for date_str, title, speaker in pattern.findall(text):
        date = datetime.strptime(date_str, "%d.%m.%Y").date()
        start = datetime(date.year, date.month, date.day, 17, 0, tzinfo=TZ)
        end = start + timedelta(hours=1, minutes=30)

        event = Event()
        event.name = f"TUM LES/VDI: {clean(title)}"
        event.begin = start
        event.end = end
        event.description = f"Speaker/info: {clean(speaker)}\n\nSource PDF: {PDF_URL}"
        event.location = "Online webinar"
        event.uid = make_uid(event.name + start.isoformat())

        cal.events.add(event)

    with open("docs/seminars.ics", "w", encoding="utf-8") as f:
        f.writelines(cal)

if __name__ == "__main__":
    main()
