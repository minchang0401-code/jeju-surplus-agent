"""전력거래소 EPSIS에서 제주 시간별 SMP를 받아 CSV로 저장합니다. (API 키 필요 없음)

사용 예:
    python collect_smp.py --start 2024-06-01 --end 2026-11-16

결과: data/smp_jeju_hourly.csv  (열: date, hour, smp, is_surplus)
  - hour 는 EPSIS 화면 표기 그대로 1~24 입니다.
  - is_surplus = smp <= SURPLUS_THRESHOLD_WON (기본 0원)

EPSIS 화면: https://epsis.kpx.or.kr  > 전력거래 > 계통한계가격 > 시간별SMP
화면이 바뀌어 수집이 안 되면, 화면에서 기간과 '제주'를 고른 뒤 CSV 버튼으로 내려받아
같은 형식으로 바꿔 쓰면 됩니다.
"""
from __future__ import annotations

from time_utils import as_kst, now_kst, today_kst

import argparse
import re
from datetime import date, timedelta

import pandas as pd
import requests

from config import DATA, SMP_HOURLY_CSV, SURPLUS_THRESHOLD_WON

EPSIS_URL = "https://epsis.kpx.or.kr/epsisnew/selectEkmaSmpShd.ajax"
_VALUE = re.compile(r'c(\d+) = textFormmat\("([^"]*)"')


def _fetch_chunk(start: date, end: date) -> list[dict]:
    resp = requests.post(
        EPSIS_URL,
        data={
            "beginDate": start.strftime("%Y%m%d"),
            "endDate": end.strftime("%Y%m%d"),
            "selYear": "",
            "selMonth": "",
            "selKind": "jeju",
            "locale": "",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
        timeout=60,
    )
    resp.raise_for_status()
    text = resp.text
    blocks = text.split('gridData.push({"Date":"')
    rows: list[dict] = []
    prev = blocks[0]
    for block in blocks[1:]:
        values = {int(k): v for k, v in _VALUE.findall(prev)}
        day = block[:10].replace("/", "-")
        for hour in range(1, 25):
            raw = values.get(hour, "")
            smp = float(raw) if raw not in ("", None) else float("nan")
            rows.append({"date": day, "hour": hour, "smp": smp})
        prev = block
    return rows


def collect(start: date, end: date, chunk_days: int = 120) -> pd.DataFrame:
    rows: list[dict] = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=chunk_days - 1), end)
        print(f"  {cur} ~ {chunk_end} 수집 중...")
        rows.extend(_fetch_chunk(cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    df = pd.DataFrame(rows).drop_duplicates(["date", "hour"]).sort_values(["date", "hour"])
    df["smp"] = pd.to_numeric(df["smp"], errors="coerce").replace([float("inf"), -float("inf")], float("nan"))
    df["is_surplus"] = (df["smp"] <= SURPLUS_THRESHOLD_WON).astype("Int64").where(df["smp"].notna())
    return df.reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-06-01")
    parser.add_argument("--end", default=str(today_kst() - timedelta(days=1)))
    args = parser.parse_args()

    df = collect(date.fromisoformat(args.start), date.fromisoformat(args.end))
    DATA.mkdir(exist_ok=True)
    df.to_csv(SMP_HOURLY_CSV, index=False, encoding="utf-8-sig")
    days = df["date"].nunique()
    print(f"저장: {SMP_HOURLY_CSV}  ({days}일, 잉여 시간 {int(df['is_surplus'].sum())}개)")


if __name__ == "__main__":
    main()
