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
"""Deploy notebook to nuclio"""

import logging
from argparse import FileType
from base64 import b64decode
from os import environ, path
from operator import itemgetter
from subprocess import run
from sys import executable, stdout
from tempfile import mkdtemp
from time import sleep, time
from urllib.parse import urlparse

import yaml

import requests
from nuclio.export import get_in, update_in

project_key = 'nuclio.io/project-name'


class DeployError(Exception):
    pass


def iter_projects(reply):
    if not reply:
        return []

    for data in reply.values():
        labels = data['metadata'].get('labels', {})
        for key, value in labels.items():
            if key == project_key:
                yield value


def iter_functions(reply):
    if not reply:
        return []

    for data in reply.values():
        yield data['metadata']['name']


def get_functions(api_url):
    resp = requests.get(api_url)
    if not resp.ok:
        raise OSError('cannot call API')
    return resp.json()


def find_dashboard_url():
    value = environ.get('DEFAULT_TENANT_NUCLIO_DASHBOARD_PORT')
    if not value:
        addr = 'localhost:8070'
    else:
        addr = urlparse(value).netloc

    return 'http://' + addr


def create_logger():
    handler = logging.StreamHandler(stdout)
    handler.setFormatter(
        logging.Formatter('[%(name)s] %(asctime)s %(message)s'))
    logger = logging.getLogger('nuclio.deploy')
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


logger = create_logger()


def project_name(config):
    labels = config['metadata'].get('labels', {})
    return labels.get(project_key)


def update_project(config, project, reply):
    # Can't use str here since porject_key contains a .
    key = ['metadata', 'labels', project_key]
    if project:
        update_in(config, key, project)
        return

    project = get_in(config, key)
    if project:
        return

    projects = sorted(iter_projects(reply))
    if not projects:
        raise DeployError(
            'no project name and no existing projects')
    project = projects[0]
    update_in(config, key, project)


def deploy(nb_file, dashboard_url='', project='', verbose=False):
    # logger level is INFO, debug won't emit
    log = logger.info if verbose else logger.debug

    tmp_dir = mkdtemp()
    cmd = [
        executable, '-m', 'nbconvert',
        '--to', 'nuclio.export.NuclioExporter',
        '--output-dir', tmp_dir,
        nb_file,
    ]
    log(' '.join(cmd))
    out = run(cmd)
    if out.returncode != 0:
        raise DeployError('cannot convert notebook')

    base = path.basename(nb_file).replace('.ipynb', '.yaml')
    cfg_file = '{}/{}'.format(tmp_dir, base)
    with open(cfg_file) as fp:
        config_data = fp.read()
    config = yaml.safe_load(config_data)

    log('Config:\n{}'.format(config_data))
    py_code = config['spec']['build'].get('functionSourceCode')
    if py_code:
        py_code = b64decode(py_code).decode('utf-8')
    log('Python code:\n{}'.format(py_code))

    api_url = '{}/api/functions'.format(dashboard_url or find_dashboard_url())
    log('api URL: %s', api_url)
    try:
        reply = get_functions(api_url)
    except OSError:
        raise DeployError('error: cannot connect to {}'.format(api_url))

    name = config['metadata']['name']
    is_new = name not in set(iter_functions(reply))
    verb = 'creating' if is_new else 'updating'
    log('%s %s', verb, name)

    update_project(config, project, reply)
    log('using project %s', config['metadata']['labels'][project_key])

    headers = {
        'Content-Type': 'application/json',
        'x-nuclio-project-name': project,
    }

    try:
        resp = requests.post(api_url, json=config, headers=headers)
    except OSError as err:
        log('ERROR: %s', str(err))
        raise DeployError('error: cannot {} to {}'.format(verb, api_url))

    if not resp.ok:
        log('ERROR: %s', resp.text)
        raise DeployError('failed {} {}'.format(verb, name))

    log('deploying ...')
    state = deploy_progress(api_url, name)
    if state != 'ready':
        log('ERROR: {}'.format(resp.text))
        raise DeployError('cannot deploy ' + resp.text)

    log('done %s %s', verb, name)


def populate_parser(parser):
    parser.add_argument('notebook', help='notebook file', type=FileType('r'))
    parser.add_argument('--dashboard-url', help='dashboard URL')
    parser.add_argument('--project', help='project name')
    parser.add_argument(
        '--verbose', '-v', action='store_true', default=False,
        help='emit more logs',
    )


def deploy_progress(api_url, name):
    url = '{}/{}'.format(api_url, name)
    last_time = time() * 1000.0

    while True:
        resp = requests.get(url)
        if not resp.ok:
            raise DeployError('error: cannot poll {} status'.format(name))

        state, last_time = process_resp(resp.json(), last_time)
        if state != 'building':
            return state

        sleep(1)


def process_resp(resp, last_time):
    status = resp['status']
    state = status['state']
    logs = status.get('logs', [])
    for log in sorted(logs, key=itemgetter('time')):
        timestamp = log['time']
        if timestamp <= last_time:
            continue
        last_time = timestamp
        logger.info('(%s) %s', log['level'], log['message'])

    return state, last_time
