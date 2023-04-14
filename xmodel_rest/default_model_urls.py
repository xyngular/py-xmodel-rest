from xurls import HTTPGet, HTTPPatch, HTTPDelete, URL


DefaultModelURLs = [
    URL("{id}", methods=(HTTPGet, HTTPPatch, HTTPDelete), singular=True),
    URL(methods=(HTTPGet, HTTPPatch, HTTPDelete), singular=False),
]
""" Default set of urls if no `urls` are provided in class arguments.
    The first url is for single-objects and appends the `id` component as placeholder to the path.
    The second is for multiple-objects, with no extra path component to append.

    We want to try and use the singular version first, since the URL is more specific.
    So we order it above the general full collection-based url.
"""
