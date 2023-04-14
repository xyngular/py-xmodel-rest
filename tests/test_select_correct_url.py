from __future__ import annotations

import pytest
import requests_mock
import math
from .test_models import TestModel
from xurls import URL, HTTPPut, HTTPPost


class UpdateCreateModel(
    TestModel,
    urls=[
        URL("put-path", methods=(HTTPPut,)),
        URL("post-path", methods=(HTTPPost,))
    ]
):
    """ Should select the PUT when updating and POST when creating, by default if PATCH
        unavailable.
    """
    pass


@pytest.fixture
def mocked_resp():
    with requests_mock.Mocker() as mocker:
        yield mocker


@pytest.fixture
def test_obj():
    obj = UpdateCreateModel()
    obj.account_id = 2
    obj.name = "New Test"
    obj.description = "TestNewObject"
    return obj


def test_correct_url_selected_for_create(mocked_resp, test_obj):
    # Testing to see if post-path URL gets selected
    patch_adapter = mocked_resp.post(
        'http://api/v1/my_cool_endpoint/post-path?APIKey=api_key_123&APISecret=api_secret_ABC',
        json={}
    )

    test_obj.id = None
    test_obj.api.send()
    assert patch_adapter.call_count == 1


def test_correct_url_selected_for_update(mocked_resp, test_obj):
    # Testing to see if put-path URL gets selected
    patch_adapter = mocked_resp.put(
        'http://api/v1/my_cool_endpoint/put-path?APIKey=api_key_123&APISecret=api_secret_ABC',
        json={}
    )

    test_obj.id = 123
    test_obj.api.send()
    assert patch_adapter.call_count == 1
