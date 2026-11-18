"""Stable attribution without turning a passwordless desktop profile into authentication."""
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import threading
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ConfigDict, Field, model_serializer
from config_models import StrictModel
from config import atomic_write, config_dir

IDENTITY = ContextVar('sap_lens_identity_snapshot', default=None)
MODE = ContextVar('sap_lens_identity_mode', default=None)
lock = threading.RLock()


class ActorSnapshot(StrictModel):
    model_config=ConfigDict(extra='forbid',validate_default=True,frozen=True)
    id: str = Field(pattern=r'^[a-f0-9]{32}$')
    username: str = Field(default='', max_length=100)
    display_name: str = Field(min_length=1, max_length=120)
    provenance: Literal['server-session','desktop-local']


class IdentityRecorded(StrictModel):
    actor_identity: ActorSnapshot | None = None

    @model_serializer(mode='wrap')
    def preserve_legacy(self, handler):
        result = handler(self)
        if self.actor_identity is None:
            result.pop('actor_identity',None)
        return result


def profile(display_name=None, revision=None, initial='Local reviewer'):
    path = config_dir() / 'reviewer-profile.json'
    with lock:
        if path.is_symlink() or path.is_junction():
            raise HTTPException(409,'Local reviewer profile is linked. Existing profile was preserved.')
        if path.exists():
            try:
                with path.open('rb') as stream: raw=stream.read(8193)
                if len(raw)>8192: raise ValueError()
                data=json.loads(raw)
                if data['version']!=1 or type(data['revision']) is not int or data['revision']<0:raise ValueError()
                ActorSnapshot.model_validate(data['identity'])
                if data['identity']['provenance']!='desktop-local':raise ValueError()
            except (ValueError,OSError,KeyError,TypeError):
                raise HTTPException(409,'Local reviewer profile is unreadable. Restore the profile; it was not reset.') from None
        else:
            identity=ActorSnapshot(id=uuid4().hex,display_name=initial.strip() or 'Local reviewer',provenance='desktop-local')
            data=dict(version=1,revision=0,identity=identity.model_dump())
        if display_name is not None:
            if revision!=data['revision']:raise HTTPException(409,'Reviewer profile changed. Reload before saving.')
            if not isinstance(display_name,str) or not 1<=len(display_name.strip())<=120:raise HTTPException(422,'Use a display name of 1–120 characters.')
            data['identity']['display_name']=display_name.strip();data['revision']+=1
            data['modified']=datetime.now(timezone.utc).isoformat()
        if not path.exists() or display_name is not None:
            atomic_write(path,json.dumps(data,ensure_ascii=False).encode('utf-8'))
        return data


def snapshot(fallback=''):
    identity=IDENTITY.get()
    if identity is not None:return ActorSnapshot.model_validate(identity).model_dump()
    if MODE.get()=='desktop':return profile()['identity']
    return None


def name(fallback=''):
    value=snapshot(fallback)
    return (value['username'] if value['provenance']=='server-session' else value['display_name']) if value else fallback
