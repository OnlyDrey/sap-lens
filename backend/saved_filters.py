"""Local, bounded saved investigations. Unknown schema definitions are retained."""
import json
import threading
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import HTTPException
from config import config_dir, atomic_write

lock = threading.RLock()
MAX_BYTES = 1_000_000


def read():
    path = config_dir() / 'saved-filters.json'
    if not path.exists(): return []
    try:
        if path.stat().st_size > MAX_BYTES: raise ValueError()
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('items'), list): raise ValueError()
        if len(data['items']) > 250: raise ValueError()
        for item in data['items']:
            if not isinstance(item, dict) or not all(isinstance(item.get(k),str) for k in ('id','name','view','created','modified')) or not isinstance(item.get('filters'),dict) or type(item.get('filter_schema')) != int: raise ValueError()
        if len({i['id'] for i in data['items']}) != len(data['items']): raise ValueError()
        return data['items']
    except (OSError, ValueError, TypeError):
        raise HTTPException(409, 'Saved filters are unreadable or unsupported. The original file has been preserved; restore a local backup.')


def write(items):
    content = json.dumps(dict(schema_version=1,items=items),ensure_ascii=False).encode('utf-8')
    if len(content)>MAX_BYTES: raise HTTPException(422,'Saved filters exceed the local storage limit.')
    try: atomic_write(config_dir() / 'saved-filters.json',content)
    except OSError: raise HTTPException(409,'Saved filters could not be saved; the previous file is retained.')


def save(name, view, filters, identifier='', expected='', rename=False):
    with lock:
        items=read()
        previous=next((i for i in items if i['id']==identifier),None)
        if identifier and previous is None: raise HTTPException(404,'Saved filter no longer exists.')
        if previous and previous['modified']!=expected: raise HTTPException(409,'Saved filter changed. Reload before updating.')
        if previous and previous['view']!=view: raise HTTPException(422,'Cannot move a saved filter to another view.')
        if any(i['view']==view and i['name'].casefold()==name.casefold() and i['id']!=identifier for i in items): raise HTTPException(409,'A filter with this name already exists in this view.')
        if not previous and len(items)>=250: raise HTTPException(422,'The 250 saved-filter limit has been reached.')
        stamp=datetime.now(timezone.utc).isoformat()
        entry=dict(id=identifier or uuid4().hex,name=name,view=view,filters=filters,filter_schema=1,created=previous['created'] if previous else stamp,modified=stamp)
        if rename:
            if previous is None: raise HTTPException(422,'Select an existing filter to rename.')
            entry={**previous,'name':name,'modified':stamp}
        write([i for i in items if i['id']!=identifier]+[entry])
        return entry
