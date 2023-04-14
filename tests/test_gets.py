from __future__ import annotations

import gc
import pytest
import requests_mock
import requests

from xmodel.errors import XynModelError
from xmodel_rest.errors import XynRestError
from .test_models import TestModel, TestFormatBodyModel, TestRestSettings
from unittest.mock import patch
import time
from xmodel.remote import WeakCachePool
from requests_mock.exceptions import NoMockAddress
from xmodel_rest.settings import RestSettings


@pytest.fixture
def mocked_resp():
    with requests_mock.Mocker() as mocker:
        yield mocker


def test_responses(mocked_resp):
    mocked_resp.get('http://twitter.com/api/1/foobar', text='{}', status_code=200)
    resp = requests.get('http://twitter.com/api/1/foobar')
    assert resp.status_code == 200


def test_basic_get(mocked_resp):

    body = {
        'id': 2,
        'address2': "my cool address",
        'name': "my name",
        'something_else': "some other info here",
    }

    call = mocked_resp.get(
        'http://api/v1/my_cool_endpoint/2?APIKey=api_key_123&APISecret=api_secret_ABC',
        json=body,
        status_code=200,
    )

    obj = TestModel.api.get_via_id(2)

    assert call.call_count == 1
    assert obj.name == 'my name'
    assert obj.something_else == 'some other info here'
    assert obj.address2 == 'my cool address'


def test_basic_get_without_timeout(mocked_resp):
    body = {
        'id': 2,
        'address2': "my cool address",
        'name': "my name",
        'something_else': "some other info here",
    }

    call = mocked_resp.get(
        'http://api/v1/my_cool_endpoint/2?APIKey=api_key_123&APISecret=api_secret_ABC',
        json=body,
        status_code=200,
    )

    obj = TestModel.api.get_via_id(2)

    assert call.call_count == 1
    assert obj.name == 'my name'
    assert obj.something_else == 'some other info here'
    assert obj.address2 == 'my cool address'

    first_time = True

    def text_callback(request, context):
        nonlocal first_time
        # Fail with 500 the first time, and not on the second try.
        if not first_time:
            return body
        context.status_code = 500
        first_time = False
        return {'detail': 'mocking 500 error'}

    call = mocked_resp.get(
        'http://api/v1/my_cool_endpoint/2',
        json=text_callback,
        status_code=200,
    )

    obj = TestModel.api.get_via_id(2)
    assert obj.name == 'my name'
    assert obj.something_else == 'some other info here'
    assert obj.address2 == 'my cool address'

    # Should have been called twice, the second call to retry the first 500 failure.
    assert call.call_count == 2

    call.reset()

    # We disable retry_requests, and it should fail on the first call and not retry.
    TestRestSettings.resource().retry_requests = False
    first_time = True
    with pytest.raises(XynModelError):
        obj = TestModel.api.get_via_id(2)
    assert call.call_count == 1


def test_basic_get_via_id_for_list_with_aux_query(mocked_resp):

    body = {
        'id': 2,
        'address2': "my cool address",
        'name': "my name",
        'something_else': "some other info here",
    }

    mocked_resp.get(
        'http://api/v1/my_cool_endpoint/2?APIKey=api_key_123&APISecret=api_secret_ABC'
        '&extra_name=extra-query-value',
        json=body,
        status_code=200,
    )

    objs = TestModel.api.get_via_id([2], aux_query={"extra_name": "extra-query-value"})
    obj = next(objs)
    assert obj.name == 'my name'
    assert obj.something_else == 'some other info here'
    assert obj.address2 == 'my cool address'


def test_basic_get_for_valid_json_but_non_dict_root(mocked_resp):

    body = "some string"

    mocked_resp.get(
        'http://api/v1/my_cool_endpoint/2?APIKey=api_key_123&APISecret=api_secret_ABC',
        json=body,
        status_code=200,
    )

    with pytest.raises(XynModelError):
        TestModel.api.get_via_id(2)


def test_basic_get_for_basic_error_response(mocked_resp):
    body = {}

    mocked_resp.get(
        'http://api/v1/my_cool_endpoint/2?APIKey=api_key_123&APISecret=api_secret_ABC',
        json=body,
        status_code=500,
    )

    with pytest.raises(XynModelError):
        TestModel.api.get_via_id(2)


def test_basic_get_for_invalid_json_response_body(mocked_resp):
    body = "Invalid JSON"

    mocked_resp.get(
        'http://api/v1/my_cool_endpoint/2?APIKey=api_key_123&APISecret=api_secret_ABC',
        text=body,
        status_code=200,
    )

    with pytest.raises(XynModelError):
        TestModel.api.get_via_id(2)


def test_dictionary_list_in_get_via_id(mocked_resp):
    body = {
        'results': [
            {
                'account_id': 232,
                'number': "1112223333",
                "description": "cell",
                "is_active": True
            },
            {
                "account_id": 233,
                "number": "4445556666",
                "description": "home",
                "is_active": True
            },
            {
                "account_id": 234,
                "number": "7778889999",
                "description": "other",
                "is_active": False
            }
        ]
    }

    object_dicts = [
        {
            "account_id": 234,
            "number": "7778889999"
        },
        {
            "account_id": 232,
            "number": "1112223333"
        },
        {
            "account_id": 233,
            "number": "4445556666"
        },
    ]

    mocked_url = (
        'http://api/v1/my_cool_endpoint?account_id__in=233%2C232%2C234&number__in'
        '=4445556666%2C1112223333%2C7778889999&limit=15000&APIKey=api_key_123&APISecret'
        '=api_secret_ABC'
    )

    mocked_resp.get(
        mocked_url,
        json=body,
        status_code=200,
    )

    gen = TestModel.api.get_via_id(id=object_dicts)
    returned_objs = []

    for obj in gen:
        returned_objs.append(obj)

    assert returned_objs[0].account_id == 232
    assert returned_objs[0].number == '1112223333'
    assert returned_objs[0].description == 'cell'
    assert returned_objs[0].is_active is True

    assert returned_objs[1].account_id == 233
    assert returned_objs[1].number == '4445556666'
    assert returned_objs[1].description == 'home'
    assert returned_objs[1].is_active is True

    assert returned_objs[2].account_id == 234
    assert returned_objs[2].number == '7778889999'
    assert returned_objs[2].description == 'other'
    assert returned_objs[2].is_active is False


def test_multiple_different_dicts_in_get_via_id_calls_urls(mocked_resp):
    object_dicts = [
        {
            'key': 1,
            'rand': 1
        },
        {
            'red': 2,
            'green': 2,
            'blue': 2
        },
        {
            'key': 2,
            'rand': 2
        },
        {
            'date': 1
        },
        {
            'key': 3,
            'rand': 3
        },
        {
            'date': 2
        },
        {
            'key': 4,
            'rand': 4
        },
        {
            'red': 1,
            'green': 1,
            'blue': 1
        },
    ]

    base_url = 'http://api/v1/my_cool_endpoint?'
    base_auth = '&APIKey=api_key_123&APISecret=api_secret_ABC'

    one_key_url = (
        base_url +
        'date__in=2%2C1&limit=15000' +
        base_auth
    )

    two_key_url = (
        base_url +
        'key__in=4%2C3%2C2%2C1&rand__in=4%2C3%2C2%2C1&limit=15000' +
        base_auth
    )

    three_key_url = (
        base_url +
        'green__in=1%2C2&blue__in=1%2C2&red__in=1%2C2&limit=15000' +
        base_auth
    )

    mocked_resp.get(
        one_key_url,
        json={'results': []},
        status_code=200
    )
    mocked_resp.get(
        two_key_url,
        json={'results': []},
        status_code=200
    )
    mocked_resp.get(
        three_key_url,
        json={'results': []},
        status_code=200
    )

    TestModel.api.get_via_id(object_dicts)


def test_get_via_id_with_hundreds_of_objects_calls_urls(mocked_resp):
    object_dicts = []

    base_url = 'http://api/v1/my_cool_endpoint?'
    base_auth = '&APIKey=api_key_123&APISecret=api_secret_ABC'

    url_one = (
        base_url +
        'number__in=100%2C99%2C98%2C97%2C96%2C95%2C94%2C93%2C92%2C91%2C90%2C89%2C88%2C87%2C86'
        '%2C85%2C84%2C83%2C82%2C81%2C80%2C79%2C78%2C77%2C76%2C75%2C74%2C73%2C72%2C71%2C70%2C69'
        '%2C68%2C67%2C66%2C65%2C64%2C63%2C62%2C61%2C60%2C59%2C58%2C57%2C56%2C55%2C54%2C53%2C52'
        '%2C51%2C50%2C49%2C48%2C47%2C46%2C45%2C44%2C43%2C42%2C41%2C40%2C39%2C38%2C37%2C36%2C35'
        '%2C34%2C33%2C32%2C31%2C30%2C29%2C28%2C27%2C26%2C25%2C24%2C23%2C22%2C21%2C20%2C19%2C18'
        '%2C17%2C16%2C15%2C14%2C13%2C12%2C11%2C10%2C9%2C8%2C7%2C6%2C5%2C4%2C3%2C2%2C1&limit'
        '=15000' +
        base_auth
    )

    url_two = (
        base_url +
        'number__in=200%2C199%2C198%2C197%2C196%2C195%2C194%2C193%2C192%2C191%2C190%2C189%2C188'
        '%2C187%2C186%2C185%2C184%2C183%2C182%2C181%2C180%2C179%2C178%2C177%2C176%2C175%2C174'
        '%2C173%2C172%2C171%2C170%2C169%2C168%2C167%2C166%2C165%2C164%2C163%2C162%2C161%2C160'
        '%2C159%2C158%2C157%2C156%2C155%2C154%2C153%2C152%2C151%2C150%2C149%2C148%2C147%2C146'
        '%2C145%2C144%2C143%2C142%2C141%2C140%2C139%2C138%2C137%2C136%2C135%2C134%2C133%2C132'
        '%2C131%2C130%2C129%2C128%2C127%2C126%2C125%2C124%2C123%2C122%2C121%2C120%2C119%2C118'
        '%2C117%2C116%2C115%2C114%2C113%2C112%2C111%2C110%2C109%2C108%2C107%2C106%2C105%2C104'
        '%2C103%2C102%2C101&limit=15000' +
        base_auth
    )

    url_three = (
        base_url +
        'number__in=300%2C299%2C298%2C297%2C296%2C295%2C294%2C293%2C292%2C291%2C290%2C289%2C288'
        '%2C287%2C286%2C285%2C284%2C283%2C282%2C281%2C280%2C279%2C278%2C277%2C276%2C275%2C274'
        '%2C273%2C272%2C271%2C270%2C269%2C268%2C267%2C266%2C265%2C264%2C263%2C262%2C261%2C260'
        '%2C259%2C258%2C257%2C256%2C255%2C254%2C253%2C252%2C251%2C250%2C249%2C248%2C247%2C246'
        '%2C245%2C244%2C243%2C242%2C241%2C240%2C239%2C238%2C237%2C236%2C235%2C234%2C233%2C232'
        '%2C231%2C230%2C229%2C228%2C227%2C226%2C225%2C224%2C223%2C222%2C221%2C220%2C219%2C218'
        '%2C217%2C216%2C215%2C214%2C213%2C212%2C211%2C210%2C209%2C208%2C207%2C206%2C205%2C204'
        '%2C203%2C202%2C201&limit=15000' +
        base_auth
    )

    mocked_resp.get(
        url_one,
        json={'results': []},
        status_code=200
    )

    mocked_resp.get(
        url_two,
        json={'results': []},
        status_code=200
    )

    mocked_resp.get(
        url_three,
        json={'results': []},
        status_code=200
    )

    for i in range(1, 301):
        object_dicts.append({"number": i})

    results = TestModel.api.get_via_id(object_dicts)

    for result in results:
        assert result is not None


def test_auto_get_bulk_children(mocked_resp):
    parent_results = {
        'results': [
            {
                'id': 1,
                'name': 'parent1',
                'child_id': 1
            },
            {
                'id': 2,
                'name': 'parent2',
                'child_id': 2
            },
            {
                'id': 3,
                'name': 'parent3',
                'child_id': 3
            },
        ]
    }
    child_results = {
        'results': [
            {
                'id': 1,
                'name': 'child1'
            },
            {
                'id': 2,
                'name': 'child2'
            },
            {
                'id': 3,
                'name': 'child3'
            },
        ]
    }
    base_auth = '&APIKey=api_key_123&APISecret=api_secret_ABC'
    parent_url = (
        'http://api/v1/my_cool_endpoint?' +
        base_auth
    )
    child_url = (
        'http://api/v1/my_cool_child_endpoint?limit=15000' +
        base_auth
    )

    mocked_resp.get(
        parent_url,
        json=parent_results,
        status_code=200
    )

    mocked_resp.get(
        child_url,
        json=child_results,
        status_code=200
    )

    TestModel.api.options.auto_get_child_objects = True

    results = TestModel.api.get()

    index = 1
    for result in results:
        assert result.id == index
        assert result.name == 'parent' + str(index)
        assert result.child.id == index
        assert result.child.name == 'child' + str(index)
        index += 1

    # Ensure the option is still enabled, it gets temporarily disabled in RestClient
    # It should have been restored back to it's orginal value.
    assert TestModel.api.options.auto_get_child_objects


def test_top_in_get_all_limits_how_many_objects_returned(mocked_resp):
    response_objects = []
    top_amount = 20
    for i in range(top_amount * 5):
        response_objects.append({
            'id': i,
            'name': 'Test' + str(i)
        })
    response = {
        'results': response_objects
    }
    mocked_resp.get(
        f'http://api/v1/my_cool_endpoint?limit={top_amount}&APIKey=api_key_123'
        f'&APISecret=api_secret_ABC',
        json=response,
        status_code=200
    )

    objs_returned = TestModel.api.get(top=top_amount)
    objs_returned_count = 0

    for obj in objs_returned:
        objs_returned_count += 1

    assert objs_returned_count == top_amount


def test_not_getting_excluded_field(mocked_resp):
    result_object = {
        'id': 1,
        'name': "Test"
    }

    response = {
        'results': [result_object]
    }

    mocked_resp.get(
        'http://api/v1/my_cool_endpoint?field%21__in=excluded_field&limit=15000'
        '&APIKey=api_key_123&APISecret=api_secret_ABC',
        json=response,
        status_code=200
    )
    obj_to_get = None
    objs_to_get = TestModel.api.get()
    for obj in objs_to_get:
        obj_to_get = obj
        break

    assert obj_to_get.id == result_object['id']
    assert obj_to_get.name == result_object['name']
    assert getattr(obj_to_get, 'excluded_field', None) is None


def test_getting_object_via_id_from_weak_ref_cache(mocked_resp):
    body = {
        'results': [
            {
                'id': 2,
                'address2': "my cool address 2",
                'name': "id 2",
                'something_else': "I like cars",
            },
            {
                'id': 3,
                'address2': "my cool address 3",
                'name': "id 3",
                'something_else': "I like boats",
            },
            {
                'id': 4,
                'address2': "my cool address 4",
                'name': "id 4",
                'something_else': "I like planes",
            },
        ]
    }

    call = mocked_resp.get(
        'http://api/v1/my_cool_endpoint?field%21__in=excluded_field&limit=15000&APIKey=api_key_123'
        '&APISecret=api_secret_ABC',
        json=body,
        status_code=200,
    )

    # By default, weak-caching should be disabled!
    models = [*TestModel.api.get()]

    # If we fail here, it means the object was not cached because we tried to fetch-it again
    with pytest.raises(NoMockAddress):
        TestModel.api.get_via_id(2)

    assert call.call_count == 1

    with WeakCachePool(enable=True):
        models = [*TestModel.api.get()]

        gc.collect()

        # If we fail here, it means the object was not cached because we tried to fetch-it again
        cache_result = TestModel.api.get_via_id(2)

        assert cache_result.id == 2
        assert cache_result.address2 == "my cool address 2"
        assert cache_result.name == "id 2"
        assert cache_result.something_else == "I like cars"

    assert call.call_count == 2


def test_getting_object_via_id_from_weak_ref_cache_with_no_ref_after_gc(mocked_resp):
    body = {
        'results': [
            {
                'id': 2,
                'address2': "my cool address 2",
                'name': "id 2",
                'something_else': "I like cars",
            },
            {
                'id': 3,
                'address2': "my cool address 3",
                'name': "id 3",
                'something_else': "I like boats",
            },
            {
                'id': 4,
                'address2': "my cool address 4",
                'name': "id 4",
                'something_else': "I like planes",
            },
        ]
    }

    mocked_resp.get(
        'http://api/v1/my_cool_endpoint?field%21__in=excluded_field&limit=15000&'
        'APIKey=api_key_123&APISecret=api_secret_ABC',
        json=body,
        status_code=200,
    )

    get_via_id_call = mocked_resp.get(
        'http://api/v1/my_cool_endpoint/2?APIKey=api_key_123&APISecret=api_secret_ABC',
        json=body['results'][0],
        status_code=200
    )

    models = [*TestModel.api.get()]

    del models

    gc.collect()

    cache_result = TestModel.api.get_via_id(2)

    assert cache_result.id == 2
    assert cache_result.address2 == "my cool address 2"
    assert cache_result.name == "id 2"
    assert cache_result.something_else == "I like cars"
    assert get_via_id_call.call_count == 1


def test_getting_objects_with_id_field_only(mocked_resp):
    body = {
        'results': [
            {
                'id': 2,
            },
            {
                'id': 3,
            },
            {
                'id': 4,
            },
        ]
    }

    mocked_resp.get(
        'http://api/v1/my_cool_endpoint?field__in=id&limit=15000&APIKey=api_key_123&'
        'APISecret=api_secret_ABC',
        json=body
    )

    # running generator through list to execute generator
    list(TestModel.api.get(fields=['id']))

    assert mocked_resp.call_count == 1


def test_getting_objects_with_simple_query(mocked_resp):
    body = {
        'results': [
            {
                'id': 2,
            },
            {
                'id': 3,
            },
            {
                'id': 4,
            },
        ]
    }

    mocked_resp.get(
        'http://api/v1/my_cool_endpoint?field__in=id&limit=15000&APIKey=api_key_123&'
        'APISecret=api_secret_ABC&number=541',
        json=body
    )

    # running generator through list to execute generator
    list(TestModel.api.get({'number': 541}, fields=['id']))

    assert mocked_resp.call_count == 1


def test_timeout_error(mocked_resp):
    first_call = True

    def is_first_call(request):
        nonlocal first_call
        if first_call:
            first_call = False
            return True
        else:
            return False

    def is_second_call(request):
        nonlocal first_call
        return not first_call

    failed_resp = mocked_resp.get(
        'http://api/v1/my_cool_endpoint',
        exc=requests.exceptions.Timeout,
        additional_matcher=is_first_call
    )

    body = {
        'results': [
            {
                'id': 2,
            },
            {
                'id': 3,
            },
            {
                'id': 4,
            },
        ]
    }

    success_resp = mocked_resp.get(
        'http://api/v1/my_cool_endpoint',
        status_code=200,
        json=body,
        additional_matcher=is_second_call
    )

    # running generator through list to execute generator
    response = list(TestModel.api.get({'number': 541}, fields=['id']))

    # Failed response has returns a timeout error and retries
    assert failed_resp.call_count == 1
    assert success_resp.call_count == 1
    assert len(response) == 3


def test_connection_error(mocked_resp):
    first_call = True

    def is_first_call(request):
        nonlocal first_call
        if first_call:
            first_call = False
            return True
        else:
            return False

    def is_second_call(request):
        nonlocal first_call
        return not first_call

    failed_resp = mocked_resp.get(
        'http://api/v1/my_cool_endpoint',
        exc=requests.exceptions.ConnectionError,
        additional_matcher=is_first_call
    )

    body = {
        'results': [
            {
                'id': 2,
            },
            {
                'id': 3,
            },
            {
                'id': 4,
            },
        ]
    }

    success_resp = mocked_resp.get(
        'http://api/v1/my_cool_endpoint',
        status_code=200,
        json=body,
        additional_matcher=is_second_call
    )

    # running generator through list to execute generator
    response = list(TestModel.api.get({'number': 541}, fields=['id']))

    # Failed response has returns a timeout error and retries
    assert failed_resp.call_count == 1
    assert success_resp.call_count == 1
    assert len(response) == 3


def test_get_via_post_format_body_method(mocked_resp):
    body = {
        "id": 2,
        "name": "Test Object"
    }

    call = mocked_resp.post(
        'http://api/v1/my_cool_body_formatting_endpoint/2',
        json=body,
        status_code=200,
    )

    obj = TestFormatBodyModel.api.get_via_id(2)

    assert call.call_count == 1
    # These queries were added by the library to the url and the test model moved them to the
    # body in the format body for get method.
    assert call.last_request.json() == {'limit': '1', 'top': 1}

    assert obj is not None
    assert obj.id == 2
    assert obj.name == 'Test Object'


def test_get_via_post_format_body_method_with_query(mocked_resp):
    body = {
        'results': [
            {
                "id": 2,
                "name": "Test Object"
            }
        ]
    }

    call = mocked_resp.post(
        'http://api/v1/my_cool_body_formatting_endpoint',
        json=body,
        status_code=200,
    )

    query = {'name': 'Test Object'}

    obj = [*TestFormatBodyModel.api.get(query=query, top=100)][0]

    # These queries were added by the library to the url and the test model moved them to the
    # body in the format body for get method.
    query['top'] = 100
    query['limit'] = '100'

    assert call.call_count == 1
    assert call.last_request.json() == query

    assert obj is not None
    assert obj.id == 2
    assert obj.name == 'Test Object'
