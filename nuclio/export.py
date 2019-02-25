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
import logging
import re
from base64 import b64encode
from collections import namedtuple
from copy import deepcopy
from datetime import datetime
from io import StringIO
from os import environ, path
from textwrap import indent

import yaml
from nbconvert.exporters import Exporter
from nbconvert.filters import ipython2python

from .utils import (env_keys, iter_env_lines, parse_config_line, parse_env,
                    update_in)
from .import magic as magic_module

here = path.dirname(path.abspath(__file__))

Magic = namedtuple('Magic', 'name args lines is_cell')
magic_handlers = {}  # name -> function
env_files = set()

is_comment = re.compile(r'\s*#.*').match
# # nuclio: return
is_return = re.compile(r'#\s*nuclio:\s*return').search
# # nuclio: ignore
has_ignore = re.compile(r'#\s*nuclio:\s*ignore').search
has_start = re.compile(r'#\s*nuclio:\s*start').search
handler_decl = 'def {}(context, event):'
indent_prefix = '    '
line_magic = '%nuclio'
cell_magic = '%' + line_magic

_function_config = {
    'apiVersion': 'nuclio.io/v1',
    'kind': 'Function',
    'metadata': {
        'name': 'notebook',
        'namespace': 'default-tenant',
    },
    'spec': {
        'runtime': 'python:3.6',
        'handler': None,
        'env': [],
        'build': {
            'commands': [],
            'noBaseImagesPull': True,
        },
        # TODO: Remove this once this is fixed in nuclio
        'minReplicas': 1,
        'maxReplicas': 1,
    },
}

handlers = []


class MagicError(Exception):
    pass


logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s - %(name)s - %(levelname)s] %(message)s',
    datefmt='%Y%m%dT%H%M%S',
)
log = logging.getLogger('nuclio.export')


def new_config():
    return deepcopy(_function_config)


class NuclioExporter(Exporter):
    """Export to nuclio handler"""

    # Add "File -> Download as" menu in the notebook
    export_from_notebook = 'Nuclio'

    output_mimetype = 'application/yaml'

    def _file_extension_default(self):
        """Return default file extension"""
        return '.yaml'

    def from_notebook_node(self, nb, resources=None, **kw):
        config = new_config()
        name = get_in(resources, 'metadata.name')  # notebook name
        if name:
            config['metadata']['name'] = normalize_name(name)
        config['spec']['handler'] = handler_name()

        io = StringIO()
        print(header(), file=io)

        for cell in filter(is_code_cell, nb['cells']):
            code = cell['source']
            if has_ignore(code):
                continue

            if has_start(code):
                # if we see indication of start, we ignore all previous cells
                io = StringIO()
                print(header(), file=io)

            code = filter_comments(code)
            if not code.strip():
                continue

            lines = code.splitlines()
            if cell_magic in code:
                self.handle_cell_magic(lines, io, config)
                continue

            self.handle_code_cell(lines, io, config)

        process_env_files(env_files, config)
        py_code = io.getvalue()
        handler_path = environ.get(env_keys.handler_path)
        if handler_path:
            with open(handler_path) as fp:
                py_code = fp.read()

        data = b64encode(py_code.encode('utf-8')).decode('utf-8')
        if env_keys.no_embed_code not in environ:
            update_in(config, 'spec.build.functionSourceCode', data)

        config = gen_config(config)
        resources['output_extension'] = '.yaml'
        return config, resources

    def find_cell_magic(self, lines):
        """Return index of first line that has %%nuclio"""
        for i, line in enumerate(lines):
            if cell_magic in line:
                return i
        return -1

    def handle_cell_magic(self, lines, io, config):
        i = self.find_cell_magic(lines)
        if i == -1:
            raise MagicError('cannot find {}'.format(cell_magic))

        lines = lines[i:]
        name, args = parse_magic_line(lines[0])
        magic = Magic(name, args, lines[1:], is_cell=True)
        handler = magic_handlers.get(magic.name)
        if not handler:
            if magic.name not in magic_module.commands:
                raise NameError(
                    'unknown nuclio command: {}'.format(magic.name))
            else:
                log.warning('skipping %s - not implemented', magic.name)
                code = ''
        else:
            code = handler(magic, config)

        if code:
            print(ipython2python(code), file=io)

    def handle_code_cell(self, lines, io, config):
        buf = []
        for line in lines:
            if is_comment(line):
                continue

            if '%nuclio' not in line:
                # ignore command or magic commands (other than %nuclio)
                if not (line.startswith('!') or line.startswith('%')):
                    buf.append(line)
                continue

            if buf:
                print(ipython2python('\n'.join(buf)), file=io)
                buf = []

            name, args = parse_magic_line(line)
            magic = Magic(name, args, [], is_cell=False)
            handler = magic_handlers.get(magic.name)
            if not handler:
                raise NameError(
                    'unknown nuclio command: {}'.format(magic.name))

            out = handler(magic, config)
            if out:
                print(ipython2python(out), file=io)

        if buf:
            print(ipython2python('\n'.join(buf)), file=io)


def normalize_name(name):
    # TODO: Must match
    # [a-z0-9]([-a-z0-9]*[a-z0-9])?(\\.[a-z0-9]([-a-z0-9]*[a-z0-9])?
    name = re.sub(r'\s+', '-', name)
    name = name.replace('_', '-')
    return name.lower()


def header():
    name = exporter_name()
    now = datetime.now()
    return '# Generated by {} on {:%Y-%m-%d %H:%M}\n'.format(name, now)


def exporter_name():
    return '{}.{}'.format(NuclioExporter.__module__, NuclioExporter.__name__)


def gen_config(config):
    return header() + yaml.dump(config, default_flow_style=False)


def parse_magic_line(line):
    """Parse a '%nuclio' command. Return name, args

    >>> parse_magic_line('%nuclio config a="b"')
    ('config', ['a="b"'])
    """
    if line_magic not in line:
        return None

    line = line.strip()
    match = re.search(r'^%?%nuclio\s+(\w+)\s*', line)
    if not match:
        raise MagicError(line)

    cmd = match.group(1)
    args = line[match.end():].strip()
    return cmd, args


def magic_handler(fn):
    magic_handlers[fn.__name__] = fn
    return fn


def set_env(config, key, value):
    obj = {
        'name': key,
        'value': value,
    }
    config['spec']['env'].append(obj)


@magic_handler
def env(magic, config):
    argline = magic.args.strip()
    if argline.startswith('--local-only') or argline.startswith('-l'):
        return ''

    if argline.startswith('--config-only'):
        argline = argline.replace('--config-only', '').strip()
    if argline.startswith('-c'):
        argline = argline.replace('-c', '').strip()

    for line in [argline] + magic.lines:
        line = line.strip()
        if not line or line[0] == '#':
            continue

        key, value = parse_env(line)
        if not key:
            raise ValueError(
                'cannot parse environment value from: {}'.format(line))
        set_env(config, key, value)
    return ''


@magic_handler
def cmd(magic, config):
    argline = magic.args.strip()
    if argline.startswith('--config-only'):
        argline = argline.replace('--config-only', '').strip()
    if argline.startswith('-c'):
        argline = argline.replace('-c', '').strip()

    for line in [argline] + magic.lines:
        line = line.strip()
        if not line or line[0] == '#':
            continue

        line = path.expandvars(line)
        update_in(config, 'spec.build.commands', line, append=True)
    return ''


@magic_handler
def env_file(magic, config):
    for line in [magic.args] + magic.lines:
        file_name = line.strip()
        if file_name[:1] in ('', '#'):
            continue

        if not path.isfile(file_name):
            log.warning('skipping %s - not found', file_name)
            continue
        env_files.add(file_name)
    return ''


def process_env_files(env_files, config):
    # %nuclio env_file magic will populate this
    from_env = json.loads(environ.get(env_keys.env_files, '[]'))
    for fname in (env_files | set(from_env)):
        with open(fname) as fp:
            for line in iter_env_lines(fp):
                key, value = parse_env(line)
                if not key:
                    raise ValueError(
                        '{}: cannot parse environment: {}'.format(fname, line))
                set_env(config, key, value)


def is_code_cell(cell):
    return cell['cell_type'] == 'code'


def is_code_line(line):
    """A code line is a non empty line that don't start with #"""
    return line.strip()[:1] not in {'#', '%', ''}


def add_return(line):
    """Add return to a line"""
    match = re.search(r'\w', line)
    if not match:
        # TODO: raise?
        return line

    return line[:match.start()] + 'return ' + line[match.start():]


@magic_handler
def handler(magic, config):
    name = magic.args if magic.args else next_handler_name()
    if env_keys.handler_name not in environ:
        module, _ = config['spec']['handler'].split(':')
        config['spec']['handler'] = '{}:{}'.format(module, name)

    code = '\n'.join(magic.lines)
    return handler_code(name, code)


def handler_code(name, code):
    lines = [handler_decl.format(name)]
    code = indent(code, indent_prefix)
    for line in code.splitlines():
        if is_return(line):
            line = add_return(line)
        lines.append(line)

    # Add return to last code line (if not there)
    for i, line in enumerate(lines[::-1]):
        if not is_code_line(line):
            continue

        if 'return' not in line:
            lines[len(lines)-i-1] = add_return(line)
        break

    return '\n'.join(lines)


@magic_handler
def export(magic, config):
    return ''


@magic_handler
def deploy(magic, config):
    return ''


@magic_handler
def config(magic, config):
    for line in [magic.args] + magic.lines:
        line = line.strip()
        if not line or line[0] == '#':
            continue

        key, op, value = parse_config_line(line)
        append = op == '+='
        update_in(config, key, value, append)
    return ''


def next_handler_name():
    if handlers:
        name = 'handler_{}'.format(len(handlers))
    else:
        name = 'handler'
    handlers.append(name)
    return name


def module_name(py_file):
    """
    >>> module_name('/path/to/handler.py')
    'handler'
    """
    base = path.basename(py_file)
    module, _ = path.splitext(base)
    return module


def handler_name():
    handler_path = environ.get(env_keys.handler_path)
    if handler_path:
        module = module_name(handler_path)
    else:
        module = 'handler'

    name = environ.get(env_keys.handler_name, 'handler')
    return '{}:{}'.format(module, name)


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


def filter_comments(code):
    lines = (line for line in code.splitlines() if not is_comment(line))
    return '\n'.join(lines)
