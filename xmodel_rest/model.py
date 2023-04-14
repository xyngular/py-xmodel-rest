from typing import TypeVar, TYPE_CHECKING

from xmodel.remote import RemoteModel


if TYPE_CHECKING:
    # Prevents circular imports, only needed for IDE type completion
    # (and static analyzers, if we end up using them in the future).
    # We don't need the to be resolvable at run-time.
    from .api import RestApi

M = TypeVar("M", bound=RemoteModel)


def _lazy_load_types(cls):
    """
    Lazy import RestApi into module, helps resolve RestApi forward-refs;
    ie: `api: "RemoteApi[T]"`

    We need to resolve these forward-refs due to use of `get_type_hints()` in
    BaseModel.__init_subclass__; so get_type_hints can find the correct type for the
    forward-ref string in out `RemoteModel` class below.

    Sets it in such a way so IDE's such as pycharm don't get confused + pydoc3
    can still find it and use the type forward-reference.

    See `xmodel.base.model.BaseModel.__init_subclass__` for more details.
    """
    if 'RestApi' not in globals():
        from xmodel_rest.api import RestApi
        globals()['RestApi'] = RestApi


class RestModel(RemoteModel[M], lazy_loader=_lazy_load_types):
    """ Intended to be used as general base-class for use with rest-api's.

        Sets `xynlib.orm.base.model.BaseModel` to use the following classes:

        - `RestApi`
            - `RestAuth`
            - `RestClient`
            - `RestStructure`

        These classes are generally useful for rest-based API's.
    """
    api: "RestApi[M]"
