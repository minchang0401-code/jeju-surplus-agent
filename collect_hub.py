"""제주데이터허브(대회 필수 데이터) 수집.

준비:
  1) jejudatahub.net 로그인 → 마이페이지 → 프로젝트 관리 → [프로젝트 만들기]
  2) 579·1226·1225·862 상세 페이지에서 [프로젝트 담기]
  3) 프로젝트 상세의 '프로젝트키'를 .env 의 JEJU_DATAHUB_PROJECT_KEY 에 입력
  4) 파일·링크형(877·123·472)은 직접 내려받아 data/hub/ 아래 폴더에 넣기 (README 참고)

사용 예:
    python collect_hub.py --only 862
    python collect_hub.py --only 579 --start 2024-06-01 --end 2026-11-16
    python collect_hub.py            # 전부

요청 주소 형식(허브 화면 표기): https://open.jejudatahub.net/api/proxy/{dataKey}/{projectKey}?{변수}
※ 페이지 나눔 변수(limit·number)와 응답 구조는 허브 기술문서(hwp) 기준으로 추정해 둔 것입니다.
   첫 실행 때 --debug 로 응답 모양을 확인하고, 다르면 _get_all() 만 고치면 됩니다.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import date, timedelta

import pandas as pd
import requests

from config import HUB, HUB_DATA, HUB_OPENAPI, HUB_WEATHER_DAILY_CSV, get_key

DEBUG = False
LIMIT = 100   # 한 번에 받을 행 수 (--limit 로 바꿈). 호출 1번 = 하루 한도 1건


def _get_all(data_no: int, params: dict, limit: int | None = None, max_pages: int = 500) -> list[dict]:
    key = get_key("JEJU_DATAHUB_PROJECT_KEY")
    if not key:
        raise RuntimeError("JEJU_DATAHUB_PROJECT_KEY 가 .env 에 없습니다.")
    data_key = HUB_DATA[data_no][0]
    url = HUB_OPENAPI.format(data_key=data_key, project_key=key)
    limit = limit or LIMIT
    rows: list[dict] = []
    for page in range(1, max_pages + 1):
        q = {**params, "limit": limit, "number": page}
        r = requests.get(url, params=q, timeout=60)
        if r.status_code != 200:
            # 오류 메시지에 주소(프로젝트키 포함)를 넣지 않음
            raise requests.HTTPError(f"허브 {data_no} 응답 {r.status_code}: {r.text[:300]}")
        body = r.json()
        if DEBUG and page == 1:
            print(json.dumps(body, ensure_ascii=False)[:1500])
        if isinstance(body, list):
            rows.extend(body)
            break
        data = body.get("data") or body.get("items") or []
        rows.extend(data)
        if not body.get("hasMore") or not data:
            break
        time.sleep(0.2)
    return rows


def collect_579(start: date, end: date) -> pd.DataFrame:
    """일별 기상 정보: 하루씩 조회(searchDate). 하루 호출 한도(약 1000건)에 주의하세요."""
    out = HUB_DATA[579][1]
    done = pd.read_csv(out) if out.exists() else pd.DataFrame()
    have = set(done["baseDate"].astype(str)) if "baseDate" in done else set()
    rows = []
    d = start
    while d <= end:
        ymd = d.strftime("%Y%m%d")
        if ymd not in have:
            try:
                rows.extend(_get_all(579, {"searchDate": ymd}))
            except requests.HTTPError as e:
                print(f"  {ymd} 실패: {e}")
        d += timedelta(days=1)
    df = pd.concat([done, pd.DataFrame(rows)], ignore_index=True)
    if not df.empty:
        df["baseDate"] = df["baseDate"].astype(str)
        df = df.drop_duplicates(["baseDate", "observatoryName"])
        df.to_csv(out, index=False, encoding="utf-8-sig")
        summarize_579(df)
    return df


def summarize_579(df: pd.DataFrame) -> None:
    """관측소들의 값을 섬 평균 하루 값으로 정리 → 모델 변수로 사용."""
    num = ["averageTemperature", "highestTemperature", "dailyRainfall",
           "averageWindSpeed", "maximumWindSpeed"]
    d = df.copy()
    for c in num:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    daily = d.groupby("baseDate")[num].mean().reset_index()
    daily["date"] = pd.to_datetime(daily["baseDate"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
    daily = daily.rename(columns={
        "averageTemperature": "hub_day_avg_temp", "highestTemperature": "hub_day_max_temp",
        "dailyRainfall": "hub_day_rain", "averageWindSpeed": "hub_day_avg_wind",
        "maximumWindSpeed": "hub_day_max_wind"})
    daily.drop(columns="baseDate").to_csv(HUB_WEATHER_DAILY_CSV, index=False, encoding="utf-8-sig")
    print(f"  섬 평균 일별 기상 저장: {HUB_WEATHER_DAILY_CSV} ({len(daily)}일, "
          f"{daily['date'].min()} ~ {daily['date'].max()})")


def collect_monthly(data_no: int, start_ym: str, end_ym: str, fmt: str, months: int = 0) -> pd.DataFrame:
    """1226·1225처럼 기간 변수로 조회하는 데이터. 달마다 따로 저장해 두고, 이미 받은 달은 건너뜀
    (하루 호출 한도에 걸려 중간에 멈춰도 다음 날 이어 받기 가능). months>0 이면 그 개월 수만."""
    cache = HUB / f"{data_no}_months"
    cache.mkdir(parents=True, exist_ok=True)
    periods = list(pd.period_range(start_ym, end_ym, freq="M"))
    if months:
        periods = periods[:months]
    for p in periods:
        f = cache / f"{p}.csv"
        if f.exists():
            continue
        s, e = p.start_time.strftime(fmt), p.end_time.strftime(fmt)
        print(f"  {data_no}: {s} ~ {e}")
        rows = _get_all(data_no, {"startDate": s, "endDate": e})
        pd.DataFrame(rows).to_csv(f, index=False, encoding="utf-8-sig")
        print(f"    → {len(rows)}행")
    parts = [pd.read_csv(f) for f in sorted(cache.glob("*.csv")) if f.stat().st_size > 5]
    df = pd.concat(parts, ignore_index=True).drop_duplicates() if parts else pd.DataFrame()
    df.to_csv(HUB_DATA[data_no][1], index=False, encoding="utf-8-sig")
    return df


def collect_862() -> pd.DataFrame:
    df = pd.DataFrame(_get_all(862, {}))
    df.to_csv(HUB_DATA[862][1], index=False, encoding="utf-8-sig")
    return df


def probe_579(max_calls: int = 150) -> None:
    """579 가 어느 날짜까지 데이터가 있는지 찾기: 오늘부터 한 달씩 거슬러 매달 15일을 조회.
    첫 데이터가 나오면 그 달을 하루씩 훑어 마지막 날짜를 찾고, 첫 행 모양을 보여 줌."""
    d = date.today().replace(day=15)
    for _ in range(max_calls):
        rows = _get_all(579, {"searchDate": d.strftime("%Y%m%d")})
        if rows:
            print(f"[579] {d:%Y-%m-%d} 에 데이터 있음 ({len(rows)}행). 첫 행:")
            print(json.dumps(rows[0], ensure_ascii=False)[:800])
            last = d
            nxt = d + timedelta(days=1)
            while nxt <= date.today():
                if not _get_all(579, {"searchDate": nxt.strftime("%Y%m%d")}):
                    break
                last, nxt = nxt, nxt + timedelta(days=1)
            print(f"[579] 마지막으로 데이터가 있는 날짜(추정): {last:%Y-%m-%d}")
            return
        print(f"[579] {d:%Y-%m-%d} 없음")
        d = (d.replace(day=1) - timedelta(days=1)).replace(day=15)
    print("[579] 데이터를 찾지 못했습니다.")


def main() -> None:
    global DEBUG
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", type=int, choices=[579, 1226, 1225, 862])
    parser.add_argument("--start", default="2024-06-01", help="579 시작일")
    parser.add_argument("--end", default=str(date.today() - timedelta(days=1)), help="579 종료일")
    parser.add_argument("--debug", action="store_true", help="첫 응답 모양 출력")
    parser.add_argument("--limit", type=int, default=100, help="한 번에 받을 행 수 (클수록 호출 수가 줄어듦)")
    parser.add_argument("--months", type=int, default=0, help="1226·1225 를 앞에서부터 이 개월 수만 받기")
    parser.add_argument("--probe579", action="store_true", help="579 데이터가 있는 마지막 날짜 찾기")
    args = parser.parse_args()
    DEBUG = args.debug
    global LIMIT
    LIMIT = args.limit
    if DEBUG and args.only == 579:
        # 시험 모드: 579는 하루 1회 호출이라 최근 2일만 (하루 한도 1000건 보호)
        args.start = str(date.today() - timedelta(days=2))
    HUB.mkdir(parents=True, exist_ok=True)
    if args.probe579:
        probe_579()
        return

    jobs = {
        862: collect_862,
        1225: lambda: collect_monthly(1225, "2022-07", "2022-10", "%Y%m%d", args.months),
        1226: lambda: collect_monthly(1226, "2021-01", "2022-06", "%Y%m", args.months),
        579: lambda: collect_579(date.fromisoformat(args.start), date.fromisoformat(args.end)),
    }
    for no, job in jobs.items():
        if args.only and no != args.only:
            continue
        print(f"[{no}] {HUB_DATA[no][2]} 수집 시작")
        try:
            df = job()
            print(f"[{no}] 저장 완료: {HUB_DATA[no][1].name} ({len(df)}행)")
        except Exception as e:  # 키 없음·형식 차이 등은 건너뛰고 다음 데이터 진행
            print(f"[{no}] 건너뜀: {e}")


if __name__ == "__main__":
    main()
