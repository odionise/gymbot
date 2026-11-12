"""Admin program access uses signed actors and never grants user search to others."""

from test_replacement_http import client, signed_header  # noqa: F401


def test_only_named_admin_can_search_and_edit_other_programs(client, database, clock):
    admin = signed_header(5540948403, clock)
    owner = signed_header(833001, clock, username='synthetic_lifter')
    stranger = signed_header(833002, clock)
    assert client.get('/api/me', headers=admin).json()['is_admin'] is True
    assert client.get('/api/me', headers=owner).json()['is_admin'] is False
    client.get('/api/me', headers=owner)
    search = client.get('/api/admin/users?q=lifter', headers=admin)
    assert search.status_code == 200
    assert [item['telegram_id'] for item in search.json()] == [833001]
    whole_list = client.get('/api/admin/users', headers=admin)
    assert whole_list.status_code == 200
    assert {item['telegram_id'] for item in whole_list.json()} >= {5540948403, 833001}
    assert client.get('/api/admin/users', headers=stranger).status_code == 403
    assert client.get('/api/admin/users?q=lifter', headers=stranger).status_code == 403
    target = {'X-Admin-Target-User-Id': '833001'}
    assert client.get('/api/templates', headers={**stranger, **target}).status_code == 403
    created = client.post('/api/templates', headers={**admin, **target}, json={
        'name': 'Программа подопечного', 'muscle_group': 'Грудь', 'weekday': 1, 'send_time': '09:00',
    })
    assert created.status_code == 200
    template_id = created.json()['id']
    movement = client.post('/api/movements', headers={**admin, **target}, json={
        'name': 'Синтетический жим', 'kind': 'strength', 'primary_group': 'Грудь',
    })
    assert movement.status_code == 200
    assert client.get('/api/movements', headers=owner).json()[0]['id'] == movement.json()['id']
    exercise = client.post(f'/api/templates/{template_id}/exercises', headers={**admin, **target}, json={
        'name': 'Синтетический жим', 'movement_id': movement.json()['id'],
        'medium_weight': 30, 'sets_count': 3, 'weight_step': 2.5, 'rep_min': 6, 'rep_max': 12,
    })
    assert exercise.status_code == 200
    assert client.get('/api/templates', headers=owner).json()[0]['exercises'][0]['id'] == exercise.json()['id']
    assert client.get('/api/movements', headers={**stranger, **target}).status_code == 403
    assert len(client.get('/api/templates', headers=owner).json()) == 1
    assert client.get('/api/templates', headers=admin).json() == []
    assert client.put(f'/api/templates/{template_id}', headers=stranger, json={
        'name': 'Чужое изменение', 'muscle_group': 'Грудь', 'weekday': 2, 'send_time': '09:00',
    }).status_code == 404
    assert client.put(f'/api/templates/{template_id}', headers={**admin, **target}, json={
        'name': 'Новый план', 'muscle_group': 'Грудь', 'weekday': 2, 'send_time': '09:00',
    }).status_code == 200
    assert client.get('/api/templates', headers=owner).json()[0]['name'] == 'Новый план'
    assert client.get('/api/templates', headers={**admin, 'X-Admin-Target-User-Id': '833002'}).json() == []
