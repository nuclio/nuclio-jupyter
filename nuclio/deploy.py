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
import json
from os import environ
from operator import itemgetter
from tempfile import mktemp
from time import sleep, time
from datetime import datetime

import yaml
import requests
from .utils import DeployError, list2dict, str2nametag, logger, normalize_name
from .config import (update_in, meta_keys, ConfigSpec, extend_config, Volume,
                     set_handler, new_config)
from .archive import get_archive_config, build_zip, upload_file, is_archive
from .build import code2config, build_file, archive_path

VERIFY_CERT = False


def get_function(api_address, name):
    api_url = '{}/functions/{}'.format(api_address, name)
    return requests.get(api_url, verify=VERIFY_CERT)


service_names = {
    'DEFAULT_TENANT_NUCLIO_DASHBOARD': 'default-tenant-nuclio-dashboard',
    'NUCLIO_DASHBOARD': 'nuclio-dashboard'
}


def find_dashboard_url(dashboard_url=''):

    def with_prefix(url):
        api_prefix = '/api'
        if environ.get('NUCLIO_DROP_API'):
            api_prefix = ''
        return url + api_prefix

    if dashboard_url:
        return with_prefix(dashboard_url)

    if 'NUCLIO_DASHBOARD_URL' in environ:
        return with_prefix(environ.get('NUCLIO_DASHBOARD_URL'))

    for service, endpoint in service_names.items():
        env_name = service + '_SERVICE_PORT'
        if env_name in environ:
            port = environ.get(env_name) or '8070'
            return with_prefix('http://{}:{}'.format(endpoint, port))

    return with_prefix('http://localhost:8070')


def project_name(config):
    labels = config['metadata'].get('labels', {})
    return labels.get(meta_keys.project)


def deploy_from_args(args, name=''):
    envdict = list2dict(args.env)
    if args.env_json:
        envdict = json.loads(args.env_json)
    spec = ConfigSpec(env=envdict)
    if args.spec_json:
        spec.config = json.loads(args.spec_json)
    if args.cmd_json:
        spec.cmd = json.loads(args.cmd_json)
    if args.mount:
        sp = ''.split(':')
        if len(sp) == 2:
            spec.mount = Volume(sp[1], sp[0])
        if len(sp) == 3:
            spec.mount = Volume(sp[1], sp[2], sp[0])

    addr = deploy_file(name or args.file, args.dashboard_url, name=args.name,
                       project=args.project, verbose=args.verbose,
                       create_project=args.create_project, spec=spec,
                       archive=args.archive, tag=args.tag, kind=args.kind)
    with open('/tmp/output', 'w') as fp:
        fp.write(addr)
    return addr


def deploy_model(models: dict, source='', model_class='', protocol='',
                 endpoint='', dashboard_url='', name='', project='', tag='',
                 explainer=False, spec: ConfigSpec = None, image='',
                 workers=8, canary=None, handler='', verbose=False):

    if not models or not isinstance(models, dict):
        raise DeployError('please specify models dict {model-name: path}')

    if not spec:
        spec = ConfigSpec()

    for k, v in models.items():
        spec.set_env('SERVING_MODEL_{}'.format(k), v)

    spec.set_env('TRANSPORT_PROTOCOL', protocol or 'seldon')
    spec.set_env('ENABLE_EXPLAINER', str(explainer))
    spec.set_env('MODEL_CLASS', model_class)
    spec.with_http(workers, host=endpoint, canary=canary)

    if not image:
        return deploy_file(source, dashboard_url, name, project, tag=tag,
                           verbose=verbose, spec=spec, kind='serving',
                           handler=handler)
    config = new_config()
    update_in(config, 'spec.handler', handler or 'serving_template:handler')
    update_in(config, 'spec.image', image)
    update_in(config, 'spec.build.baseImage', image + '_base')
    update_in(config, 'spec.build.codeEntryType', 'image')

    config = extend_config(config, spec, tag, 'code')
    update_in(config, 'metadata.name', name)

    return deploy_config(config, dashboard_url, name=name, project=project,
                         tag=tag, verbose=verbose, create_new=True)


def deploy_file(source='', dashboard_url='', name='', project='', handler='',
                tag='', verbose=False, create_project=True, archive=False,
                spec: ConfigSpec = None, files=[], output_dir='', kind=None):

    if source.startswith('$') or is_archive(source):
        return deploy_zip(source, name, project, tag,
                          dashboard_url=dashboard_url,
                          verbose=verbose, spec=spec,
                          create_project=create_project)

    if archive or files:
        _, url_target = archive_path(output_dir, project, name, tag)
        if not url_target:
            raise DeployError('deploy from archive require a remote path')

    name, config, code = build_file(source, name, handler=handler,
                                    archive=archive, tag=tag, spec=spec,
                                    files=files, project=project,
                                    output_dir=output_dir, kind=kind)

    addr = deploy_config(config, dashboard_url, name=name, project=project,
                         tag=tag, verbose=verbose, create_new=create_project)

    return addr


def deploy_zip(source='', name='', project='', tag='', dashboard_url='',
               verbose=False, spec: ConfigSpec = None,
               create_project=True):

    if source.startswith('$'):
        oproject, oname, otag = str2nametag(source[1:])
        source, _ = archive_path('', oproject, oname, otag)

    if not source or ('://' not in source):
        raise DeployError('archive URL must be specified')

    name = normalize_name(name)
    config = get_archive_config(name, source)
    config = extend_config(config, spec, tag, 'archive '+source)

    if verbose:
        logger.info('Config:\n{}'.format(
            yaml.dump(config, default_flow_style=False)))

    addr = deploy_config(config, dashboard_url, name=name, project=project,
                         tag=tag, verbose=verbose, create_new=create_project)

    return addr


def deploy_code(code, dashboard_url='', name='', project='', handler='',
                lang='.py', tag='', verbose=False, create_project=True,
                archive='', spec: ConfigSpec = None, files=[], kind=None):

    name = normalize_name(name)
    newconfig, code = code2config(code, lang, kind=kind)
    set_handler(newconfig, '', handler, lang)
    if spec:
        spec.merge(newconfig)
    if verbose:
        logger.info('Code:\n{}'.format(code))
        logger.info('Config:\n{}'.format(
            yaml.dump(newconfig, default_flow_style=False)))

    if archive:
        archive, url_target = archive_path(archive, name=name,
                                           project=project, tag=tag)
    if files and not (archive and url_target):
        raise DeployError('archive URL must be specified when packing files')

    if files:
        zip_path = archive
        if url_target:
            zip_path = mktemp('.zip')
        build_zip(zip_path, newconfig, code, files, lang)
        upload_file(zip_path, archive, True)
        newconfig = get_archive_config(name, archive)
        if verbose:
            logger.info('Archive Config:\n{}'.format(
                yaml.dump(newconfig, default_flow_style=False)))

    newconfig = extend_config(newconfig, None, tag, 'code')
    update_in(newconfig, 'metadata.name', name)

    return deploy_config(newconfig, dashboard_url, name=name, project=project,
                         tag=tag, verbose=verbose, create_new=create_project)


def deploy_config(config, dashboard_url='', name='', project='', tag='',
                  verbose=False, create_new=False, watch=True):
    # logger level is INFO, debug won't emit
    log = logger.info if verbose else logger.debug

    if not project:
        raise DeployError('project name must be specified (using -p option)')

    api_address = find_dashboard_url(dashboard_url)
    project = find_or_create_project(api_address, project, create_new)

    try:
        resp = get_function(api_address, name)
    except OSError:
        raise DeployError('error: cannot connect to {}'.format(api_address))

    is_new = not resp.ok
    verb = 'creating' if is_new else 'updating'
    log('%s %s', verb, name)
    if resp.ok:
        func_project = resp.json()['metadata']['labels'].get(
            meta_keys.project, '')
        if func_project != project:
            raise DeployError('error: function name already exists under a '
                              + 'different project ({})'.format(func_project))

    key = ['metadata', 'labels', meta_keys.project]
    update_in(config, key, project)

    headers = {
        'Content-Type': 'application/json',
        'x-nuclio-project-name': project,
    }

    api_url = '{}/functions'.format(api_address)
    try:
        if is_new:
            resp = requests.post(api_url, json=config,
                                 headers=headers, verify=VERIFY_CERT)
        else:
            resp = requests.put(api_url+'/'+name, json=config,
                                headers=headers, verify=VERIFY_CERT)

    except OSError as err:
        log('ERROR: %s', str(err))
        raise DeployError('error: cannot {} to {}'.format(verb, api_url))

    if not resp.ok:
        log('ERROR: %s', resp.text)
        raise DeployError('failed {} {}'.format(verb, name))

    log('deploying ...')

    if watch:
        state, address = deploy_progress(api_address, name, verbose)
        if state != 'ready':
            log('ERROR: {}'.format(resp.text))
            raise DeployError('cannot deploy ' + resp.text)

        logger.info('done %s %s, function address: %s', verb, name, address)
        return address

    return None


def populate_parser(parser):
    parser.add_argument('file', help='notebook/code file',
                        nargs='?', default='')
    parser.add_argument('--dashboard-url', '-d', help='dashboard URL')
    parser.add_argument('--name', '-n',
                        help='function name (notebook name by default)')
    parser.add_argument('--project', '-p', help='project name')
    parser.add_argument('--archive', '-a', action='store_true', default=False,
                        help='remote archive for storing versioned functions')
    parser.add_argument('--output_dir', '-o', default='',
                        help='output dir for files/archives')
    parser.add_argument('--tag', '-t', default='', help='version tag')
    parser.add_argument(
        '--verbose', '-v', action='store_true', default=False,
        help='emit more logs',
    )
    parser.add_argument(
        '--create-project', '-c', action='store_true', default=True,
        help='create new project if doesnt exist',
    )
    parser.add_argument('--env', '-e', default=[], action='append',
                        help='override environment variable (key=value)')
    parser.add_argument('--env-json', default='',
                        help='override environment variable {key: value, ..}')
    parser.add_argument('--spec-json', default='',
                        help='override function spec {spec.xy.z: value, ..}')
    parser.add_argument('--cmd-json', default='',
                        help='add build commands from list ["pip install x"]')
    parser.add_argument('--mount', default='',
                        help='volume mount, [vol-type:]<vol-url>:<dst>')
    parser.add_argument('--kind', default=None)


def deploy_progress(api_address, name, verbose=False):
    url = '{}/functions/{}'.format(api_address, name)
    last_time = time() * 1000.0
    address = ''

    while True:
        resp = requests.get(url, verify=VERIFY_CERT)
        if not resp.ok:
            raise DeployError('error: cannot poll {} status'.format(name))

        state, last_time, _ = process_resp(resp.json(), last_time,
                                           verbose, log_message=True)
        if state in {'ready', 'error'}:

            if state == 'ready':
                ip = get_address(api_address)
                address = '{}:{}'.format(ip, resp.json()['status']
                                         .get('httpPort', 0))

            return state, address

        sleep(1)


def get_deploy_status(api_address, name, last_time=None, verbose=False):
    url = '{}/functions/{}'.format(api_address, name)
    last_time = last_time or (time() * 1000.0)
    address = ''

    resp = requests.get(url, verify=VERIFY_CERT)
    if not resp.ok:
        raise DeployError('error: cannot poll {} status'.format(name))

    state, last_time, outputs = process_resp(resp.json(), last_time,
                                             verbose, log_message=False)
    if state in {'ready', 'error'}:

        if state == 'ready':
            ip = get_address(api_address)
            address = '{}:{}'.format(ip, resp.json()['status']
                                     .get('httpPort', 0))

    return state, address, last_time, outputs


def get_address(api_url):
    resp = requests.get('{}/external_ip_addresses'.format(api_url),
                        verify=VERIFY_CERT)
    if not resp.ok:
        logger.warning('failed to obtain external IP address, returned local')
        return "localhost"

    addresses = resp.json()['externalIPAddresses']['addresses']
    return addresses[0]


def process_resp(resp, last_time, verbose=False, log_message=False):
    status = resp['status']
    state = status['state']
    logs = status.get('logs', [])

    message = status.get('message', '')
    if state == 'error' and message != '':
        message = f'Failed to deploy. Details:\n{message}'
        if log_message:
            logger.info(message)
        return state, last_time, [message]

    outputs = []
    for log in sorted(logs, key=itemgetter('time')):
        timestamp = log['time']
        if timestamp <= last_time:
            continue
        last_time = timestamp
        if log_message:
            logger.info('(%s) %s', log['level'], log['message'])
        time_string = datetime.fromtimestamp(
            timestamp/1000).strftime('%Y-%m-%d %H:%M:%S')
        message = f'{time_string}  ({log["level"]}) {log["message"]}'
        if verbose:
            if log_message:
                logger.info(str(log))
            message += '\n' + str(log)
        outputs.append(message)

    return state, last_time, outputs


def find_or_create_project(api_url, project, create_new=False):
    apipath = '{}/projects'.format(api_url)
    resp = requests.get(apipath, verify=VERIFY_CERT)

    project = project.strip()
    if not resp.ok:
        raise OSError('nuclio API call failed')
    for k, v in resp.json().items():
        if v['spec'].get('displayName') == project:
            return k

        if k == project:
            return k

    if not create_new:
        raise DeployError('project name {} not found'.format(project))

    # create a new project
    headers = {'Content-Type': 'application/json'}
    config = {"metadata": {"name": project}, "spec": {"displayName": project}}

    try:
        resp = requests.post(apipath, json=config,
                             headers=headers, verify=VERIFY_CERT)
    except OSError as err:
        logger.info('ERROR: %s', str(err))
        raise DeployError(
            'error: cannot create project {} on {}'.format(project, apipath))

    if not resp.ok:
        raise DeployError('failed to create project {}'.format(project))

    logger.info('project name not found created new (%s)', project)
    return resp.json()['metadata']['name']


def list_functions(dashboard_url='', namespace=''):
    api_address = find_dashboard_url(dashboard_url)
    api_url = '{}/functions'.format(api_address)
    headers = {}
    if namespace:
        headers = {'x-nuclio-function-namespace': namespace}
    try:
        resp = requests.get(api_url, headers=headers, verify=VERIFY_CERT)

    except OSError as err:
        logger.error('ERROR: %s', str(err))
        raise DeployError(
            'error: cannot list functions at {}'.format(api_address))

    if not resp.ok:
        logger.warning(f'failed to list functions, {resp.text}')
        return None
    return resp.json()


def delete_func(name, dashboard_url='', namespace=''):
    api_address = find_dashboard_url(dashboard_url)
    headers = {'Content-Type': 'application/json'}
    body = {'metadata': {'name': name}}
    if namespace:
        body['metadata']['namespace'] = namespace

    api_url = '{}/functions'.format(api_address)
    try:
        resp = requests.delete(api_url, json=body,
                               headers=headers, verify=VERIFY_CERT)
    except OSError as err:
        logger.error('ERROR: %s', str(err))
        raise DeployError('error: cannot del {} at {}'.format(name, api_url))

    if not resp.ok:
        logger.error('ERROR: %s', resp.text)
        raise DeployError('failed to delete {}'.format(name))
    print('Delete successful')


def delete_parser(parser):
    parser.add_argument('name', help='function name', default='')
    parser.add_argument('--dashboard-url', '-d', help='dashboard URL')
    parser.add_argument('--namespace', '-n', help='kubernetes namespace')
