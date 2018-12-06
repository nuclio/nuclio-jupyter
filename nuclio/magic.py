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

from os import environ
from sys import stderr

import yaml
from IPython.core.magic import register_line_cell_magic
from IPython import get_ipython

# name -> function
commands = {}


def noop_log(msg):
    pass


def verbose_log(message):
    print('%nuclio: {}'.format(message))


log = verbose_log


def log_error(msg):
    print('%nuclio: {}'.format(msg), file=stderr)


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
    """Toggle verbose mode.\n\nExample:

    In [1]: %nuclio verobose
    %nuclio: verbose off
    In [2]: %nuclio verobose
    %nuclio: verbose on
    """
    global log

    log = noop_log if log is verbose_log else verbose_log
    print('%nuclio: verbose {}'.format('on' if log is verbose_log else 'off'))


def set_env(line):
    i = line.find('=')
    if i == -1:
        log_error('cannot find "=" in line')
        return
    key, value = line[:i].strip(), line[i+1:].strip()
    # We don't print the value since it might be password, API key ...
    log('setting {!r} environment variable'.format(key))
    environ[key] = value


def cell_lines(cell):
    if cell is None:
        return []

    return filter(str.strip, cell.splitlines())


@command
def env(line, cell):
    """Set environment variable.\n\nExamples:

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
    """Print help on command.\n\nExample:

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
            print('- {}: {}'.format(cmd, short_help))
        return

    fn = commands.get(cmd)
    if not fn:
        log_error('unknown command: {}'.format(cmd))
        return

    print(fn.__doc__)


def env_from_file(path):
    with open(path) as fp:
        data = yaml.safe_load(fp)

    if isinstance(data, list):
        for line in data:
            set_env(line)
    elif isinstance(data, dict):
        for key, value in data.items():
            set_env('{}={}'.format(key, value))
    else:
        log_error('wrong type for env_file: {}'.format(type(data)))


@command
def env_file(line, cell):
    """Set environment from YAML file(s).\n\nExamples:

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
    """Run a command.\n\nExamples:
    In [1]: %nuclio cmd pip install chardet==1.0.1

    In [2]: %%nuclio cmd
    ...: apt-get install -y libyaml-dev
    ...: pip install pyyaml==3.13

    If you'd like to only to add the instructions to function.yaml without
    running it locally, use the '--config-only' flag

    In [3]: %nuclio cmd --config-only apt-get install -y libyaml-dev
    """
    if line.startswith('--config-only'):
        return

    ipy = get_ipython()
    if line:
        ipy.system(line)

    for line in cell_lines(cell):
        ipy.system(line)


@command
def export(line, cell):
    """Export function .\n\nExamples:
    In [1]: %nuclio export
    nulcio: /tmp/handler.zip created
    """


@command
def ignore(line, call):
    """Mark this cell as ignored by nuclio. It won't be included in the
    generated handler."""
    pass


@command
def handler(line, cell):
    """Mark this cell as handler function. Export will make it a function.

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
    pass
