"""프로젝트 공통 설정.

API 키는 이 파일에 쓰지 않습니다. 프로젝트 폴더의 .env 파일에 넣으세요 (.env.example 참고).
대회 규칙상 데이터 API 키는 제출물에 포함하면 안 됩니다.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
HUB = DATA / "hub"              # 제주데이터허브 데이터 (대회 필수 데이터)
MODELS = ROOT / "models"
REPORTS = ROOT / "reports"

# ---------------------------------------------------------------- 정답 (전력거래소 EPSIS)
SMP_HOURLY_CSV = DATA / "smp_jeju_hourly.csv"          # collect_smp.py 결과 (실제 가격 포함)
SMP_COMPACT_TXT = DATA / "smp_jeju_surplus_compact.txt"  # 동봉된 요약본 (잉여 여부만)
SURPLUS_THRESHOLD_WON = 0.0                             # 제주 SMP가 이 값 이하이면 '잉여 시간'

# ---------------------------------------------------------------- 날씨
WEATHER_HOURLY_CSV = DATA / "weather_jeju_hourly.csv"     # 기상청 ASOS 시간자료 (학습용)
FORECAST_HOURLY_CSV = DATA / "forecast_jeju_hourly.csv"   # 기상청 단기예보 (예측용)
KMA_ASOS_STATIONS = {184: "제주", 185: "고산", 188: "성산", 189: "서귀포"}
# 단기예보 격자 (제주시, 서귀포시). 기상청 「격자 위경도」 자료로 한 번 확인하세요.
KMA_FCST_GRIDS = {"제주시": (53, 38), "서귀포시": (52, 33)}

# ---------------------------------------------------------------- 제주데이터허브
HUB_OPENAPI = "https://open.jejudatahub.net/api/proxy/{data_key}/{project_key}"
HUB_DATA = {
    # 번호: (dataKey, 저장 파일, 설명)
    579: ("1aD5taat1attaa51Db1511b51ab9Da19", HUB / "579_daily_weather.csv", "일별 기상 정보"),
    1226: ("DD96616t226D16at11ta92D6DD19DttD", HUB / "1226_ev_charging_month.csv", "월별 전기자동차 충전 이력"),
    1225: ("a26229112651226a625t1b155at61bt1", HUB / "1225_ev_waiting_day.csv", "일별 전기자동차 충전 이력"),
    862: ("atDab6t8218btaa122b26DDtbatD86t1", HUB / "862_ev_stations.csv", "전기자동차 충전소 정보"),
}
# 파일·링크형 허브 데이터: 허브(또는 연결된 공공데이터포털)에서 내려받아 아래 폴더에 넣으세요.
HUB_FILE_DIRS = {
    877: HUB / "877_daily_climate",     # 2000-2021 제주도 일간 기후 (4지점 CSV)
    123: HUB / "123_solar_business",    # 전기사업체(태양광) 등록현황
    472: HUB / "472_wind_power",        # 풍력발전현황
}
HUB_WEATHER_DAILY_CSV = DATA / "weather_hub_daily.csv"   # 579 를 섬 평균 일 단위로 정리한 파일

# ---------------------------------------------------------------- 모델
TEST_START = "2026-01-01"   # 시험(평가) 시작일
MAX_HORIZON_DAYS = 5        # 몇 일 앞까지 예측할지 (단기예보 범위)
PREDICTION_LOG = DATA / "forecast_log.csv"   # 에이전트가 낸 예보 기록 (검증용)

# ---------------------------------------------------------------- 에이전트(LLM)
# LLM_PROVIDER: openai (OpenAI·Upstage Solar 등 OpenAI 호환) / anthropic / none
DEFAULT_LLM = {
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "upstage": {"base_url": "https://api.upstage.ai/v1", "model": "solar-pro2"},
    "anthropic": {"base_url": "https://api.anthropic.com/v1", "model": "claude-sonnet-4-5"},
}

# 대한민국 공휴일 (2024~2026). 2026-11-17 웹 자료로 대조함:
#  - 2025-10-10 임시공휴일은 지정되지 않음
#  - 2026년부터 노동절(5/1)·제헌절(7/17)이 공휴일로 추가됨
# 제출 전 공공데이터포털 「한국천문연구원_특일 정보」로 한 번 더 확인하면 좋습니다.
HOLIDAYS = {
    # 2024
    "2024-01-01", "2024-02-09", "2024-02-10", "2024-02-11", "2024-02-12",
    "2024-03-01", "2024-04-10", "2024-05-05", "2024-05-06", "2024-05-15",
    "2024-06-06", "2024-08-15", "2024-09-16", "2024-09-17", "2024-09-18",
    "2024-10-01", "2024-10-03", "2024-10-09", "2024-12-25",
    # 2025
    "2025-01-01", "2025-01-27", "2025-01-28", "2025-01-29", "2025-01-30",
    "2025-03-01", "2025-03-03", "2025-05-05", "2025-05-06", "2025-06-03",
    "2025-06-06", "2025-08-15", "2025-10-03", "2025-10-05", "2025-10-06",
    "2025-10-07", "2025-10-08", "2025-10-09", "2025-12-25",
    # 2026
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-01",
    "2026-03-02", "2026-05-01", "2026-05-05", "2026-05-24", "2026-05-25", "2026-06-03",
    "2026-06-06", "2026-07-17", "2026-08-15", "2026-08-17", "2026-09-24", "2026-09-25",
    "2026-09-26", "2026-10-03", "2026-10-05", "2026-10-09", "2026-12-25",
}


def load_env(path: Path = ROOT / ".env") -> None:
    """간단한 .env 로더 (python-dotenv 없이도 동작)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def get_key(name: str) -> str | None:
    load_env()
    return os.environ.get(name) or None
