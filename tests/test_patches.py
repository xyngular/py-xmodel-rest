from __future__ import annotations

import pytest
import requests_mock
import math
from .test_models import TestModel, TestMultipleResultsPathModel
from unittest.mock import patch
import math


@pytest.fixture
def mocked_resp():
    with requests_mock.Mocker() as mocker:
        yield mocker


def get_new_object_setup():
    obj = TestModel()
    obj.account_id = 2
    obj.name = "New Test"
    obj.description = "TestNewObject"

    return [obj]


def get_object_setup(mocked_resp):
    original_object = {
        'results': [
            {
                'id': 1,
                'account_id': 1,
                'name': "Test",
                'description': "TestObject",
                'excluded_field': "excluded value",
                'read_only_field': "read only value"
            }
        ]
    }
    mocked_resp.get(
        'http://api/v1/my_cool_endpoint/1?limit=1&APIKey=api_key_123&APISecret=api_secret_ABC',
        json=original_object
    )

    return [TestModel.api.get_via_id(1)]


# THE FOLLOWING TESTS DO NOT HAVE THE CLIENT SETTING {enable_send_changes_only} SET TO TRUE SO
# EVEN IF THERE ARE NO CHANGES THEY WILL STILL SEND A PATCH REQUEST
def test_patching_changed_object(mocked_resp):
    patch_adapter = mocked_resp.patch(
        'http://api/v1/my_cool_endpoint?APIKey=api_key_123&APISecret=api_secret_ABC',
        json={}
    )

    object_to_update = get_object_setup(mocked_resp)
    object_to_update[0].name = "Test Changed"
    object_to_update[0].description = "Object has been changed"

    assert object_to_update[0].api.did_send_count == 0
    object_to_update[0].api.client.send_objs(object_to_update)
    assert object_to_update[0].api.did_send_count == 1

    assert patch_adapter.call_count == 1
    # Should only send fields defined in the object class that have been updated
    assert patch_adapter.last_request.json() == [{
        'description': 'Object has been changed',
        'name': "Test Changed"
    }]


def test_patching_unchanged_object(mocked_resp):
    patch_adapter = mocked_resp.patch(
        'http://api/v1/my_cool_endpoint?APIKey=api_key_123&APISecret=api_secret_ABC',
        json={}
    )
    object_to_update = get_object_setup(mocked_resp)

    object_to_update[0].api.client.send_objs(object_to_update)

    assert patch_adapter.call_count == 1
    assert patch_adapter.last_request.json() == [{}]


def test_sending_object_with_new_field(mocked_resp):
    patch_adapter = mocked_resp.patch(
        'http://api/v1/my_cool_endpoint?APIKey=api_key_123&APISecret=api_secret_ABC',
        json={}
    )
    object_to_update = get_object_setup(mocked_resp)
    object_to_update[0].test_variable = "This is a variable not originally in the object"

    object_to_update[0].api.client.send_objs(object_to_update)

    assert patch_adapter.call_count == 1
    # Should not send fields not defined in the object class
    assert patch_adapter.last_request.json() == [{}]


def test_sending_new_and_updated_objects(mocked_resp):
    patch_adapter = mocked_resp.patch(
        'http://api/v1/my_cool_endpoint?APIKey=api_key_123&APISecret=api_secret_ABC',
        json={}
    )

    objects_to_update = []
    objects_to_update.extend(get_new_object_setup())

    updated_object = get_object_setup(mocked_resp)
    updated_object[0].description = "This object has been updated"
    objects_to_update.extend(updated_object)

    objects_to_update[0].api.client.send_objs(objects_to_update)

    assert patch_adapter.call_count == 1
    assert patch_adapter.last_request.json() == [
        # This is the new object
        {
            'account_id': 2,
            'description': 'TestNewObject',
            'name': 'New Test'
        },
        # This is the updated object
        {
            'description': "This object has been updated"
        }
    ]


def test_sending_new_object(mocked_resp):
    patch_adapter = mocked_resp.patch(
        'http://api/v1/my_cool_endpoint?APIKey=api_key_123&APISecret=api_secret_ABC',
        json={}
    )

    objects_to_update = get_new_object_setup()

    objects_to_update[0].api.client.send_objs(objects_to_update)

    assert patch_adapter.call_count == 1
    assert patch_adapter.last_request.json() == [
        {
            'account_id': 2,
            'description': 'TestNewObject',
            'name': 'New Test'
        }
    ]


def test_sending_500_new_objects(mocked_resp):
    patch_adapter = mocked_resp.patch(
        'http://api/v1/my_cool_endpoint?APIKey=api_key_123&APISecret=api_secret_ABC',
        json={}
    )

    objects_to_update = []
    expected_objects = []

    for i in range(1, 500):
        expected_objects.append({
            'account_id': i,
            'name': ("Test" + str(i))
        })
        obj = TestModel()
        obj.name = "Test" + str(i)
        obj.account_id = i
        objects_to_update.append(obj)

    objects_to_update[0].api.client.send_objs(objects_to_update)

    assert patch_adapter.call_count == 1
    assert patch_adapter.last_request.json() == expected_objects


@patch.object(TestModel.api.client, 'default_send_batch_size', 20)
def test_sending_multiple_batches_of_new_objects(mocked_resp):
    patch_adapter = mocked_resp.patch(
        'http://api/v1/my_cool_endpoint?APIKey=api_key_123&APISecret=api_secret_ABC',
        json={}
    )

    objects_to_update = []
    expected_objects = []
    total_object_count = 203  # Using non-evenly divisible number
    object_group_count = TestModel.api.client.default_send_batch_size
    total_call_count = math.ceil(total_object_count / object_group_count)

    for i in range(total_call_count):
        expected_objects.append([])

    for i in range(1, total_object_count + 1):
        index = math.floor((i - 1) / object_group_count)
        expected_objects[index].append({
            'account_id': i,
            'name': ("Test" + str(i))
        })
        obj = TestModel()
        obj.name = "Test" + str(i)
        obj.account_id = i
        objects_to_update.append(obj)

    objects_to_update[0].api.client.send_objs(objects_to_update)

    assert patch_adapter.call_count == total_call_count
    for i in range(len(patch_adapter.request_history)):
        assert patch_adapter.request_history[i].json() == expected_objects[i]


def test_read_only_field(mocked_resp):
    patch_adapter = mocked_resp.patch(
        'http://api/v1/my_cool_endpoint?APIKey=api_key_123&APISecret=api_secret_ABC',
        json={}
    )

    object_to_update = get_object_setup(mocked_resp)

    object_to_update[0].read_only_field = "New read only value"
    object_to_update[0].name = "New name"

    object_to_update[0].api.client.send_objs(object_to_update)

    assert patch_adapter.call_count == 1
    assert patch_adapter.last_request.json() == [
        {
            'name': "New name"
        }
    ]


def test_sending_objs_returns_dict_instead_of_list(mocked_resp):
    patch_adapter = mocked_resp.patch(
        'http://api/v1/my_cool_multiple_results_path_endpoint?APIKey=api_key_123&'
        'APISecret=api_secret_ABC',
        json={'data': [], 'meta': {}}
    )

    objects_to_update = []
    for x in range(10):
        object_to_update = TestMultipleResultsPathModel()
        object_to_update.id = x
        object_to_update.name = f"Test Object {x}"
        objects_to_update.append(object_to_update)

    # We don't want an error thrown in this method when posting multiple objects to an endpoint
    # and receiving back a dict with an empty list and the key to that list matching the
    # multiple_results_json_path key stored on the object structure.
    objects_to_update[0].api.client.send_objs(objects_to_update)

    # We are experiencing a different error where posting is not working if the call count does
    # not equal 1
    assert patch_adapter.call_count == 1
