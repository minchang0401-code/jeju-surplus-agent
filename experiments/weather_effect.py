"""날씨 효과 미리 보기: Open-Meteo 하루 요약을 붙였을 때 성능이 얼마나 오르는지 (대회 제출용 아님)."""
import sys; sys.path.insert(0, '.')
import numpy as np, pandas as pd
from pathlib import Path
from sklearn.metrics import average_precision_score
import features as F, train as T

lines = Path('experiments/openmeteo_daily.txt').read_text(encoding='utf-8').splitlines()
start = [l for l in lines if l.startswith('START')][0].split()[1]
vals = [list(map(float, x.split(','))) for x in lines[-1].split(';')]
W = pd.DataFrame(vals, columns=['om_rad_mid', 'om_cloud_mid', 'om_wind_mid', 'om_wind_night', 'om_temp', 'om_rain'])
W['date'] = pd.date_range(start, periods=len(W))

lab = F.load_labels()
t = F.add_recent_trend(F.add_calendar(lab), lab).merge(W, on='date', how='left')
t = t.dropna(subset=['recent_surplus_days']).reset_index(drop=True)
base = F.CALENDAR_FEATURES + F.TREND_FEATURES
wcols = list(W.columns[:-1])

# 1) 날씨와 잉여의 관계
day = t.groupby('date').agg(y=('is_surplus', 'max'), rad=('om_rad_mid', 'first'), cloud=('om_cloud_mid', 'first'),
                            temp=('om_temp', 'first'), month=('month', 'first'), off=('is_offday', 'first'))
day['sunny'] = pd.cut(day['cloud'], [-1, 3, 7, 10], labels=['맑음(0~3)', '구름(4~7)', '흐림(8~10)'])
cool = day[~day['month'].isin([6, 7, 8, 9])]
print('6~9월 제외, 한낮 구름양별 잉여일 비율:'); print(cool.groupby('sunny', observed=True)['y'].agg(['mean', 'size']).round(3))
print('\n6~9월 제외, 맑음(0~3) & 휴일 여부별:'); print(cool[cool['sunny'] == '맑음(0~3)'].groupby('off')['y'].agg(['mean', 'size']).round(3))

# 2) 성능 비교 (같은 평가 방식)
train, test = t[t.date < '2026-01-01'], t[t.date >= '2026-01-01']
y = test.is_surplus.to_numpy()
def run(cols):
    p_static = T.new_model().fit(train[cols], train.is_surplus).predict_proba(test[cols])[:, 1]
    p_roll = T.walk_forward(t, cols)
    return T.evaluate(y, p_static, test, 0.3), T.evaluate(y, p_roll, test, 0.3), p_roll
rows = {}
for name, cols in [('달력·경향', base), ('+날씨 전체', base + wcols),
                   ('+일사·구름만', base + ['om_rad_mid', 'om_cloud_mid']),
                   ('+일사·구름·기온', base + ['om_rad_mid', 'om_cloud_mid', 'om_temp'])]:
    s, r, p = run(cols)
    rows[name] = {'고정 날짜PR': s['day_pr_auc'], '월별 날짜PR': r['day_pr_auc'], '고정 시간PR': s['hour_pr_auc'],
                  '월별 시간PR': r['hour_pr_auc'], '월별 날짜정밀도@0.3': r['day_precision'], '월별 날짜재현율@0.3': r['day_recall']}
    if name == '+날씨 전체':
        bt = test.assign(p=p).groupby('date').agg(y=('is_surplus', 'max'), p=('p', 'max'))
        bt['m'] = bt.index.to_period('M')
        print('\n월별 재학습(+날씨 전체): 실제 잉여일의 평균 예측확률')
        print(bt[bt.y == 1].groupby('m')['p'].mean().round(2).to_string())
print('\n', pd.DataFrame(rows).T.round(3).to_string())

# 3) 기상청 단기예보에 있는 형태로만 (일사 없음, 구름은 하늘상태 3단계)
t['sky'] = pd.cut(t['om_cloud_mid'], [-1, 5, 8, 10], labels=[1, 3, 4]).astype(float)
t['rain_flag'] = (t['om_rain'] >= 1).astype(int)
train, test = t[t.date < '2026-01-01'], t[t.date >= '2026-01-01']
fc_cols = base + ['sky', 'om_temp', 'om_wind_mid', 'om_wind_night', 'rain_flag']
s, r, _ = run(fc_cols)
print('\n예보형 변수만(하늘상태·기온·풍속·강수, 일사 제외): 고정 날짜PR %.3f / 월별 날짜PR %.3f / 고정 시간PR %.3f / 월별 시간PR %.3f'
      % (s['day_pr_auc'], r['day_pr_auc'], s['hour_pr_auc'], r['hour_pr_auc']))
m = T.new_model().fit(train[base + wcols], train.is_surplus)
from sklearn.inspection import permutation_importance
imp = permutation_importance(m, test[base + wcols], test.is_surplus, scoring='average_precision', n_repeats=3, random_state=0)
print('\n변수 중요도(시험 기간, 날씨 전체 모델):')
print(pd.Series(imp.importances_mean, index=base + wcols).sort_values(ascending=False).head(8).round(3).to_string())
