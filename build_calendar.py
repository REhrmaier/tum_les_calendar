import requests

from src.ics_writer import dedupe_events, write_debug_json, write_ics, write_index
from src.parsers import parse_source
from src.scoring import score_event, should_include
from src.utils import make_session, read_sources_config


def validate_outputs() -> None:
    with open("docs/seminars.ics", "r", encoding="utf-8") as handle:
        content = handle.read()
    if not content.startswith("BEGIN:VCALENDAR"):
        raise RuntimeError("ics output invalid: missing begin")
    if "summary:[general high impact] page updated" in content.lower():
        raise RuntimeError("ics output invalid: placeholder title present")


def main() -> None:
    session = make_session()
    sources = read_sources_config("config/sources.yaml")
    accepted = []
    rejected = []
    source_errors = []
    source_stats = []
    for source in sources:
        candidates_count = 0
        included_count = 0
        rejected_count = 0
        errors_count = 0
        try:
            parsed = parse_source(session, source)
            candidates_count = len(parsed)
        except Exception as exc:
            status = None
            attempted_url = source["url"]
            if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
                status = exc.response.status_code
                attempted_url = exc.response.url or attempted_url
            rejected.append(
                {
                    "title": f"source failure: {source['name']}",
                    "start": None,
                    "end": None,
                    "timezone": "Europe/Berlin",
                    "speaker": None,
                    "affiliation": None,
                    "location": None,
                    "online_url": None,
                    "source_name": source["name"],
                    "source_url": attempted_url,
                    "event_url": None,
                    "description": str(exc),
                    "categories": [],
                    "score": 0,
                    "score_reasons": ["source_error"],
                    "uid_seed": source["name"],
                    "include": False,
                    "reject_reasons": ["source_error"],
                    "http_status": status,
                }
            )
            source_errors.append(
                {
                    "source_name": source["name"],
                    "source_url": attempted_url,
                    "http_status": status,
                    "description": str(exc),
                }
            )
            errors_count += 1
            source_stats.append(
                {
                    "source_name": source["name"],
                    "candidates": candidates_count,
                    "included": included_count,
                    "rejected": rejected_count,
                    "errors": errors_count,
                }
            )
            continue
        for event in parsed:
            scored = score_event(event, source.get("source_weight", 20))
            include, reasons = should_include(scored, source.get("source_group", "generic"))
            scored.include = include
            scored.reject_reasons = reasons
            if include:
                accepted.append(scored)
                included_count += 1
            else:
                rejected.append(scored)
                rejected_count += 1
        source_stats.append(
            {
                "source_name": source["name"],
                "candidates": candidates_count,
                "included": included_count,
                "rejected": rejected_count,
                "errors": errors_count,
            }
        )

    accepted = dedupe_events(accepted)
    write_ics("docs/seminars.ics", accepted)
    write_debug_json("docs/events_debug.json", accepted)
    reject_objects = []
    for item in rejected:
        if isinstance(item, dict):
            reject_objects.append(item)
        else:
            reject_objects.append(item)
    write_debug_json("docs/rejected_events_debug.json", reject_objects)
    write_index("docs/index.html", accepted, source_errors, source_stats)
    validate_outputs()

if __name__ == "__main__":
    main()
