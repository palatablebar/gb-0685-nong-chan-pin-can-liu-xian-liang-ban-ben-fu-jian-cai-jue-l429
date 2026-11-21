from decimal import Decimal
from app import catalog
from app.errors import DomainError

def standards():
    return catalog.snapshot()[1]

def choose(row, limits, pins=None):
    candidates=[l for l in limits if l['product']==row['product'] and l['analyte']==row['analyte'] and l['start']<=row['sampled']<l['end']]
    adjudicated=False
    if len(candidates)!=1:
        # 生效期重叠时不静默选版：须由目录版本登记的裁决指定唯一依据。
        pin=(pins or {}).get(row['product']+'|'+row['analyte'])
        matched=[c for c in candidates if c['id']==pin]
        if pin and len(candidates)>1 and matched:
            candidates=matched;adjudicated=True
        else:raise DomainError('VERSION','采样日期的限量版本缺失或重叠')
    limit=candidates[0]
    if row['method'] not in limit['methods'].split('|'):raise DomainError('METHOD','检测方法不在标准适用范围')
    return {'standard_id':limit['id'],'limit':str(Decimal(limit['limit_mgkg'])),'methods':limit['methods'],'standard_start':limit['start'],'standard_end':limit['end'],'adjudicated':adjudicated}
