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


import re
import shlex
from argparse import ArgumentParser
from ast import literal_eval
from base64 import b64decode

import yaml

missing = object()


class env_keys:
    handler_name = 'NUCLIO_HANDLER_NAME'
    handler_path = 'NUCLIO_HANDLER_PATH'
    no_embed_code = 'NUCLIO_NO_EMBED_CODE'


def parse_env(line):
    i = line.find('=')
    if i == -1:
        return None, None
    key, value = line[:i].strip(), line[i+1:].strip()
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
    try:
        value = literal_eval(value)
    except SyntaxError:
        raise ValueError(line)

    return key, op, value


def parse_export_line(args):
    parser = ArgumentParser(prog='%nuclio', add_help=False)
    parser.add_argument('--output-dir')
    parser.add_argument('--notebook')
    parser.add_argument('--handler-name')
    parser.add_argument('--handler-path')
    parser.add_argument('--no-embed')

    if isinstance(args, str):
        args = shlex.split(args)

    return parser.parse_known_args(args)


def update_in(obj, key, value, append=False):
    parts = key.split('.')
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
        obj[last_key].append(value)
    else:
        obj[last_key] = value


def load_config(config_file):
    config = yaml.load(config_file)
    code = config['spec']['build'].get('functionSourceCode')
    if code:
        code = b64decode(code).decode('utf-8')
    return code, config
