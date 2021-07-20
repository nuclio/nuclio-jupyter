import os

import requests.auth


class AuthKinds:
    nop = "nop"
    iguazio = "iguazio"


class AuthInfo:
    """
    Accommodate Iguazio-based authentication mechanism
    """

    def __init__(self, username="", password="", mode=AuthKinds.nop):
        self._username = username
        self._password = password
        self._mode = mode

    @classmethod
    def from_envvar(cls):
        access_key = os.getenv("V3IO_ACCESS_KEY")
        if access_key:
            return cls(password=access_key, mode=AuthKinds.iguazio)
        return cls(mode=AuthKinds.nop)

    def to_requests_auth(self):
        if self._mode == AuthKinds.iguazio:
            return IguazioBasicAuthRequests(self._username, self._password)
        elif self._username or self._password:
            return requests.auth.HTTPBasicAuth(self._username, self._password)
        return None


class IguazioBasicAuthRequests(requests.auth.HTTPBasicAuth):

    def __call__(self, r: requests.request):
        # password as session key, send as a cookie
        r.prepare_cookies({
            "session": f'j:{{"sid": "{self.password}"}}',
        })
        return r
