from requests.models import PreparedRequest

from xinject import Dependency
from requests.auth import AuthBase as Requests_AuthBase
from requests import PreparedRequest
from .settings import RestSettings

__pdoc__ = {
    "RestAuth.__call__": True
}


class RestAuth(Dependency, Requests_AuthBase):
    """ Abstract type from which all-other api-auth-context's are descended from.
        For an example of one used for our Xyngular API's (that can also be used directly with
        the Requests 3rd party library), see: `xyn_sdk.core.common.Auth`.
    """

    def requests_callable(self, settings: RestSettings) -> Requests_AuthBase:
        """ Right now returns self by default, since by default we will use the current/default
            settings (see `RestAuth.__call__`).

            This is an opportunity to map/return a custom or shared
            `requests.auth.AuthBase` resource customized for the settings that are passed in.

            .. todo:: Put some common logic in here to map passed in settings object
                We want to use a standard set of things we return here to map the passed
                in settings to a callable that the `requests` library can use to inject
                credentials into it's request.

                For now we just return self and expect the current settings to be used,
                which should be good enough for now.
         """
        return self

    def refresh_token(self, settings: RestSettings = None):
        """ Forces the token/credentials to be refreshed, can use if the token is about to expire.

            When Requests calls to get new token, the expiration should be checked and refreshed
            if needed, which the result of you can pass back [ie: block].

            Args:
                settings (xynlib.orm.base.settings.Settings): Will pass in the settings that
                    need the token refresh.

                    If None (default): The subclass will retrieve the current default settings
                        and use them (the Auth subclass should know what base-settings it needs).
        """
        pass

    def __call__(self, request: PreparedRequest):
        """ Called from requests library to modify request as needed to provide auth.
            Modify the request as needed and return it. Whatever is returned is what is executed.

            `BaseAuth` by default just simply returns the request unmodified.

            If you need Settings, get the default one via, normally you do this by calling
            `xynlib.context.Resource.resource` on the specific
            `xynlib.orm.base.settings.BaseSettings` subclass that you normally use.
        Args:
            request (requests.PreparedRequest): Is the `requests.PreparedRequest` of the request
                that needs the authorization added.
        Returns:
            requests.PreparedRequest: The request object you passed in, modified as needed.
        """
        return request
