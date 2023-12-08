from typing import TypeVar, List, Tuple, Iterable, Union

from .default_model_urls import DefaultModelURLs
from xurls.url import URLStr
from xmodel import Field
from xmodel.remote import RemoteStructure
from xsentinels import Default
from xurls import HTTPGet, HTTPPatch, HTTPDelete, URL


F = TypeVar("F", bound=Field)


class RestStructure(RemoteStructure[F]):
    """
    Rest version fo base `xynlib.orm.base.structure.BaseStructure` class.
    Adds extra common attributes that are used by:

    - `xynlib.orm.rest.api.RestApi`
    - `xynlib.orm.rest.client.RestClient`

    See `RestStructure.configure_for_model_type` for class arguments specific to Rest models.

    See [Basic BaseModel Example](../#basic-model-example) for an example of what class arguments
    are.

    See parent `xynlib.orm.base.structure.BaseStructure` for more options that are common among all
    model types (regardless if they are rest or dynamo).
    """

    def configure_for_model_type(
            self,
            *,
            # todo: consider a different name for `base_url`, the structure object calls this
            #  attribute the `endpoint_base_url` right now.
            base_url: URLStr = Default,
            urls: List[URLStr] = Default,
            multiple_results_json_path: str = Default,
            **kwargs
    ):
        """

        Args:
            **kwargs: For other/base arguments, see super-class method
                `xynlib.orm.base.structure.BaseStructure`.

            base_url (xynlib.url.URLStr): This is appended to
                `xynlib.orm.rest.settings.RestSettings.api_url` as urls
                are constructed from `urls` passed in to determine if the URL is valid and should
                be used.

            urls (List[xynlib.url.URLStr]): List of URL's to traverse, in order.
                Generally speaking, the system will go though these URL's in order, the first valid
                URL that is found is the one that is selected. If you don't provide these then
                we use `DefaultModelURLs`.

                The `xynlib.url.URL.methods` are used to match up the operation, and then
                the URL is valid if it can be formatted with the avalaible information on
                the BaseModel or in URL query.

                Look at `xynlib.orm.rest.RestClient.url_for_endpoint` for more information about
                how the URL find/construction process takes place. This list eventually gets passed
                to the `xynlib.orm.rest.RestClient.url_for_endpoint` method.
                That method runs though this list and determines which URL to use.

                Look at `xynlib.url.URL.is_valid` for more information about how a URL is valid.

            multiple_results_json_path (str): Many API's have a key that is used to contain
                the results, specially if there are more than one of them.
                This allows for pagination and other meta data to be passed back in the response.
                The default value for this is `"results"`.
        """
        super().configure_for_model_type(**kwargs)

        if multiple_results_json_path is not Default:
            self.multiple_results_json_path = multiple_results_json_path

        # Inherit from parent if Default.
        if base_url is not Default:
            self.base_model_url = base_url

        # We inherit the `urls` from parent if they are not provided directly by user.
        if urls is Default:
            if self.model_urls is None:
                self.model_urls = DefaultModelURLs
        else:
            self.model_urls = [*urls]

    multiple_results_json_path = "results"

    _base_model_url: URL = None

    @property
    def base_model_url(self) -> URL:
        """
        Used to store endpoint or the most common portion of all the endpoint urls.
        ie: 'point_events', or other such pieces of the URL.

        The endpoint is the part after the version and namespace in the context/base_path
        that client gets on init, eg: `/v1/presclub/{endpoint}`.

        Example:
          'point_events' could be returned, which could ultimately create this URL:
          /v1/presclub/point_events

          The `xynlib.orm.base.client.BaseClient` provides the version and namespace part of the
          `xynlib.url.URL`.
          So the proper RestClient combined with this endpoint method is how the URL is
          constructed.
        """
        return self._base_model_url

    @base_model_url.setter
    def base_model_url(self, value: Union[URLStr, bool]):
        self._base_model_url = URL(value) if value else None

    _model_urls: Tuple[URL] = None

    @property
    def model_urls(self) -> Tuple[URL]:
        """
        If you need more than one endpoint url, use this. Every URL in this list will be appended
        to the `self.base_endpoint_url` when it's used.

        For more details on how the final url is found and constructed see
        `xynlib.orm.rest.RestClient.url_for_endpoint`.

        If you don't provide any endpoint_urls, then we will create a few standard ones
        automatically, such as "/{id}" (for getting a singular object via id).

        See `DefaultModelURLs` for the default list.

        When routing to the correct url, the first url that provides a valid path for the needed
        method + singular state will be used.  You can use path parameters, and order them to most
        specific to least specific, as we try to get a URL in the order they are defined.

        See:

        - `xynlib.url.URL`: for more details on how path formatting, methods, singular work.
        - `xynlib.orm.rest.RestClient.url_for_endpoint`: details on how final `xynlib.url.URL`
            is constructed.
        """
        return self._model_urls

    @model_urls.setter
    def model_urls(self, value: Iterable[URLStr]):
        self._model_urls = tuple(URL.ensure_url(v).copy() for v in value) if value else None

    @property
    def have_api_endpoint(self) -> bool:
        """ Right now, a ready-only property that tells you if this BaseModel has an API endpoint.
            That's determined right now via seeing if we have any model_urls or not.

            .. todo:: Consider changing this to use
                `xynlib.orm.base.structure.BaseStructure.have_usable_id`
        """
        return bool(self.model_urls)

    @property
    def endpoint_description(self):
        return self.base_model_url
