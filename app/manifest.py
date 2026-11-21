import hashlib,json,time
from datetime import datetime,timezone
from app.config import RULE_VERSION

def identity(content, parameters, catalog_id):
    raw = content + json.dumps(parameters,sort_keys=True,ensure_ascii=False).encode() + RULE_VERSION.encode() + catalog_id.encode()
    return hashlib.sha256(raw).hexdigest()[:20]

def manifest(content, parameters, elapsed, catalog_id, adjudication):
    return {'sha256':hashlib.sha256(content).hexdigest(),'rule_version':RULE_VERSION,
        'catalog_id':catalog_id,'adjudication':adjudication,
        'parameters':parameters,'elapsed_ms':round(elapsed*1000),
        'generated_at':datetime.now(timezone.utc).isoformat(),'timezone':'Asia/Shanghai'}
