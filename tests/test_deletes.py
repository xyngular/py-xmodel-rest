from __future__ import annotations

import pytest
import requests
from random import randint
from .test_models import TestModel, TestFormatBodyModel


def get_objects_setup(requests_mock, get_object_count: int):
    original_objects = {'results': []}
    results = []
    for i in range(0, get_object_count):
        results.append(
            {
                'id': i,
                'account_id': i,
                'name': "Test" + str(i),
                'description': "TestObject" + str(i),
            }
        )

    original_objects['results'] = results

    requests_mock.get(
        'http://api/v1/my_cool_endpoint?limit=15000&APIKey=api_key_123&APISecret=api_secret_ABC',
        json=original_objects,
    )

    return TestModel.api.get()


def test_delete_obj(requests_mock):
    obj_count = 100
    objs_to_get = get_objects_setup(requests_mock, obj_count)
    random_object_index = randint(0, obj_count)

    delete_adapter = requests_mock.delete(
        f'http://api/v1/my_cool_endpoint/{random_object_index}?APIKey=api_key_123'
        f'&APISecret=api_secret_ABC',
        json={},
        status_code=200,
    )
    count = 0
    for obj in objs_to_get:
        if count == random_object_index:
            TestModel.api.client.delete_obj(obj)
            break
        count += 1

    assert delete_adapter.call_count == 1


def test_delete_obj_status_code_300(requests_mock):
    obj_to_get = []
    obj_to_get.extend(get_objects_setup(requests_mock, 1))

    delete_adapter = requests_mock.delete(
        'http://api/v1/my_cool_endpoint/0?APIKey=api_key_123&APISecret=api_secret_ABC',
        json={},
        status_code=300,
    )

    TestModel.api.client.delete_objs(obj_to_get)

    assert delete_adapter.call_count == 1
    assert obj_to_get[0].api.response_state.had_error is True


def test_delete_none_obj(requests_mock):
    obj_to_delete = None

    with pytest.raises(AttributeError):
        TestModel.api.client.delete_obj(obj_to_delete)


def test_delete_empty_obj(requests_mock):
    obj_to_delete = TestModel()
    delete_adapter = requests_mock.delete(
        'http://api/v1/my_cool_endpoint?APIKey=api_key_123&APISecret=api_secret_ABC',
        status_code=200,
    )

    TestModel.api.client.delete_obj(obj_to_delete)

    assert delete_adapter.call_count == 1


def test_delete_objs_via_post_format_body(requests_mock):
    obj_count = 100
    objs_to_get = []
    expected_post_body = []
    for x in range(obj_count):
        objs_to_get.append(TestFormatBodyModel({'id': x, 'name': str(x)}))
        expected_post_body.append({'id': x})

    delete_adapter = requests_mock.post(
        f'http://api/v1/my_cool_body_formatting_endpoint',
        json={},
        status_code=200,
    )
    TestFormatBodyModel.api.client.delete_objs(objs_to_get)

    assert delete_adapter.call_count == 1
    assert delete_adapter.last_request.json() == expected_post_body
