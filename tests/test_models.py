from __future__ import annotations

from requests import PreparedRequest
from dataclasses import dataclass
from xmodel import Field
from xmodel.common.types import FieldNames, JsonDict
from xsentinels import Default
from xsentinels.default import DefaultType

from xmodel_rest import RestModel, RestSettings, RestAuth, RestClient, RestApi
from xurls import URLStr, URL, URLMutable
from typing import TypeVar, Dict, Sequence, Tuple, Union

T = TypeVar('T')

# ----------------------
# ***** My Models ******


class TestModel(RestModel['TestModel'], base_url="my_cool_endpoint"):
    # Defined the api type/class to use.
    api: TestApi[T]
    id: int
    account_id: int
    number: str
    description: str
    is_active: bool
    address2: str
    name: str
    something_else: str
    child: TestModelChild
    excluded_field: str = Field(exclude=True)
    read_only_field: str = Field(read_only=True)


class TestModelChild(RestModel['TestModelChild'], base_url="my_cool_child_endpoint"):
    # Defined the api type/class to use.
    api: TestApi[T]
    id: int
    name: str


class TestMultipleResultsPathModel(
    RestModel['TestMultipleResultsPathModel'],
    multiple_results_json_path='data',
    base_url='my_cool_multiple_results_path_endpoint'
):
    api: TestApi[T]
    id: int
    name: str


class TestFormatBodyModel(
    RestModel['TestFormatBodyModel'],
    base_url='my_cool_body_formatting_endpoint'
):
    api: TestFormatBodyApi[T]
    id: int
    name: str


# -------------------------------------
# ***** Custom Base Test Classes ******
#
# These are here to test a custom test model, with a custom auth class.


@dataclass()
class TestRestSettings(RestSettings):
    # "https://preview-xyngular.myvoffice.com/index.cfm"
    base_api_url: URLStr = "http://api/v1"
    api_key: str = "api_key_123"
    api_secret: str = "api_secret_ABC"


class TestApi(RestApi[T]):
    # This tells the system we want to use this type for the client, and type-hinting
    # for type-completion will also now reflect the correct type as well!
    auth: TestAuth
    client: TestClient
    settings: TestRestSettings

    did_send_count = 0

    def did_send(self):
        self.did_send_count += 1


class TestFormatBodyApi(RestApi[T]):
    auth: TestAuth
    client: TestFormatBodyClient
    settings: TestRestSettings

    did_send_count = 0

    def did_send(self):
        self.did_send_count += 1


class TestFormatBodyClient(RestClient):
    def url_for_read(
            self, *,
            url: URL,
            top: int = None,
            fields: FieldNames = Default
    ) -> URLMutable:
        url = super().url_for_read(url=url, top=top, fields=fields)
        url.methods = "POST"
        return url

    def url_for_delete(
            self, *, url: URL, model_objs: Sequence[RestModel]
    ) -> URLMutable:
        url = super().url_for_delete(url=url, model_objs=model_objs)
        url.methods = "POST"
        return url

    def format_body_for_delete(
        self, objects: Sequence[Tuple[RestModel, JsonDict]], url: URLMutable
    ):
        json = []

        for obj in objects:
            json.append({"id": obj.id})

        return json

    def format_body_for_get(
        self,
        url: URLMutable,
        top: int = None,
        fields: Union[FieldNames, DefaultType] = Default
    ):
        json = {}
        query = url.query.copy()
        for key in query.keys():
            json[key] = query[key]
            url.query_remove(key)
        if top:
            json['top'] = top
        return json


class TestAuth(RestAuth):
    def __call__(self, request: PreparedRequest):
        config = TestRestSettings.grab()
        auth_dict = dict(APIKey=config.api_key, APISecret=config.api_secret)
        request.prepare_url(request.url, auth_dict)
        return request

    def refresh_token(self, *args, **kwargs):
        # No need to refresh a token for this auth type.
        pass


# We use the base RestClient, because it's good enough for getting things from evo.
class TestClient(RestClient):
    # This tells the system with type to use for Auth [defaults to api.Auth],
    # and informs type completion about it to!
    pass


