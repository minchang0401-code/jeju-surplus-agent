"""추천 시간대를 휴대폰 캘린더에 넣기 — 그 시간 10분 전에 알림이 오게 함.

- 구글 캘린더 링크: 안드로이드·PC에서 눌러 바로 저장
- .ics 파일: 아이폰·아웃룩에서 열어 저장 (VALARM 10분 전 알림 포함)
서버가 알림을 보내는 방식이 아니라, 사용자의 캘린더가 알림을 띄웁니다(개인정보를 서버에 남기지 않음).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
import zlib

KST = timezone(timedelta(hours=9))


def pick_window(trace: list) -> dict | None:
    """답변에 쓰인 도구 결과에서 캘린더에 넣을 시간대 하나를 고름.
    우선순위: 원한 때(가능성 낮음 아님) → 더 나은 때 → 대안 1순위 → 추천 1순위."""
    for t in reversed(trace or []):
        if t.get("tool") != "plan_appliance_use":
            continue
        r = t.get("result") or {}
        if r.get("error") or r.get("not_forecast"):
            continue
        cands = []
        req = r.get("requested_window_best")
        if req and req.get("level") != "낮음":
            cands.append(req)
        if r.get("better_option"):
            cands.append(r["better_option"])
        cands += (r.get("alternatives") or []) + (r.get("best_windows") or [])
        if not cands:
            continue
        w = cands[0]
        return {"appliance": r.get("appliance", "전기 사용"), "date": w["date"], "start_hour": int(w["start_hour"]),
                "end_hour": int(w["end_hour"]), "time_text": w.get("time_text", ""), "level": w.get("level", ""),
                "how": r.get("how", "")}
    return None


def _span(w: dict) -> tuple[datetime, datetime]:
    d = datetime.strptime(w["date"], "%Y-%m-%d").replace(tzinfo=KST)
    return d + timedelta(hours=w["start_hour"]), d + timedelta(hours=w["end_hour"])


def _title(w: dict) -> str:
    verb = "충전하기" if w["appliance"] == "전기차" else "돌리기"
    return f"⚡ {w['appliance']} {verb} — 제주 남는 전기 시간"


def _details(w: dict) -> str:
    return (f"제주 잉여전력 도우미 추천: {w['time_text']} (남을 가능성 {w['level']}). {w['how']} "
            "예보는 확률이라 틀릴 수 있어요.")


def google_url(w: dict) -> str:
    s, e = _span(w)
    fmt = "%Y%m%dT%H%M%S"
    q = {"action": "TEMPLATE", "text": _title(w), "dates": f"{s:{fmt}}/{e:{fmt}}", "ctz": "Asia/Seoul",
         "details": _details(w)}
    return "https://calendar.google.com/calendar/render?" + urlencode(q)


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_bytes(w: dict, now: datetime | None = None) -> bytes:
    s, e = _span(w)
    utc = lambda x: x.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stamp = utc(now or datetime.now(timezone.utc))
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//jeju-surplus-agent//KO", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{w['date']}-{w['start_hour']}-{zlib.crc32(w['appliance'].encode()) % 10**8}@jeju-surplus-agent",
        f"DTSTAMP:{stamp}", f"DTSTART:{utc(s)}", f"DTEND:{utc(e)}",
        f"SUMMARY:{_esc(_title(w))}", f"DESCRIPTION:{_esc(_details(w))}",
        "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(_title(w))}", "TRIGGER:-PT10M", "END:VALARM",
        "END:VEVENT", "END:VCALENDAR", ""]
    return "\r\n".join(_fold(l) for l in lines).encode("utf-8")


def _fold(line: str) -> str:
    """iCalendar 규칙: 한 줄 75바이트를 넘으면 줄을 나눠 다음 줄을 공백으로 시작 (한글이 잘리지 않게 글자 단위로)."""
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > (75 if not out else 74):
            out.append(cur)
            cur, size = "", 0
        cur += ch
        size += n
    out.append(cur)
    return "\r\n ".join(out)
