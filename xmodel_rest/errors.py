from xmodel.remote.errors import XynRemoteError


# todo: look to inherit from a 'XynRemoteError' type thing in xmodel.remote
class XynRestError(XynRemoteError):
    pass
