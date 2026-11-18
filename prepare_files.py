"""파일형 허브 데이터 정리 (877 기후 · 123 태양광 · 472 풍력)

    python prepare_files.py

877 「2000-2021 제주도 일간 기후 데이터」(4지점 CSV)를 data/hub/877_daily_climate/ 에 넣고 실행하면
data/hub/877_daily_climate_clean.csv 한 개로 정리합니다.

원본에서 확인한 문제와 처리
- 열 이름 앞뒤 공백(' Humid_mean ') → 공백 제거
- 숫자 칸의 ' - ' → 빈 값
- 제주(시) 파일: 2007-12-04부터 일조·일사·운량 열이 한 칸씩 밀려 있고, 그 전의 일조 값도 단위가 다름
  → 제주 지점은 기온·풍속·습도만 쓰고 일조·일사·운량은 쓰지 않음
- 일사는 고산 지점만 처음부터 끝까지 온전함 → 월별 일사 통계는 고산 기준
"""
from pathlib import Path

import pandas as pd

from config import HUB_FILE_DIRS

STATIONS = {"제주": 184, "고산": 185, "성산": 188, "서귀포": 189}
NUM_COLS = ["Tem_mean", "Tem_max", "Tem_min", "Wspeed_mean", "Wspeed_max", "Wspeed_min",
            "Humid_mean", "Sunshine_mean", "Solar_mean", "Cloud_max", "Cloud_min"]
CLEAN_877 = HUB_FILE_DIRS[877].parent / "877_daily_climate_clean.csv"
CLEAN_123 = HUB_FILE_DIRS[123].parent / "123_solar_business_clean.csv"
CLEAN_472 = HUB_FILE_DIRS[472].parent / "472_wind_power_clean.csv"


def _read_kr(p: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(p, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"글자 인코딩을 알 수 없음: {p}")


def prepare_123() -> pd.DataFrame:
    """전기사업체(태양광) 등록현황: 설비용량(kW)·사업개시일 → 연도별 신규·누적 용량"""
    files = sorted(HUB_FILE_DIRS[123].glob("*.csv"))
    if not files:
        print(f"[123] {HUB_FILE_DIRS[123]} 에 CSV가 없습니다.")
        return pd.DataFrame()
    d = _read_kr(files[-1])
    d["capacity_mw"] = pd.to_numeric(d["설비용량"], errors="coerce") / 1000   # 원본 단위 kW
    d["start_date"] = pd.to_datetime(d["사업개시일"], errors="coerce")
    d["city"] = d["설치장소"].astype(str).str.split().str[1]
    d["town"] = d["설치장소"].astype(str).str.split().str[2]
    out = d[["상호", "capacity_mw", "start_date", "city", "town", "데이터기준일자"]].rename(
        columns={"상호": "name", "데이터기준일자": "base_date"})
    out.to_csv(CLEAN_123, index=False, encoding="utf-8-sig")
    print(f"[123] 태양광 사업체 {len(out)}곳, 합계 {out['capacity_mw'].sum():.0f}MW, "
          f"사업개시 {out['start_date'].min():%Y}~{out['start_date'].max():%Y} → {CLEAN_123.name}")
    return out


def prepare_472() -> pd.DataFrame:
    """풍력발전현황: 발전소별 설비용량(MW)·설치장소"""
    files = sorted(HUB_FILE_DIRS[472].glob("*.csv"))
    if not files:
        print(f"[472] {HUB_FILE_DIRS[472]} 에 CSV가 없습니다.")
        return pd.DataFrame()
    d = _read_kr(files[-1])
    out = pd.DataFrame({
        "name": d["발전소명"],
        "capacity_mw": pd.to_numeric(d["설비용량(MW)"], errors="coerce"),
        "town": d["설치장소"].astype(str).str.split().str[0],
        "offshore": d["설치장소"].astype(str).str.contains("해역"),
        "base_date": d["데이터기준일자"],
    })
    out.to_csv(CLEAN_472, index=False, encoding="utf-8-sig")
    print(f"[472] 풍력발전소 {len(out)}곳, 합계 {out['capacity_mw'].sum():.0f}MW → {CLEAN_472.name}")
    return out


def _read(p: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp949"):
        try:
            d = pd.read_csv(p, encoding=enc, dtype=str)
            break
        except UnicodeDecodeError:
            continue
    d.columns = [c.strip() for c in d.columns]
    for c in NUM_COLS:
        if c in d:
            d[c] = pd.to_numeric(d[c].str.strip().replace({"-": None, "": None}), errors="coerce")
    d["Date"] = pd.to_datetime(d["Date"], errors="coerce")
    return d.dropna(subset=["Date"])


def _guess_station(name: str, d: pd.DataFrame, taken: set) -> str:
    for st in sorted(STATIONS, key=len, reverse=True):   # '서귀포'가 '제주'보다 먼저
        if st in name:
            return st
    # 파일 이름에 지점이 없으면(한글이 깨진 경우) 값의 특징으로 추정 — 실행 결과를 꼭 확인하세요
    wind, temp = d["Wspeed_mean"].mean(), d["Tem_mean"].mean()
    has_solar = d["Solar_mean"].notna().mean() > 0.5
    if wind > 5 and "고산" not in taken:
        return "고산"
    if has_solar and "제주" not in taken:
        return "제주"
    if temp > 16.8 and "서귀포" not in taken:
        return "서귀포"
    return next(s for s in ("성산", "서귀포", "제주", "고산") if s not in taken)


def prepare_877() -> pd.DataFrame:
    folder = HUB_FILE_DIRS[877]
    files = sorted(folder.glob("*.csv"))
    if not files:
        print(f"[877] {folder} 에 CSV가 없습니다.")
        return pd.DataFrame()
    frames, taken = [], set()
    for p in files:
        d = _read(p)
        st = _guess_station(p.name, d, taken)
        taken.add(st)
        if st == "제주":
            d[["Sunshine_mean", "Solar_mean", "Cloud_max", "Cloud_min"]] = float("nan")
        d.insert(1, "station", st)
        d.insert(2, "stn_id", STATIONS[st])
        frames.append(d)
        print(f"[877] {p.name} → {st}({STATIONS[st]}) {len(d)}일, "
              f"평균기온 {d['Tem_mean'].mean():.1f}℃, 평균풍속 {d['Wspeed_mean'].mean():.1f}m/s")
    out = pd.concat(frames, ignore_index=True)
    out.to_csv(CLEAN_877, index=False, encoding="utf-8-sig")
    print(f"[877] 저장: {CLEAN_877} ({len(out)}행)")
    return out


if __name__ == "__main__":
    prepare_877()
    prepare_123()
    prepare_472()
