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

from conftest import here, patch
import pytest

from nuclio import deploy
from nuclio.config import meta_keys, ConfigSpec, Volume

handler_nb = '{}/handler.ipynb'.format(here)


functions = {
    'test-handler': {
        'metadata': {
            'name': 'test-handler',
            'labels': {
                meta_keys.project: 'test-project',
            },
        },
    },
}

projects = {
    '03ff81bf-00d6-41a4-899c-869a12f06d8c': {
        "metadata": {
            "name": "03ff81bf-00d6-41a4-899c-869a12f06d8c",
            "namespace": "default-tenant"},
        "spec":
            {"displayName": "test-project"}
    }
}

ip_addresses = {'externalIPAddresses': {'addresses': ['18.197.86.33']}}

api_prefix = '/api/functions'
projects_prefix = '/api/projects'
address_prefix = '/api/external_ip_addresses'
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

        if path == projects_prefix or path == projects_prefix + '/':
            return Response(projects)

        if path == address_prefix:
            return Response(ip_addresses)

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
    with patch(deploy, requests=mock_requests):
        yield


def first(seq):
    return next(iter(seq))


def test_deploy_nb(requests):
    names = set(functions)
    deploy.deploy_file(handler_nb, project='test-project')
    new_names = set(functions)
    assert len(new_names) == len(names) + 1, 'not deployed'
    name = first(new_names - names)
    func = functions[name]
    assert func['status']['state'] == 'ready', 'not ready'


def test_deploy_code(requests):
    # define my function code template
    code = '''
    def handler(context, event):
        context.logger.info('text')
        return 'something'
    '''

    # deploy my code with extra configuration (env vars, mount)
    vol = Volume('data', '~/')
    spec = ConfigSpec(env={'MYENV_VAR': 'something'}, mount=vol)
    names = set(functions)
    deploy.deploy_code(code, name='myfunc', project='test-project',
                       verbose=True, spec=spec)

    new_names = set(functions)
    assert len(new_names) == len(names) + 1, 'not deployed'
    name = first(new_names - names)
    func = functions[name]
    assert func['status']['state'] == 'ready', 'not ready'


class MockLogger:
    def __init__(self):
        self.logs = []

    def info(self, msg, *args):
        self.logs.append((msg, args))


def test_process_resp():
    with open('{}/deploy.json'.format(here)) as fp:
        resp = json.load(fp)

    logs = resp['status']['logs']
    last_time = min(log['time'] for log in logs) - 7

    logger = MockLogger()
    with patch(deploy, logger=logger):
        for i in range(len(logs) + 1):
            resp['status']['logs'] = logs[:i]
            state, last_time = deploy.process_resp(resp, last_time, False)
            if i > 0:
                assert last_time == logs[i-1]['time'], 'bad last_time'
            assert state == resp['status']['state'], 'bad state'

    assert len(logger.logs) == len(logs), 'bad number of logs'
