import os

import requests.auth


class AuthInfo(requests.auth.HTTPBasicAuth):
    """
    Accommodate Iguazio-based authentication mechanism
    """

    @classmethod
    def from_session_key(cls, session_key):
        return cls("", session_key)

    @classmethod
    def from_envvar(cls):
        access_key = os.getenv("V3IO_ACCESS_KEY")
        if access_key:
            return cls.from_session_key(access_key)

        return None

    def compile_iguazio_cookie(self):
        return f'j:{{"sid": "{self.password}"}}'

    def __call__(self, r: requests.request):

        # if provided a username, let it be a basic auth
        if self.username != "":
            return super.__call__(r)

        # otherwise, treat as a session key in which we send as a cookie
        r.prepare_cookies({
            "session": self.compile_iguazio_cookie(),
        })
        return r
