"""New profile and anatomy contracts on synthetic identities only."""

import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app import bot
from app.migrations import migrate
from app.models import User, WorkoutSession
from app.muscles import ALL_DETAILED_GROUPS, VOLUME_TARGET_GROUPS, volume_group
from test_replacement_http import client, signed_header  # noqa: F401


@pytest.mark.parametrize('factory_fixture', ['database', 'postgres_database'])
def test_profile_migration_from_six_preserves_existing_user(request, factory_fixture):
    factory = request.getfixturevalue(factory_fixture)
    with factory() as db:
        db.add(User(telegram_id=7501))
        db.commit()
        engine = db.bind
    with engine.begin() as connection:
        connection.execute(text('DROP INDEX IF EXISTS ix_users_telegram_username'))
        connection.execute(text('ALTER TABLE users DROP COLUMN sex'))
        connection.execute(text('ALTER TABLE users DROP COLUMN display_name'))
        connection.execute(text('ALTER TABLE users DROP COLUMN birth_date'))
        connection.execute(text('ALTER TABLE users DROP COLUMN telegram_username'))
        connection.execute(text('DELETE FROM schema_versions WHERE version = 7'))
        connection.execute(text('DELETE FROM schema_versions WHERE version = 8'))
    migrate(engine)
    migrate(engine)
    with engine.connect() as connection:
        assert connection.execute(text('SELECT MAX(version) FROM schema_versions')).scalar_one() == 8
        assert connection.execute(text('SELECT telegram_id, sex, display_name, birth_date FROM users')).one() == (7501, None, None, None)


def test_profile_is_owned_and_age_is_derived(client, clock):
    owner = signed_header(7301, clock)
    other = signed_header(7302, clock)
    initial = client.get('/api/me', headers=owner).json()
    assert initial['profile_complete'] is False
    assert initial['birth_date'] is None and initial['age'] is None
    data = {'sex': 'female', 'display_name': '  Анна  ', 'birth_date': '2000-01-02'}
    saved = client.put('/api/me/profile', json=data, headers=owner)
    assert saved.status_code == 200
    assert saved.json()['display_name'] == 'Анна'
    assert saved.json()['age'] == 26
    assert client.get('/api/me', headers=other).json()['profile_complete'] is False
    assert client.put('/api/me/profile', json={**data, 'birth_date': '2099-01-01'}, headers=owner).status_code == 422
    assert client.get('/api/me', headers=owner).json()['birth_date'] == '2000-01-02'
    edited = client.put('/api/me/profile', json={**data, 'sex': 'male', 'display_name': 'Иван'}, headers=owner)
    assert edited.json()['sex'] == 'male' and edited.json()['age'] == 26


def test_fine_anatomy_uses_coarse_volume_targets(client, clock):
    headers = signed_header(7303, clock)
    catalog = client.get('/api/muscle-groups', headers=headers).json()
    assert {'Спина', 'Ромбовидные', 'Камбаловидные', 'Верх груди', 'Пресс'} <= set(ALL_DETAILED_GROUPS)
    assert 'Ромбовидные' in catalog['Спина']
    targets = client.get('/api/muscle-targets', headers=headers).json()
    assert set(targets) == set(VOLUME_TARGET_GROUPS)
    assert 'Ромбовидные' not in targets
    assert volume_group('Ромбовидные') == 'Верх спины'
    assert volume_group('Камбаловидные') == 'Икры'
    assert volume_group('Верх груди') == 'Грудь'


def test_bot_collects_persistent_profile_before_plan(database, monkeypatch, clock):
    monkeypatch.setattr(bot, 'SessionLocal', database)
    monkeypatch.setattr(bot, 'get_settings', lambda: SimpleNamespace(public_url='https://synthetic.invalid'))
    telegram = SimpleNamespace(set_chat_menu_button=AsyncMock())

    def message(value=None):
        return SimpleNamespace(from_user=SimpleNamespace(id=7401, first_name='Тест'),
                               chat=SimpleNamespace(id=7401, type='private'), text=value, answer=AsyncMock())

    first = message('/start')
    asyncio.run(bot.start(first, telegram))
    assert 'Выберите пол' in first.answer.call_args.args[0]
    with database() as db:
        assert bot.today_replies(db, 7401)[0][0].startswith('Перед первой тренировкой')
        assert db.query(WorkoutSession).count() == 0
    for answer, expected in [('Женский', 'Как вас зовут'), ('Анна', 'Укажите дату рождения'),
                             ('02.01.2000', 'Анкета заполнена')]:
        reply = message(answer)
        asyncio.run(bot.profile_answer(reply))
        assert expected in reply.answer.call_args.args[0]
    with database() as db:
        user = db.get(User, 7401)
        assert (user.sex, user.display_name, user.birth_date) == ('female', 'Анна', date(2000, 1, 2))
