# Copyright 2018 The Nuclio Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
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
