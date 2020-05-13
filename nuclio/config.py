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

from base64 import b64decode
from copy import deepcopy
from datetime import datetime
from os import path, environ
import yaml
from IPython import get_ipython

from .utils import parse_env
from .archive import url2repo
from .triggers import HttpTrigger

default_volume_type = 'v3io'
v3ioenv_magic = '%v3io'
missing = object()


class meta_keys:
    project = 'nuclio.io/project-name'
    tag = 'nuclio.io/tag'
    extra_files = 'nuclio.io/extra_files'
    generated_by = 'nuclio.io/generated_by'


_function_config = {
    'apiVersion': 'nuclio.io/v1',
    'kind': 'Function',
    'metadata': {
        'name': 'notebook',
        'labels': {},
        'annotations': {},
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


def load_config(config_file):
    config_data = url2repo(config_file).get()
    return load_config_data(config_data)


def load_config_data(config_data):
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

        vol = {}
        mnt = {}
        if self.type == 'v3io':
            if self.remote.startswith('~/'):
                user = environ.get('V3IO_USERNAME', '')
                self.remote = 'users/' + user + self.remote[1:]

            container, subpath = split_path(self.remote)
            key = self.key or environ.get('V3IO_ACCESS_KEY', '')

            vol = {'name': self.name, 'flexVolume': {
                'driver': 'v3io/fuse',
                'options': {
                    'container': container,
                    'subPath': subpath,
                    'accessKey': key,
                }
            }}

        elif self.type == 'pvc':
            vol = {
                'name': self.name,
                'persistentVolumeClaim': {'claimName': self.remote},
            }
        elif self.type == 'secret':
            vol = {
                'name': self.name,
                'secret': {'secretName': self.remote}
            }
        else:
            raise Exception('unknown volume type {}'.format(self.type))

        mnt = {'name': self.name, 'mountPath': self.local}
        update_in(config, 'spec.volumes',
                  {'volumeMount': mnt, 'volume': vol}, append=True)


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

        if line.strip() == v3ioenv_magic:
            for key in ['V3IO_FRAMESD', 'V3IO_USERNAME',
                        'V3IO_ACCESS_KEY', 'V3IO_API']:
                if key in environ:
                    update_env_var(config, key, environ[key])
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

    def __init__(self, env={}, config={}, cmd=[],
                 mount: Volume = None, v3io=False):
        self.env = env
        self.extra_config = config
        self.cmd = cmd
        self.mounts = []
        if mount:
            self.mounts.append(mount)
        if v3io:
            self.with_v3io()

    def merge(self, config):
        if self.extra_config:
            for k, v in self.extra_config.items():
                current = get_in(config, k)
                update_in(config, k, v, isinstance(current, list))
        if self.env:
            set_env_dict(config, self.env)
        if self.cmd:
            set_commands(config, self.cmd)
        for mount in self.mounts:
            mount.render(config)

    def apply(self, skipcmd=False):
        for k, v in self.env.items():
            environ[k] = v

        if not skipcmd:
            ipy = get_ipython()
            for line in self.cmd:
                ipy.system(path.expandvars(line))

    def set_env(self, name, value):
        self.env[name] = value
        return self

    def set_config(self, key, value):
        self.extra_config[key] = value
        return self

    def add_commands(self, *cmd):
        self.cmd += cmd
        return self

    def add_volume(self, local, remote, kind='', name='fs',
                   key='', readonly=False):
        vol = Volume(local, remote, kind, name, key, readonly)
        self.mounts.append(vol)
        return self

    def add_trigger(self, name, spec):
        if hasattr(spec, 'to_dict'):
            spec = spec.to_dict()
        self.extra_config['spec.triggers.{}'.format(name)] = spec
        return self

    def with_http(self, workers=8, port=0,
                  host=None, paths=None, canary=None):
        self.add_trigger('http',
                         HttpTrigger(workers, port=port,
                                     host=host, paths=paths, canary=canary))
        return self

    def with_v3io(self):
        for key in ['V3IO_FRAMESD', 'V3IO_USERNAME',
                    'V3IO_ACCESS_KEY', 'V3IO_API']:
            if key in environ:
                self.env[key] = environ[key]
        return self


def extend_config(config, spec, tag, source=''):
    if spec:
        spec.merge(config)
    if tag:
        config['metadata']['labels'][meta_keys.tag] = tag
    if source:
        now = datetime.utcnow().strftime("%d-%m-%Y")
        if environ.get('V3IO_USERNAME'):
            now += ' by ' + environ.get('V3IO_USERNAME')
        genstr = 'function generated from {}'.format(now, source)
        config['metadata']['annotations'][meta_keys.generated_by] = genstr

    return config


def set_handler(config, module, handler, ext):
    if not module:
        module = 'handler'
    if not handler:
        handler = 'handler'
    if ext == '.sh':
        module += '.sh'
    update_in(config, 'spec.handler', '{}:{}'.format(module, handler))
