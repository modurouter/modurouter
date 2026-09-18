from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from modurouter.auth import COOKIE, csrf_token, digest
from modurouter.config import get_settings
from modurouter.curriculum import TASKS
from modurouter.db import get_db, utcnow
from modurouter.learning import coaching_context
from modurouter.main import app
from modurouter.models import LearningSession, LoginSession, User
from sqlalchemy import select


@pytest_asyncio.fixture
async def learner(database):
    async with database.begin() as db:
        for name in ('learner', 'other'):
            user = User(google_sub=name, email='', display_name=name)
            db.add(user)
            await db.flush()
            db.add(LoginSession(user_id=user.id, token_hash=digest(name), csrf_hash=digest(csrf_token(name)), expires_at=utcnow()+timedelta(days=1)))
    async def override():
        async with database() as db:
            yield db
    app.dependency_overrides[get_db] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', cookies={COOKIE:'learner'}, headers={'Origin':get_settings().web_origin, 'X-CSRF-Token':csrf_token('learner')}) as client:
        yield client
    app.dependency_overrides.clear()


async def mutate(client, state, action='answer', answer='', request_id=None):
    return await client.post(f'/v1/learning/sessions/{state["id"]}', json={'revision':state['revision'], 'request_id':request_id or str(uuid4()), 'action':action, 'answer':answer})


@pytest.mark.parametrize('task', TASKS, ids=lambda task:task['id'])
async def test_all_activities_complete_resume_and_export(learner, task):
    catalog = (await learner.get('/v1/learning/catalog')).json()
    assert len(catalog['tasks']) == 9
    assert all('correct' not in step and 'explanation' not in step for item in catalog['tasks'] for step in item['steps'])
    state = (await learner.post(f'/v1/learning/tasks/{task["id"]}/session')).json()
    assert (await learner.post(f'/v1/learning/tasks/{task["id"]}/session')).json()['id'] == state['id']
    for step in task['steps']:
        answer = step['options'][step['correct']] if step['kind']=='choice' else step['example']
        response = await mutate(learner, state, answer=answer)
        assert response.status_code == 200, response.text
        state = response.json()
        assert (await learner.get(f'/v1/learning/sessions/{state["id"]}')).json() == state
    assert state['complete'] and state['completions'] == 1 and state['step'] == len(task['steps'])
    assert task['outcome'] in state['result']
    assert all(answer['answer'] in state['result'] for answer in state['answers'])
    assert (await mutate(learner, state, answer='중복 완료는 안 됩니다.')).status_code == 409
    restarted = (await mutate(learner, state, action='restart')).json()
    assert restarted['step'] == 0 and restarted['completions'] == 1 and not restarted['complete']
    assert restarted['previous_result'] == state['result']


async def test_wrong_answer_draft_hint_idempotency_and_stale_writes(learner):
    state = (await learner.post('/v1/learning/tasks/error-practice/session')).json()
    state = (await mutate(learner, state, answer='양변에서 2를 뺄 때')).json()
    assert state['step'] == 0 and state['feedback']['kind'] == 'retry' and not state['answers']
    assert (await mutate(learner, state, answer='조작한 선택지')).status_code == 422
    key = str(uuid4())
    correct = (await mutate(learner, state, answer='괄호를 풀 때', request_id=key)).json()
    assert (await mutate(learner, state, answer='괄호를 풀 때', request_id=key)).json() == correct
    assert (await mutate(learner, state, answer='괄호를 풀 때')).status_code == 409
    state = (await learner.post('/v1/learning/tasks/my-problem/session')).json()
    assert (await mutate(learner, state, answer='짧음')).status_code == 422
    draft = '내가 직접 푼 문제와 아직 풀지 못한 내용을 기록한다.'
    state = (await mutate(learner, state, action='draft', answer=draft)).json()
    assert state['draft'] == draft and not state['answers']
    state = (await mutate(learner, state, action='hint', answer=draft)).json()
    assert state['draft'] == draft and state['step'] == 0


async def test_ownership_csrf_conversation_and_deletion(learner, database):
    state = (await learner.post('/v1/learning/tasks/my-problem/session')).json()
    endpoint = f'/v1/learning/sessions/{state["id"]}'
    learner.headers.pop('X-CSRF-Token')
    assert (await mutate(learner, state, answer='내 풀이 내용을 적어 보았습니다.')).status_code == 403
    learner.cookies.set(COOKIE, 'other')
    learner.headers['X-CSRF-Token'] = csrf_token('other')
    assert (await learner.get(endpoint)).status_code == 404
    assert (await learner.get('/v1/learning/sessions')).json()['items'] == []
    assert (await learner.delete(endpoint)).status_code == 404
    assert (await learner.post(endpoint+'/conversation')).status_code == 404
    learner.cookies.set(COOKIE, 'learner')
    learner.headers['X-CSRF-Token'] = csrf_token('learner')
    draft = '괄호를 전개할 때 상수에 곱하는 것을 빠뜨렸다.'
    state = (await mutate(learner, state, action='draft', answer=draft)).json()
    cid = (await learner.post(endpoint+'/conversation')).json()['conversation_id']
    assert (await learner.post(endpoint+'/conversation')).json()['conversation_id'] == cid
    async with database() as db:
        row = await db.get(LearningSession, state['id'])
        context = await coaching_context(db, row.user_id, cid)
        assert draft in context and '내 문제로 복습' in context
        assert await coaching_context(db, 'other-id', cid) == ''
    assert (await learner.delete(f'/v1/conversations/{cid}')).status_code == 200
    assert (await learner.post(endpoint+'/conversation')).json()['conversation_id'] != cid
    assert (await learner.delete(endpoint)).status_code == 200
    assert (await learner.get(endpoint)).status_code == 404


async def test_account_erasure_removes_learning_answers(learner, database):
    await learner.post('/v1/learning/tasks/review-plan/session')
    assert (await learner.delete('/v1/me')).status_code == 200
    async with database() as db:
        assert await db.scalar(select(LearningSession)) is None


async def test_concurrent_answers_do_not_advance_twice(learner):
    import asyncio
    state = (await learner.post('/v1/learning/tasks/error-practice/session')).json()
    results = await asyncio.gather(*(mutate(learner, state, answer='괄호를 풀 때') for _ in range(2)))
    assert sorted(result.status_code for result in results) == [200, 409]
    saved = (await learner.get(f'/v1/learning/sessions/{state["id"]}')).json()
    assert saved['step'] == 1 and len(saved['answers']) == 1


async def test_outdated_record_can_be_deleted_and_restarted(learner, database):
    state = (await learner.post('/v1/learning/tasks/review-plan/session')).json()
    async with database.begin() as db:
        (await db.get(LearningSession, state['id'])).task_version = 999
    assert (await mutate(learner, state, action='draft', answer='저장 시도')).status_code == 409
    assert (await learner.delete(f'/v1/learning/sessions/{state["id"]}')).status_code == 200
    fresh = (await learner.post('/v1/learning/tasks/review-plan/session')).json()
    assert fresh['task_version'] == 1 and fresh['step'] == 0
