from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import current_admin
from .billing import admission_lock
from .config import get_settings
from .db import get_db, utcnow
from .errors import AppError
from .models import RuntimeSettings, User
from .providers import create_adapters
from .router import candidates, model_catalog, sync_models
from .runtime_config import RoutingPolicy, effective_settings

router = APIRouter(prefix='/v1/admin')
settings = get_settings()


class PolicyUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=0)
    policy: RoutingPolicy


async def settings_view(db):
    row = await db.get(RuntimeSettings, 'routing')
    effective = await effective_settings(db, settings)
    return {'revision': row.revision if row else 0,
            'policy': RoutingPolicy.from_settings(effective).model_dump(mode='json'),
            'updated_at': row.updated_at.isoformat() + 'Z' if row else None,
            'providers': [{'code': code, 'configured': code in settings.configured_providers}
                          for code in ('openrouter','zenmux','openai','upstage')]}


@router.get('/settings')
async def read_settings(user: User = Depends(current_admin), db: AsyncSession = Depends(get_db)):
    return await settings_view(db)


@router.post('/settings')
async def save_settings(body: PolicyUpdate, user: User = Depends(current_admin), db: AsyncSession = Depends(get_db)):
    user_id = user.id
    await db.commit()
    async with db.begin():
        await admission_lock(db)
        row = await db.get(RuntimeSettings, 'routing', with_for_update=True)
        if body.revision != (row.revision if row else 0):
            raise AppError('SETTINGS_CONFLICT', '다른 관리자가 설정을 변경했습니다. 최신 설정을 다시 불러온 뒤 저장해 주세요.', 409)
        if set(body.policy.enabled_providers) - set(settings.configured_providers):
            raise AppError('PROVIDER_NOT_CONFIGURED', 'API 키가 설정된 제공처만 활성화할 수 있습니다.', 422)
        effective = body.policy.apply(settings)
        if body.policy.default_routing.mode == 'manual':
            await candidates(db, effective, 0, routing=body.policy.default_routing)
        if row is None:
            row = RuntimeSettings(key='routing', revision=0, values={})
            db.add(row)
        row.values = body.policy.model_dump(mode='json')
        row.revision += 1
        row.updated_by = user_id
        row.updated_at = utcnow()
        await db.flush()
    return await settings_view(db)


@router.get('/models')
async def models(user: User = Depends(current_admin), db: AsyncSession = Depends(get_db)):
    effective = await effective_settings(db, settings)
    # Operators must also see disabled providers and models to enable them.
    visible = effective.model_copy(update={'enabled_providers':None, 'manual_model_allowlist':None})
    return await model_catalog(db, visible)


@router.post('/models/refresh')
async def refresh_models(user: User = Depends(current_admin), db: AsyncSession = Depends(get_db)):
    effective = await effective_settings(db, settings)
    await db.commit()
    adapters = create_adapters(effective.model_copy(update={'enabled_providers':None}))
    results = []
    try:
        for code, adapter in adapters.items():
            try:
                count = await sync_models(db, adapter, effective)
                results.append({'provider':code, 'count':count, 'error':None})
            except Exception:
                results.append({'provider':code, 'count':0, 'error':'PRICE_REFRESH_FAILED'})
    finally:
        for adapter in adapters.values():
            await adapter.close()
    return {'results':results}
