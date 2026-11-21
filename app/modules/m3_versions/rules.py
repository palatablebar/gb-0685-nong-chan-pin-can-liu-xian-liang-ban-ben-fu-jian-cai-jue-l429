from app.modules.m3_versions.standards import choose
from app import catalog
from app.errors import DomainError
from decimal import Decimal

def apply(state):
    snap=state.pop('_catalog',None)
    if snap is None:snap=catalog.snapshot()[1:]
    limits,pins=snap
    reports=[];bad=[];applied={}
    for r in state['rows']:
        try:
            if r['reported']<r['sampled'] or Decimal(str(r['lod']))<=0:raise DomainError('RANGE','报告日期或检出限无效')
            report=dict(r);chosen=choose(r,limits,pins);report.update(chosen)
            if chosen['adjudicated']:
                key=(r['product'],r['analyte'],chosen['standard_id']);applied.setdefault(key,set()).add(r['sampled'])
            reports.append(report)
        except DomainError as e:bad.append((r,e.code))
    lines={r['_line'] for r,_ in bad};state['rows']=[r for r in state['rows'] if r['_line'] not in lines]
    for r,c in bad:state['quarantine'].append({'line':r['_line'],'id':r['id'],'code':c,'raw':r['_raw']})
    state['adjudication']={'catalog_pins':pins,
        'pins_applied':[{'product':k[0],'analyte':k[1],'standard_id':k[2],'sampled':sorted(v)} for k,v in sorted(applied.items())]}
    state['reports']=reports;return state
