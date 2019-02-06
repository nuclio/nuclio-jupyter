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
import shlex
from argparse import ArgumentParser
from base64 import b64decode
from glob import glob
from os import environ, path
from shutil import copy
from subprocess import PIPE, run, Popen
from sys import executable, stderr
from tempfile import mkdtemp
from urllib.parse import urlencode, urljoin
from urllib.request import urlopen

import yaml
import ipykernel
from IPython import get_ipython
from IPython.core.magic import register_line_cell_magic
from notebook.notebookapp import list_running_servers

from .deploy import populate_parser as populate_deploy_parser
from .utils import (env_keys, iter_env_lines, load_config, parse_config_line,
                    parse_env, parse_export_line)

log_prefix = '%nuclio: '
here = path.dirname(path.abspath(__file__))


# Make sure we're working when not running under IPython/Jupyter
kernel = get_ipython()
if kernel is None:
    def register_line_cell_magic(fn):  # noqa
        return fn

# name -> function
commands = {}


def noop_log(msg):
    pass


def verbose_log(message):
    print('{}{}'.format(log_prefix, message))


log = verbose_log


def log_error(msg):
    print('{}{}'.format(log_prefix, msg), file=stderr)


def command(fn):
    """Decorator to register fn as nuclio magic command"""
    commands[fn.__name__] = fn
    return fn


@register_line_cell_magic
def nuclio(line, cell=None):
    line = line.strip()
    if not line:
        log_error('require one of: {}'.format(sorted(commands)))
        return

    cmd = line.split()[0].lower()
    fn = commands.get(cmd)
    if fn is None:
        log_error('unknown command: {}'.format(cmd))
        return

    line = line[len(cmd):].strip()  # Remove command from line
    fn(line, cell)


@command
def verbose(line, cell):
    """Toggle verbose mode.

    Example:
    In [1]: %nuclio verobose
    %nuclio: verbose off
    In [2]: %nuclio verobose
    %nuclio: verbose on
    """
    global log

    log = noop_log if log is verbose_log else verbose_log
    print('%nuclio: verbose {}'.format('on' if log is verbose_log else 'off'))


def set_env(line):
    key, value = parse_env(line)
    if key is None:
        log_error('cannot find "=" in line')
        return
    # We don't print the value since it might be password, API key ...
    log('setting {!r} environment variable'.format(key))
    environ[key] = value


def cell_lines(cell):
    if cell is None:
        return []

    return filter(str.strip, cell.splitlines())


@command
def env(line, cell):
    """Set environment variable. Will update "spec.env" in configuration.

    Examples:
    In [1]: %nuclio env USER=iguzaio
    %nuclio: setting 'iguazio' environment variable

    In [2]: %%nuclio env
    ...: USER=iguazio
    ...: PASSWORD=t0ps3cr3t
    ...:
    ...:
    %nuclio: setting 'USER' environment variable
    %nuclio: setting 'PASSWORD' environment variable
    """
    if line:
        set_env(line)

    for line in cell_lines(cell):
        set_env(line)


@command
def help(line, cell):
    """Print help on command.

    Example:
    In [1]: %nuclio help
    Available commands:
    - env
    - env_file
    ...

    In [2]: %nuclio help env
    ... (verbose env)
    """
    cmd = line.strip().lower()
    if not cmd:
        print('Show help on command. Available commands:')
        for cmd, fn in sorted(commands.items()):
            doc = fn.__doc__
            if doc is None:
                short_help = ''
            else:
                i = doc.find('.')
                short_help = doc[:i] if i != -1 else doc[:40]
            print('    - {}: {}'.format(cmd, short_help))
        return

    fn = commands.get(cmd)
    if not fn:
        log_error('unknown command: {}'.format(cmd))
        return

    print(fn.__doc__)


def env_from_file(path):
    with open(path) as fp:
        for line in iter_env_lines(fp):
            set_env(line)
    update_env_files(path)


@command
def env_file(line, cell):
    """Set environment from file(s). Will update "spec.env" in configuration.

    Examples:
    In [1]: %nuclio env_file env.yml

    In [2]: %%nuclio env_file
    ...: env.yml
    ...: dev-env.yml
    """
    if line:
        env_from_file(line.strip())

    for line in cell_lines(cell):
        env_from_file(line)


@command
def cmd(line, cell):
    """Run a command, add it to "build.Commands" in exported configuration.

    Examples:
    In [1]: %nuclio cmd pip install chardet==1.0.1

    In [2]: %%nuclio cmd
    ...: apt-get install -y libyaml-dev
    ...: pip install pyyaml==3.13

    If you'd like to only to add the instructions to function.yaml without
    running it locally, use the '--config-only' or '-c' flag

    In [3]: %nuclio cmd --config-only apt-get install -y libyaml-dev
    """
    if line.startswith('--config-only') or line.startswith('-c'):
        return

    ipy = get_ipython()
    if line:
        ipy.system(line)

    for line in cell_lines(cell):
        ipy.system(line)


@command
def deploy(line, cell):
    """Deploy function .

    Examples:
    In [1]: %nuclio deploy
    %nuclio: function deployed

    In [2] %nuclio deploy --dashboard-url http://localhost:8080
    %nuclio: function deployed

    In [3] %nuclio deploy --project faces
    %nuclio: function deployed
    """
    class ParseError(Exception):
        pass

    def error(message):
        raise ParseError(message)

    cmd = shlex.split(line)
    try:
        # See if we're missing notebook name
        p = ArgumentParser()
        populate_deploy_parser(p)
        p.error = error
        p.parse_args(cmd)
    except ParseError:
        nb_file = notebook_file_name()
        if not nb_file:
            log_error('cannot find notebook file name')
            return

        cmd.append(shlex.quote(nb_file))

    cmd = [executable, '-m', 'nuclio', 'deploy'] + cmd
    pipe = Popen(cmd, stderr=PIPE, stdout=PIPE)
    for line in pipe.stdout:
        log(line.decode('utf-8').rstrip())

    if pipe.wait() != 0:
        log_error('cannot deploy')
        error = pipe.stderr.read().decode('utf-8')
        log_error(error.rstrip())
        return

    log('function deployed')


@command
def handler(line, cell):
    """Mark this cell as handler function. You can give optional name

    %%nuclio handler
    ctx.logger.info('handler called')
    # nuclio:return
    'Hello ' + event.body

    Will become

    def handler(context, event):
        ctx.logger.info('handler called')
        # nuclio:return
        return 'Hello ' + event.body
    """
    kernel.run_cell(cell)


# Based on
# https://github.com/jupyter/notebook/issues/1000#issuecomment-359875246
def notebook_file_name():
    """Return the full path of the jupyter notebook."""
    # Check that we're running under notebook
    if not (kernel and kernel.config['IPKernelApp']):
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


def save_handler(config_file, out_dir):
    with open(config_file) as fp:
        config = yaml.load(fp)

    py_code = b64decode(config['spec']['build']['functionSourceCode'])
    py_module = config['spec']['handler'].split(':')[0]
    with open('{}/{}.py'.format(out_dir, py_module), 'wb') as out:
        out.write(py_code)


@command
def export(line, cell, return_dir=False):
    """Export notebook. Possible options are:

    --output-dir path
        Output directory path
    --notebook path
        Path to notebook file
    --handler-name name
        Name of handler
    --handler-file path
        Path to handler code (Python file)

    Example:
    In [1] %nuclio export
    Notebook exported to handler at '/tmp/nuclio-handler-99'
    In [2] %nuclio export --output-dir /tmp/handler
    Notebook exported to handler at '/tmp/handler'
    In [3] %nuclio export --notebook /path/to/notebook.ipynb
    Notebook exported to handler at '/tmp/nuclio-handler-29803'
    In [4] %nuclio export --handler-name faces
    Notebook exported to handler at '/tmp/nuclio-handler-29804'
    In [5] %nuclio export --handler-file /tmp/faces.py
    Notebook exported to handler at '/tmp/nuclio-handler-29805'
    """

    args, rest = parse_export_line(line)
    if rest:
        log_error('unknown arguments: {}'.format(' '.join(rest)))
        return

    notebook = args.notebook or notebook_file_name()
    if not notebook:
        log_error('cannot find notebook name (try with --notebook)')
        return

    out_dir = args.output_dir or mkdtemp(prefix='nuclio-handler-')

    env = environ.copy()  # Pass argument to exporter via environment
    if args.handler_name:
        env[env_keys.handler_name] = args.handler_name

    if args.handler_path:
        if not path.isfile(args.handler_path):
            log_error(
                'cannot find handler file: {}'.format(args.handler_path))
            return
        copy(args.handler_path, out_dir)
        env[env_keys.handler_path] = args.handler_path

    if args.no_embed:
        env[env_keys.no_embed_code] = '1'

    cmd = [
        executable, '-m', 'nbconvert',
        '--to', 'nuclio.export.NuclioExporter',
        '--output-dir', out_dir,
        notebook,
    ]
    out = run(cmd, env=env, stdout=PIPE, stderr=PIPE)
    if out.returncode != 0:
        print(out.stdout.decode('utf-8'))
        print(out.stderr.decode('utf-8'), file=stderr)
        log_error('cannot convert notebook')
        return

    yaml_files = glob('{}/*.yaml'.format(out_dir))
    if len(yaml_files) != 1:
        log_error('wrong number of YAML files in {}'.format(out_dir))
        return

    save_handler(yaml_files[0], out_dir)
    log('notebook exported to {}'.format(out_dir))

    if return_dir:
        return out_dir


def uncomment(line):
    line = line.strip()
    return '' if line[:1] == '#' else line


@command
def config(line, cell):
    """Set function configuration value. Values need to be Python literals (1,
    "debug", 3.3 ...). You can use += to append values to a list

    Example:
    In [1] %nuclio config spec.maxReplicas = 5
    In [2]: %%nuclio config
    ...: spec.maxReplicas = 5
    ...: spec.runtime = "python2.7"
    ...: build.commands +=  "apk --update --no-cache add ca-certificates"
    ...:
    """
    cell = cell or ''
    for line in filter(None, map(uncomment, [line] + cell.splitlines())):
        try:
            key, op, value = parse_config_line(line)
        except ValueError:
            log_error('bad config line - {!r}'.format(line))
            return

        if op == '=':
            log('setting {} to {!r}'.format(key, value))
        else:
            log('appending {!r} to {}'.format(value, key))


def print_handler_code(notebook_file=None):
    """Prints handler code (as it was exported).

   You should save the notebook before calling this function.
    """
    notebook_file = notebook_file or notebook_file_name()
    if not notebook_file:
        raise ValueError('cannot find notebook file name')

    notebook_file = shlex.quote(notebook_file)
    line = '--notebook {}'.format(notebook_file)
    out_dir = export(line, None, return_dir=True)
    if not out_dir:
        raise ValueError('failed to export {}'.format(notebook_file))

    files = glob('{}/*.yaml'.format(out_dir))
    if len(files) != 1:
        raise ValueError('too many YAML files in {}'.format(out_dir))

    with open(files[0]) as fp:
        code, _ = load_config(fp)
    print(code)


def update_env_files(file_name):
    files = json.loads(environ.get(env_keys.env_files, '[]'))
    files.append(file_name)
    environ[env_keys.env_files] = json.dumps(files)
