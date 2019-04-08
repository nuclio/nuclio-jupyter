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

import os
from os import path, environ
from tempfile import mktemp
from sys import executable, stderr
from subprocess import run, PIPE
from base64 import b64encode, b64decode

import yaml
from IPython import get_ipython

from .utils import env_keys, notebook_file_name, logger, normalize_name, BuildError
from .archive import build_zip, get_archive_config, url2repo, upload_file
from .config import (update_in, new_config, ConfigSpec, load_config,
                     meta_keys, extend_config, set_handler)


def build_file(filename='', name='', handler='', archive='', project='',
               tag="", spec: ConfigSpec = None, files=[], output_dir='',
               verbose=False):

    dont_embed = (len(files) > 0) or output_dir != '' or archive != ''

    if not filename:
        kernel = get_ipython()
        if kernel:
            filename = notebook_file_name(kernel)
        else:
            raise ValueError('please specify file name/path/url')

    filebase, ext = path.splitext(path.basename(filename))
    if ext == '.ipynb':
        config, code = build_notebook(filename, dont_embed, tag)
        nb_files = config['metadata']['annotations'].get(meta_keys.extra_files)
        ext = '.py'
        if nb_files:
            files += nb_files.split(',')
            config['metadata']['annotations'].pop(meta_keys.extra_files, None)

    elif ext in ['.py', '.go', '.js', '.java', '.sh']:
        code = url2repo(filename).get()
        config = code2config(code, ext)

    elif ext == '.yaml':
        code, config = load_config(filename)
        ext = get_lang_ext(config)

    else:
        raise BuildError('illegal filename or extension: '+filename)

    if not code:
        code_buf = config['spec']['build'].get('functionSourceCode')
        code = b64decode(code_buf).decode('utf-8')

    name = normalize_name(name or filebase)
    update_in(config, 'metadata.name', name)
    config = extend_config(config, spec, tag, filename)
    set_handler(config, filebase, handler, ext)

    log = logger.info if verbose else logger.debug
    log('Code:\n{}'.format(code))
    log('Config:\n{}'.format(yaml.dump(config, default_flow_style=False)))

    if output_dir:
        output_dir = path.abspath(output_dir)
        os.makedirs(output_dir, exist_ok=True)
        config['metadata'].pop("name", None)
        with open('{}/function.yaml'.format(output_dir), 'w') as fp:
            fp.write(yaml.dump(config, default_flow_style=False))
            fp.close()
        update_in(config, 'metadata.name', name)
        with open('{}/{}{}'.format(output_dir, filebase, ext), 'w') as fp:
            fp.write(code)
            fp.close()

    archive, url_target = archive_path(archive, name=name,
                                       project=project, tag=tag)
    if archive:
        if url_target:
            zip_path = mktemp('.zip')
        else:
            zip_path = path.abspath(archive)
        build_zip(zip_path, config, code, files, ext)
        if url_target:
            upload_file(zip_path, archive, True)
            config = get_archive_config(name, archive)
            config = extend_config(config, None, tag, filename)
            config_text = yaml.dump(config, default_flow_style=False)
            log('Archive Config:\n{}'.format(config_text))

    return name, config, code


def archive_path(archive, **kw):
    archive = archive or environ.get(env_keys.default_archive)
    if not archive:
        return '', False

    url_target = '://' in archive
    archive = archive.format(**kw) + '.zip'
    return archive, url_target


def build_notebook(nb_file, no_embed=False, tag=""):
    env = environ.copy()  # Pass argument to exporter via environment
    yaml_path = mktemp('.yaml')
    py_path = ''
    code = ''
    if no_embed:
        py_path = mktemp('.py')
        env[env_keys.code_target_path] = py_path
    env[env_keys.drop_nb_outputs] = 'y'

    cmd = [
        executable, '-m', 'nbconvert',
        '--to', 'nuclio.export.NuclioExporter',
        '--output', yaml_path,
        nb_file,
    ]
    out = run(cmd, env=env, stdout=PIPE, stderr=PIPE)
    if out.returncode != 0:
        print(out.stdout.decode('utf-8'))
        print(out.stderr.decode('utf-8'), file=stderr)
        raise BuildError('cannot convert notebook')

    if not path.isfile(yaml_path):
        raise BuildError('failed to convert, tmp file %s not found', yaml_path)

    with open(yaml_path) as yp:
        config_data = yp.read()
    config = yaml.safe_load(config_data)
    os.remove(yaml_path)

    if py_path:
        with open(py_path) as pp:
            code = pp.read()
            os.remove(py_path)

    return config, code


def code2config(code, ext='.py'):
    config = new_config()
    if ext == '.go':
        config['spec']['runtime'] = 'golang'
    elif ext == '.js':
        config['spec']['runtime'] = 'nodejs'
    elif ext == '.java':
        config['spec']['runtime'] = 'java'
    elif ext == '.sh':
        config['spec']['runtime'] = 'shell'
    elif ext != '.py':
        raise ValueError('unsupported extension {}'.format(ext))

    data = b64encode(code.encode('utf-8')).decode('utf-8')
    update_in(config, 'spec.build.functionSourceCode', data)
    return config


def get_lang_ext(config):
    ext = '.py'
    func_runtime = config['spec']['runtime']
    if func_runtime.startswith('python'):
        ext = '.py'
    elif func_runtime == 'golang':
        ext = '.go'
    elif func_runtime == 'nodejs':
        ext = '.js'
    elif func_runtime == 'java':
        ext = '.java'
    elif func_runtime == 'shell':
        ext = '.sh'
    else:
        raise ValueError('unsupported extension {}'.format(ext))
    return ext
