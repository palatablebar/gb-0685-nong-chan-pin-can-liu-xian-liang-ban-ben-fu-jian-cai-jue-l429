from pathlib import Path
import pytest
from app import catalog, store
from app.errors import DomainError
from app.modules.m3_versions.standards import choose
from app.modules.m7_archive.export_out import bundle
from app.workflow import load, run

SAMPLES = Path(__file__).resolve().parents[1] / 'sample_data'
PINS = {'苹果|P01': 'APL-P01-V2'}

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH', str(tmp_path / 't.db'))

def overlap_catalog():
    return (SAMPLES / 'limits_overlap.csv').read_bytes()

def test_overlap_detected(db):
    cid, overlaps, created = catalog.activate(overlap_catalog(), '2026下半年目录', PINS)
    assert created is True
    assert overlaps == [{'product': '苹果', 'analyte': 'P01', 'day': '2026-12-31', 'versions': ['APL-P01-V2', 'APL-P01-V3']}]

def test_overlap_day_ruled_old_basis(db):
    # 裁决：重叠日（2026-12-31）采样的在途批次按旧版出证
    cid, _, _ = catalog.activate(overlap_catalog(), '2026下半年目录', PINS)
    s = run(load('overlap_day.csv'), {})
    calc = {(c['sample_id'], c['analyte']): c for c in s['calculations']}
    assert calc['T001','P01']['standard'] == 'APL-P01-V2' and calc['T001','P01']['code'] == 'PASS' and calc['T001','P01']['adjudicated'] is True
    assert calc['T002','P01']['code'] == 'PASS'
    # 重叠日后新目录全面适用，方法范围与限量变化不漏
    assert calc['T003','P01']['standard'] == 'APL-P01-V3' and calc['T003','P01']['code'] == 'FAIL' and calc['T003','P01']['adjudicated'] is False
    # 项目结论、批次等级、封存标记共用同一工作台结果
    assert {g['batch']: g['code'] for g in s['reconcile']['grades']} == {'C101': 'PASS', 'C102': 'FAIL'}
    assert s['catalog_id'] == cid and s['manifest']['catalog_id'] == cid
    assert s['manifest']['adjudication']['catalog_pins'] == PINS
    assert s['manifest']['adjudication']['pins_applied'] == [{'product': '苹果', 'analyte': 'P01', 'standard_id': 'APL-P01-V2', 'sampled': ['2026-12-31']}]
    evidence = bundle(s)
    assert 'APL-P01-V2' in evidence and 'pins_applied' in evidence and s['archive']['ready'] is True

def test_overlap_day_ruled_new_basis(db):
    # 同一机制支持监管方要求从新的情形
    catalog.activate(overlap_catalog(), '从新', {'苹果|P01': 'APL-P01-V3'})
    s = run(load('overlap_day.csv'), {})
    calc = {(c['sample_id'], c['analyte']): c for c in s['calculations']}
    assert calc['T001','P01']['standard'] == 'APL-P01-V3' and calc['T001','P01']['code'] == 'FAIL' and calc['T001','P01']['adjudicated'] is True

def test_overlap_without_ruling_quarantined(db):
    # 未登记裁决不静默选版：重叠日采样行隔离，重叠日后仍按新版
    catalog.activate(overlap_catalog(), '无裁决')
    s = run(load('overlap_day.csv'), {})
    assert [q['code'] for q in s['quarantine']].count('VERSION') == 2
    calc = {(c['sample_id'], c['analyte']): c for c in s['calculations']}
    assert calc['T003','P01']['standard'] == 'APL-P01-V3' and calc['T003','P01']['code'] == 'FAIL'
    assert s['reconcile']['balanced'] is True

def test_old_catalog_misses_new_period(db):
    # 沿用旧目录：重叠日后采样无版可用，证明不能整份沿用旧目录
    s = run(load('overlap_day.csv'), {})
    assert any(q['code'] == 'VERSION' and q['id'] == '10005' for q in s['quarantine'])
    calc = {(c['sample_id'], c['analyte']): c for c in s['calculations']}
    assert calc['T001','P01']['standard'] == 'APL-P01-V2' and calc['T001','P01']['code'] == 'PASS' and calc['T001','P01']['adjudicated'] is False

def test_invalid_rulings_rejected(db):
    for pins in ({'苹果|P01': 'NOPE'}, {'苹果|P02': 'APL-P02-V1'}, {'苹果P01': 'APL-P01-V2'}, ['苹果|P01']):
        with pytest.raises(DomainError) as e:
            catalog.activate(overlap_catalog(), '坏裁决', pins)
        assert e.value.code == 'ADJUDICATION'
    cid, rows, pins = catalog.snapshot()
    assert pins == {} and [r['id'] for r in rows] == ['APL-P01-V1', 'APL-P01-V2', 'APL-P02-V1']

def test_invalid_catalog_rejected(db):
    before = catalog.snapshot()[0]
    bad_bodies = (
        'id,product\n1,2\n',
        'id,product,analyte,start,end,limit_mgkg,methods\nX,苹果,P01,2027-01-01,2026-01-01,0.1,LC-MS/MS\n',
        'id,product,analyte,start,end,limit_mgkg,methods\nX,苹果,P01,2026-01-01,2027-01-01,-0.1,LC-MS/MS\n',
        'id,product,analyte,start,end,limit_mgkg,methods\nX,苹果,P01,2026-01-01,2027-01-01,0.1,LC-MS/MS\nX,苹果,P02,2026-01-01,2027-01-01,0.2,GC-MS\n',
    )
    for bad in bad_bodies:
        with pytest.raises(DomainError):
            catalog.activate(bad)
    assert catalog.snapshot()[0] == before and len(catalog.history()) == 1

def test_switch_interruption_keeps_old(db, monkeypatch):
    before = catalog.snapshot()[0]
    def boom(db_, cid):
        raise RuntimeError('中断')
    monkeypatch.setattr(catalog, '_flip', boom)
    with pytest.raises(RuntimeError):
        catalog.activate(overlap_catalog(), '中断的切换', PINS)
    assert catalog.snapshot()[0] == before
    assert len(catalog.history()) == 1

def test_rerun_same_catalog_reuses_batch(db):
    cid, _, _ = catalog.activate(overlap_catalog(), '2026下半年目录', PINS)
    a = run(load('overlap_day.csv'), {})
    store.save(a['run_id'], a)
    b = run(load('overlap_day.csv'), {})
    store.save(b['run_id'], b)
    assert a['run_id'] == b['run_id'] and len(store.history()) == 1
    again, _, created = catalog.activate(overlap_catalog(), '重复登记', PINS)
    assert again == cid and created is False and len(catalog.history()) == 2

def test_catalog_switch_creates_new_batch_and_keeps_records(db):
    s1 = run(load('overlap_day.csv'), {})
    store.save(s1['run_id'], s1)
    catalog.activate(overlap_catalog(), '2026下半年目录', PINS)
    s2 = run(load('overlap_day.csv'), {})
    store.save(s2['run_id'], s2)
    assert s1['run_id'] != s2['run_id'] and len(store.history()) == 2
    kept = store.get(s1['run_id'])
    assert kept['calculations'] == s1['calculations'] and kept['catalog_id'] == s1['catalog_id']
    versions = catalog.history()
    assert len(versions) == 2 and versions[0]['active'] is False and versions[1]['active'] is True
    again = run(load('overlap_day.csv'), {})
    assert again['run_id'] == s2['run_id'] and len(store.history()) == 2

def test_choose_unit_pin_resolution(db):
    _, rows, _ = catalog.snapshot()
    rows = rows + [dict(rows[1], id='APL-P01-V3', start='2026-12-31', end='2027-07-01', limit_mgkg='0.003')]
    row = {'product': '苹果', 'analyte': 'P01', 'sampled': '2026-12-31', 'method': 'LC-MS/MS'}
    with pytest.raises(DomainError):
        choose(row, rows)
    with pytest.raises(DomainError):
        choose(row, rows, {'苹果|P01': 'ABSENT'})
    chosen = choose(row, rows, {'苹果|P01': 'APL-P01-V2'})
    assert chosen['standard_id'] == 'APL-P01-V2' and chosen['adjudicated'] is True
    other_day = choose(dict(row, sampled='2026-08-01'), rows, {'苹果|P01': 'APL-P01-V2'})
    assert other_day['standard_id'] == 'APL-P01-V2' and other_day['adjudicated'] is False

def test_catalog_api_flow(client):
    text = overlap_catalog().decode()
    r = client.post('/api/catalog', json={'csv': text, 'note': '2026下半年目录', 'overlap_pins': PINS})
    body = r.get_json()
    assert r.status_code == 200 and body['created'] is True and body['overlaps'][0]['day'] == '2026-12-31'
    shown = client.get('/api/catalog').get_json()
    assert shown['active'] == body['active'] and shown['pins'] == PINS and shown['unresolved'] == []
    r = client.post('/api/runs', json={'csv': load('overlap_day.csv').decode()})
    s = r.get_json()
    assert r.status_code == 200 and s['manifest']['catalog_id'] == body['active']
    assert {g['batch']: g['code'] for g in s['reconcile']['grades']} == {'C101': 'PASS', 'C102': 'FAIL'}
    e = client.get('/api/archive/' + s['run_id'] + '/export.csv')
    assert e.status_code == 200 and 'APL-P01-V2' in e.data.decode('utf-8-sig')

def test_catalog_api_unresolved(client):
    client.post('/api/catalog', json={'csv': overlap_catalog().decode()})
    shown = client.get('/api/catalog').get_json()
    assert len(shown['unresolved']) == 1 and shown['unresolved'][0]['day'] == '2026-12-31'

def test_catalog_api_rejects_bad_payload(client):
    assert client.post('/api/catalog', json={'csv': 1}).status_code == 422
    assert client.post('/api/catalog', json={'csv': 'a,b\n1,2\n'}).status_code == 422
