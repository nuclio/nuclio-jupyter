from base64 import b64decode
from copy import deepcopy
from os import path, environ
import yaml
from IPython import get_ipython

from .utils import read_or_download, parse_env

default_volume_type = 'v3io'
missing = object()

_function_config = {
    'apiVersion': 'nuclio.io/v1',
    'kind': 'Function',
    'metadata': {
        'name': 'notebook',
    },
    'spec': {
        'runtime': 'python:3.6',
        'handler': None,
        'env': [],
        'volumes': [],
        'build': {
            'commands': [],
            'noBaseImagesPull': True,
        },
    },
}


def new_config():
    return deepcopy(_function_config)


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


def set_commands(config, commands):
    for line in commands:
        line = line.strip()
        if not line or line[0] == '#':
            continue

        line = path.expandvars(line)
        update_in(config, 'spec.build.commands', line, append=True)


def set_env(config, env):
    for line in env:
        line = line.strip()
        if not line or line[0] == '#':
            continue

        key, value = parse_env(line)
        if not key:
            raise ValueError(
                'cannot parse environment value from: {}'.format(line))

        update_env_var(config, key, value)


def set_env_dict(config, env={}):
    for k, v in env.items():
        update_env_var(config, k, str(v))


def update_env_var(config, key, value):
    i = 0
    found = False
    for v in config['spec']['env']:
        if v['name'] == key:
            found = True
            break
        i += 1

    item = {'name': key, 'value': value}
    if found:
        config['spec']['env'][i] = item
    else:
        config['spec']['env'].append(item)


def fill_config(config, extra_config={}, env={}, cmd=[], mount: Volume = None):
    if config:
        for k, v in extra_config.items():
            current = get_in(config, k)
            update_in(config, k, v, isinstance(current, list))
    if env:
        set_env_dict(config, env)
    if cmd:
        set_commands(config, cmd)
    if mount:
        mount.render(config)


class ConfigSpec:
    """Function configuration spec

    env    - dictionary of environment variables {"key1": val1, ..}
    config - function spec parameters dictionary {"config_key": config, ..}
            e.g. {"config spec.build.baseImage" : "python:3.6-jessie"}
    cmd    - string list with build commands
            e.g. ["pip install requests", "apt-get wget -y"]
    mount  - Volume object for remote mount into a function

    """

    def __init__(self, env={}, config={}, cmd=[], mount: Volume = None):
        self.env = env
        self.extra_config = config
        self.cmd = cmd
        self.mount = mount

    def merge(self, config):
        fill_config(config, self.extra_config, self.env, self.cmd, self.mount)

    def apply(self, skipcmd=False):
        for k, v in self.env.items():
            environ[k] = v

        if not skipcmd:
            ipy = get_ipython()
            for line in self.cmd:
                ipy.system(path.expandvars(line))
