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
from nuclio.export import update_in
from nuclio.utils import parse_env

project_key = 'nuclio.io/project-name'


class DeployError(Exception):
    pass


def get_function(api_address, name):
    api_url = '{}/api/functions/{}'.format(api_address, name)
    return requests.get(api_url)


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


def deploy(nb_file, dashboard_url='', name='', project='',
           verbose=False, create_new=False, tmp_dir='', env=[]):
    # logger level is INFO, debug won't emit
    log = logger.info if verbose else logger.debug

    if not project:
        raise DeployError('project name must be specified using -p option')

    if not tmp_dir:
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

    if env:
        new_list = []
        for v in env:
            key, value = parse_env(v)
            if key is None:
                log('ERROR: cannot find "=" in env var %s', v)
                raise DeployError('failed to deploy, error in env var option')

            i = find_env_var(config['spec']['env'], key)
            if i >= 0:
                config['spec']['env'][i]['name'] = key
                config['spec']['env'][i]['value'] = value
            else:
                new_env = {'name': key, 'value': value}
                new_list += [new_env]

        config['spec']['env'] += new_list

    log('Config:\n{}'.format(config_data))
    py_code = config['spec']['build'].get('functionSourceCode')
    if py_code:
        py_code = b64decode(py_code).decode('utf-8')
    log('Python code:\n{}'.format(py_code))

    api_address = dashboard_url or find_dashboard_url()
    project = find_or_create_project(api_address, project, create_new)

    if not name:
        name = config['metadata']['name']
    else:
        config['metadata']['name'] = name

    try:
        resp = get_function(api_address, name)
    except OSError:
        raise DeployError('error: cannot connect to {}'.format(api_address))

    is_new = not resp.ok
    verb = 'creating' if is_new else 'updating'
    log('%s %s', verb, name)
    if resp.ok:
        func_project = resp.json()['metadata']['labels'].get(project_key, '')
        if func_project != project:
            raise DeployError('error: function name already exists under a '
                              + 'different project ({})'.format(func_project))

    key = ['metadata', 'labels', project_key]
    update_in(config, key, project)

    headers = {
        'Content-Type': 'application/json',
        'x-nuclio-project-name': project,
    }

    api_url = '{}/api/functions'.format(api_address)
    try:
        if is_new:
            resp = requests.post(api_url, json=config, headers=headers)
        else:
            resp = requests.put(api_url+'/'+name, json=config, headers=headers)

    except OSError as err:
        log('ERROR: %s', str(err))
        raise DeployError('error: cannot {} to {}'.format(verb, api_url))

    if not resp.ok:
        log('ERROR: %s', resp.text)
        raise DeployError('failed {} {}'.format(verb, name))

    log('deploying ...')
    state, address = deploy_progress(api_address, name, verbose)
    if state != 'ready':
        log('ERROR: {}'.format(resp.text))
        raise DeployError('cannot deploy ' + resp.text)

    logger.info('done %s %s, function address: %s', verb, name, address)


def find_env_var(env_list, key):
    i = 0
    for v in env_list:
        if v['name'] == key:
            return i
        i += 1

    return -1


def populate_parser(parser):
    parser.add_argument('notebook', help='notebook file', type=FileType('r'))
    parser.add_argument('--dashboard-url', '-u', help='dashboard URL')
    parser.add_argument('--name', '-n',
                        help='function name (notebook name by default)')
    parser.add_argument('--project', '-p', help='project name')
    parser.add_argument('--work-dir', '-d',
                        help='work dir for .py & .yaml files')
    parser.add_argument(
        '--verbose', '-v', action='store_true', default=False,
        help='emit more logs',
    )
    parser.add_argument(
        '--create-project', '-c', action='store_true', default=False,
        help='create new project if doesnt exist',
    )
    parser.add_argument('--env', '-e', default=[], action='append',
                        help='override environment variable (key=value)')


def deploy_progress(api_address, name, verbose=False):
    url = '{}/api/functions/{}'.format(api_address, name)
    last_time = time() * 1000.0
    address = ''

    while True:
        resp = requests.get(url)
        if not resp.ok:
            raise DeployError('error: cannot poll {} status'.format(name))

        state, last_time = process_resp(resp.json(), last_time, verbose)
        if state in {'ready', 'error'}:

            if state == 'ready':
                ip = get_address(api_address)
                address = '{}:{}'.format(ip, resp.json()['status']
                                         .get('httpPort', 0))

            return state, address

        sleep(1)


def get_address(api_url):
    resp = requests.get('{}/api/external_ip_addresses'.format(api_url))
    if not resp.ok:
        raise OSError('nuclio API call failed')

    addresses = resp.json()['externalIPAddresses']['addresses']
    return addresses[0]


def process_resp(resp, last_time, verbose=False):
    status = resp['status']
    state = status['state']
    logs = status.get('logs', [])
    for log in sorted(logs, key=itemgetter('time')):
        timestamp = log['time']
        if timestamp <= last_time:
            continue
        last_time = timestamp
        logger.info('(%s) %s', log['level'], log['message'])
        if state == 'error' and 'errVerbose' in log.keys():
            logger.info(str(log['errVerbose']))
        elif verbose:
            logger.info(str(log))

    return state, last_time


def find_or_create_project(api_url, project, create_new=False):
    apipath = '{}/api/projects'.format(api_url)
    resp = requests.get(apipath)

    project = project.strip()
    if not resp.ok:
        raise OSError('nuclio API call failed')
    for k, v in resp.json().items():
        if v['spec']['displayName'] == project:
            return k

        if k == project:
            return k

    if not create_new:
        raise DeployError('project name {} not found'.format(project))

    # create a new project
    headers = {'Content-Type': 'application/json'}
    config = {"metadata": {}, "spec": {"displayName": project}}

    try:
        resp = requests.post(apipath, json=config, headers=headers)
    except OSError as err:
        logger.info('ERROR: %s', str(err))
        raise DeployError(
            'error: cannot create project {} on {}'.format(project, apipath))

    if not resp.ok:
        raise DeployError('failed to create project {}'.format(project))

    logger.info('project name not found created new (%s)', project)
    return resp.json()['metadata']['name']
