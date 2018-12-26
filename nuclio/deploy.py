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
from subprocess import run
from sys import executable, stdout
from tempfile import mkdtemp
from time import sleep
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
            if key == 'nuclio.io/project-name':
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


def create_logger(level):
    handler = logging.StreamHandler(stdout)
    handler.setFormatter(
        logging.Formatter('[%(name)s] %(asctime)s %(message)s'))
    logger = logging.getLogger('nuclio.deploy')
    logger.addHandler(handler)
    logger.setLevel(level)
    return logger


def project_name(config):
    labels = config['metadata'].get('lables', {})
    return labels.get(project_key)


def deploy(nb_file, dashboard_url='', verbose=False):
    log_level = logging.INFO if verbose else logging.ERROR
    log = create_logger(log_level).info

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
        raise SystemExit('error: cannot convert notebook')

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
        raise SystemExit('error: cannot connect to {}'.format(api_url))

    name = config['metadata']['name']
    is_new = name not in set(iter_functions(reply))
    verb = 'creating' if is_new else 'updating'
    log('%s %s', verb, name)

    key = 'metadata.labeles.{}'.format(project_key)
    project = get_in(config, key)
    if not project:
        projects = sorted(iter_projects(reply))
        if not projects:
            raise SystemExit(
                'error: no project name and no existing projects')
        project = projects[0]
        log('using project %s', project)
        update_in(config, key, project)

    headers = {
        'Content-Type': 'application/json',
    }
    try:
        if is_new:
            resp = requests.post(api_url, json=config, headers=headers)
        else:
            resp = requests.put(api_url, json=config, headers=headers)
    except OSError:
        raise SystemExit('error: cannot {} to {}'.format(verb, api_url))

    if not resp.ok:
        log('ERROR: %s', resp.text)
        raise SystemExit('error: failed {} {}'.format(verb, name))

    url = '{}/{}'.format(api_url, name)
    while True:
        resp = requests.get(url)
        if not resp.ok:
            raise SystemExit('error: cannot poll {} status'.format(name))
        if get_in(resp.json(), 'status.state') == 'ready':
            break
        sleep(1)

    log('done %s %s', verb, name)


def populate_parser(parser):
    parser.add_argument('notebook', help='notebook file', type=FileType('r'))
    parser.add_argument('--dashboard-url', help='dashboard URL')
    parser.add_argument(
        '--verbose', '-v', action='store_true', default=False,
        help='emit more logs',
    )
