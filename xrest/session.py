import requests
from xinject import DependencyPerThread


class Session(DependencyPerThread, attributes_to_skip_while_copying=['_requests_session']):
    """ Simple resource to keep track of a common requests session.
        For unit-tests, if they use the `xynlib.fixtures.context` fixture, they will get
        a blank-context, and so a new `Session` object  will be created each time;
        there-by creating a new requests-session.

        This is important, since when you mock requests library, you must create your
        session object that you want to use for mock library while unit test is running.

        But at the same time, we want the application to really share a session when using the
        requests library so existing http connections can be reused (ie: keep connections open).

        This helps facilitate using the requests mocking library while at the same time
        preserving the ability to reused requests library connections like you would normally
        want to do.

        In normal situations, this resource will be kept around and re-used when a requests
        session is needed.  Therefore, requests is given an opportunity to reuse an
        already open http-connection to an API.
    """
    # So we know if we lazily created the session yet or not.
    _requests_session = None

    def reset(self):
        """ Next time we are asked for the current requests Session, we will generate a new one.
        """
        self._requests_session = None

    @property
    def requests_session(self) -> requests.Session:
        session = self._requests_session
        if not session:
            session = requests.session()
            self._requests_session = session
        return session
