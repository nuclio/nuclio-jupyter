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
import re
from os import path, environ
import shlex
from argparse import ArgumentParser
from base64 import b64decode

import yaml
import requests

default_volume_type = 'v3io'
missing = object()


class env_keys:
    handler_name = 'NUCLIO_HANDLER_NAME'
    handler_path = 'NUCLIO_HANDLER_PATH'
    no_embed_code = 'NUCLIO_NO_EMBED_CODE'
    env_files = 'NUCLIO_ENV_FILES'


def parse_env(line):
    i = line.find('=')
    if i == -1:
        return None, None
    key, value = line[:i].strip(), line[i+1:].strip()
    value = path.expandvars(value)
    return key, value


def iter_env_lines(fp):
    for line in fp:
        line = line.strip()
        if not line or line[0] == '#':
            continue
        yield line


def parse_config_line(line):
    # a.b.c = "x"
    # a += 17
    match = re.search(r'(\w+(\.\w+)*)\s*(\+?=)\s*?(.+)', line)
    if not match:
        raise ValueError('bad config line - {!r}'.format(line))

    key = match.group(1)
    op = match.group(3)
    value = match.group(4).strip()
    value = path.expandvars(value)
    try:
        value = json.loads(value)
    except (SyntaxError, ValueError):
        raise ValueError(
            'cant eval config value: "{}" in line: {}'.format(value, line))

    return key, op, value


def parse_export_line(args):
    parser = ArgumentParser(prog='%nuclio', add_help=False)
    parser.add_argument('--target-dir', '-t', default='')
    parser.add_argument('--name', '-n', default='')
    parser.add_argument('--key', '-k', default='')
    parser.add_argument('--username', '-u', default='')
    parser.add_argument('--secret', '-s', default='')
    parser.add_argument('--handler')

    if isinstance(args, str):
        args = path.expandvars(args)
        args = shlex.split(args)

    return parser.parse_known_args(args)


def get_in(obj, keys):
    """
    >>> get_in({'a': {'b': 1}}, 'a.b')
    1
    """
    if isinstance(keys, str):
        keys = keys.split('.')

    for key in keys:
        if not obj or key not in obj:
            return None
        obj = obj[key]
    return obj


def update_in(obj, key, value, append=False):
    parts = key.split('.') if isinstance(key, str) else key
    for part in parts[:-1]:
        sub = obj.get(part, missing)
        if sub is missing:
            sub = obj[part] = {}
        obj = sub

    last_key = parts[-1]
    if last_key not in obj:
        if append:
            obj[last_key] = []
        else:
            obj[last_key] = {}

    if append:
        if isinstance(value, list):
            obj[last_key] += value
        else:
            obj[last_key].append(value)
    else:
        obj[last_key] = value


def load_config(config_file, auth=None):
    config_data = read_or_download(config_file, auth)
    return load_config_data(config_data)


def load_config_data(config_data, auth=None):
    config = yaml.safe_load(config_data)
    code = config['spec']['build'].get('functionSourceCode')
    if code:
        code = b64decode(code).decode('utf-8')
    return code, config


def parse_mount_line(args):
    parser = ArgumentParser(prog='%nuclio', add_help=False)
    parser.add_argument('--type', '-t', default='')
    parser.add_argument('--name', '-n', default='fs')
    parser.add_argument('--key', '-k', default='')
    parser.add_argument('--readonly', '-r', default=False)

    if isinstance(args, str):
        args = path.expandvars(args)
        args = shlex.split(args)

    return parser.parse_known_args(args)


class Volume:
    """nuclio volume mount"""

    def __init__(self, local, remote, typ='', name='fs',
                 key='', readonly=False):
        self.local = local
        self.remote = remote
        self.name = name
        self.key = key
        self.type = typ
        if not typ:
            self.type = default_volume_type
        self.readonly = readonly

    def render(self, config):

        if self.remote.startswith('~/'):
            user = environ.get('V3IO_USERNAME', '')
            self.remote = 'users/' + user + self.remote[1:]

        container, subpath = split_path(self.remote)
        key = self.key or environ.get('V3IO_ACCESS_KEY', '')

        if self.type == 'v3io':
            vol = {'name': self.name, 'flexVolume': {
                'driver': 'v3io/fuse',
                'options': {
                    'container': container,
                    'subPath': subpath,
                    'accessKey': key,
                }
            }}

            mnt = {'name': self.name, 'mountPath': self.local}
            update_in(config, 'spec.volumes',
                      {'volumeMount': mnt, 'volume': vol}, append=True)

        else:
            raise Exception('unknown volume type {}'.format(self.type))


def split_path(mntpath=''):
    if mntpath[0] == '/':
        mntpath = mntpath[1:]
    paths = mntpath.split('/')
    container = paths[0]
    subpath = ''
    if len(paths) > 1:
        subpath = mntpath[len(container):]
    return container, subpath


def fill_config(config, extra_config={}, env=[], cmd='', mount: Volume = None):
    if config:
        for k, v in extra_config.items():
            current = get_in(config, k)
            update_in(config, k, v, isinstance(current, list))
    if env:
        set_env(config, env)
    if cmd:
        set_commands(config, cmd.splitlines())
    if mount:
        mount.render(config)


def set_env(config, env):
    for line in env:
        line = line.strip()
        if not line or line[0] == '#':
            continue

        key, value = parse_env(line)
        if not key:
            raise ValueError(
                'cannot parse environment value from: {}'.format(line))

        i = find_env_var(config['spec']['env'], key)
        item = {'name': key, 'value': value}
        if i >= 0:
            config['spec']['env'][i] = item
        else:
            config['spec']['env'].append(item)


def find_env_var(env_list, key):
    i = 0
    for v in env_list:
        if v['name'] == key:
            return i
        i += 1

    return -1


def set_commands(config, commands):
    for line in commands:
        line = line.strip()
        if not line or line[0] == '#':
            continue

        line = path.expandvars(line)
        update_in(config, 'spec.build.commands', line, append=True)


def read_or_download(urlpath, auth=None):
    if urlpath.startswith('http://') or urlpath.startswith('https://'):
        return download_http(urlpath, auth)

    with open(urlpath) as fp:
        return fp.read()


def download_http(url, auth=None):
    headers = {}
    if isinstance(auth, dict):
        headers = auth
        auth = None

    try:
        resp = requests.get(url, headers=headers, auth=auth)
    except OSError:
        raise OSError('error: cannot connect to {}'.format(url))

    if not resp.ok:
        raise OSError('failed to read file in {}'.format(url))

    return resp.text


def is_url(file_path):
    return file_path.startswith('http://') or \
           file_path.startswith('https://') or file_path.startswith('s3://')


def normalize_name(name):
    # TODO: Must match
    # [a-z0-9]([-a-z0-9]*[a-z0-9])?(\\.[a-z0-9]([-a-z0-9]*[a-z0-9])?
    name = re.sub(r'\s+', '-', name)
    name = name.replace('_', '-')
    return name.lower()
