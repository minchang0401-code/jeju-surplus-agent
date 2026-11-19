"""추천·대안·캘린더에 공통으로 적용하는 생활시간 제약."""
def window_context(window, schedule, is_ev=False):
    if not schedule or schedule.get("away_start") is None:
        return "unspecified"
    start, end = int(window["start_hour"]), int(window["end_hour"])
    a0, a1 = schedule["away_start"], schedule["away_end"]
    if schedule.get("weekdays_only", True) and window["weekday"] in ("토", "일"):
        return "home"
    overlap = start < a1 and end > a0
    if not overlap:
        return "home"
    if is_ev:
        return "away" if a0 <= start and end <= a1 else None
    return "away" if schedule.get("reservable") else None
