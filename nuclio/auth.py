import os

import requests.auth


class AuthInfo:
    """
    Accommodate Iguazio-based authentication mechanism
    """

    def __init__(self, username="", password="", mode="nop"):
        self._username = username
        self._password = password
        self._mode = mode

    @classmethod
    def from_envvar(cls):
        access_key = os.getenv("V3IO_ACCESS_KEY")
        if access_key:
            return cls(password=access_key, mode="iguazio")
        return cls(mode="nop")

    def to_requests_auth(self):
        if self._mode == "iguazio":
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
