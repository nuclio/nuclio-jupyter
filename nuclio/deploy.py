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
from sys import stdout
from tempfile import mktemp
from time import sleep, time
from urllib.parse import urlparse

import yaml
import requests
from nuclio.utils import (get_in, update_in, is_url, normalize_name,
                          Volume, fill_config, load_config, read_or_download)
from .archive import get_archive_config, build_zip, upload_file
from .build import code2config, build_notebook

project_key = 'nuclio.io/project-name'
tag_key = 'nuclio.io/tag'


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


def deploy_file(nb_file, dashboard_url='', name='', project='', handler='',
                tag='', verbose=False, create_new=False, target_dir='',
                auth=None, env=[], extra_config={}, cmd='',
                mount: Volume = None):

    # logger level is INFO, debug won't emit
    log = logger.info if verbose else logger.debug

    code = ''
    filebase, ext = path.splitext(path.basename(nb_file))
    name = normalize_name(name or filebase)
    if ext == '.ipynb':

        file_path, ext, has_url = build_notebook(nb_file, name, handler,
                                                 target_dir, auth)
        if ext == '.zip':
            if not has_url:
                raise DeployError('archive path must be a url (http(s)://..)')
            config = get_archive_config(normalize_name(name), file_path,
                                        auth=auth)
        else:
            if has_url:
                raise DeployError('yaml path must be a local dir')
            with open(file_path) as fp:
                config_data = fp.read()
            config = yaml.safe_load(config_data)

    elif ext in ['.py', '.go', '.js']:
        code = read_or_download(nb_file, auth)
        config = code2config(code, name, handler, ext)

    elif ext == '.yaml':
        code, config = load_config(nb_file)

    elif ext == '.zip':
        if not is_url(nb_file):
            raise DeployError('archive path must be a url (http(s)://..)')
        config = get_archive_config(name, nb_file, auth=auth, workdir='')

    else:
        raise DeployError('illegal filename or extension: '+nb_file)

    if get_in(config, 'spec.build.codeEntryType') != 'archive':
        if not code:
            code_buf = config['spec']['build'].get('functionSourceCode')
            code = b64decode(code_buf).decode('utf-8')
        log('Python code:\n{}'.format(code))
        fill_config(config, extra_config, env, cmd, mount)

    log('Config:\n{}'.format(yaml.dump(config, default_flow_style=False)))

    addr = deploy_config(config, dashboard_url, name=name, project=project,
                         tag=tag, verbose=verbose, create_new=create_new)

    return addr


def deploy_code(code, dashboard_url='', name='', project='', handler='',
                lang='.py', tag='', verbose=False, create_new=False,
                archive='', auth=None, env=[], config={}, cmd='',
                mount: Volume = None, files=[]):

    newconfig = code2config(code, name, handler, lang)
    fill_config(newconfig, config, env, cmd, mount)
    if verbose:
        logger.info('Config:\n{}'.format(
            yaml.dump(newconfig, default_flow_style=False)))

    if files and not archive:
        raise DeployError('archive must be specified when packing files')
    if archive:
        tmp_file = mktemp('.zip')
        build_zip(tmp_file, newconfig, code, files)
        upload_file(tmp_file, archive, auth, True)
        newconfig = get_archive_config(name, archive, auth=auth)
        if verbose:
            logger.info('Archive Config:\n{}'.format(
                yaml.dump(newconfig, default_flow_style=False)))

    return deploy_config(newconfig, dashboard_url, name=name, project=project,
                         tag=tag, verbose=verbose, create_new=create_new)


def deploy_config(config, dashboard_url='', name='', project='', tag='',
                  verbose=False, create_new=False):
    # logger level is INFO, debug won't emit
    log = logger.info if verbose else logger.debug

    if not project:
        raise DeployError('project name must be specified (using -p option)')

    api_address = dashboard_url or find_dashboard_url()
    project = find_or_create_project(api_address, project, create_new)

    if not name:
        name = config['metadata']['name']
    else:
        config['metadata']['name'] = name

    if tag:
        update_in(config, ['metadata', 'labels', tag_key], tag)

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
    return address


def populate_parser(parser):
    parser.add_argument('notebook', help='notebook file', type=FileType('r'))
    parser.add_argument('--dashboard-url', '-d', help='dashboard URL')
    parser.add_argument('--name', '-n',
                        help='function name (notebook name by default)')
    parser.add_argument('--project', '-p', help='project name')
    parser.add_argument('--target-dir', '-t', default='',
                        help='target dir/url for .zip or .yaml files')
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
    parser.add_argument('--key', '-k', default='',
                        help='authentication/access key')
    parser.add_argument('--username', '-u', default='',
                        help='username for authentication')
    parser.add_argument('--secret', '-s', default='',
                        help='secret-key/password for authentication')


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
