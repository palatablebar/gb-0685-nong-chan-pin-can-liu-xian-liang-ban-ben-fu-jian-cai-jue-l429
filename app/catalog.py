import csv,hashlib,io,json
from collections import defaultdict
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
from app import store
from app.errors import DomainError
from app.modules.m1_ingest.decode import decode

HEADER=['id','product','analyte','start','end','limit_mgkg','methods']
SEED=Path(__file__).resolve().parents[1]/'sample_data'/'limits.csv'

def ensure(db):
    db.execute('CREATE TABLE IF NOT EXISTS catalogs (id TEXT PRIMARY KEY, body TEXT NOT NULL, pins TEXT NOT NULL DEFAULT "{}", note TEXT NOT NULL DEFAULT "", created_at TEXT NOT NULL)')

def parse_text(text):
    reader=csv.DictReader(io.StringIO(text,newline=''))
    if reader.fieldnames is None or [h.strip().lstrip('\ufeff') for h in reader.fieldnames]!=HEADER:
        raise DomainError('CATALOG','目录表头必须是 '+','.join(HEADER))
    rows=[];seen=set()
    for line,row in enumerate(reader,2):
        if None in row:raise DomainError('CATALOG','目录第%d行列数不齐'%line)
        item={k:(row.get(k) or '').strip() for k in HEADER}
        if not all(item.values()):raise DomainError('CATALOG','目录第%d行存在空字段'%line)
        if item['id'] in seen:raise DomainError('CATALOG','目录标准号重复: '+item['id'])
        seen.add(item['id'])
        try:
            if not date.fromisoformat(item['start'])<date.fromisoformat(item['end']):raise ValueError
        except ValueError:raise DomainError('CATALOG','目录第%d行生效区间无效'%line)
        try:
            if Decimal(item['limit_mgkg'])<=0:raise InvalidOperation
        except InvalidOperation:raise DomainError('CATALOG','目录第%d行限量无效'%line)
        rows.append(item)
    if not rows:raise DomainError('CATALOG','目录为空')
    return rows

def find_overlaps(rows):
    groups=defaultdict(list)
    for r in rows:groups[(r['product'],r['analyte'])].append(r)
    out=[]
    for (product,analyte),items in sorted(groups.items()):
        days=defaultdict(set)
        for r in items:
            day=date.fromisoformat(r['start']);end=date.fromisoformat(r['end'])
            while day<end:days[day.isoformat()].add(r['id']);day+=timedelta(1)
        for day_iso,ids in sorted(days.items()):
            if len(ids)>1:out.append({'product':product,'analyte':analyte,'day':day_iso,'versions':sorted(ids)})
    return out

def validate_pins(rows,pins):
    ids={r['id'] for r in rows}
    overlapped={o['product']+'|'+o['analyte'] for o in find_overlaps(rows)}
    for key,standard_id in pins.items():
        if key.count('|')!=1:raise DomainError('ADJUDICATION','裁决键必须是 产品|项目')
        if standard_id not in ids:raise DomainError('ADJUDICATION','裁决指向不存在的标准版本')
        if key not in overlapped:raise DomainError('ADJUDICATION','裁决的产品项目不存在版本重叠')

def version_id(text,pins):
    return hashlib.sha256(text.encode()+json.dumps(pins,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:20]

def _record(db,cid,text,pins,note):
    db.execute('INSERT OR IGNORE INTO catalogs(id,body,pins,note,created_at) VALUES (?,?,?,?,?)',
        (cid,text,json.dumps(pins,sort_keys=True,ensure_ascii=False),note,datetime.now(timezone.utc).isoformat()))

def _flip(db,cid):
    db.execute("INSERT INTO meta(key,value) VALUES ('active_catalog',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(cid,))

def _ensure_seed(db):
    # 原始目录始终登记为首个版本，任何切换都不能把它冲掉。
    if db.execute("SELECT 1 FROM meta WHERE key='active_catalog'").fetchone() is None:
        text=SEED.read_text(encoding='utf-8-sig')
        cid=version_id(text,{})
        _record(db,cid,text,{},'初始目录')
        _flip(db,cid)

def activate(content,note='',pins=None):
    if isinstance(content,str):content=content.encode()
    if len(content)>2_000_000:raise DomainError('SIZE','目录超过2MB',413)
    if not isinstance(note,str):raise DomainError('NOTE','目录备注必须是文本')
    pins=pins or {}
    if not isinstance(pins,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in pins.items()):
        raise DomainError('ADJUDICATION','裁决必须是 产品|项目 到 标准号 的映射')
    text,_=decode(content)
    rows=parse_text(text)
    validate_pins(rows,pins)
    cid=version_id(text,pins);overlaps=find_overlaps(rows)
    # 版本登记与生效指针在同一事务：中断即回滚，旧版继续生效。
    with store.connection() as db:
        ensure(db)
        _ensure_seed(db)
        created=db.execute('SELECT 1 FROM catalogs WHERE id=?',(cid,)).fetchone() is None
        _record(db,cid,text,pins,note)
        _flip(db,cid)
    return cid,overlaps,created

def snapshot():
    with store.connection() as db:
        ensure(db)
        _ensure_seed(db)
        row=db.execute("SELECT c.id,c.body,c.pins FROM catalogs c JOIN meta m ON m.key='active_catalog' AND m.value=c.id").fetchone()
        return row['id'],parse_text(row['body']),json.loads(row['pins'])

def history():
    with store.connection() as db:
        ensure(db)
        active=db.execute("SELECT value FROM meta WHERE key='active_catalog'").fetchone()
        rows=db.execute('SELECT id,pins,note,created_at FROM catalogs ORDER BY rowid').fetchall()
    current=active['value'] if active else None
    return [{'id':r['id'],'pins':json.loads(r['pins']),'note':r['note'],'created_at':r['created_at'],'active':r['id']==current} for r in rows]
