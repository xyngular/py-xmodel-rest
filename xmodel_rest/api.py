from xinject import XContext
from .client import RestClient
from .errors import XynRestError
from .settings import RestSettings
from xmodel.remote import RemoteApi, RemoteModel
from typing import TypeVar, List, Tuple, Iterable, Union, Type, get_type_hints, TYPE_CHECKING
from logging import getLogger
from xurls.url import URLStr
from xmodel import Field
from abc import ABC
from .structure import RestStructure
from .auth import RestAuth
from xsentinels import Default
from xurls.url import HTTPGet, HTTPPatch, HTTPDelete, URL
from .auth import RestAuth
from .auth import RestAuth
from typing import TypeVar
from .model import RestModel


# It's really bound to `RestModel`, but I need an easier way to tie into lazy-loading
# BaseModel.__init_subclass__ system, so I can lazy-load my own stuff first before it does.
# Decided it was an exercise for future day. We can live with it for now.
M = TypeVar("M", bound=RemoteModel)


class RestApi(RemoteApi[M]):
    """ Base `xynlib.orm.base.api.BaseApi` subclass generally used by Rest API's.

        Things specific and common to rest api's should go in this class.

        See parent `xynlib.orm.base.api.BaseApi` for things in common among all API's.
    """

    # Telling system about the default/base rest types we want to use with `RestApi`.
    client: RestClient[M]
    structure: RestStructure[Field]
    auth: RestAuth
    settings: RestSettings

    # todo: decide if we should just remove the below, not strictly needed, more of a convenience.
    #
    # Only used for IDE so it knows what type should be here, not used to know which Model to
    # allocate object.
    # This is because RestModel will tell/pass this into RestApi via `__init__`,
    # it happens when a RestModel/BaseModel is created (in BaseModel.__init__).
    model: RestModel[M]

    def send(self, url: URLStr = None):
        """ REQUIRES associated model object [see self.model].

        Convenience method to send this single object to API, it simply calls
        `xynlib.orm.base.client.Client.send_objs` with a single object in the list
        (via `xynlib.orm.base.api.BaseApi.model`).

        If you want to send multiple objects, call `xynlib.orm.base.client.Client.send_objs`.

        Example is below, it uses a made-up rest model called 'SomeRestModelSubclass'.

        (I did not provide all details it would need to use the made-up/imagained rest-api;
        trying to illisrate a basic point here is all.
        If you want more details on how to make a real full/valid rest-model subclass
        see #INSERT-README-LINK#.)

        >>> from xmodel_rest import RestModel
        >>> class SomeRestModelSubclass(RestModel, base_url="....etc...."):
        ...     pass  # Some attributes from the rest-api go here
        >>> obj1 = SomeRestModelSubclass()
        >>> obj2 = SomeRestModelSubclass()
        >>> RestModel.api.client.send_objs([obj1, obj2])

        If you pass in a `url` paramater to the `send_objs` method, the url gets appended to the
        final constructed url before the url gets validated.

        If the url is validated, it will use that final url [with passed in `url` this appended].
        For more information about how URL's are appended to each-other see:
        `xurls.url.URLMutable.append_url`.

        The response from API will update all the values on this object with the results
        of the change [all fields will be updated] and with the latest values from API.

        You can check for errors on model object via `xmodel.remote.api.response_state`, ie:

        >>> from xynlib.orm import BaseModel
        >>> obj: BaseModel
        >>> # Check response_state to see if it had an error:
        >>> obj.api.response_state.had_error
        False
        """
        # Redirect to client.send_objs:
        self.client.send_objs([self.model], url=url)

    # This is a resource-type, see `def auth()` doc-comment below for more details.
    # Subclasses can override this type-hint, and `RestApi` will allocate the new
    # type instead automatically, on demand.
    #
    # The type-hints inform this class what type of objects to create when `auth` along
    # with other special attributes such as `client` and `structure` are needed/asked-for.
    #
    # You can override the type by making your own type-hint on a sub-class.
    # See xmodel.base.api.BaseApi and xmodel.remote.api.RemoteApi for its various special
    # type-hinted attributes for more details, it has more detailed comments/documentation on it.
    auth: RestAuth

    @property
    def _auth(self):
        """
        Treated a `xyn_resaource.context.Resource`, a context resource for the purposes of sharing
        auth credentials. The type-hint assoicated with `auth: XYZ` will be used to grab
        a resource of that type from the current context each time we are asked.

        Thus resource is the auth object used by your `xmodel.base.client.BaseClient` subclass,
        (such as `xynlib.orm.rest.RestClient`),
        to set what type should be used for this, in your BaseClient sub-class, make a type-hint
        like below.

        Let's say you have an auth class you want to use:

        >>> import xmodel.base.auth
        >>> import xmodel
        >>> class MyCoolAuthClass(xmodel.base.auth.RelationAuth)
        ...     pass

        You can set a type-hint for it like so, and it will be automatiaclly used when needed:

        >>> class MyApi(xmodel.RemoteApi):
        ...     auth: MyCoolAuthClass

        Doing that is enough, `xynlib.orm.rest.RestClient` class will see the type-hint and will
        grab one of that type from the XContext and return it.
        In the example above, it would be a `MyCoolAuthClass` type.

        The type-hint is lazily cached in self for fast lookup in the future.

        To see details on what the Auth object should do,
        see `xmodel.base.auth.BaseAuth`.
        """

        auth_type: Type[RestAuth] = self._auth_type
        if not auth_type:
            # Will get all type-hints, and ensure they are valid type refrences
            # (otherwise will error out)
            auth_type = get_type_hints(type(self)).get('auth', RestAuth)
            self._auth_type = auth_type

        # Auth has tokens we want to try and share, treat it as a resource.
        return auth_type.grab()

    _settings_type: Type[RestSettings] = None

    @property
    def _settings(self):
        """ The config object that this api uses, can be customized per-model. All you have to
            do is this to make it a different type:

            >>> import xmodel
            >>>
            >>> class MySettings(BaseSettings):
            ...     my_custom_var: str = xmodel.ConfigVar(
            ...         "MY_CUSTOM_ENVIRONMENTAL_VAR",
            ...         "default"
            ...     )
            >>> class MyApi(xmodel.BaseApi[M]):
            ...     settings: MySettings
            >>> class MyModel(xmodel.model.BaseModel['MyModel']):
            ...     api: MyApi

            The type-hints are enough to tell the system what types to use. They also will
            tell any IDE in use about what type it should be, for type-completion.
            So it's sort of doing double-duty!
        """
        config_type = self._settings_type
        if not config_type:
            config_type = get_type_hints(type(self)).get('settings', None)
            self._settings_type = config_type  # Cache config-type.
            if config_type is None:
                raise XynRestError(
                    f"BaseClient subclass type is undefined for model class ({self.model_type}), "
                    f"a type-hint for 'client' on BaseApi class must be in place for me to know "
                    f"what type to get."
                )

        return XContext.current(for_type=config_type)

    # PyCharm has some sort of issue, if I provide property type-hint and then a property function
    # that implements it. For some reason, this makes it ignore the type-hint in subclasses
    # but NOT in the current class.  It's some sort of bug. This gets around it since pycharm
    # can't figure out what's going on here.
    auth = _auth
    settings = _settings
