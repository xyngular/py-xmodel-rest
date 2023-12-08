# Includes all the basic generic/abstract types we use everywhere, very light-weight.
from xmodel.remote.options import ApiOptionsGroup

from xurls.url import DefaultQueryValueListFormat
import time
from collections import deque
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING, TypeVar, Sequence, List, Union, Iterable, Set, Deque, Optional, Tuple,
    Callable, Dict, Any
)
from xmodel.common.types import FieldNames
from .auth import RestAuth
import requests
from xsentinels.singleton import Singleton
from xmodel.common.types import JsonDict
from xurls.url import (
    URLMutable, URL, URLStr, HTTPPatch, HTTPPost, HTTPPut, HTTPGet, HTTPDelete, HTTPMethodType
)
from .errors import XynRestError
from xmodel.remote.response_state import ResponseStateRetryValue, ErrorHandler
from logging import getLogger
from xloop import xloop
from xurls.url import Query
from xmodel.remote import RemoteModel
from .session import Session
from xsentinels.default import Default, DefaultType
from xmodel.remote import RemoteClient
from .model import RestModel
from requests.exceptions import ConnectionError, Timeout, ReadTimeout

if TYPE_CHECKING:
    # Prevents circular imports, only needed for IDE type completion
    # (and static analyzers, if we end up using them in the future).
    # We don't need the to be resolvable at run-time.
    from .api import RestApi

log = getLogger(__name__)
M = TypeVar('M', bound="RestModel")


class UseSingularValueType(Singleton):
    """
    Used by RestClient class to indicate URL generator is requesting a single object [vs multiple].
    See `UseSingularValue` below.
    Also, we always evaluate to False (default for Singleton objects, like how `None` is false).
    """
    pass


UseSingularValue = UseSingularValueType()
""" Used by RestClient class to indicate URL generator is requesting a single object [vs multiple].
    This will always evaluate to False.
"""


DefaultStatusSetToRaiseForSending = frozenset(xloop([400, 401, 403], range(500, 599)))
""" Default set of status to raise exceptions for vs  """

# todo: This may have things in it that are more specific to how Xyngular BaseApi's work.
# todo: Go though this and perhaps split some of this off into another class someday.

# todo: Add more ways into RestClient/Etc, to more easily intercept and handle any kind of error
#       after all other error handlers have been consulted.

# todo: Right now, `error_handler` api.option... is only consulted when we send an object;
#       ie: POST/PUT/PATCH. I need to check for a 'error_handler' in GET/DELETE as well.


@dataclass(frozen=True)
class GeneratedURL:
    """
    Allows `RestClient.url_for_send` to specify a URL and a set of objects to send for the URL when
    it returns a URL it found that the client and use to send objects with.
    """
    url: URL
    """ URL to use to send the objects with.
    """
    models: "Sequence[RestModel[M]]"
    """ Set of models to send objects with.  Models that were unselected should be sent
        to another call of the `RestClient.url_for_send` to see if it can match a URL for the
        objects that were not selected the first time.
    """


class RestClient(RemoteClient[M]):
    """
    Keep in mind this is sort of the 'base' client class for basic rest-based API's.
    I thought about renaming this from "Client" to "RestClient", but it is the most-used
    ORM Client class and there are a LOT of references to it.  I decided to leave the name alone.

    If we start creating other Client classes for other rest based API's and we discover some
    common code they could all use, then you can start putting things in a common `RestClient`
    class.

    This class is responsible for communicate with API (or the network in general).
    It will figure out the correct endpoint to use and construct a request and execute it
    via the Requests 3rd party library.

    I grab the auth object via `xynlib.orm.rest.RestApi.auth`. This object must be usable as an
    auth object for 3rd part `Requests` library.

    The `xynlib.orm.rest.model.RestModel` classes have a order list of URL's attached to the class
    that we
    try to use in order when we need to find a URL to send/get objects.
    The list is at `xynlib.orm.base.structure.BaseStructure.model_urls`.

    See `self.url_for_endpoint()` for complete details on the url construction process.

    Basic Actions:

    - `RestClient.delete_objs`
    - `RestClient.send_objs`
    - These call `RestClient.get` (higher-level methods):
        - `RestClient.get`
        - `RestClient.get_first_for_query`

    URL generation:

    - `RestClient.url_for_endpoint` is called from:
        - `RestClient.url_for_read`
        - `RestClient.url_for_delete`
        - `RestClient.url_for_send`
    - `RestClient.url_for_next_page`
        - Used to generate URL for the next page of results.

    Parse Response:

    - `RestClient.parse_json_from_get_response`
    - `RestClient.parse_errors_from_send_response`
        - This can be overridden to provide more detail for model
          `xynlib.orm.http_state.HttpState`.

    Configuration, use these to customize a sub-class:

    - `RestClient.base_api_url`
    - `RestClient.base_endpoint_url`
    - `RestClient.root_read_url`
    - `RestClient.default_send_batch_size`
    - `RestClient.enable_send_changes_only`
    - `RestClient.method_status_to_raise_my_default`

    Read-Only attrs:

    - `RestClient.auth`

    Customization Examples:

    >>> class CustomSettings(RestClient):
    ...     # Make singular=True the default when generating read-urls.
    ...     root_read_url = URL(singular=True)

    """

    # This typehint is only here to provide a better type-hint to IDE's.
    # The `xynlib.orm.rest.api.RestApi.client` typehint is what is actually used to figure out what
    # RestClient type to allocate.
    api: "RestApi[M]"

    # todo: Perhaps move this into the 'xynlib.orm.options.ApiOptions'?
    base_endpoint_url: URLStr = ""
    """ Whenever a request is executed this is used, it is appended to the base_api_url;

        .. important:: see `RestClient.base_api_url` docs for more details
            It will give you details you how the url construction process works, where
            `base_api_url` comes from and how to override it in various ways.
            *Those same ways also apply to this attribute.*

        .. warning:: Other Notes Related To Auth
            This url is NOT used with Auth obj/class,
            see "Other Notes Related To Auth" in `RestClient.base_api_url` for more details about
            this.
    """

    # todo: Perhaps move this into the 'xynlib.orm.options.ApiOptions'?
    # todo: Perhaps call this `root_url_for_get` instead?
    root_read_url: URLStr = None
    """
    Starting root-url for all get requests; it's the starting url to every GET request url.
    By default, we use a blank url (aka: None).

    See `RestClient.url_for_endpoint()` and `RestClient.base_api_url` for complete details on the
    url construction process and various ways to customize it (be sure to read both places).

    The purpose of this is easily to modify the URL used for all GET/read requests if necessary
    without having to override a method like `RestClient.url_for_read` (ie: for simple cases).

    .. tip:: Real Example:
        Right now, I use it in `xyn_sdk.datatrax_api.evo.EvoClient.root_read_url`
        to hint that by default every get request singular=True.
    """

    # todo: Potentially? Move this into the 'xynlib.orm.options.ApiOptions'.
    default_send_batch_size = 500
    """ Used to set default batch size (if not passed directly into `RestClient.send_objs` method).

        Defaults to 500.

        A RestClient subclass can change this if they have endpoints that are slower or have to
        accept less at a time.
    """

    # todo: Move this into the 'xynlib.orm.options.ApiOptions'.
    enable_send_changes_only = False  # type: bool
    """ If `True`, will keep track of changes to api-attributes, and system will only 'patch'
        what has actually changed via a PATCH request (normally).
        It only sends the primary 'id' field and the fields that actually changed;
        (although this can be changed/customized for other API's, like hubspot's for example;
        see hubspot project for example).

        I decided for now this should be opt-in behavior, the default is False for now and
        it will work like it did before, where it sends everything that is not 'None'.

        When `xynlib.orm.base.api.BaseApi.update_from_json` is called, it will reset the list of
        changed properties, this
        is normally called after a patch with the latest attribute values from the server.

        If response does not contain the latest attributes for object from server (ie: blank)
        you should still call `xynlib.orm.base.api.BaseApi.update_from_json` with a blank dict so
        it can try and do this housekeeping (I think it will have to assume that everything got
        updated correctly and adjust internal dict of changed attributes like normal).

        .. todo: Verify above behavior, when using API's that don't give back latest value
            of attributes when updating them with only the changes.
    """

    # todo: Perhaps move this into the 'xynlib.orm.options.ApiOptions'?
    base_api_url: URLStr = None
    """
    Normally this will come from the `xynlib.orm.rest.settings.RestSettings.api_url` via
    `xynlib.orm.rest.api.RestApi.settings` object.
    But you can override it here if needed.
    For example, you might want to use a `RestClient` sub-class for a non xyngular api.

    Whenever a request is executed this is used, this is used if it's set to something that looks
    `True` (ie: non-blank string) instead of grabbing the one from api.settings.api_url.
    So you can use this property to 'override' the api_url if you want.

    General logic summary of what I am saying above:

    >>> base_url_to_use = self.base_api_url or self.api.settings.api_url

    .. info:: `RestClient.base_endpoint_url` considerations:
        If something is also defined in the `RestClient.base_endpoint_url`,
        we will append that to this base_api_url while determining final url.
        We would then finally append anything passed into the
        method making the request (such as additional Query params or url arguments) and so forth.

        See `RestClient.url_for_endpoint()` for complete details on the url construction process.

    **To Use:**

    You can make a custom-subclass of RestClient and define this property. You can then add this
    custom-subclass as the RestClient to use via custom BaseApi class type-hint
    `client: MyAuthClass`.
    The advantage here is you can reused that same `RestClient` sub-type with other RestModel's.

    Or if you just want to change it for a single-RestModel, you can just set it before using it
    like so:

    >>> some_model_obj.api.client.base_url_to_use = "api.host.com/base_path"

    If you do it that way, it has to laizly-configure the classes. If you do it via a subclass:

    >>> from xynlib.orm import RestClient
    >>> class MyClient: RestClient
    >>>     base_url_to_use = "api.host.com/base_path"

    Then it will work for other `xynlib.orm.rest.model.RestModel` sub-types, and won't trigger the
    lazy RestModel configuration code (ie: it will only trigger later if the RestModel's are truly
    used).

    See `xynlib.orm.base.model.RestModel.__init_subclass__` for more details on what I mean by
    lazily configuring the RestModel class.


    .. warning:: Other Notes Related To Auth
        At the moment the url the auth-client uses will not use what's in this `RestClient`'s
        `base_api_url`, since the Auth object can be shared among a number of different client
        instances/types.

        If you need something specific for auth that's different vs standard way, you should
        sub-class
        the `xmodel_rest.auth.RestAuth` sub-type/class you want to customize.
        The sub-class can customize it's self however it wants.

        You then set a type-annotation/hint via type hint on BaseApi class:
        `xynlib.orm.base.api.BaseApi.auth`.
        This makes the `RestClient` use this auth-type and hence your auth customizations.

        See `RestClient.auth` documentation for a code example of how to do this.

        Real world examples on how to create custom auth/api sub-classes as needed:

        - `xyn_sdk.core.common.Auth`
        - `xyn_sdk.core.common.BaseApi`
    """

    # todo: Move this into the 'xynlib.orm.options.ApiOptions'?
    method_status_to_raise_by_default: Dict[HTTPMethodType, Set[int]] = None
    """ A mapping of HTTP-method (HTTPPost/HTTPPut/etc) to a set of status codes that if
        encountered should result in automatically raising an error, with no attempt to parse
        the error response body.

        If set to None, or if method not mapped in dict, the defaults are:

        `DefaultStatusSetToRaiseForSending` when we send objects, which right now has:
        POST/PUT/PATCH: 400, 401, 403, 500-599

        And this for get/delete (work not done yet in RestClient to check this for GET/DELETE).
        GET/DELETE: 400-599
    """

    def __init__(self, api: "RestApi[M]"):
        super().__init__(api)
        from xmodel_rest import RestModel
        if not issubclass(api.model_type, RestModel):
            raise XynRestError(f"You have created a rest api with a model type ({api.model_type}) "
                               f"that is not a subclass of RestModel.")

    # todo: create public alias: `plain_request = _wrap_request`
    # todo: xyndw likes to execute custom requests but take advantage of the _wrap_request.
    #
    # todo: I think it might also want to auto-use my auth-class. I think it would be nice
    # todo: to have an easy-way to execute a Requests.request object with my auth and wrapper.

    # ------------------------------------------------
    # --------- Send Requests to API Methods ---------

    def delete_obj(self, obj: M):
        """
        Calls `RestClient.delete_objects` with passed in object in a list.

        Args:
            obj (xynlib.orm.rest.model.RestModel): model to delete.
        """
        self.delete_objs([obj])

    def format_body_for_delete(
        self, objects: Sequence[Tuple[RestModel, JsonDict]], url: URLMutable
    ):
        return None

    def delete_objs(self, objs: Iterable[M], url: URLStr = None):
        """
        Allows you to delete a bunch of objects, bulk-deleting if possible.
        Automatically falls back to one at a time if necessary.

        Regardless of how it does it, it will attempt to delete every object passed in.

        The objects must have their `xynlib.orm.rest.model.RestModel.id` set to something,
        otherwise they will be skipped.

        Args:
            objs (Iterable[xynlib.orm.rest.model.RestModel]): The objects to delete
                (only attribute needed on them is `xynlib.orm.rest.model.RestModel.id`).
            url (xynlib.url.URLStr): Optional URL to append onto final URL.
        """
        # Note for future: Keeping `objs` declared as an Iterable for use with generators in the
        # future [etc, etc].
        preped_objs = self._create_deque_verify_and_reset_http_state(objs)
        url = URL.ensure_url(url)

        def do_delete_request(url: URL, objects: Sequence[M]):
            # todo: Move this into `_wrap_request`, pass in high-level url object to it.
            url = URLMutable(url)
            url_methods = url.methods
            assert len(url_methods) == 1, (
                f"Should only be one method ({url_methods}) for url ({url}) for delete."
            )

            id_list = list(map(lambda x: x.id, objects))
            # todo: We don't format 'query' params right now inside URL [only the path portion]
            #       so for now we need to do that ourselves here. But in the future, we could
            #       generalize it and have URL format the query param for us!!!
            if not url.singular:
                url.query_add(
                    key="id",
                    value=id_list,
                )

            json_body = self.format_body_for_delete(objects, url)

            url_str = url.url()

            response = self._wrap_request(
                lambda: self._requests_session.request(
                    method=url_methods[0],
                    url=url_str,
                    auth=self.auth.requests_callable(self.api.settings),
                    json=json_body,
                    timeout=30
                ),
                creating_objects=False
            )

            if response.status_code >= 300:
                log.error(
                    f"[DELETE]: Non-Success Status ({response.status_code}) from url "
                    f"({url}) - see debug log level for raw response."
                )

                for obj in objects:
                    obj.api.response_state.had_error = True

            text = response.text
            if text is not None and len(text) > 0:
                log.debug(
                    f"RestClient.delete_objs() - url ({url}) - raw response ({response.text})"
                )

        def debug_log_item(item):
            log.debug(f"Sending DELETE for ({item})")

        self._do_http_method_on_objs(
            objects=preped_objs,
            url_generator=self.url_for_delete,  # noqa: See note about python 3.8
            object_to_request_item=lambda x: x,  # No need to do any extra work
            request_item_to_obj=lambda x: x,  # No need to do any extra work
            log_request_item=debug_log_item,
            request_generator=do_delete_request,
            send_limit=100,
            url=url
        )

    def send_objs(
            self, objs: "Iterable[RestModel[M]]", *, url: URLStr = None, send_limit: int = None
    ):
        """
        Sends `objs` to the API as efficiently as possible. If you specify `url`, it will be
        appended onto the final candidate url via `xynlib.url.URLMutable.append_url`.
        If the url is still valid (via `xynlib.url.URL.is_valid`) then that's the final
        url that will be used.

        See `RestClient.url_for_endpoint` for details on how the base URL is found and then how
        our passed in url is appended and final url is formatted.

        Args:
            objs (Iterable[xynlib.orm.rest.model.RestModel]): Objects to send to API.
                If an object has not changes and `RestClient.enable_send_changed_only` is `True`
                then it will be skipped.  Otherwise the entire object is sent.

            url (xynlib.url.URLStr): url to append to final candidate url.

            send_limit (int): How many objects to send at a time (batch size).
                Leave as None to use the default. You can override it by passing a number here.

        Returns:

        """
        url = URL.ensure_url(url)

        def model_to_request_item(obj: "RestModel[M]") -> "Optional[Tuple[RestModel, JsonDict]]":
            json: JsonDict = obj.api.json(
                only_include_changes=self.enable_send_changes_only,
                log_output=True
            )
            if json is None:
                log.debug(f"API Obj {obj} did not have any changes to send, skipping.")
                return None
            # Make a tuple and return it as one of the items to send to `_send_objs_to_url`.
            item = (obj, json)
            return item

        def request_item_to_model(item: Any):
            return item[0]

        def debug_log_item(item):
            log.debug(f"Sending JSON ({item[1]})")

        starting_objects = list(xloop(objs))
        objs_by_endpoint = self._create_deque_verify_and_reset_http_state(starting_objects)
        self._do_http_method_on_objs(
            objects=objs_by_endpoint,
            url_generator=self.url_for_send,  # noqa: See note about python 3.8
            object_to_request_item=model_to_request_item,
            request_item_to_obj=request_item_to_model,
            log_request_item=debug_log_item,
            request_generator=self._send_objs_to_url,
            send_limit=send_limit,
            url=url
        )

        # If no unhandled error happened (ie: exception),
        # we will get to this point.
        for obj in starting_objects:
            obj.api.did_send()

    # ---------------------------------------
    # --------- GET via API Methods ---------

    def get(
            self,
            query: Dict[str, Any] = None,
            *,
            top: int = None,
            fields: Union[FieldNames, DefaultType] = Default,
    ) -> Iterable[M]:
        """
        Returns result of calling `RestClient.get` with the query converted into a URL for you.

        Args:
            fields (xynlib.orm.types.FieldNames): You can pass in a list of fields.
                We will attempt to pass this to API if
                possible. The idea is the API will only return the list fields.
                If the API honors it, then they will be the only ones set on the objects.
                If the API returns more fields, they will still be set on the object.

                The field 'id' will always be included as a field,
                no need to add that one your self.

                If `xynlib.orm.types.Default` or Empty List (default):
                All fields will be retrieved except the ones ignored by
                (set via `xynlib.orm.fields.Field.exclude`,you can get the full list
                via `xynlib.orm.base.structure.BaseStructure.excluded_field_map`).

                If `None`: Nothing about what fields to include/exclude will be passed to API.
                It should grab everything.

            query: Dictionary for query filters.
            top: Top/Maximum number of objects to return.
        Returns:
            Iterable[xynlib.orm.rest.model.RestModel]: A `Generator`, that when ran will return all
                model objects one at a time (paginating as needed while running the generator).
        """
        comps = None
        if query:
            comps = URLMutable().append_query(query)

        return self.get_url(comps, top, fields=fields)

    def get_url(
            self, url: URLStr = None, top: int = None,
            fields: FieldNames = Default
    ) -> Iterable[M]:
        """
        The most basic public method for get requests to API.

        Executes a basic GET request for URL, and returns back a list of objects base
        on the BaseApi you pass in.  If `top` defined, we will append a 'limit' query param
        for you and only return at most that many regardless of how many are really
        returned from BaseApi.

        Args:
            fields (xynlib.orm.types.FieldNames): You can pass in a list of fields.
                We will attempt to pass this to API if
                possible. The idea is the API will only return the list fields.
                If the API honors it, then they will be the only ones set on the objects.
                If the API returns more fields, they will still be set on the object.

                The field 'id' will always be included as a field,
                no need to add that one your self.

                If `xynlib.orm.types.Default` or Empty List (default):
                All fields will be retrieved except the ones ignored by
                (set via `xynlib.orm.fields.Field.exclude`,you can get the full list
                via `xynlib.orm.base.structure.BaseStructure.excluded_field_map`).

                If `None`: Nothing about what fields to include/exclude will be passed to API.
                It should grab everything.

            url (xynlib.url.URLStr): URL to append on the end of the final constructed URL.
                If you specify `url`, it will be
                appended onto the final candidate url via `xynlib.url.URLMutable.append_url`.
                If the url is still valid (via `xynlib.url.URL.is_valid`) then that's the final
                url that will be used.

                See `RestClient.url_for_endpoint` for details on how the base URL is found and then
                how our passed in url is appended and final url is formatted.
            top (int): The maximum number of objects to iterate though via returned `Generator`.
                We will attempt to tell API to limit the returns results to this.
                But even if API returns more objects in the response only this many objects will
                be returned (via Generator). We will also paginate though result set until
                we get enough objects. We will return less then what you pass in here if
                after paginating the results there are no more left.
        Returns:
            Iterable[xynlib.orm.rest.model.RestModel]: A `Generator`, that when ran will return all
                model objects one at a time (paginating as needed while running the generator).
        """

        url_for_reading = self.url_for_read(url=url, top=top, fields=fields)
        return self._get_objects(url_for_reading, top, fields)

    # ------------------------------------------
    # --------- Implementation Details ---------

    # noinspection PyRedeclaration
    @property
    def auth(self) -> RestAuth:
        """
        This is the auth object used by client, to set what type should be used for this,
        in your `xynlib.orm.base.api.Api` sub-class, make a type-hint like this in the
        Api subclass definition:

        >>> from xmodel_rest import RestApi, RestAuth
        >>> from typing import TypeVar
        >>>
        >>> class MyAuth(BaseAuth):
        >>>    pass  # Put your auth stuff here
        >>>
        >>> M = TypeVar("M")
        >>> class MyApi(BaseApi[M]):
        ...     auth: MyAuth

        Doing that is enough, `xynlib.orm.base.api.Api` will see the type-hint and will grab one of
        that
        type from the `xynlib.context.Context`. `RestClient` gets `xynlib.orm.base.auth.BaseAuth`
        instance from `xynlib.orm.base.api.Api.auth` via `RestClient.api`.
        In the example above, it would be a `MyAuth`.

        Defaults to `xynlib.orm.base.auth.BaseAuth`, which will not do any auth by default.
        See `xyn_sdk.core.common.Auth` for a concrete subclass that implments auth for
        Xyngular API's.

        """
        return self.api.auth

    # noinspection PyMethodMayBeStatic
    # We want to keep this as non-static, for more flexibility when overriding in subclass.
    def parse_json_from_get_response(
            self,
            *,
            url: URL,
            response: requests.Response
    ) -> Optional[JsonDict]:
        """
        When we have a response for a GET request, this is called to parse the JSON out of it.

        For a real-world example of a override of this method (among other overrides) see
        `hubspot.api.common.RestClient`.

        ## Parsing Error

        First thing we look for are handling response-level errors and conditions,
        such as 500 errors. Or situations where there is no valid JSON to extract from the
        response (invalid JSON syntax).

        By default if `response.status_code` is:

        - 404: Log warning.
        - 401/403/5xx/4xx: Raise an XynRestError.
            - We will try to parse JSON to get some more detail out of it to log with;
                we then raise an XynRestError.

        ## Parsing JSON

        This basic REST `RestClient` expects:
        - For multiple results: a dict with a key that has a list of dicts,
            or a list of dicts. We could have a list with just one dict in it.
        - For a request that always has a single result: a single dict is usually what is needed.

        For each of these dict(s), the standard dict-format is:

        >>> {"attr-name": "attr-value"}

        If it's something else, this is normally handled in the
        `xynlib.orm.base.api.BaseApi.update_from_json` / `xynlib.orm.base.api.BaseApi.json` methods
        associated with Model via type-hint on `xynlib.orm.rest.model.RestModel.api`.
        You can override theose methods to manipulate the json-dict you get passed
        to the standard format before passing it to the `super()` implementation.
        You can see an example of this in `hubspot.api.common.BaseApi.json`.

        If the structure outside of the dict is diffrent, then that's handled in this
        method unless the only diffrence is the key used to get the multiple results.
        You can easily configure the key to use to get the multiple results list via
        `xynlib.orm.base.structure.BaseStructure.multiple_results_json_path`.

        Example of settting `xynlib.orm.base.structure.BaseStructure.multiple_results_json_path`:

        >>> from xmodel_rest import RestModel
        >>>
        >>> class MyModel(
        ...     RestModel["MyModel"],
        ...     multiple_results_json_path="response_list"
        ... )
        ...     first_name: str
        >>>
        >>> # A response like this from API would now work correctly with MyModel:
        >>> {
        ...     "response_list": [
        ...         {"id": 1, "first_name": "Gordan"}.
        ...         {"id": 2, "first_name": "JD"}
        ...     ]
        ... }

        Most of the attributes `xynlib.orm.base.structure.BaseStructure` are configurable via
        class arguments, like you see in the above example.
        For more information on this see:

        - `xynlib.orm.base.structure.BaseStructure.configure_for_model_type`
        - `xynlib.orm.base.model.RestModel.__init_subclass__`
        - `xynlib.orm.base.model.RestModel`

        Args:
            url (URL): The URL we got. Keep in mind the auth provider can add or modify URL if
                needed,
                but it won't be visible in the url passed here. Therefore, you can feel free to log
                the url out if needed, as it should not contain any secrets.
            response (requests.Response): The request response, from the Requests library.
                Dive into the JSON, and parse out enough to get a dict for a single object
                or a dict with key to a list of dicts, or a list of dicts.

                See general doc-comment for `RestClient.parse_json_from_get_response` for more
                details.
        Returns:
            Optional[xynlib.orm.types.JsonDict]: None if 404-NotFound response,
                otherwise a JsonDict.
        Raises:
            XynRestError: Raise if there is a 4xx error that is NOT a 404, or a >=500 error.
        """
        status = response.status_code

        if status == 404:
            log.warning(
                f"API result status 404 for GET on url ({url}). "
                f"Returning blank list/None."
            )
            return None

        if status == 401 or status == 403:
            try:
                detail = response.json().get('detail')
            except ValueError:
                detail = response.text

            raise XynRestError(
                f"API result returned unauthorized ({status}) for url "
                f"({url}) detail: ({detail})"
            )

        if status >= 500:
            raise XynRestError(
                f"API result status ({status}) >= 500 for GET on url "
                f"({url}) with raw response text ({response.text})."
            )

        if status >= 400:
            raise XynRestError(
                f"API result status ({status}) is a 4xx (and NOT 404/401/403) for GET on url "
                f"({url}) for response ({response.text})."
            )

        try:
            return response.json()
        except ValueError as e:
            raise XynRestError(
                f"Unparsable JSON in response for status ({status}) for url ({url}) with "
                f"response text ({response.text})."
            )

    def parse_errors_from_send_response(
            self,
            *,  # Tells Python the following are named-arguments only:
            url: URL,
            json: JsonDict,
            response: requests.Response,
            request_objs: 'List[RestModel]'
    ):
        """
        You can override this to provide more details to the individual objects.
        `RestClient` call this to parse the errors into the objects http-state
        (keep reading further below for more about that)
        and will check for error's on the objects and call any error handlers for you.

        .. note:: For more details about error handlers:

            Error handlers let you more easily handle errors on individual objects,
            since this method here will hopefully parse the error details in such a
            way to easily check for then.

            Ways to add Error Handlers and what they may use to check for errors and retry sends:

            - `xynlib.orm.options.ApiOptions.error_handler`
            - `xynlib.orm.http_state.HttpState.error_handler`
            - `xynlib.orm.http_state.HttpState.has_field_error`
            - `xynlib.orm.http_state.HttpState.retry_send`

        For a real-world example of a override of this method (among other overrides) see:

        - `hubspot.api.common.RestClient`.
        - `xyn_sdk.core.common.RestClient.parse_errors_from_send_response`

        By default, this method simply sets the `xynlib.orm.http_state.HttpState` you can
        get this object via `xynlib.orm.base.api.BaseApi.http` state of each request_objs with:

        - `xynlib.orm.http_state.HttpState.response_code` = Response code.
        - `xynlib.orm.http_state.HttpState.had_error` = `True`
        - `xynlib.orm.http_state.HttpState.errors` = A list with the
            `response.text` as the only item.
            - And override of `RestClient.parse_errors_from_send_response` can provide more list
                items and other info (keep reading below for more details).

        After doing that by default this method will get
        `RestClient.method_status_to_raise_by_default`
        and if there is nothing defined for the method in that dict then we use
        `DefaultStatusSetToRaiseForSending`.

        If the status code is found what is found above or if the status code is
        `>=600` then an `xynlib.orm.errors.OrmError` is raised.

        Feel free to override this method and provide more details in via
        `xynlib.orm.base.api.BaseApi.http`; or do something entirely different.

        .. tip:: Ways to set/provide more detailed error information + retrying

            Using object at `xynlib.orm.base.api.BaseApi.http` you can uses these methods to both
            provide more info and retry request:

            - `xynlib.orm.http_state.HttpState.add_field_error`
            - `xynlib.orm.http_state.HttpState.retry_send`

            You can see a real-world example using these ^ at:

            - `xyn_sdk.core.common.RestClient.parse_errors_from_send_response`
            - `hubspot.api.common.RestClient.parse_errors_from_send_response`
            - `hubspot.processors.update_contact.execute_transactions`

        It is valid to call `xynlib.orm.http_state.HttpState.retry_send`
        using `xynlib.orm.base.api.BaseApi.http`
        via model object's `xynlib.orm.rest.model.RestModel.api`
        in this methods and in any error-handlers if you needed to retry a request for a
        particular object.

        You can even change a field/attribute value on a model object and tell it to retry
        again if you pass `xynlib.orm.http_state.ResponseStateRetryValue.EXPORT_JSON_AGAIN` into
        `xynlib.orm.http_state.HttpState.retry_send`, like so:

        >>> from xmodel.remote.response_state import ResponseStateRetryValue
        >>> from xmodel_rest.model import RestModel
        >>>
        >>> model_obj: RestModel  # <-- Some RestModel Object
        >>> model_obj.api.response_state.retry_send(ResponseStateRetryValue.EXPORT_JSON_AGAIN)

        See docs for `xynlib.orm.http_state.HttpState.retry_send` for more details.

        Args:
            url (xynlib.url.URL): The [almost] final URL that was used to make the request.
                The only thing possibly
                missing is anything the 'Auth' class adds to the URL for authentication purposes
                (which could have been a header and not any URL changes).

                This URL is guaranteed to have one and only method assigned to it, the method used
                for the original request.
            json (xynlib.orm.types.JsonDict): If we were able to parse any json from the response,
                we provide that here.
            response (requests.Response): Response of the request that had the error.
            request_objs (List[xynlib.orm.rest.model.RestModel]): The objects, in the order we sent
                them in the request.
        """
        # If the response was successful, and we don't know what the body contents look like,
        # so there is nothing more to do.  Subclasses of RestClient class should override this
        # method if there are more things inside response body to indicate errors for particular
        # objects if we sent more then one object in the same request.
        if response.status_code < 300:
            return

        # TODO: Consolidate this and self.get_all_objects() error handling logging/exceptions.

        url_methods = url.methods
        assert len(url_methods) == 1, (
            f"Should only be one method ({url_methods}) for url ({url})."
        )

        http_method = url_methods[0]
        status_code = response.status_code

        log.warning(
            f"({http_method}): Non-success request response code ({status_code}) for url "
            f"({url}) with raw response ({response.text})."
        )

        # If we failed due to an authorization issue, we need to stop processing and raise
        # an exception, there is something wrong with our configuration, and we are very
        # likely to keep failing, so might as well stop here.
        status_map = self.method_status_to_raise_by_default
        if not status_map:
            status_map = {}

        # todo: I think I would like to try any error handlers first before defaulting
        #       back to an exception.
        statuses_to_raise = status_map.get(
            http_method, DefaultStatusSetToRaiseForSending
        )

        for obj in request_objs:
            # Communicate to each object about its current api http error status.
            http = obj.api.response_state
            http.had_error = True
            http.response_code = status_code

            # Likely the raw response has more details that pertain to the situation,
            # so just put the response text in the http errors list.
            http.errors = [response.text]

        # >= 600 should never happen, it means that the http server is totally screwed up.
        if status_code >= 600 or status_code in statuses_to_raise:
            try:
                # Try to get some detail out of the response.
                #
                # todo: (
                #     This is Xyngular specific, consider moving this to the
                #     xyn_sdk.core.common.RestClient subclass
                #  ).
                detail = response.json().get('detail')
            except (ValueError, AttributeError):
                detail = None

            raise XynRestError(
                f"API result for url ({url}) returned "
                f"status ({status_code}), with detail "
                f"({detail}) with raw response "
                f"({response.text}) with objects ({request_objs})."
            )

    # -----------------------------------
    # --------- Private Methods ---------
# _objs_by_endpoint

    def _create_deque_verify_and_reset_http_state(
            self, objs: 'Iterable[RestModel[M]]'
    ) -> 'Deque[RestModel[M]]':
        """ Goes though all objects, reset's their http state, verifies they can be used
            by this RestClient object (check's their API object is the same as ours).

            After this, it adds them to a `deque` and returns that.

            .. todo:: I am thinking of separating them by their BaseApi object instance and then
                returning ones that don't match self.api in a separate dict that would let
                the send/delete_objs method
                call the send/delete_objs method on their proper RestClient instance/object
                (ie: redirect call to the correct RestClient instance).
            ..
        """
        # My API, to compare to model's type `RestModel.api` api object.
        api = self.api
        result = deque()

        # todo: Think about separating the objects by their BaseApi/RestClient instance and
        #  redirect call's of ones that don't match self.api to their proper RestClient instance.
        for obj in objs:
            obj.api.response_state.reset()

            if api is type(obj).api:
                result.append(obj)
                continue

            raise XynRestError(
                f"For right now, you can't mix different RestModel object types in the same "
                f"list and send/delete them all in one call to `RestClient.send_objs` or "
                f"`RestClient.delete_objs`.  Separate them into different lists and call"
                f"RestClient separately.\n"
                f""
                f"Details:\n"
                f""
                f"I ({self}) was passed a RestModel object ({obj}) with api "
                f"({type(obj).api}); this api instance normally works with "
                f"({type(obj).api.model_type}) type models.\n"
                f""
                f"I normally only work with ({api.model_type}) type objects, but I got a "
                f"{type(obj).api.model_type} type object instead. "
                f"You can't mix different model types in the same list and send them to the "
                f"same RestClient subclass instance.\n"
                f""
                f"Each RestClient is set to work only with one model type. "
                f"You need to use `{type(obj).api.model_type}.api.client` or "
                f"`obj_instance.api.client` for the correct client instance for that "
                f"model type/object.\n"
                f""
                f"The RestModel.api object instance must match what's put in RestClient.api. "
                f"It could be a single RestClient instance got multiple-different model types "
                f"to send at the same time OR the RestClient class was setup incorrectly."
            )

        return result

    def format_body_for_get(
        self,
        url: URLMutable,
        top: int = None,
        fields: Union[FieldNames, DefaultType] = Default
    ):
        raise XynRestError(
            "We don't know how to generically format this. For now override the method."
        )

    def _get_objects(
        self,
        url: URLMutable,
        top: int = None,
        fields: Union[FieldNames, DefaultType] = Default
    ) -> Iterable[M]:
        """
        Return objects based on URL, internal method only
        [subclasses can call me still if necessary].

        Args:
            url (URLMutable): URLMutable obj that can produce the URL to get the objects.
            top (int): Only return first top/maximum number of objects.
            request_method (function): method used to send request
        Returns:
            Iterable[xmodel_rest.model.RestModel]: Sequence/List of
                `xmodel_rest.model.RestModel` objects.
        """
        api = self.api

        objs = []
        object_count = 0
        obj_type = api.model_type
        structure = api.structure
        multiple_results_json_path = structure.multiple_results_json_path

        # todo: Make this a general option, instead of hard-coded.
        #       Right now the below is for an optimization, it speeds up the API requests.
        #       We don't use the fields at the moment.

        # We want to use the /v1/endpoint/id_value version instead of the /v1/endpoint?id=id_value
        # version if there is a ?id=id_value with a single value in query.

        singular = url.singular

        # todo: figure out a better way [ie: with new singular var or something].
        # singular_id = url.query_id_if_singular()
        # if singular_id is not None:
        #     # So, we want to change the URL from /endpoint?id= to /endpoint/id
        #     # todo: make the primary key name configurable per-api, don't assume it's 'id'.
        #     url.append_path(singular_id)
        #     url.query_remove(key="id")
        #     singular = True

        use_get = HTTPGet in url.methods or len(url.methods) == 0
        if not use_get and HTTPPost not in url.methods:
            raise XynRestError(
                'We are currently only supporting HTTPGet and HTTPPost for retrieving objects.'
            )

        get_child_objects = api.option_for_name("auto_get_child_objects")
        if use_get:
            url = URLMutable(url, methods=(HTTPGet,))
        else:
            url = URLMutable(url, methods=(HTTPPost,))
            # We are assuming for now that the json_body will stay the same and if there is any
            # pagination it will be added to the url as a query param.
        current_url_str = url.url()
        try:
            while current_url_str:
                if isinstance(current_url_str, URL):
                    current_url_str = current_url_str.url()
                if use_get:
                    result = self._wrap_request(
                        lambda: self._requests_session.get(
                            current_url_str,
                            auth=self.auth.requests_callable(self.api.settings),
                            timeout=30
                        ),
                        creating_objects=False
                    )
                else:
                    post_url = URLMutable(current_url_str)
                    json_body = self.format_body_for_get(post_url, top, fields)
                    current_url_str = post_url.url()
                    log.debug(
                        f"Going to read from ({current_url_str}) via (POST) with body "
                        f"({json_body})."
                    )
                    result = self._wrap_request(
                        lambda: self._requests_session.post(
                            current_url_str,
                            json=json_body,
                            auth=self.auth.requests_callable(self.api.settings),
                            timeout=30
                        ),
                        creating_objects=False
                    )

                json = self.parse_json_from_get_response(url=url, response=result)
                if json is None:
                    return []

                results_list = []

                # todo: Handle the `singular is None` option, and examine result and guess.
                if singular:
                    results_list.append(json)
                else:
                    if not isinstance(json, list):
                        if multiple_results_json_path in json:
                            results_list = json[multiple_results_json_path]
                        else:
                            # todo: We could potentially just assume the dict we have is an
                            #   single/normal object (and not a list of them).
                            raise XynRestError(
                                f"Result from api was a dict, but the multiple_results_json_path "
                                f"({multiple_results_json_path}) key was not in the result dict "
                                f"({json}). Did we expect singular or multiple results at "
                                f"url ({url})?"
                            )
                    else:
                        results_list = json
                    if results_list is None:
                        # Might be a single object-result, or no pagination
                        # todo: Consider adapting to no-pagination or single-object response?
                        break

                objs: 'List[RestModel]' = []

                for obj_dict in results_list:
                    objs.append(obj_type(obj_dict))

                if get_child_objects:
                    from xmodel.common.children import bulk_request_lazy_children
                    # todo: idea:  use a `with` statement directly on `api.options`
                    #   have it return object to modify and properly activate it (dynamic class?).

                    # Create new ApiOptionsGroup, that way we can set a few temporary options.
                    # Once the `with` is done it will revert back-to previous ApiOptionsGroup.
                    with ApiOptionsGroup():
                        # We are configuring a context so that when an object retrieves
                        # children of its own type it doesn't recursively grab their children.
                        # I think we can improve this in some way by using an `Options` resource
                        # or some such instead directly.... for now I'm going to leave it like
                        # this.
                        api.options.auto_get_child_objects = False
                        bulk_request_lazy_children(objs)

                for obj in objs:
                    object_count += 1
                    yield obj
                    if top is not None and object_count >= top:
                        return

                # Check if we used the single-result end point.
                if singular:
                    break

                # This is a standard method to find the next page of results url.
                # If the value is None, the while loop will exit for us automatically.
                current_url_str = self.url_for_next_page(
                    original_url=url,
                    json_response=json
                )

        except requests.exceptions.RequestException as exc:
            # Transform this exception into a more standard one, which will eventually be caught
            # and logged out appropriately.
            raise XynRestError(
                f"There was a problem connecting to api endpoint ({url}), "
                f"due to a request exception ({exc}) via ({self})."
            )

    # todo: When we use Python 3.8 (soon), have _URLGenerator inherit from Protocol, we only care
    #   about defining the method signature, don't care about the specific type...
    #   ie: structural subtyping, see https://www.python.org/dev/peps/pep-0544/#callback-protocols
    class _URLGenerator:
        def __call__(self, model_objs: 'List[RestModel[M]]', url: URL) -> Union[
            UseSingularValueType, GeneratedURL, URL
        ]:
            raise NotImplementedError(
                "Use a concrete url generator, "
                "see `xmodel_rest.client.RestClient.url_for_delete` "
                "for an example."
            )

    def _do_http_method_on_objs(
            self,
            objects: Deque[RestModel[M]],
            object_to_request_item: Callable[[RestModel[M]], Any],
            request_item_to_obj: Callable[[Any], RestModel[M]],
            url_generator: _URLGenerator,  # See todo on _URLGenerator, talks about Python 3.8.
            log_request_item: Callable[[Any], None],
            request_generator: Callable,  # See doc-comment for call signature for now.
            send_limit: int = None,
            log_limit: int = 4,
            url: URL = None
    ):
        """
        Internal method to execute a URL (with it's corresponding method) on a set of objects.
        The url_generator passed in produces a URL as it's return value.  This URL should only
        have one method attached to it, the method to use for the request.

        .. todo:: Perhapse make this method public in the near-future.

        Args:
            objects: RestModel objects to send to API.
            url: If provided, URL gets appended to final url before it's validated.
                If valid, the end result is used to connect to API for the request.
            url_generator: Generator for URL, needs a method that can be called like this:

                >>> url_for_send(model_objs=[v[0] for v in objects], url=url)

                See `RestClient.url_for_send` for an example.
            request_generator: Generates and executes request, needs a method that can be
                called like this:

                >>> _send_objs_to_url(url=final_url, objects=buffer_list)

                See `RestClient._send_objs_to_url` for an example.
            object_to_request_item: Generator to convert an object into and item,
                which will eventually be passed to request_generator.
                If requested, we may resend the request without having to convert
                the object again (we will buffer the converted item for you).

                It gets called like this:

                >>> item_to_send_to_request_generator = object_to_request_item(obj)

                see method definition for `RestClient.send_objs` for an example.
            request_item_to_obj: Callable/Method to extract the RestModel object out of the
                item.
            log_request_item: This is a method I can call when I want to log about what
                will be sent for converted item.  If we are going to Post/Patch JSON,
                we would want to log the JSON [for example].

                It gets called like this:

                >>> request_item_send_logger(item)

                Generally, you'll want to log this on the debug log level, something like this:

                >>> log.debug(f"Will send json: {item[1]}")

            send_limit: How many objects to send at a time, defaults to 500.
            log_limit: How many objects to log, defaults to the first 3 sent.
        """
        api = self.api

        if len(objects) == 0:
            return

        if send_limit is None:
            send_limit = self.default_send_batch_size

        # Convert the list objects into a list of dicts to send via json, this holds the json.
        request_objs: List[RestModel[M]] = []

        assert send_limit > 0

        BufferItem = Tuple[RestModel, JsonDict]
        objects: Deque[Union[RestModel, BufferItem]] = objects.copy()

        # todo:
        #  Right now all endpoints support simultaneous update/create with multiple objects
        #  at the same time. If ever need to change this assumption, we can order create first
        #  transactions than updates into separate. For now, I am not going to worry about it.

        # We create a list of objects and their json documents.
        buffer_list: Deque[BufferItem] = deque()
        num_objects_skipped = 0

        def log_about_skipped_objects_if_needed():
            nonlocal num_objects_skipped
            if not num_objects_skipped:
                return
            log.info(f"Skipped ({num_objects_skipped}) because there are no changes to send.")
            num_objects_skipped = 0

        while len(objects) > 0 or len(buffer_list) > 0:
            buffer_count = len(buffer_list)
            objects_count = len(objects)

            if buffer_count >= send_limit or objects_count <= 0:
                log_about_skipped_objects_if_needed()
                model_objs = [request_item_to_obj(i) for i in buffer_list]

                generated_url: Union[UseSingularValue, GeneratedURL] = url_generator(
                    model_objs=model_objs,
                    url=url
                )

                if generated_url and isinstance(generated_url, URL):
                    generated_url = GeneratedURL(url=generated_url, models=model_objs)

                if generated_url and generated_url is not UseSingularValue:
                    buffer_items_to_send: Union[List[BufferItem], Sequence[BufferItem]] = []
                    buffer_items_to_keep: List[BufferItem] = []
                    if len(model_objs) == len(generated_url.models):
                        buffer_items_to_send = buffer_list
                    else:
                        model_hash_ids_for_url = {id(x) for x in generated_url.models}
                        for x in buffer_list:
                            # todo:
                            #  We could 'continue' back to to the `while len(...)...` statement
                            #  above to try to fill in more objects to send if we can't send
                            #  everything right now, so we can maximize how many we send
                            #  pre-request, but that's a future optimization for right now.
                            #  for the moment we are willing to live with sending less
                            #  pre-request then we could theoretically do for simplicity's sake.
                            if id(request_item_to_obj(x)) in model_hash_ids_for_url:
                                buffer_items_to_send.append(x)
                            else:
                                # We will keep these in buffer_list after we send the objects
                                # the url_generator told us we could.
                                buffer_items_to_keep.append(x)

                    final_url = generated_url.url

                    # todo: Lot out at verbose logging level without using the verbose log method.
                    # todo: Figure out how we want to log updates [perhaps just log everything].
                    #
                    # if i < log_limit:
                    #     log.verbose(f"Did Update Obj: {obj}")
                    # elif i == log_limit:
                    #     log.verbose(
                    #       f"Did Update Obj: And many more were updated [log throttled]."
                    #     )

                    # self._send_objs_to_url(api=api, url=final_url, objects=buffer_list)
                    request_generator(
                        url=final_url, objects=buffer_items_to_send
                    )

                    # We are iterating though this in reverse, so we append to the
                    # left of objects [if needed] in the correct order.
                    for buffer_item in reversed(buffer_items_to_send):
                        obj = request_item_to_obj(buffer_item)
                        last_http = obj.api.response_state

                        if not last_http.had_error:
                            continue

                        # Error handler for object could request a retry_send, check for that here.
                        should_retry = last_http.should_retry_send
                        if not should_retry:
                            continue

                        last_http = obj.api.response_state
                        if last_http.try_count > 4:
                            last_http.should_retry = False
                            log.warning(
                                f"We got an object {obj} we are trying to resend, it has "
                                f"a try count of ({last_http.try_count}), and so we will stop "
                                f"retrying to send it as a sanity check."
                            )
                            continue

                        log.info(
                            f"Failed to send {obj}, but it was requested to be retried, "
                            f"with a try-count of ({last_http.try_count})."
                        )

                        last_http.reset(for_retry=True)
                        if should_retry is ResponseStateRetryValue.AS_IS:
                            objects.appendleft(buffer_item)
                        elif should_retry is ResponseStateRetryValue.EXPORT_JSON_AGAIN:
                            objects.appendleft(obj)

                        last_http.should_retry = None

                    buffer_list.clear()
                    buffer_list.extend(buffer_items_to_keep)
                    continue

                log.info(
                    f"Have multiple objects, but can't find endpoint for Model ({api.model_type}) "
                    f"that supports sending multiple objects, attempting to send them as "
                    f"individual/single objects instead (one per-request, multiple requests). "
                )

                # url_for_send should raise an exception for us, this just here as a
                # sanity check to ensure we don't infinite loop.
                assert buffer_count > 1, "Could not find URL to send a singular object."

                objects.extendleft(buffer_list)
                buffer_list.clear()
                send_limit = 1
                continue

            obj_or_buffer_item = objects.popleft()

            if isinstance(obj_or_buffer_item, RestModel):
                item = object_to_request_item(obj_or_buffer_item)
                if item is None:
                    # This means there is nothing to send, so skip to next object, no error.
                    #
                    # We rely on the `object_to_request_item` method to log any needed
                    # info about why it could not send this object. We track the number of skipped
                    # objects so we can post a summary of how many objects where skipped.
                    num_objects_skipped += 1
                    obj_or_buffer_item.api.response_state.did_send = False
                    continue
                buffer_item = item
            else:
                buffer_item = obj_or_buffer_item

            # We could be sending tens of thousands of objects, only log a few of them.
            # todo: override log_limit when 'verbose' logging level is on [on step past debug].
            if buffer_count < log_limit:
                log_request_item(buffer_item)
            elif buffer_count == log_limit:
                obj_count_left = send_limit - buffer_count
                if obj_count_left > len(objects):
                    obj_count_left = len(objects)

                obj_count_left += 1
                log.debug(f"Will send ({obj_count_left}) more objects in request [log throttled].")

            buffer_list.append(buffer_item)
            continue
        log_about_skipped_objects_if_needed()

    def format_body_for_send(
        self, objects: Sequence[Tuple[RestModel, JsonDict]], url: URLMutable
    ):
        """
        If you send us a list or dictionary we will json encode it for you otherwise if you
        pass back a string we will just use that as is.
        """
        return [v[1] for v in objects]

    def _send_objs_to_url(self, url: URL, objects: Sequence[Tuple[RestModel, JsonDict]]):
        """
        This method is used as a request-generator for `RestClient._do_http_method_on_objs`.
        `RestClient.send_objs` is what sets this up.

        `RestClient._do_http_method_on_objs` is used as the main driver, it uses
        `RestClient.url_for_send` as the URL generator, that in turns tells it how to group objects
        into a single-request.  It that uses us here to generate a request and execute it.

        Based on URL, we know the HTTP method + endpoint URL, we construct and execute request
        to send objects there.

        Response is parsed for errors via `RestClient.parse_errors_from_send_response`.

        If errors are found, awe also execute any error handler's as needed for any objects
        that have an error.
        `RestClient._do_http_method_on_objs` is responsible for checking for errors and
        calling as a second time with those objects if they need to be retried
        (see `xynlib.orm.http_state.HttpState.retry_send`).

        Args:
            objects: Objects to send; we parse and set error info on any objects as needed.
        """
        api = self.api

        url = URLMutable(url)

        if not objects:
            return

        request_objs = [v[0] for v in objects]
        if url.singular:
            assert len(request_objs) == 1, "Got more objects that url supports"
            request_json = objects[0][1]
        else:
            request_json = self.format_body_for_send(objects, url)

        url_str = url.url()
        assert url_str, f"Passed an invalid url (path: {url.path}) for api ({api})."

        # todo: Move this into `_wrap_request`, pass in high-level url object to it.
        url_methods = url.methods
        assert len(url_methods) == 1, (
            f"Should only be one method ({url_methods}) for url ({url_str})."
        )

        http_method = url_methods[0]

        log.info(
            f"Sending a total of ({len(request_objs)}) objects to url ({url_str}) "
            f"via method ({http_method})."
        )

        # Quick check to see if we are creating any objects or not.
        # If we even have a single create among a sea of updates, say we are creating.
        creating_objects = False
        for o in request_objs:
            if o.id is None:
                creating_objects = True
                break

        try:
            log.debug(f"Going to ({http_method}) to ({url_str}) with ({request_json}) ")
            response = self._wrap_request(
                lambda: self._requests_session.request(
                    method=http_method,
                    url=url_str,
                    json=request_json,
                    auth=self.auth.requests_callable(api.settings),
                    timeout=30
                ),
                creating_objects=creating_objects
            )
        except requests.exceptions.RequestException as exc:
            # Transform this exception into a more standard one, which will eventually be caught
            # and logged out appropriately.
            raise XynRestError(
                f"There was a problem connecting to api endpoint ({url_str}), "
                f"due to a request exception ({exc}) via ({self})."
            )

        status_code = response.status_code
        resp_list = None
        # HTTP 204 means there is 'No Content', ie: they did not return the current obj values
        # after the update happened. So we assume all went well and the values we sent
        # are unchanged after they processed them.
        if status_code != 204 or len(response.text) > 0:
            try:
                resp_list = response.json()
                if resp_list and isinstance(resp_list, dict):
                    structure = api.structure
                    multiple_results_json_path = structure.multiple_results_json_path
                    resp_check = resp_list.get(multiple_results_json_path)
                    if resp_check is not None:
                        resp_list = resp_check
            except (ValueError, KeyError) as e:
                if len(response.text) > 0:
                    log.warning(
                        f"Could not parse JSON from response ({response}). With response text "
                        f"({response.text}) with error({e})."
                    )
                    if status_code < 300:
                        # If we have an OK status [<300], we should be able to parse the JSON.
                        # Re-raise the exception so to continues to propagate.
                        raise e
                else:
                    log.warning(
                        f"Received blank response for response ({response}), assuming we are "
                        f"fine and continuing as normal."
                    )

        for obj in request_objs:
            http = obj.api.response_state
            http.try_count += 1
            http.did_send = True
        http = None

        # TODO: Consolidate this and self.get_all_objects() error handling logging/exceptions.
        self.parse_errors_from_send_response(
            url=url, json=resp_list, response=response, request_objs=request_objs
        )

        if url.singular:
            # We change the JSON to a list, so we can consolidate the multi/single obj code.
            if resp_list:
                resp_list = [resp_list]

        if not resp_list:
            resp_list = []

        # todo: Consider:
        #  Consolidate non-error obj updating into `parse_json_from_get_response`? Rename method
        #  to parse_json_from_response? See below `to-do` under `if not http.had_error:`.

        resp_list_len = 0
        if response.status_code < 300:
            if not isinstance(resp_list, list):
                raise XynRestError(
                    f"We got a response of status OK ({response.status_code}) but the result was "
                    f"not in a list, it was instead a ({type(resp_list).__name__}) for "
                    f"url ({url})."
                )
            resp_list_len = len(resp_list)

        for i, obj in enumerate(request_objs):
            obj: RestModel

            # We did not get anything in the response body, probably an async operation
            # on their end and so we have nothing else to do.
            # I know hubspot can return a 202 without a body for bulk-importing of contacts.
            response_json: Optional[Dict[str, Any]] = {}
            if i < resp_list_len:
                response_json = resp_list[i]

            http = obj.api.response_state

            if not http.had_error:
                """
                    Example Xyngular API Ok Response:
                  {
                    "status_code": 201,
                    "status_text": "Created",
                    "data": {
                      "id": 5,
                      "url": "http://127.0.0.1:49120/v1/presclub/point_events/5",
                      "point_type_url": "http://127.0.0.1:49120/v1/presclub/point_types/1",
                      "account_id": 123,
                      "event_date": "2010-03-03",
                      "points_earned": 100,
                      "description": "Some Desc",
                      "detail": {},
                      "waiver": false,
                      "created_at": "2017-09-12T22:11:41.352839Z",
                      "updated_at": "2017-09-12T22:11:41.352867Z"
                    }
                  }
                """

                if not response_json or not isinstance(response_json, dict):
                    continue

                # todo: Move this into something in xyn_sdk.core.common.RestClient
                #   we want to make this specific to Xyngular api's only [vs hubspot, etc].
                #   for now if we have a 'data' element, use that if it's a dict, otherwise
                #   just use the entire response.
                #
                # todo: Another Idea: Instead of doing what I am talking about above, just switch
                #   to always sending the full response data and having the BaseApi class parse
                #   out the 'data' or whatever else it needs [I do that for hubspot current].
                obj_resp_data = response_json.get('data')
                if obj_resp_data and isinstance(obj_resp_data, dict):
                    obj.api.update_from_json(obj_resp_data)
                else:
                    obj.api.update_from_json(response_json)
                continue

            # Next, if the obj had an error, we call their error handler if they have one.
            error_handlers: List[ErrorHandler] = []
            if http.error_handler:
                error_handlers.append(http.error_handler)

            error_handlers.extend(obj.api.option_all_for_name('error_handler'))

            # todo: Have a catch-all error handler @ self.error_handler or some such...

            handled = False
            for handler in error_handlers:
                if handler(obj, http, url) or obj.api.response_state.should_retry_send:
                    # If the error on the object was handled or the object was marked to retry
                    # sending we will say it was handled.
                    handled = True
                    break

            if handled:
                # Error was handled in some way, no need to log about it.
                continue

            if not obj.api.response_state.should_retry_send:
                # If we did not handle it or are not going to retry to send it, log out details
                # about this object's error.
                log.error(
                    f"Had error for url ({url_str}) while updating object ({obj}) "
                    f"via ({http_method}) with full response ({response_json})."
                )

    def _wrap_request(
            self, handler: Callable[[], requests.Response], creating_objects: bool
    ) -> requests.Response:
        """
            Used internally to make requests, and will do some standard error checking.

            If it decides the entire request needs to be resent, it will call handler a second
            time.
            This could happen, for example, if an auth token has expired, and it refreshed it
            and so the call should be attempted a second time.

            If the error happens a second time, or if the original error was not recoverable,
            then the errored response will be returned from handler.  If the second request is
            successful, then that will be the response that is returned.

            .. important:: This request retrying ONLY happens if the entire request failed, and
                it's determined it's safe to retry the request
                (ie: no chance of accidentally making more objects a second time).

                Otherwise, retrying individual objects is handled via the standard error
                handlers and retrying mechanism.

                For details on that see:

                - `RestClient.parse_errors_from_send_response`
                - `RestClient.parse_json_from_get_response`

        Args:
            handler: Called to construct a ready to use request. May be called a second time
                if the original request has an issue, and we determine we can resend it.
            creating_objects: True if we could possibly create objects/resources.
                If we are only updating existing ones, or getting/deleting them, then pass in
                False. If this is True we have to limit what error codes we will trigger a re-try
                of the request on, to be safe.

        Returns:
            requests.Response: The response.
        """
        retry_requests = self.api.settings.retry_requests

        # Default retry_requests to True.
        if retry_requests is Default:
            retry_requests = True

        try:
            response = handler()
        except (ConnectionResetError, ConnectionAbortedError, ConnectionError, Timeout) as e:

            if not retry_requests:
                raise

            log.warning(
                f"We had the connect reset or abort with exception ({e}). "
                f"Will reset the requests session and then attempt the request a second time "
                f"before giving up."
            )

            # Next time the current requests Session is asked for, we will generate a new Session.
            # This forces a new connection to be used.
            # We don't want to attempt to reuse any of the old connections, to be safe.
            Session.grab().reset()

            if creating_objects and isinstance(e, ReadTimeout):
                # We reset the connection so the next time we try to use the connection it gets
                # a new one. But we are not retrying the request, so it doesn't attempt to create
                # a second object (We don't know if the original request made it to the server).
                raise

            # If we get error this second time, let the exception propagate.
            response = handler()

        request: requests.PreparedRequest = response.request

        if response.status_code in [401]:
            # We want to try to refresh the token and try request again.
            log.warning(
                f"Executed request and got response status ({response.status_code}), going to "
                f"attempt refreshing token and then retrying the ({request.method}) request with "
                f"url ({request.url})."
            )
            self.auth.refresh_token(settings=self.api.settings)
            response = handler()
            request = response.request

        if not retry_requests:
            return response

        status_codes_to_retry = {500, 502, 503}
        if not creating_objects:
            status_codes_to_retry.add(504)

        if response.status_code in status_codes_to_retry:

            log.warning(
                f"Executed request and got response status ({response.status_code}), going to "
                f"attempt to retry the ({request.method}) request with url ({request.url})."
            )

            # If it's a 502/503/504, then try request again before giving up.
            response = handler()
            request = response.request

        # Whatever the latest response is at this point, return it.
        return response

    # -------------------------------
    # --------- URL Methods ---------

    def url_for_read(
            self, *,
            url: URL,
            top: int = None,
            fields: FieldNames = Default
    ) -> URLMutable:
        """
        Given an url, top; returns the URL that should be requested for a read/get.

        `RestClient.root_read_url` is used a the root_url (see `RestClient.url_for_endpoint`).

        The `id` query value is used to determine if we should look for singular or non-singular
        URL's first.  If that does not work, I look at all of them.
        See `RestClient.url_for_endpoint` and it's `singular_values` Args doc for more details
        about this (we pass in None for this arg to that method).

        By default, look only for URL's that support url.HTTPGet.

        .. todo:: Put in correct API error class below

        If we can't find a valid url, will raise an XynRestError.

        Args:
            url (xynlib.url.URL): Appended to endpoint url(s), first valid url will be used.

            fields (Sequence[str]): You can pass in a list of fields, which will be the only ones
                returned in the objects.
                The field 'id' will always be included, no need to add that one your self.

                If `xynlib.orm.types.Default` or Empty List (default):
                Then all fields will be retrieved except the ones ignored by default.

                .. note:: `xynlib.orm.base.structure.BaseStructure.excluded_field_map` is used if
                    fields is left as Default as a way to exclude specific fields
                    by default.

                If `None`: Nothing about what fields to include/exclude will be passed to API.
                It should grab everything.

            top: If provided, provides a 'max' of how many results pre-request should come back.
        Returns:
            xynlib.url.URLMutable: Best url to use from among the candidate urls.
        """
        api = self.api

        excluded_field_map = api.structure.excluded_field_map()
        only_fields: Optional[Set[str]] = None
        ignore_fields: Optional[Set[str]] = None

        extra_query: Query = {}

        if fields is not None:
            if fields and fields is not Default:
                only_fields = set(xloop(fields))
            elif excluded_field_map:
                # noinspection PyTypeChecker
                ignore_fields = excluded_field_map.keys()

        # todo: For now, assume fields are specified this way, split it out later when we need to.
        if only_fields:
            only_fields.add('id')
            # It may be ok with a `set`, but just use a `list` for now.
            extra_query['field__in'] = list(only_fields)
        elif ignore_fields:
            extra_query['field!__in'] = list(ignore_fields)

        # Append user provided url on-top of the extra_query, the passed in url overrides any
        # conflicting values provided.
        if extra_query:
            url = URLMutable(query=extra_query).append_url(url)

        final_url = self.url_for_endpoint(
            root_url=URL.ensure_url(self.root_read_url), url=url, methods=(HTTPGet,)
        )

        formatting_options = final_url.formatting_options or DefaultQueryValueListFormat

        limit_name = formatting_options.query_limit_key or "limit"
        max_limit = formatting_options.query_limit_max
        query_limit_value = None
        if limit_name in final_url.query:
            query_limit_value = final_url.query.get(limit_name)

        final_limit_value = None
        if top:
            # Top has the highest priority and will override anything passed into the query.
            if max_limit and top > max_limit:
                # Some endpoints have a max query limit which we will respect here.
                final_limit_value = max_limit
            else:
                # The top value was fine, so we will add or override the limit in the query for
                # the final url.
                final_limit_value = top
        elif query_limit_value:
            # This will be overridden if it is higher than the configured max limit, otherwise we
            # will leave it alone within the final url.
            if max_limit and query_limit_value > max_limit:
                final_limit_value = max_limit
        elif formatting_options.query_limit_always_include:
            # We want to set the limit, but we will not be able to if there was no top,
            # manual query limit, or max limit configured.
            # TODO: We may want to raise an exception saying the max_limit was not configured and
            #  that query_limit_always_include depends on that value. Or have a hardcoded value
            #  we default to.
            if max_limit:
                final_limit_value = max_limit

        if final_limit_value:
            final_url.query_add(limit_name, final_limit_value)

        return final_url

    def url_for_next_page(
            self, original_url: URL, json_response: JsonDict
    ) -> Optional[URLStr]:
        """
        This is called to get next url to call for next page of results in a GET request.
        If you return `None`, then pagination will stop.

        By default we just get `next` attribute in JSON response and return that.
        You can see an alternative real-world example at
        `hubspot.api.common.RestClient.url_for_next_page`. That shows how hubspot API does
        pagination and how it's communicated to ORM library.

        Args:
            original_url (xynlib.url.URL): The current url that was just requested,
                as a URL object.

            json_response (xynlib.orm.types.JsonDict): The response as a JSON dict from the
                requested_url.

        Returns:
            xynlib.url.URLStr: Can either by a `xynlib.url.URL` or a url as a `str`.

            None: pagination stops.
        """
        # Standard Xyngular API's have a 'next' field that has a full URL to request next.
        return json_response.get('next', None)

    def url_for_delete(
            self, *, url: URL, model_objs: Sequence[RestModel]
    ) -> URLMutable:
        """
        Simply calls `RestClient.url_for_endpoint` and returns the result; with
        `xynlib.url.HTTPDelete`
        as the only `methods` arg and singular_values set as `(True, None)` if there is more
        than one `model_objs` or `(False,)` if there is only one object to delete.

        See `RestClient.url_for_endpoint` for more details.
        You may also glean some more insight from `RestClient.url_for_send` and
        `RestClient.url_for_read`.

        Args:
            url (xynlib.url.URL): This is passed to `url` arg on `RestClient.url_for_endpoint`.
                It's supposed to be the final url appended to the resulting URL via
                `xynlib.url.URLMutable.append_url`.
            model_objs (Sequence[xynlib.orm.rest.model.RestModel]): Objects to delete.

        Returns:
            xynlib.url.URLMutable: Final url used to delete the passed in objects.

        """
        have_multiple_models = len(model_objs) > 1
        return self.url_for_endpoint(
            url=url,
            methods=(HTTPDelete,),
            singular_values=(False,) if have_multiple_models else (True, None),
            secondary_values=model_objs,
            raise_if_none=not have_multiple_models
        )

    def url_for_send(
            self, *, model_objs: Sequence[RestModel], url: URL = None
            # todo: `GeneratedURL` revamp!!!!
    ) -> Union[GeneratedURL, UseSingularValueType]:
        """
        We have more than one model object, we return UseSingularValue if we can't find a valid url
        to indicate that a single model object should be tried instead of multiple.

        If we only have a single, we will raise an exception.

        If we send back a result, it's a `GeneratedURL`. This `GeneratedURL` contains the
        `xurls.URL`
        to use plus the model objects that are valid for this URL.

        You must call us again
        in the future with the other object(s) that did not make it the first time to get
        their URL. If you call us back a second time with other objects in addition to the ones
        that were previously skipped, we may still skip the previously skipped ones again. Just
        keep calling us over and over and eventually everything will have a URL to send it with
        or you will get an exception.

        The RestModel classes have an ordered list of URLs attached to the class that we try to use
        in order when we need to find a URL to send/get objects.

        By default: We attempt to find a method/url using a prioritized method order.
        We look for he first valid url in this prioritized order.
        I use `RestClient.url_for_endpoint` to find the URL for each method in the priority list
        below.
        The first valid url (`orm.url.URL.is_valid`) is what is used.

        The method priority list is:

        1. `xynlib.url.HTTPPatch`
        2. `xynlib.url.HTTPPost`
        3. `xynlib.url.HTTPPut`

        If a `xynlib.url.URL.is_valid` method/url is not found we go to the next method and try
        again by calling `RestClient.url_for_endpoint` with the proper arguments.

        If one is found, we will return a url to use that method/url first with all objects
        that can use that method/url. It could be only 100 objects are supported in a single
        request (as an example). So we may use the same method/url each time you call us as
        we "paginate" though all the objects to send. We will do as many objects as we can as
        you call us back with this same higher-priority url/method.

        Eventually, all of the objects for this higher-priority url will have been gotten to
        and what are left over (if any) are objects that need a different lower-priority
        method/url.
        When they are the only ones passed into this method, we will use that lower-priority
        method/url.

        This will keep happening until all objects have had a url to use with them.
        If all the objects passed into this method can't find a `xynlib.url.URL.is_valid` url
        to use, then we will raise an `xynlib.orm.errors.OrmError`.

        If you pass us no model objects, we will also raise an `xynlib.orm.errors.OrmError`.
        This usually means you meant to pass in some objcts but did not by mistake.

        Args:
            model_objs: RestModel objects to send.
            url: URL to append to end of final URL. This final URL is checked for validity.
                If it's valid, we will return it.  Otherwise we try other URL's.
        Returns
            UseSingularValue: We are requesting you call us back with a single model object.

            GeneratedURL: The URL and objects to send.
        """
        # We first look for Patch, then Put, and finally a Post method.

        if not model_objs:
            raise XynRestError(
                "For some reason we got passed no model objects when generating url."
            )

        have_multiple_models = len(model_objs) > 1
        methods = [HTTPPatch]

        url = self.url_for_endpoint(
            url=url,
            methods=(HTTPPatch,),
            singular_values=(False,) if have_multiple_models else (True, None),
            secondary_values=model_objs,
            raise_if_none=False
        )

        if url:
            return GeneratedURL(url=url, models=model_objs)

        # Else, we have to figure out if we are creating/modifying objects to select correct
        # http method to use. We look for creation first.

        created = []
        updated = []
        for model in model_objs:
            if model.id is None:
                # We are creating the object, we have no id.
                created.append(model)
            else:
                updated.append(model)

        if created:
            # for now, we send back a single URL that indicates we are only creating.
            url = self.url_for_endpoint(
                url=url,
                methods=(HTTPPost,),
                singular_values=(False,) if have_multiple_models else (True, None),
                secondary_values=created,
                raise_if_none=not have_multiple_models
            )
            if not url:
                return UseSingularValue
            return GeneratedURL(url=url, models=created)

        url = self.url_for_endpoint(
            url=url,
            methods=(HTTPPut,),
            singular_values=(False,) if have_multiple_models else (True, None),
            secondary_values=updated,
            raise_if_none=not have_multiple_models
        )

        if not url:
            return UseSingularValue

        return GeneratedURL(url=url, models=updated)

    def url_for_endpoint(
            self,
            *,
            methods: Iterable[str],
            url: URL = None,
            root_url: URL = None,
            singular_values: Iterable[Union[bool, None]] = None,
            secondary_values: Union[dict, RestModel[M], Sequence[RestModel[M]]] = None,
            raise_if_none: bool = True
    ) -> Optional[URLMutable]:
        """
        Normally, this method is called from:

        - `RestClient.url_for_read`
        - `RestClient.url_for_send`
        - `RestClient.url_for_delete`

        To construct the final URL.

        Returns a copy of full/appended `xynlib.url.URLMutable` for the endpoint for the api
        passed, along
        with the root_url and url passed in.

        The resulting URL that is returned will only have one `xynlib.url.URL.methods`
        assigned to it, which is the first method we found a valid url for in the order
        in which you specify them. You can use this method to figure out what HTTP method is
        needed.

        Look at `xynlib.url.URL.is_valid` for more information about how `xynlib.url.URL`'s
        are valid.

        `xynlib.url.URL` Construction Process
        (when it says append, it's using `xynlib.url.URLMutable.append_url`):

        1. Start with passed in `root_url`, or a blank `xynlib.url.URL`
           if `root_url` is `None` (default).
        2. Append `RestClient.base_api_url` if not None, otherwise RestSettings.api_url.
        3. Append `RestClient.base_endpoint_url`.
        4. Append `xynlib.orm.rest.RestStructure.base_model_url` from
           `xynlib.orm.base.api.BaseApi.structure` via `RestClient.api`.
        5. Loop though singular_values, followed by methods, and finally each model_urls,
           in that order.
            - Append model url, and check if it's valid. If it is not, continue looping.
            - Return the first valid url that is found.

        Take a look at docs for `xynlib.orm.rest.RestStructure.base_model_url` for some
        more details.

        Args:
            root_url: A url that is the starting-point for any generated candidate url that we
                consider. If you don't provide one, a blank-url is the starting point.

                Sometimes we have special base-url's depending on if we are trying to get or send
                an object. An example of one is `RestClient.root_read_url`, which is passed in as
                the `root_url` arg when attempting to do a get request via
                `RestClient.url_for_read`
                (side note: we should have called it `root_url_for_read` probably).

            url: After calculating a candidate endpoint url, we append this to it before checking
                the url's validity. If the url is valid, we return this fully constructed
                candidate url.

                If None, then nothing will be appended to the final candidate endpoint url.

            methods: Only use URLs where at least on of these methods are valid for it.
                If None, methods are not considered when selecting URL.

            singular_values: The order to try singular_values. Only use URLs where this matches
                the singularity of the url. Will try urls in the order provided.

                Example: (True, False) -> So we look at singular url's first, and then
                non-singular.

                The default is a None for the iterable value [ie: `singular_values = None`];
                this means singularity is preferred based on how many values are in the
                url's 'id' query parameter. But it will ultimately consider all urls when
                looking though url list.

                If a value inside the iterable is None [ie: `(True, None)` or some such],
                the `None` value will force us to look at all urls
                [regardless of their singularity] based purely on their order.

            secondary_values: Backup list of values to use if url can't satisfy a formatting
                placeholder it's self.

            raise_if_none: Raise an XynRestError instead of returning None when we can't find a
                valid URL.
        """

        # TODO - TODO - TODO: return METHOD to use, and if response will contain obj data...

        api = self.api
        structure = api.structure

        if structure.base_model_url is False:
            raise XynRestError(
                f"RestClient was asked to do something with api RestModel type ({api.model_type}),"
                f" but the model has a False for it's base_url, that means it does not have an "
                f"API endpoint the client ({self}) can use.."
            )

        base_model_url = URL.ensure_url(structure.base_model_url)

        # May consider caching this in the future.
        api_url = self.base_api_url or api.settings.api_url

        # we do a copy here for efficiency/safety-purposes. We will get an error if we try
        # to modify it. We don't want to modify it accidentally after this point.
        base_url = (
            URLMutable(root_url)
            .append_url(api_url)
            .append_url(self.base_endpoint_url)
            .append_url(base_model_url).copy()
        )

        # Figure out a good default for singular_values if needed.
        if singular_values is None:
            #  For now we are assuming 'id' as special throughout, if we do add standard
            #  generic way to remap id, pay attention to that here.
            #
            #  todo: When we must remap id, we do it via overriding `Api.json*` methods at the
            #        moment. I don't have a generic way to do it.
            #
            #   For now we assume if we have a single value, that the 'id' in the query values
            #   is the key to use. We do this consistently across everything at the moment.
            #   The URL list of the model can put this 'id' anywhere (see xynlib.url, formatting).
            id_value = api_url.query_value('id')
            singular_values = (None,)
            if id_value:
                if isinstance(id_value, list) and len(id_value) > 0:
                    singular_values = (len(id_value) == 1, None)
                else:
                    singular_values = (True, None)

        all_candidate_urls_cache: List[URLMutable] = []

        # Generator that will cache the values so you can reuse generator again
        # without having to re-calculate the urls again.
        def all_urls():
            if all_candidate_urls_cache:
                for v in all_candidate_urls_cache:
                    yield v
            else:
                for ep_url in structure.model_urls:
                    # Make a copy, going through a list to try out on the base_url.
                    # We append any url provided by caller, and then check validity.
                    final_url = base_url.copy().append_url(ep_url).append_url(url)
                    all_candidate_urls_cache.append(final_url)
                    yield final_url

        for singular in singular_values:
            for method in methods:
                for candidate_url in all_urls():

                    if singular is not None and candidate_url.singular != singular:
                        continue

                    if not candidate_url.methods_contain(method):
                        continue

                    if candidate_url.is_valid(
                            secondary_values=secondary_values, attach_values=True
                    ):
                        candidate_url.methods = (method,)
                        return candidate_url

        if raise_if_none:
            raise XynRestError(
                f"Could not find valid URL from base_url ({base_url}) + url ({url}) for API {api} "
                f"for methods ({methods}), singular ({singular_values}), "
                f"secondary values ({secondary_values})."
            )

        return None

    @property
    def _requests_session(self) -> requests.Session:
        return Session.grab().requests_session
