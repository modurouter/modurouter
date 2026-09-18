import pytest
import pytest_asyncio
import test_harness as harness_tests
from modurouter import admin, auth, harness, main
from modurouter.models import RuntimeSettings, User
from modurouter.router import sync_models
from modurouter.runtime_config import effective_settings
from pydantic import SecretStr
from sqlalchemy import select
from test_router import model

world = harness_tests.world
provider = harness_tests.provider

@pytest_asyncio.fixture
async def admin_world(world, database, monkeypatch):
    monkeypatch.setattr(auth.settings,'admin_username','operator')
    monkeypatch.setattr(auth.settings,'admin_password',SecretStr('admin-test-secret'))
    monkeypatch.setattr(admin,'settings',harness.settings)
    monkeypatch.setattr(main,'settings',harness.settings)
    async with database.begin() as db:
        user = await db.scalar(select(User).where(User.google_sub == 'test'))
        user.google_sub = 'admin:operator'
    yield world


async def test_admin_settings_require_admin_identity_and_csrf(world):
    client, _ = world
    assert (await client.get('/v1/admin/settings')).status_code == 403
    assert (await client.get('/v1/admin/models')).status_code == 403
    assert (await client.post('/v1/admin/models/refresh')).status_code == 403
    anonymous = await client.get('/v1/admin/settings',headers={'Cookie':''})
    assert anonymous.status_code == 401


async def test_admin_settings_persist_revision_conflicts_and_provider_state(admin_world,database):
    client, _ = admin_world
    assert (await client.get('/v1/me')).json()['admin']
    original = (await client.get('/v1/admin/settings')).json()
    assert original['revision'] == 0
    assert 'test-key' not in str(original) and 'api_key' not in str(original)
    policy = original['policy']
    policy['input_price_cap_usd_per_m'] = '2'
    policy['model_allowlist'] = ['test/b']
    body = {'revision':0,'policy':policy}
    no_csrf = await client.post('/v1/admin/settings',json=body,headers={'X-CSRF-Token':''})
    assert no_csrf.status_code == 403
    saved = await client.post('/v1/admin/settings',json=body)
    assert saved.status_code == 200
    assert saved.json()['revision'] == 1
    assert (await client.post('/v1/admin/settings',json=body)).status_code == 409
    async with database() as db:
        effective = await effective_settings(db,harness.settings)
        assert effective.model_allowlist == 'test/b'
        assert str(effective.input_price_cap_usd_per_m) == '2'
        assert (await db.get(RuntimeSettings,'routing')).updated_by is not None
    assert harness.settings.model_allowlist == 'test/a,test/b'
    policy['enabled_providers'] = ['zenmux']
    unconfigured = await client.post('/v1/admin/settings',json={'revision':1,'policy':policy})
    assert unconfigured.status_code == 422
    assert unconfigured.json()['code'] == 'PROVIDER_NOT_CONFIGURED'


async def test_saved_default_and_manual_restrictions_apply_to_real_runs(admin_world,provider):
    client, conversation = admin_world
    policy = (await client.get('/v1/admin/settings')).json()['policy']
    policy['default_routing'] = {'mode':'manual','provider':'openrouter','model_id':'test/b'}
    saved = await client.post('/v1/admin/settings',json={'revision':0,'policy':policy})
    assert saved.status_code == 200
    response = await client.post(f'/v1/conversations/{conversation}/runs',json={'message':'기본 모델로 답해 줘'})
    assert response.status_code == 200
    assert provider.calls == ['test/b']
    policy['default_routing'] = {'mode':'auto'}
    policy['allow_manual_selection'] = False
    assert (await client.post('/v1/admin/settings',json={'revision':1,'policy':policy})).status_code == 200
    retry = await client.post(f'/v1/conversations/{conversation}/runs',json={'message':'기본 모델로 답해 줘'})
    assert retry.json()['routing']['model_id'] == 'test/b'
    assert provider.calls == ['test/b']
    denied = await client.post(f'/v1/conversations/{conversation}/runs',headers={'Idempotency-Key':'manual-disabled'},json={
        'message':'질문','routing':{'mode':'manual','provider':'openrouter','model_id':'test/a'}})
    assert denied.status_code == 403
    catalog = (await client.get('/v1/models')).json()
    assert catalog['default_routing']['mode'] == 'auto'
    assert catalog['allow_manual_selection'] is False


async def test_admin_manual_allowlist_and_disabled_provider_block_new_requests(admin_world,provider):
    client, conversation = admin_world
    policy = (await client.get('/v1/admin/settings')).json()['policy']
    policy['manual_model_allowlist'] = ['openrouter::test/b']
    assert (await client.post('/v1/admin/settings',json={'revision':0,'policy':policy})).status_code == 200
    catalog = (await client.get('/v1/models')).json()
    assert [m['model_id'] for m in catalog['models']] == ['test/b']
    assert len((await client.get('/v1/admin/models')).json()['models']) == 2
    denied = await client.post(f'/v1/conversations/{conversation}/runs',json={
        'message':'질문','routing':{'mode':'manual','provider':'openrouter','model_id':'test/a'}})
    assert denied.status_code == 409
    policy['enabled_providers'] = []
    assert (await client.post('/v1/admin/settings',json={'revision':1,'policy':policy})).status_code == 200
    disabled = await client.post(f'/v1/conversations/{conversation}/runs',json={'message':'질문'})
    assert disabled.status_code == 503
    assert provider.calls == []


async def test_admin_budget_applies_to_premium_generation(admin_world,database,provider):
    client, conversation = admin_world
    class Catalog:
        async def list_models(self):
            return [model('test/premium','0.000003','0.000015')]
    async with database() as db:
        await sync_models(db,Catalog(),harness.settings)
    policy = (await client.get('/v1/admin/settings')).json()['policy']
    policy['user_daily_budget_usd'] = '0.001'
    assert (await client.post('/v1/admin/settings',json={'revision':0,'policy':policy})).status_code == 200
    body = {'message':'질문','routing':{'mode':'manual','provider':'openrouter','model_id':'test/premium'}}
    assert (await client.post(f'/v1/conversations/{conversation}/runs',json=body)).status_code == 200
    saved = (await client.post(f'/v1/conversations/{conversation}/runs',json=body)).json()
    assert saved['error_code'] == 'BUDGET_EXCEEDED'
    assert provider.calls == []
    assert (await client.get('/v1/usage')).json()['limit_usd'] == '0.001'


@pytest.mark.parametrize('change',[
    {'default_routing':{'mode':'manual'}},
    {'input_price_cap_usd_per_m':'NaN'},
    {'price_refresh_seconds':1000,'price_stale_seconds':100},
    {'model_allowlist':['invalid::model']},
    {'openrouter_api_key':'not-accepted'},
])
async def test_admin_invalid_policy_is_not_saved(admin_world,database,change):
    client, _ = admin_world
    policy = (await client.get('/v1/admin/settings')).json()['policy']
    result = await client.post('/v1/admin/settings',json={'revision':0,'policy':{**policy,**change}})
    assert result.status_code == 422
    async with database() as db:
        assert await db.get(RuntimeSettings,'routing') is None
