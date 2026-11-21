import time,importlib,json,base64
from pathlib import Path
from app.config import MODULES
from app.errors import DomainError
from app.manifest import identity,manifest
from app import catalog

def load(sample):
    if sample not in ('dirty.csv','clean.csv','legacy.csv','overlap_day.csv'):raise DomainError('SAMPLE','样例名称无效')
    return (Path(__file__).resolve().parents[1]/'sample_data'/sample).read_bytes()

def run(content,parameters=None,stage=7):
    if len(content)>2_000_000:raise DomainError('SIZE','文件超过2MB',413)
    params=parameters or {}
    if not isinstance(params,dict):raise DomainError('PARAMETERS','参数必须是对象')
    start=time.monotonic();state=None
    # 一次运行固定一份目录快照：项目结论、批次等级与封存标记共用同一限定依据。
    cat_id,cat_rows,cat_pins=catalog.snapshot()
    for n,entry in enumerate(MODULES,1):
        if n>stage:break
        fn=importlib.import_module('app.modules.'+entry[0]+'.service').execute
        state=fn(content,params) if n==1 else fn(state)
        if n==1:state['_catalog']=(cat_rows,cat_pins)
    state.pop('_catalog',None)
    # Decimal values are serialized as strings before any storage or response.
    state=json.loads(json.dumps(state,default=str,ensure_ascii=False))
    state['catalog_id']=cat_id
    state['run_id']=identity(content,params,cat_id)
    state['manifest']=manifest(content,params,time.monotonic()-start,cat_id,state.get('adjudication',{'catalog_pins':{},'pins_applied':[]}))
    state['source_b64']=base64.b64encode(content).decode('ascii')
    if stage>=7:
        from app.modules.m7_archive.export_out import checksum
        state['archive']['sha256']=checksum(state)
    return state
