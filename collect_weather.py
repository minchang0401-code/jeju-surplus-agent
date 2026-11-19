"""기상청 날씨 수집.

1) 과거 관측 (학습용): 기상청 API허브 · 지상관측 ASOS 시간자료 (제주·고산·성산·서귀포 4지점)
     python collect_weather.py history --start 2024-06-01 --end 2026-11-16
   → data/weather_jeju_hourly.csv  (date, hour, w_ta, w_ws, w_sky, w_rain, w_ca, w_si, w_ss)
     w_si(일사)·w_ss(일조)는 예보에 없어서 모델에는 쓰지 않고 설명·분석에만 씁니다.

2) 단기예보 (예측용): 공공데이터포털 「기상청_단기예보 조회서비스」 getVilageFcst
     python collect_weather.py forecast
   → data/forecast_jeju_hourly.csv (위와 같은 열 + 하루 단위 열)

3) 중기예보 (3~5일 뒤용): 공공데이터포털 「기상청_중기예보 조회서비스」 getMidLandFcst·getMidTa (제주도)
     python collect_weather.py mid
   → data/forecast_mid_daily.csv (date, mid_sky_pm, mid_rain_pm, mid_tmax ...)

학습 변수와 예보 변수를 같은 형태로 맞춥니다.
  기온 w_ta / 풍속 w_ws / 하늘상태 w_sky(1맑음·3구름많음·4흐림) / 강수 여부 w_rain
  하늘상태는 관측 전운량(0~10)을 기상청 기준(0~5 맑음, 6~8 구름많음, 9~10 흐림)으로 바꿔 씁니다.

※ ASOS 응답의 열 순서는 기상청 API허브 '시간자료(kma_sfctm3)' 형식을 기준으로 적었습니다.
   첫 실행 때 --debug 로 머리글을 확인하고, 다르면 ASOS_COLUMNS 만 고치면 됩니다.
"""
from __future__ import annotations

from time_utils import as_kst, now_kst, today_kst

import argparse
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import requests

from config import (FORECAST_HOURLY_CSV, FORECAST_MID_CSV, KMA_ASOS_STATIONS, KMA_FCST_GRIDS,
                    WEATHER_HOURLY_CSV, get_key)

ASOS_URL = "https://apihub.kma.go.kr/api/typ01/url/kma_sfctm3.php"
ASOS_COLUMNS = {  # 열 번호(0부터): 이름
    0: "tm", 1: "stn", 3: "ws", 11: "ta", 13: "hm", 15: "rn", 25: "ca_tot", 33: "ss", 34: "si",
}
FCST_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
# 중기예보 (공공데이터포털 「기상청_중기예보 조회서비스」, 단기예보와 따로 활용신청 필요). 4~10일 뒤, 하루 2번(06·18시) 발표
MID_LAND_URL = "https://apis.data.go.kr/1360000/MidFcstInfoService/getMidLandFcst"
MID_TA_URL = "https://apis.data.go.kr/1360000/MidFcstInfoService/getMidTa"
MID_LAND_REG = "11G00000"   # 육상예보 구역: 제주도
MID_TA_REG = "11G00201"     # 기온예보 지점: 제주


def sky_from_cloud(ca: pd.Series) -> pd.Series:
    return pd.cut(ca, bins=[-0.1, 5, 8, 10], labels=[1, 3, 4]).astype(float)


# ---------------------------------------------------------------- 과거 관측
ASOS_RAW_DIR = WEATHER_HOURLY_CSV.parent / "asos_raw"   # 지점·달별 원본 응답 (이어 받기용)


def _download_asos(stn: int, start: datetime, end: datetime, key: str, tries: int = 3) -> str:
    """ASOS 원본 텍스트를 받아 옴. 실패하면 잠시 쉬고 다시 시도. 오류 메시지에 주소(키 포함)를 넣지 않음."""
    import time
    params = {"tm1": start.strftime("%Y%m%d%H00"), "tm2": end.strftime("%Y%m%d%H00"),
              "stn": stn, "help": 0, "authKey": key}
    last = ""
    for i in range(tries):
        try:
            r = requests.get(ASOS_URL, params=params, timeout=120)
            if r.status_code == 200:
                return r.content.decode("euc-kr", errors="ignore") if b"\xb0" in r.content[:2000] else r.text
            last = f"응답 {r.status_code}"
        except requests.RequestException as e:
            last = type(e).__name__
        time.sleep(5 * (i + 1))
    raise RuntimeError(f"기상청 ASOS {stn} {start:%Y-%m-%d}~{end:%Y-%m-%d} 받기 실패({last})")


def _parse_asos(text: str) -> pd.DataFrame:
    rows = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 35:
            continue
        rows.append({name: parts[i] for i, name in ASOS_COLUMNS.items()})
    df = pd.DataFrame(rows)
    for c in df.columns:
        if c != "tm":
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.replace([-9, -9.0, -99, -99.0, -999], np.nan)


def _fetch_asos_month(stn: int, s: datetime, e: datetime, key: str, final: bool) -> str | None:
    """한 지점·한 달 원본. 이미 받은 달은 파일에서 읽음(진행 중인 마지막 달은 매번 새로 받음).
    한 달 요청이 실패하면 보름씩 나눠 다시 시도."""
    ASOS_RAW_DIR.mkdir(parents=True, exist_ok=True)
    f = ASOS_RAW_DIR / f"{stn}_{s:%Y%m}.txt"
    if f.exists() and not final:
        return f.read_text(encoding="utf-8")
    try:
        text = _download_asos(stn, s, e, key)
    except RuntimeError:
        mid = s + (e - s) / 2
        mid = mid.replace(minute=0, second=0, microsecond=0)
        try:
            text = _download_asos(stn, s, mid, key) + "\n" + _download_asos(stn, mid + timedelta(hours=1), e, key)
        except RuntimeError as err:
            print(f"    {err} → 건너뜀 (다시 실행하면 이 달만 다시 받음)")
            return None
    f.write_text(text, encoding="utf-8")
    return text


def collect_history(start: date, end: date, debug: bool = False) -> pd.DataFrame:
    key = get_key("KMA_APIHUB_KEY")
    if not key:
        raise RuntimeError("KMA_APIHUB_KEY 가 .env 에 없습니다.")
    frames, shown, missing = [], False, 0
    periods = list(pd.period_range(start, end, freq="M"))
    for stn, name in KMA_ASOS_STATIONS.items():
        for p in periods:
            s = max(p.start_time.to_pydatetime(), datetime.combine(start, datetime.min.time()))
            e = min(p.end_time.to_pydatetime().replace(minute=0, second=0, microsecond=0),
                    datetime.combine(end, datetime.min.time()) + timedelta(hours=23))
            print(f"  {name}({stn}) {s:%Y-%m-%d} ~ {e:%Y-%m-%d}")
            text = _fetch_asos_month(stn, s, e, key, final=(p == periods[-1]))
            if text is None:
                missing += 1
                continue
            if debug and not shown:
                lines = text.splitlines()
                print("---- 응답 머리글 ----")
                print("\n".join([l for l in lines if l.startswith("#")][:12]))
                print("---- 첫 자료 2줄 ----")
                print("\n".join([l for l in lines if l.strip() and not l.startswith("#")][:2]))
                shown = True
            frames.append(_parse_asos(text))
    if missing:
        print(f"※ {missing}개 달을 받지 못했습니다. 같은 명령을 한 번 더 실행하면 빠진 달만 다시 받습니다.")
    raw = pd.concat(frames, ignore_index=True)
    raw["dt"] = pd.to_datetime(raw["tm"].astype(str), format="%Y%m%d%H%M")
    # 4지점 평균 (섬 전체 날씨)
    agg = raw.groupby("dt").agg(w_ta=("ta", "mean"), w_ws=("ws", "mean"), w_ca=("ca_tot", "mean"),
                                w_rn=("rn", "mean"), w_si=("si", "mean"), w_ss=("ss", "mean")).reset_index()
    agg["w_sky"] = sky_from_cloud(agg["w_ca"])
    agg["w_rain"] = (agg["w_rn"].fillna(0) > 0).astype(int)
    agg["w_rn"] = agg["w_rn"].fillna(0)
    out = _to_label_hours(agg)[["date", "hour", "w_ta", "w_ws", "w_sky", "w_rain", "w_rn", "w_ca", "w_si", "w_ss"]]
    out.to_csv(WEATHER_HOURLY_CSV, index=False, encoding="utf-8-sig")
    print(f"저장: {WEATHER_HOURLY_CSV} ({out['date'].nunique()}일)")
    return out


def _to_label_hours(df: pd.DataFrame) -> pd.DataFrame:
    """관측·예보 시각 HH:00 을 SMP 표기(1~24시)에 맞춥니다. 0시는 전날 24시로 봅니다."""
    dt = df["dt"]
    is_midnight = dt.dt.hour == 0
    out = df.copy()
    out["date"] = (dt - pd.to_timedelta(is_midnight.astype(int), unit="D")).dt.strftime("%Y-%m-%d")
    out["hour"] = np.where(is_midnight, 24, dt.dt.hour)
    return out


# ---------------------------------------------------------------- 단기예보
def _latest_base(now: datetime) -> tuple[str, str]:
    bases = [2, 5, 8, 11, 14, 17, 20, 23]
    ref = as_kst(now) - timedelta(minutes=15)  # 발표 후 약 10분 뒤부터 조회 가능
    cands = [h for h in bases if h <= ref.hour]
    if cands:
        return ref.strftime("%Y%m%d"), f"{cands[-1]:02d}00"
    prev = ref - timedelta(days=1)
    return prev.strftime("%Y%m%d"), "2300"


def _parse_pcp(v: str) -> float:
    if not isinstance(v, str) or "없음" in v:
        return 0.0
    if "미만" in v:
        return 0.5
    nums = [float(x) for x in pd.Series([v]).str.findall(r"[\d.]+").iloc[0]]
    return float(np.mean(nums)) if nums else 0.0


def collect_forecast(now: datetime | None = None) -> pd.DataFrame:
    key = get_key("DATA_GO_KR_KEY")
    if not key:
        raise RuntimeError("DATA_GO_KR_KEY 가 .env 에 없습니다.")
    base_date, base_time = _latest_base(now or now_kst())
    items = []
    for name, (nx, ny) in KMA_FCST_GRIDS.items():
        params = {"serviceKey": key, "pageNo": 1, "numOfRows": 1500, "dataType": "JSON",
                  "base_date": base_date, "base_time": base_time, "nx": nx, "ny": ny}
        # 화면을 여는 중에 부르므로 오래 기다리지 않음 (연결 5초, 응답 20초). 실패하면 저장된 예보로 안내
        r = requests.get(FCST_URL, params=params, timeout=(5, 20))
        if r.status_code != 200:   # 오류 메시지에 주소(인증키 포함)를 넣지 않음
            raise RuntimeError(f"단기예보 응답 {r.status_code}: {r.text[:200]}")
        try:
            body = r.json()["response"]["body"]["items"]["item"]
        except (ValueError, KeyError) as e:   # 키 미등록 등은 XML/다른 JSON으로 옴
            raise RuntimeError(f"단기예보 응답을 읽지 못함: {r.text[:300]}") from e
        for it in body:
            it["grid"] = name
        items.extend(body)
    df = pd.DataFrame(items)
    wide = df.pivot_table(index=["grid", "fcstDate", "fcstTime"], columns="category",
                          values="fcstValue", aggfunc="first").reset_index()
    for c in ["TMP", "WSD", "SKY", "PTY", "POP"]:
        wide[c] = pd.to_numeric(wide.get(c), errors="coerce")
    wide["PCPmm"] = wide.get("PCP", pd.Series(dtype=str)).map(_parse_pcp)
    wide["dt"] = pd.to_datetime(wide["fcstDate"] + wide["fcstTime"], format="%Y%m%d%H%M")
    g = wide.groupby("dt").agg(w_ta=("TMP", "mean"), w_ws=("WSD", "mean"), w_sky=("SKY", "mean"),
                               pty=("PTY", "max"), pcp=("PCPmm", "mean")).reset_index()
    g["w_sky"] = g["w_sky"].round().clip(1, 4).replace(2, 3)
    g["w_rain"] = (g["pty"].fillna(0) > 0).astype(int)
    out = _to_label_hours(g)
    # 허브 579(일별 기상)와 같은 의미의 하루 값 (예보에서 계산)
    day = out.groupby("date").agg(hub_day_avg_temp=("w_ta", "mean"), hub_day_max_temp=("w_ta", "max"),
                                  hub_day_rain=("pcp", "sum"), hub_day_avg_wind=("w_ws", "mean"),
                                  hub_day_max_wind=("w_ws", "max")).reset_index()
    out = out.merge(day, on="date", how="left")
    out["base"] = base_date + base_time
    cols = ["date", "hour", "w_ta", "w_ws", "w_sky", "w_rain",
            "hub_day_avg_temp", "hub_day_max_temp", "hub_day_rain", "hub_day_avg_wind",
            "hub_day_max_wind", "base"]
    out[cols].to_csv(FORECAST_HOURLY_CSV, index=False, encoding="utf-8-sig")
    print(f"저장: {FORECAST_HOURLY_CSV} (발표 {base_date} {base_time}, {out['date'].nunique()}일)")
    return out[cols]


def _mid_tmfc(now: datetime) -> str:
    ref = as_kst(now) - timedelta(minutes=30)   # 발표 뒤 조금 지나야 조회됨
    if ref.hour >= 18:
        return ref.strftime("%Y%m%d") + "1800"
    if ref.hour >= 6:
        return ref.strftime("%Y%m%d") + "0600"
    return (ref - timedelta(days=1)).strftime("%Y%m%d") + "1800"


def _mid_item(url: str, key: str, reg: str, tmfc: str) -> dict:
    params = {"serviceKey": key, "pageNo": 1, "numOfRows": 10, "dataType": "JSON", "regId": reg, "tmFc": tmfc}
    r = requests.get(url, params=params, timeout=(5, 20))
    if r.status_code != 200:
        raise RuntimeError(f"중기예보 응답 {r.status_code}: {r.text[:200]}")
    try:
        return r.json()["response"]["body"]["items"]["item"][0]
    except (ValueError, KeyError, IndexError) as e:   # 활용신청 전이면 XML 오류가 옴
        raise RuntimeError(f"중기예보 응답을 읽지 못함(활용신청 여부 확인): {r.text[:200]}") from e


def parse_mid(land: dict, ta: dict, tmfc: str) -> pd.DataFrame:
    """중기예보 응답 → 날짜별 오후 하늘(1·3·4), 오후 비 여부, 최고기온 (학습 변수 mid_* 와 같은 모양)."""
    base = datetime.strptime(tmfc[:8], "%Y%m%d")
    rows = []
    for n in range(3, 11):
        wf = land.get(f"wf{n}Pm", land.get(f"wf{n}"))
        rn = land.get(f"rnSt{n}Pm", land.get(f"rnSt{n}"))
        tx = ta.get(f"taMax{n}")
        if not wf or tx in (None, ""):
            continue
        wf = str(wf)
        sky = 1.0 if wf.startswith("맑") else (4.0 if wf.startswith("흐") else 3.0)
        try:
            rain = float(float(rn) >= 60 or any(w in wf for w in ("비", "소나기", "눈")))
        except (TypeError, ValueError):
            rain = float(any(w in wf for w in ("비", "소나기", "눈")))
        rows.append({"date": (base + timedelta(days=n)).strftime("%Y-%m-%d"), "mid_sky_pm": sky,
                     "mid_rain_pm": rain, "mid_tmax": float(tx), "mid_wf_pm": wf, "mid_rain_prob_pm": rn, "base": tmfc})
    return pd.DataFrame(rows)


def collect_mid(now: datetime | None = None) -> pd.DataFrame:
    key = get_key("DATA_GO_KR_KEY")
    if not key:
        raise RuntimeError("DATA_GO_KR_KEY 가 .env 에 없습니다.")
    tmfc = _mid_tmfc(now or now_kst())
    out = parse_mid(_mid_item(MID_LAND_URL, key, MID_LAND_REG, tmfc), _mid_item(MID_TA_URL, key, MID_TA_REG, tmfc), tmfc)
    if out.empty:
        raise RuntimeError("중기예보에 쓸 날짜가 없습니다.")
    out.to_csv(FORECAST_MID_CSV, index=False, encoding="utf-8-sig")
    print(f"저장: {FORECAST_MID_CSV} (발표 {tmfc}, {len(out)}일)")
    return out


def refresh_mid_if_stale(max_age_hours: float = 12.0) -> str:
    """중기예보는 하루 2번 발표. 오래됐으면 새로 받음. 실패해도 예외 없이 상태만 돌려줌(그 날짜는 달력 모델로)."""
    try:
        if FORECAST_MID_CSV.exists():
            base = str(pd.read_csv(FORECAST_MID_CSV, usecols=["base"], dtype=str)["base"].iloc[0])
            if (now_kst() - datetime.strptime(base[:12], "%Y%m%d%H%M")).total_seconds() / 3600 < max_age_hours:
                return "fresh"
        if not get_key("DATA_GO_KR_KEY"):
            return "no_key"
        collect_mid()
        return "updated"
    except Exception:
        return "failed"


def forecast_issued_at() -> datetime | None:
    """저장된 단기예보의 발표 시각. 파일이 없거나 읽을 수 없으면 None."""
    if not FORECAST_HOURLY_CSV.exists():
        return None
    try:
        base = str(pd.read_csv(FORECAST_HOURLY_CSV, usecols=["base"], dtype=str)["base"].iloc[0])
        return datetime.strptime(base[:12], "%Y%m%d%H%M")
    except Exception:
        return None


def refresh_forecast_if_stale(max_age_hours: float = 4.0) -> dict:
    """앱을 열 때 부름. 저장된 예보가 max_age_hours 보다 오래됐고 키가 있으면 새 예보를 받음.
    실패해도 예외를 내지 않음 → 앱은 저장된 예보로 계속 동작. 오류 메시지에 인증키를 넣지 않음.
    반환 status: fresh(아직 새것) / updated(새로 받음) / no_key(키 없음) / failed(받기 실패)"""
    mid = refresh_mid_if_stale()   # 3~5일 뒤용 중기예보 (실패해도 계속)
    issued = forecast_issued_at()
    age = None if issued is None else (now_kst() - issued).total_seconds() / 3600
    info = {"issued_at": issued.strftime("%Y-%m-%d %H:%M") if issued else None,
            "age_hours": None if age is None else round(age, 1)}
    info["mid"] = mid
    if age is not None and age < max_age_hours:
        return {"status": "fresh", **info}
    key = get_key("DATA_GO_KR_KEY")
    if not key:
        return {"status": "no_key", **info}
    try:
        collect_forecast()
    except RuntimeError as e:     # 우리가 만든 메시지 (주소·키 없음)
        return {"status": "failed", "error": str(e).replace(key, "***")[:200], **info}
    except Exception as e:        # 네트워크 오류 등은 메시지에 주소(키 포함)가 들어갈 수 있어 종류만 남김
        return {"status": "failed", "error": type(e).__name__, **info}
    issued = forecast_issued_at()
    return {"status": "updated", "mid": mid, "issued_at": issued.strftime("%Y-%m-%d %H:%M") if issued else None,
            "age_hours": 0.0 if issued is None else round((now_kst() - issued).total_seconds() / 3600, 1)}


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("history")
    h.add_argument("--start", default="2024-06-01")
    h.add_argument("--end", default=str(today_kst() - timedelta(days=1)))
    h.add_argument("--debug", action="store_true")
    sub.add_parser("forecast")
    sub.add_parser("mid")
    args = parser.parse_args()
    if args.cmd == "history":
        collect_history(date.fromisoformat(args.start), date.fromisoformat(args.end), args.debug)
    elif args.cmd == "mid":
        collect_mid()
    else:
        collect_forecast()


if __name__ == "__main__":
    main()
