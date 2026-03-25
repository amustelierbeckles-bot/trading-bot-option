from datetime import datetime

def _parse_naive_utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts.rstrip("Z").split("+")[0])
