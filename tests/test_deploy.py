# Copyright 2018 Iguazio
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
from urllib.parse import urlparse
from time import time

from conftest import here
import pytest

from nuclio import deploy

handler_nb = '{}/handler.ipynb'.format(here)


functions = {
    'test-handler': {
        'metadata': {
            'name': 'test-handler',
            'labels': {
                deploy.project_key: 'test-project',
            },
        },
    },
}

api_prefix = '/api/functions'
api_url = 'http://localhost:8080{}'.format(api_prefix)


class Response:
    def __init__(self, data, ok=True):
        self.data = data
        self.ok = ok

    def json(self):
        return self.data

    @property
    def text(self):
        return json.dumps(self.data)


# TODO: Get CI env with dashboard
class mock_requests:
    @staticmethod
    def get(url):
        path = urlparse(url).path
        if path == api_prefix or path == api_prefix + '/':
            return Response(functions)

        name = path[len(api_prefix):]
        if name[0] == '/':
            name = name[1:]
        func = functions.get(name)
        if not func:
            return Response({'error': '{} not found'.format(name)}, ok=False)

        tdiff = time() - func['status']['created']
        func['status']['state'] = 'ready' if tdiff > 2 else 'building'
        return Response(func)

    @staticmethod
    def post(url, json=None, headers=None):
        func = json or {}
        name = func['metadata']['name']
        func['status'] = {
            'state': 'building',
            'created': time(),
        }
        functions[name] = func
        return Response({'ok': True})


@pytest.fixture
def requests():
    orig_requests = deploy.requests
    deploy.requests = mock_requests
    yield
    deploy.requests = orig_requests


def test_iter_functions(requests):
    resp = deploy.get_functions(api_url)
    names = set(deploy.iter_functions(resp))
    existing = set(fn['metadata']['name'] for fn in functions.values())
    assert names == existing, 'bad names'


def test_iter_projects(requests):
    resp = deploy.get_functions(api_url)
    names = set(deploy.iter_projects(resp))
    existing = set(deploy.project_name(fn) for fn in functions.values())
    assert names == existing, 'bad projects'


def first(seq):
    return next(iter(seq))


def test_deploy(requests):
    names = set(functions)
    deploy.deploy(handler_nb)
    new_names = set(functions)
    assert len(new_names) == len(names) + 1, 'not deployed'
    name = first(new_names - names)
    func = functions[name]
    assert func['status']['state'] == 'ready', 'not ready'
