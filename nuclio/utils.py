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
from argparse import ArgumentParser
from ast import literal_eval
import shlex


class env_keys:
    handler_name = 'NUCLIO_HANDLER_NAME'
    handler_path = 'NUCLIO_HANDLER_PATH'


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
    parser = ArgumentParser(prog='%nuclio')
    parser.add_argument('--output-dir')
    parser.add_argument('--notebook')
    parser.add_argument('--handler-name')
    parser.add_argument('--handler-path')

    if isinstance(args, str):
        args = shlex.split(args)

    return parser.parse_known_args(args)
