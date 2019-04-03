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
import requests
from os import path
import shlex
from argparse import ArgumentParser

import ipykernel
from notebook.notebookapp import list_running_servers
from urllib.parse import urlencode, urljoin
from urllib.request import urlopen


class DeployError(Exception):
    pass


class env_keys:
    handler_name = 'NUCLIO_HANDLER_NAME'
    handler_path = 'NUCLIO_HANDLER_PATH'
    function_tag = 'NUCLIO_FUNCTION_TAG'
    drop_nb_outputs = 'NUCLIO_NO_OUTPUTS'
    code_target_path = 'NUCLIO_CODE_PATH'
    env_files = 'NUCLIO_ENV_FILES'
    extra_files = 'NUCLIO_EXTRA_FILES'


def list2dict(lines: list):
    out = {}
    for line in lines:
        key, value = parse_env(line)
        if key is None:
            raise ValueError('cannot find "=" in line')
            return
        out[key] = value
    return out


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
    parser.add_argument('--output', '-o', default='')
    parser.add_argument('--tag', '-t', default='')
    parser.add_argument('--name', '-n', default='')
    parser.add_argument('--key', '-k', default='')
    parser.add_argument('--username', '-u', default='')
    parser.add_argument('--secret', '-s', default='')
    parser.add_argument('--handler')
    parser.add_argument('--env', '-e', default=[], action='append',
                        help='override environment variable (key=value)')

    if isinstance(args, str):
        args = path.expandvars(args)
        args = shlex.split(args)

    return parser.parse_known_args(args)


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


# Based on
# https://github.com/jupyter/notebook/issues/1000#issuecomment-359875246
def notebook_file_name(ikernel):
    """Return the full path of the jupyter notebook."""
    # Check that we're running under notebook
    if not (ikernel and ikernel.config['IPKernelApp']):
        return

    kernel_id = re.search('kernel-(.*).json',
                          ipykernel.connect.get_connection_file()).group(1)
    servers = list_running_servers()
    for srv in servers:
        query = {'token': srv.get('token', '')}
        url = urljoin(srv['url'], 'api/sessions') + '?' + urlencode(query)
        for session in json.load(urlopen(url)):
            if session['kernel']['id'] == kernel_id:
                relative_path = session['notebook']['path']
                return path.join(srv['notebook_dir'], relative_path)
