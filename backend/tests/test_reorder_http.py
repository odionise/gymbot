"""Reordering assignments changes the future plan without changing identities or snapshots."""

from test_replacement_http import api_program, client, seed_personal_movement, signed_header  # noqa: F401


def test_reorder_exercises_preserves_history_and_existing_workout(client, clock):
    headers, _movement, first = api_program(client, clock, user_id=920001)
    template = client.get('/api/templates', headers=headers).json()[0]
    template_id = template['id']
    exercise_ids = [first['id']]
    for position, name in enumerate(('Движение Б', 'Движение В'), start=1):
        movement = seed_personal_movement(920001, name)
        response = client.post(f'/api/templates/{template_id}/exercises', headers=headers, json={
            'name': name, 'movement_id': movement['id'], 'position': position,
            'medium_weight': 20, 'sets_count': 2, 'weight_step': 2.5, 'rep_min': 6, 'rep_max': 12,
        })
        assert response.status_code == 200
        exercise_ids.append(response.json()['id'])
    before = client.get('/api/templates', headers=headers).json()[0]
    identities = {item['id']: (item['slot_id'], item['history_id']) for item in before['exercises']}
    started = client.post(f'/api/templates/{template_id}/start', headers=headers)
    assert started.status_code == 200
    session_id = started.json()['id']
    old_order = [item['exercise_id'] for item in started.json()['exercises']]
    assert old_order == exercise_ids

    path = f'/api/templates/{template_id}/exercise-order'
    desired = [exercise_ids[2], exercise_ids[0], exercise_ids[1]]
    changed = client.put(path, headers=headers, json={'exercise_ids': desired})
    assert changed.status_code == 200
    assert [item['id'] for item in changed.json()['exercises']] == desired
    assert [item['position'] for item in changed.json()['exercises']] == [0, 1, 2]
    assert {item['id']: (item['slot_id'], item['history_id']) for item in changed.json()['exercises']} == identities
    assert [item['exercise_id'] for item in client.get(f'/api/sessions/{session_id}', headers=headers).json()['exercises']] == old_order

    assert client.put(path, headers=headers, json={'exercise_ids': desired[:2]}).status_code == 409
    assert client.put(path, headers=headers, json={'exercise_ids': [desired[0]] * 3}).status_code == 422
    other = signed_header(920002, clock)
    assert client.put(path, headers=other, json={'exercise_ids': desired}).status_code == 404
    assert [item['id'] for item in client.get('/api/templates', headers=headers).json()[0]['exercises']] == desired
