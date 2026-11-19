"""실제 재현된 추천·결측·사전 예보 평가 오류의 회귀 검사. 외부 API를 사용하지 않는다."""
from datetime import datetime, date, timedelta, timezone
import os
import time

import pandas as pd
import pytest

import tools
import features
import predict
from calendar_link import pick_window
from time_utils import now_kst, as_kst


@pytest.fixture
def fixed_forecast(monkeypatch):
    today = date(2026, 11, 16)  # 월요일
    monkeypatch.setattr(tools, 'today_kst', lambda: today)
    monkeypatch.setattr(tools, 'now_kst', lambda: datetime(2026, 11, 16, 7, 30))
    def fc(start, days, **kwargs):
        return pd.DataFrame([
            {'date': d, 'hour': h, 'prob': 0.9 if 11 <= h <= 15 else 0.01,
             'model_used': 'calendar', 'trend_available': False}
            for d in pd.date_range(start, periods=days) for h in range(1, 25)])
    monkeypatch.setattr(predict, 'forecast', fc)
    return today


def test_non_reservable_schedule_applies_to_requested_alternative_and_calendar(fixed_forecast):
    r = tools.plan_appliance_use('음식물처리기', day='내일', start_hour=10, end_hour=15,
                                away_start=9, away_end=18)
    assert r['requested_window_best'] is None
    assert r['alternatives']
    for w in r['best_windows'] + r['alternatives']:
        assert w['weekday'] in ('토', '일') or w['end_hour'] <= 9 or w['start_hour'] >= 18
    w = pick_window([{'tool': 'plan_appliance_use', 'result': r}])
    assert w and (date.fromisoformat(w['date']).weekday() >= 5 or w['end_hour'] <= 9 or w['start_hour'] >= 18)


def test_ev_must_finish_before_returning_or_departing(fixed_forecast):
    r = tools.plan_appliance_use('전기차', day='내일', battery_percent=40, away_start=9, away_end=18)
    assert r['schedule']['while_away']
    for w in r['schedule']['while_away']:
        assert 9 <= w['start_hour'] < w['end_hour'] <= 18
    for w in r['schedule']['at_home']:
        assert w['end_hour'] <= 9 or w['start_hour'] >= 18


def test_calendar_rejects_invalid_candidate_in_trace(fixed_forecast):
    r = tools.plan_appliance_use('음식물처리기', day='내일', away_start=9, away_end=18)
    r['requested_window_best'] = {'date':'2026-11-17','weekday':'화','start_hour':10,'end_hour':14,'level':'높음'}
    w = pick_window([{'tool': 'plan_appliance_use', 'result': r}])
    assert w['date'] != '2026-11-17' or w['end_hour'] <= 9 or w['start_hour'] >= 18


def test_reservation_and_weekends_remain_usable(fixed_forecast):
    r = tools.plan_appliance_use('세탁기', day='내일', start_hour=10, end_hour=15, away_start=9, away_end=18)
    assert r['requested_window_best']['start_hour'] >= 10
    r = tools.plan_appliance_use('음식물처리기', day='2026-11-21', start_hour=10, end_hour=15, away_start=9, away_end=18)
    assert r['requested_window_best']


def test_collector_preserves_missing_price_and_loader_excludes_legacy_zero(tmp_path, monkeypatch):
    import collect_smp
    monkeypatch.setattr(collect_smp, '_fetch_chunk', lambda *args: [
        {'date':'2026-11-16','hour':1,'smp':float('nan')},
        {'date':'2026-11-16','hour':2,'smp':0},
        {'date':'2026-11-16','hour':3,'smp':100}])
    result = collect_smp.collect(date(2026,11,16), date(2026,11,16))
    assert pd.isna(result.iloc[0]['is_surplus'])
    result.loc[0,'is_surplus'] = 0  # 기존 잘못된 파일도 다시 읽을 때 제거
    path = tmp_path/'labels.csv';result.to_csv(path,index=False)
    monkeypatch.setattr(features,'SMP_HOURLY_CSV',path)
    lab = features.load_labels()
    assert list(lab['hour']) == [2,3]
    assert list(lab['is_surplus']) == [1,0]


def labels(start='2026-10-01', days=35):
    return pd.DataFrame([{'date':d,'hour':h,'is_surplus':0}
                         for d in pd.date_range(start,periods=days) for h in range(1,25)])


def test_missing_recent_days_and_hours_are_not_zero():
    history = labels()
    target = pd.DataFrame({'date':[pd.Timestamp('2026-11-04')], 'hour':[12]})
    assert features.add_recent_trend(target,history)['recent_surplus_days'].iloc[0] == 0
    history = history[~((history['date']==pd.Timestamp('2026-10-25')) & (history['hour']==12))]
    row = features.add_recent_trend(target,history).iloc[0]
    assert pd.isna(row['recent_surplus_days']) and pd.isna(row['recent_surplus_hours_same_hour'])
    future = pd.DataFrame({'date':[pd.Timestamp('2026-12-04')], 'hour':[12]})
    row = features.add_recent_trend(future,history).iloc[0]
    assert pd.isna(row['recent_surplus_days']) and pd.isna(row['recent_surplus_hours_same_hour'])


@pytest.fixture
def evaluation_files(tmp_path, monkeypatch):
    monkeypatch.setattr(tools,'DATA',tmp_path)
    monkeypatch.setattr(tools,'PREDICTION_LOG',tmp_path/'log.csv')
    return tmp_path


def log_rows(prob=0.1, issued='2026-10-31T10:00:00+00:00'):
    return [{'date':'2026-11-01','hour':h,'prob':prob,'issued_at':issued} for h in range(1,25)]


def test_evaluation_rejects_late_records_and_uses_earlier_forecast(evaluation_files,monkeypatch):
    lab = labels('2026-11-01',1);lab.loc[lab['hour']==12,'is_surplus']=1
    monkeypatch.setattr(tools,'load_labels',lambda:lab)
    pd.DataFrame(log_rows() + log_rows(0.9,'2026-11-03T10:00:00')).to_csv(evaluation_files/'log.csv',index=False)
    r=tools.check_past_forecast('2026-11-01','2026-11-01')
    assert r['days'][0]['max_prob']==0.1
    assert r['days'][0]['actual_surplus'] is True
    assert r['missed_surplus_days']==1


@pytest.mark.parametrize('kind',['unknown','partial_actual','late_only','partial_prediction','invalid_issue'])
def test_evaluation_excludes_unverifiable_days(evaluation_files,monkeypatch,kind):
    lab=labels('2026-11-01',1)
    if kind=='unknown':lab=labels('2026-10-31',1)
    if kind=='partial_actual':lab=lab.iloc[:23]
    rows=log_rows()
    if kind=='late_only': rows=log_rows(0.9,'2026-11-03T10:00:00')
    if kind=='partial_prediction':rows=rows[:23]
    if kind=='invalid_issue':rows=log_rows(0.9,'broken')
    monkeypatch.setattr(tools,'load_labels',lambda:lab)
    pd.DataFrame(rows).to_csv(evaluation_files/'log.csv',index=False)
    r=tools.check_past_forecast('2026-11-01','2026-11-01')
    assert r.get('error') and r['days']==[]


def test_kst_independent_of_host_timezone(monkeypatch):
    try:
        with monkeypatch.context() as m:
            m.setenv('TZ','UTC')
            if hasattr(time,'tzset'):time.tzset()
            reference=datetime.now(timezone(timedelta(hours=9))).replace(tzinfo=None)
            assert abs((now_kst()-reference).total_seconds()) < 2
            from collect_weather import _latest_base, _mid_tmfc
            utc=datetime(2026,11,16,23,tzinfo=timezone.utc)
            assert as_kst(utc)==datetime(2026,11,17,8)
            assert _latest_base(utc)==('20261117','0500')
            assert _mid_tmfc(utc)=='202611170600'
    finally:
        if hasattr(time,'tzset'):time.tzset()


def test_old_labels_status_and_forecast_warning(fixed_forecast,monkeypatch):
    monkeypatch.setattr(tools,'load_labels',lambda:labels('2026-10-01',1))
    s=tools.data_status()
    assert s['labels_stale'] and s['label_last_date']=='2026-10-01'
    assert s['label_warning']
    r=tools.forecast_surplus(1,start='2026-11-17')
    assert r['warnings'] and not r['forecast'][0]['trend_available']


def test_boiler_conversion_preserves_living_schedule(fixed_forecast):
    r=tools.plan_appliance_use('보일러',fuel='전기',day='내일',start_hour=10,end_hour=15,away_start=9,away_end=18)
    assert r['schedule']['away_start']==9
    assert r['requested_window_best'] is None


def test_empty_history_keeps_unknown_recent_trend():
    frame=pd.DataFrame({'date':[pd.Timestamp('2026-11-17')],'hour':[12]})
    r=features.add_recent_trend(frame,labels().iloc[:0])
    assert r['recent_surplus_days'].isna().all() and r['recent_surplus_hours_same_hour'].isna().all()


def test_recommendation_does_not_start_in_elapsed_part_of_hour(fixed_forecast):
    r=tools.plan_appliance_use('세탁기',day='오늘',start_hour=7,end_hour=10)
    assert r['requested_window_best']['start_hour']==8


def test_desired_time_does_not_disable_saved_away_schedule():
    import user_profile as up
    import agent
    profile={**up.empty(),'work_start':9,'work_end':18}
    question='내일 10시부터 15시 사이 음식물처리기 돌릴래'
    for name,args in [up.apply_defaults([('plan_appliance_use',{'appliance':'음식물처리기'})],question,profile)[0],
                      agent._personalized_tool_inputs('plan_appliance_use',{'appliance':'음식물처리기'},question,profile)]:
        assert args['away_start']==9 and args['away_end']==18
    name,args=agent._personalized_tool_inputs('plan_appliance_use',{'appliance':'음식물처리기','away_start':10,'away_end':16},'10시부터16시까지외출',profile)
    assert args['away_start']==10 and args['away_end']==16


@pytest.mark.parametrize('question,expected',[
    ('내일 10시부터 15시 사이에 음식물처리기 돌릴래',(10,15)),
    ('오후 1시부터 3시까지 세탁기',(13,15)),
    ('9시 출근 18시 퇴근, 10시부터 15시 사이에 세탁기',(10,15)),
    ('10시부터 16시까지 외출, 저녁에 충전',(18,22)),
    ('외출은 10시부터 16시까지, 저녁에 충전',(18,22)),
])
def test_time_range_is_not_confused_with_absence(question,expected):
    import agent
    assert agent._guess_time(question)==expected


@pytest.mark.parametrize('percent',[80,90,100])
def test_ev_above_target_does_not_create_unnecessary_charging(percent):
    import agent
    r=tools.plan_appliance_use('전기차',battery_percent=percent)
    assert r['charging_needed'] is False and not r['best_windows']
    assert pick_window([{'tool':'plan_appliance_use','result':r}]) is None
    answer=agent._plan_text(r)
    assert '추가 충전이 필요하지 않아' in answer and '10분 걸려' not in answer


def test_calendar_skips_expired_candidates(fixed_forecast):
    r=tools.plan_appliance_use('세탁기')
    trace=[{'tool':'plan_appliance_use','result':r}]
    assert pick_window(trace,now=datetime(2026,11,15)) is not None
    assert pick_window(trace,now=datetime(2026,12,1)) is None


def test_dashboard_does_not_bridge_missing_hours():
    from dashboard_view import best_windows
    frame=pd.DataFrame({'ts':pd.to_datetime(['2026-11-20 10:00','2026-11-20 12:00','2026-11-20 13:00']),
                        'prob':[.9,.9,.9]})
    assert best_windows(frame,hours=3)==[]


def test_disjoint_forecast_hours_are_not_described_as_continuous():
    assert tools._hours_text([11,12,15])=='10시~12시, 14시~15시'
