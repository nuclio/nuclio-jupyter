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
from io import StringIO
from os import environ, path
from textwrap import indent
from sys import stdout

import yaml
from nbconvert.exporters import Exporter
from nbconvert.filters import ipython2python

from .utils import (env_keys, iter_env_lines, parse_config_line,
                    parse_mount_line, normalize_name)
from .archive import parse_archive_line
from .config import (new_config, update_in, get_in, set_env, set_commands,
                     Volume, meta_keys)
from . import magic as magic_module

here = path.dirname(path.abspath(__file__))

Magic = namedtuple('Magic', 'name args lines is_cell')
magic_handlers = {}  # name -> function
env_files = set()
archive_settings = {}

annotation_prefix = r'[ \t]*#[ \t]*(nuclio|mlrun):[ \t]*'
is_comment = re.compile(r'[ \t]*#.*').match
is_annotation = re.compile(rf'{annotation_prefix}(return|ignore|start-code|end-code).*').match
# # nuclio: return
is_return = re.compile(rf'{annotation_prefix}return').search
# # nuclio: ignore
has_ignore = re.compile(rf'{annotation_prefix}ignore').search
has_start = re.compile(rf'{annotation_prefix}start-code[ \t]*(?P<name>([\S]*))?').search
has_end = re.compile(rf'{annotation_prefix}end-code[ \t]*(?P<name>([\S]*))?').search
default_ignored_tags = 'mlrun-ignore;nuclio-ignore'
handler_decl = 'def {}(context, event):'
indent_prefix = '    '
line_magic = '%nuclio'
cell_magic = '%' + line_magic

handlers = []


class MagicError(Exception):
    pass


def create_logger():
    handler = logging.StreamHandler(stdout)
    handler.setFormatter(
        logging.Formatter('[%(name)s] %(asctime)s %(message)s'))
    logger = logging.getLogger('nuclio.export')
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


log = create_logger()


def tags_to_ignore():
    ignored_tags = environ.get(env_keys.ignored_tags) or []
    if ignored_tags:
        ignored_tags = ignored_tags.split(";")
    return ignored_tags + default_ignored_tags.split(";")


def ignore_tagged_cell(tags, tags_to_ignore):
    intersected_tags = set(tags or []).intersection(tags_to_ignore)
    return len(intersected_tags) > 0


class NuclioExporter(Exporter):
    """Export to nuclio handler"""

    # Add "File -> Download as" menu in the notebook
    export_from_notebook = 'Nuclio'

    @property
    def output_mimetype(self):
        if archive_settings:
            return 'application/zip'
        else:
            return 'application/yaml'

    def _file_extension_default(self):
        """Return default file extension"""
        return '.yaml'

    def from_notebook_node(self, nb, resources=None, **kw):
        config = new_config()
        nbname = name = get_in(resources, 'metadata.name')  # notebook name
        if name:
            config['metadata']['name'] = normalize_name(name)
        config['spec']['handler'] = handler_name()

        code_cells = self.scan_notebook_cells(config, nb['cells'])
        io = self.write_code_cells(code_cells)
        process_env_files(env_files, config)
        py_code = io.getvalue()
        handler_path = environ.get(env_keys.handler_path)
        if handler_path:
            with open(handler_path) as fp:
                py_code = fp.read()

        efiles = []
        if archive_settings:
            if archive_settings['notebook'] and nbname:
                archive_settings['files'] += [nbname + '.ipynb']
            efiles = ','.join(archive_settings['files'])
            config['metadata']['annotations'][meta_keys.extra_files] = efiles

        if env_keys.code_target_path in environ:
            code_path = environ.get(env_keys.code_target_path)
            with open(code_path, 'w') as fp:
                fp.write(py_code)
                fp.close()
        elif efiles and env_keys.drop_nb_outputs not in environ:
            outputs = {'handler.py': py_code,
                       'function.yaml': gen_config(config)}
            for filename in efiles:
                with open(filename) as fp:
                    data = fp.read()
                    outputs[filename] = data
            resources['outputs'] = outputs
        else:
            data = b64encode(py_code.encode('utf-8')).decode('utf-8')
            update_in(config, 'spec.build.functionSourceCode', data)

        config = gen_config(config)
        resources['output_extension'] = '.yaml'

        return config, resources

    def scan_notebook_cells(self, config, cells):
        ended = 'ended'
        started = 'started'
        code_cells = 'code_cells'
        nameless_annotation = ''
        target_function_name = environ.get(env_keys.function_name)
        ignored_tags = tags_to_ignore()
        seen_function_name = nameless_annotation

        function_buffers = {
            nameless_annotation: {
                ended: False,
                started: False,
                code_cells: [],
            },
        }
        if target_function_name:
            function_buffers[target_function_name] = {
                ended: False,
                started: False,
                code_cells: [],
            }
        else:
            # to avoid accidental KeyError
            target_function_name = nameless_annotation

        for cell in filter(is_code_cell, cells):
            code_in_cell_with_annotation = ''
            code = cell['source']
            tags = get_in(cell, 'metadata.tags')
            if has_ignore(code) or ignore_tagged_cell(tags, ignored_tags):
                continue

            match = has_start(code)
            if match:
                current_name = match.group('name')
                if current_name in [target_function_name, nameless_annotation]:
                    if not function_buffers[current_name][started]:
                        # discard code that doesn't belong to the function
                        function_buffers[current_name][code_cells] = []
                    if function_buffers[current_name][started] \
                            and not function_buffers[current_name][ended]:
                        raise MagicError('Found multiple consecutive "start-code" annotations')
                    # keep code after 1st occurrence of start-code
                    code_in_cell_with_annotation = code[match.span()[1]:]
                    function_buffers[current_name][started] = True
                    function_buffers[current_name][ended] = False
                    seen_function_name = seen_function_name or current_name

            match = has_end(code)
            if match:
                current_name = match.group('name')
                if current_name in [target_function_name, nameless_annotation]:
                    if function_buffers[current_name][ended]:
                        raise MagicError('Found multiple consecutive "end-code" annotations')
                    # keep code before 1st occurrence of end-code
                    if code_in_cell_with_annotation:
                        match = has_end(code_in_cell_with_annotation)
                        if not match:
                            raise MagicError('end-code before start-code in '
                                             'the same cell is not '
                                             'supported')
                        code_in_cell_with_annotation = \
                            code_in_cell_with_annotation[:match.span()[0]]
                    else:
                        code_in_cell_with_annotation = code[:match.span()[0]]
                    # found code that belongs to the current function
                    function_buffers[current_name][started] = True
                    function_buffers[current_name][ended] = True
                    seen_function_name = seen_function_name or current_name

            code = filter_annotations_and_commented_magic(code)
            lines = code.splitlines()
            if cell_magic in code:
                code = self.handle_cell_magic(config, lines)

            # must be else (cell_magic token contains line_magic)
            elif line_magic in code:
                code = self.handle_line_magic(config, lines)

            for function_buffer in function_buffers.values():
                if code_in_cell_with_annotation:
                    function_buffer[code_cells].\
                        append(code_in_cell_with_annotation)
                elif not function_buffer[ended]:
                    function_buffer[code_cells].append(code)

        return function_buffers[seen_function_name][code_cells]

    def write_code_cells(self, codes):
        io = StringIO()
        print(header(), file=io)
        for code in codes:
            if not code.strip():
                continue

            lines = code.splitlines()
            self.handle_code_cell(lines, io)
        return io

    def find_cell_magic(self, lines):
        """Return index of first line that has %%nuclio"""
        for i, line in enumerate(lines):
            if cell_magic in line:
                return i
        return -1

    def handle_cell_magic(self, config, lines):
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

        return code

    def handle_code_cell(self, lines, io):
        buf = []
        for line in lines:
            if line_magic in line:
                continue

            # ignore commands or any magic commands (other than %nuclio)
            if line.startswith('!') or line.startswith('%'):
                continue

            buf.append(line)

        if buf:
            print(ipython2python('\n'.join(buf)), file=io)

    def handle_line_magic(self, config, lines):
        buf = []
        for line in lines:
            if is_comment(line):
                continue

            if line_magic not in line:
                # ignore commands or any magic commands (other than %nuclio)
                if not (line.startswith('!') or line.startswith('%')):
                    buf.append(line)
                continue

            name, args = parse_magic_line(line)
            magic = Magic(name, args, [], is_cell=False)
            handler = magic_handlers.get(magic.name)
            if not handler:
                raise NameError(
                    'unknown nuclio command: {}'.format(magic.name))

            out = handler(magic, config)
            if out:
                buf.append(out)

        return '\n'.join(buf)


def header():
    name = exporter_name()
    return '# Generated by {}\n'.format(name)


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


@magic_handler
def env(magic, config):
    argline = magic.args.strip()
    if argline.startswith('--local-only') or argline.startswith('-l'):
        return ''

    if argline.startswith('--config-only'):
        argline = argline.replace('--config-only', '').strip()
    if argline.startswith('-c'):
        argline = argline.replace('-c', '').strip()

    set_env(config, [argline] + magic.lines)
    return ''


@magic_handler
def cmd(magic, config):
    argline = magic.args.strip()
    if argline.startswith('--config-only'):
        argline = argline.replace('--config-only', '').strip()
    if argline.startswith('-c'):
        argline = argline.replace('-c', '').strip()
    set_commands(config, [argline] + magic.lines)
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
            set_env(config, iter_env_lines(fp))


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
            lines[len(lines) - i - 1] = add_return(line)
        break

    return '\n'.join(lines)


@magic_handler
def build(magic, config):
    return ''


@magic_handler
def deploy(magic, config):
    return ''


@magic_handler
def help(magic, config):
    return ''


@magic_handler
def show(magic, config):
    return ''


@magic_handler
def mount(magic, config):
    args, rest = parse_mount_line(magic.args)
    if len(rest) != 2:
        raise MagicError(
            '2 arguments must be provided (mount point and remote path)')

    volume = Volume(rest[0], rest[1], typ=args.type, name=args.name,
                    key=args.key, readonly=args.readonly)
    volume.render(config)
    return ''


@magic_handler
def add(magic, config):
    global archive_settings
    args, rest = parse_archive_line(magic.args)

    files = args.file + magic.lines
    for filename in files:
        filename = filename.strip()
        if not path.isfile(filename):
            raise MagicError('file {} doesnt exist'.format(filename))

    archive_settings = {'files': files, 'notebook': args.add_notebook}
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


def filter_annotations_and_commented_magic(code):
    lines = [
        line for line in code.splitlines() if not ((line_magic in line and is_comment(line)) or is_annotation(line))
    ]
    return '\n'.join(lines)
