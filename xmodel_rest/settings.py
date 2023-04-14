from xsentinels import Default

from xinject import Dependency
from xurls import URLStr, URLMutable, URL
from xsettings import Settings, SettingsField
import dataclasses
from copy import deepcopy
from typing import TypeVar

T = TypeVar("T")


class RestSettings(Dependency):
    """
    A basic ConfigType subclass with a few basic features that are useful.

    To see RestSettings class used by the Xyngular-API classes see:
    `xyn_sdk.core.common.RestSettings`.

    You can subclass this or `xynlib.orm.remote.settings.RestSettings` if you want a more basic
    version for other types of client. But when using the `xynlib.orm.rest.client.RestClient`
    it's expected to use `RestSettings` (or a subclass of `RestSettings`).

    You can use a custom-subclass of `RestSettings` by  creating a custom
    `xynlib.orm.base.api.BaseApi` subclass
    and then setting the type-hint for `xynlib.orm.base.api.BaseApi.settings` to you custom
    settings class.

    For more details see
    [Use of Type Hints for Changing Type Used](./api.html#use-of-type-hints-for-changing-used-type)

    ## Details when using `xsettings.Settings` with RestSettings

    You can use a `xsettings.Settings` as part of your subclass,
    just re-define the `root_url` and `base_api_url` as type-hints,
    and add any others you need.


    .. todo:: I want to have this inherit from `xsettings.Settings`, but I need to
        add support for inheritance from another `xsettings.Settings` class.
        Should be easy to add in, just need to do it sometime.
        Don't have time right now, so leaving this todo here for now.
        It would allow us to remove the properties below,
        as settings would automatically raise an exception with a nice message,
        and it would allow sub-classes of this to inherit the settings-fields
        so they don't have to redefine them again in their own Settings subclass.
    """

    root_url: URLStr = URLMutable()
    """ The basis for urls returned by `self.api_url`.
        You can set global defaults for all URL's that base them selves on this here.
    """

    retry_requests: bool = Default
    """
    If Default/True (default): Will retry some types of requests such as ones responding with
    specific 5xx errors; or if there is a connection or timeout error.

    They will be retried once before falling back on the standard library error handling.

    If False: Won't retry, will return result without retrying it.

    The class/default value is `Default`, to help support xyn-sdk, so that by default the Settings
    retriever/default values in Settings subclass will be consulted first.

    Eventually, we may create a xyn-settings v2 to handle this better, for now
    we need to keep it as `Default` at the class-level here.

    TODO: In the future if needed: This could be a `Union[Callable, bool]`, where you could assign
    a callable that would be able to decide with logic based on the response it's handed if we
    should immediately retry the full/entire request or not.
    """

    # Must put value here so pdoc3 will see the docs for it,
    # so using a property to do that and still get ability to raise an exception if not found.
    # I would have LOVED to use `xsettings.Settings` field
    # instead, but I can't until a upgrade it with an ability to use a parent Settings.
    # I have a todo (see class doc-comment above) to do that.
    @property
    def base_api_url(self) -> URLStr:
        """
        The basis for every BaseApi URL. When you call `RestSettings.api_url`,
        the `RestSettings.root_url` is taken and `RestSettings.base_api_url` is appended to it.

        Sub-classes and/or instances of `RestSettings` class need to set this with something.
        I would recommend using something like this in a Config sub-class:

        `base_api_url` = `ConfigVar`("ENV_OR_CONFIG_VAR_NAME")

        >>> from xsettings import Settings
        >>> class MySettings(Settings, RestSettings):
        ...     # Tip: Settings will auto-convert str to URL if needed!
        ...     base_api_url: URL
        >>>
        >>> class MyApi(BaseApi[M]):
        ...     # Tell my BaseApi subclass to use my custom settings
        ...     settings: MySettings
        """
        if self._base_api_url is not None:
            return self._base_api_url

        # AttributeError works with Settings, in case sub-class inherits from Settings,
        # it will inform Settings to try and retrieve value it's self if it can.
        raise AttributeError(
            f'Object {self} must have a non-None `base_api_url` attribute on it,'
            f'it is needed as a basic RestSettings setting value.'
        )

    _base_api_url = None

    @base_api_url.setter
    def base_api_url(self, value):
        # See above base_api_url getter for doc/comments/details.
        self._base_api_url = value

    @property
    def api_url(self) -> URL:
        """
        Returns a new URL with base_url plus base_api_url appended to it.

        This property should be used as the base url that all other urls are appended on for
        all rest api calls using the `xynlib.orm.rest.RestClient`, in general.

        You may have a config that does not need this, because it's a configuring some
        other aspect of the system.  In that case you can ignore this.

        I put this property here so I know I could always call it on a generic ConfigType.
        """
        url = self.base_api_url
        assert url, f"Had no configured url for base api url for ({self})."
        return URL.ensure_url(self.root_url).copy_mutable().append_url(url)

    def copy(self: T) -> T:
        return deepcopy(self)

