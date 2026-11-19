"""호스트 OS 시간대와 무관한 한국 시간. CSV의 시각도 KST로 통일한다."""
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9), name="Asia/Seoul")


def as_kst(value):
    """시간대 없는 기존 CSV/입력은 한국 시간으로, aware 입력은 한국 시간으로 변환."""
    if value.tzinfo is not None:
        value = value.astimezone(KST)
    return value.replace(tzinfo=None)


def now_kst():
    return datetime.now(KST).replace(tzinfo=None)


def today_kst():
    return now_kst().date()
