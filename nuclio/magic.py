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
import shlex
from argparse import ArgumentParser
from base64 import b64decode
from os import environ, path
from sys import stderr

import yaml
from IPython import get_ipython
from IPython.core.magic import register_line_cell_magic

from .config import ConfigSpec, v3ioenv_magic
from .deploy import populate_parser as populate_deploy_parser, deploy_from_args
from .utils import (env_keys, iter_env_lines, parse_config_line, DeployError,
                    parse_env, parse_export_line, parse_mount_line,
                    notebook_file_name, list2dict, BuildError)
from .archive import parse_archive_line
from .build import build_file

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
    if line.strip() == v3ioenv_magic:
        return
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

    If you'd like to only to add the instructions to function.yaml without
    running it locally, use the '--config-only' or '-c' flag

    In [3]: %nuclio env --config-only MODEL_DIR=/home

    If you'd like to only run locally and not to add the instructions to
    function.yaml, use the '--local-only' or '-l' flag

    """
    if line.startswith('--config-only') or line.startswith('-c'):
        return

    if line.startswith('--local-only'):
        line = line.replace('--local-only', '').strip()
    if line.startswith('-l'):
        line = line.replace('-l', '').strip()

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
                i = doc.find('\n')
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
        ipy.system(path.expandvars(line))

    for line in cell_lines(cell):
        ipy.system(path.expandvars(line))


@command
def deploy(line, cell):
    """Deploy notebook/file with configuration as nuclio function.

    %nuclio deploy [file-path|url] [options]

    parameters:
    -n, --name path
        function name, optional (default is filename)
    -p, --project
        project name (required)
    -t, --tag tag
        version tag (label) for the function
    -d, --dashboard-url
        nuclio dashboard url
    -o, --output-dir path
        Output directory/file or upload URL (see below)
    -a, --archive
        indicate that the output is an archive (zip)
    --handler name
        Name of handler function (if other than 'handler')
    -e, --env key=value
        add/override environment variable, can be repeated
    -v, --verbose
        emit more logs

    when deploying a function which contains extra files or if we want to
    archive/version functions we specify output-dir with archiving option (-a)
    (or pre-set the output using the NUCLIO_ARCHIVE_PATH env var
    supported output options include local path, S3, and iguazio v3io

    following urls can be used to deploy functions from a remote archive:
      http(s):  http://<api-url>/path.zip[#workdir]
      iguazio:  v3io://<api-url>/<data-container>/project/name_v1.zip[#workdir]
      git:      git://[token@]github.com/org/repo#master[:<workdir>]

    Examples:
    In [1]: %nuclio deploy
    In [2] %nuclio deploy -d http://localhost:8080 -p tango
    In [3] %nuclio deploy myfunc.py -n new-name -p faces
    In [4] %nuclio deploy git://github.com/myorg/repo#master -n myfunc -p proj

    """

    if isinstance(line, str):
        line = path.expandvars(line)
        line = shlex.split(line)

    p = ArgumentParser(prog='%nuclio', add_help=False)
    populate_deploy_parser(p)
    args, rest = p.parse_known_args(line)

    notebook = ''
    if len(rest) > 0:
        notebook = rest[0]

    notebook = notebook or notebook_file_name(kernel)
    if not notebook:
        log_error('cannot find notebook name (try specifying its name)')
        return

    try:
        addr = deploy_from_args(args, notebook)
    except (DeployError, BuildError, ValueError) as err:
        log_error('error: {}'.format(err))
        return

    log('function deployed')
    return addr


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


def save_handler(config_file, out_dir):
    with open(config_file) as fp:
        config = yaml.load(fp)

    py_code = b64decode(config['spec']['build']['functionSourceCode'])
    py_module = config['spec']['handler'].split(':')[0]
    with open('{}/{}.py'.format(out_dir, py_module), 'wb') as out:
        out.write(py_code)


@command
def build(line, cell, return_dir=False):
    """Build notebook/code + config, and generate/upload yaml or archive.

    %nuclio build [filename] [flags]

    when running inside a notebook the the default filename will be the
    notebook it self

    -n, --name path
        function name, optional (default is filename)
    -t, --tag tag
        version tag (label) for the function
    -p, --project
        project name (required for archives)
    -a, --archive
        indicate that the output is an archive (zip)
    -o, --output-dir path
        Output directory/file or upload URL (see below)
    --handler name
        Name of handler function (if other than 'handler')
    -e, --env key=value
        add/override environment variable, can be repeated
    -v, --verbose
        emit more logs

    supported output options:
        format:  [scheme://[username:secret@]path/to/dir/[name[.zip|yaml]]
                 name will be derived from function name if not specified
                 .zip extensions are used for archives (multiple files)

        supported schemes and examples:
            local file: my-dir/func
            AWS S3:     s3://<bucket>/<key-path>
            http(s):    http://<api-url>/path
            iguazio:    v3io://<api-url>/<data-container>/path

    Example:
    In [1] %nuclio build -v
    In [2] %nuclio build --output-dir .
    In [3] %nuclio build /path/to/code.py --handler faces
    In [4] %nuclio build --tag v1.1 -e ENV_VAR1="some text" -e ENV_VAR2=xx
    In [5] %nuclio build -p myproj -t v1.1 --output-dir v3io:///bigdata -a
    """

    args, rest = parse_export_line(line)
    notebook = ''
    if len(rest) > 0:
        notebook = rest[0]

    notebook = notebook or notebook_file_name(kernel)
    if not notebook:
        log_error('cannot find notebook name (try specifying its name)')
        return

    output = args.output_dir
    envdict = list2dict(args.env)
    spec = ConfigSpec(env=envdict)

    name, config, code = build_file(notebook, args.name, args.handler,
                                    spec=spec, output_dir=output, tag=args.tag,
                                    archive=args.archive, project=args.project,
                                    verbose=args.verbose,
                                    kind=args.kind)

    log('notebook {} exported'.format(name))
    return config, code


def uncomment(line):
    line = line.strip()
    return '' if line[:1] == '#' else line


@command
def config(line, cell):
    """Set function configuration value (resources, triggers, build, etc.).
    Values need to numeric, strings, or json strings (1, "debug", 3.3, {..})
    You can use += to append values to a list

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


@command
def show(line, cell):
    """Prints generated python code (as it is exported).

   You should save the notebook before calling this function.
    """
    print_handler_code(line.strip())


def print_handler_code(notebook_file=None):
    """Prints handler code (as it was exported).

   You should save the notebook before calling this function.
    """
    notebook_file = notebook_file or notebook_file_name(kernel)
    if not notebook_file:
        raise ValueError('cannot find notebook file name')

    line = notebook_file = shlex.quote(notebook_file)
    config, code = build(line, None, return_dir=True)
    config_yaml = yaml.dump(config, default_flow_style=False)
    print('Config:\n{}'.format(config_yaml))
    print('Code:\n{}'.format(code))


def update_env_files(file_name):
    files = json.loads(environ.get(env_keys.env_files, '[]'))
    files.append(file_name)
    environ[env_keys.env_files] = json.dumps(files)


@command
def mount(line, cell):
    """Mount a shared file Volume into the function.

    Example:
    In [1]: %nuclio mount /data /projects/netops/data
    mounting volume path /projects/netops/data as /data
    """
    args, rest = parse_mount_line(line)
    if len(rest) != 2:
        log_error('2 arguments must be provided (mount point and remote path)')
        return

    print('mounting volume path {} as {}'.format(rest[0], rest[1]))


@command
def add(line, cell):
    """add files, will be stored in an archive (zip) or git

    Example:
    In [1]: %nuclio add -f model.json -f mylib.py
    """
    args, rest = parse_archive_line(line)
    file_list = args.file
    if cell:
        file_list += cell.splitlines()

    for filename in file_list:
        if not path.isfile(filename.strip()):
            log_error('file {} doesnt exist'.format(filename))
            return
        else:
            log('appending {} to archive'.format(filename))
