import os
from os import path, environ
from tempfile import mktemp
from sys import executable, stderr
from subprocess import run, PIPE
from base64 import b64encode, b64decode

import yaml
from IPython import get_ipython

from .utils import is_url, normalize_name, env_keys, notebook_file_name
from .archive import upload_file, build_zip, get_archive_config
from .config import (update_in, new_config, ConfigSpec, read_or_download,
                     load_config, meta_keys)


def build_file(filename, name='', handler='', output='', tag="",
               spec: ConfigSpec = None, files=[], no_embed=False):

    url_target = (output != '' and is_url(output))
    is_zip = output.endswith('.zip')
    if not filename:
        kernel = get_ipython()
        if kernel:
            filename = notebook_file_name(kernel)
        else:
            raise ValueError('please specify file name/path/url')

    auth = None
    code = ''
    filebase, ext = path.splitext(path.basename(filename))
    name = normalize_name(name or filebase)
    if ext == '.ipynb':
        config, code = build_notebook(filename, handler,
                                      no_embed or is_zip or url_target, tag)
        nb_files = config['metadata']['annotations'].get(meta_keys.extra_files)
        ext = '.py'
        if nb_files:
            files += nb_files.split(',')
            config['metadata']['annotations'].pop(meta_keys.extra_files, None)

    elif ext in ['.py', '.go', '.js', '.java']:
        code = read_or_download(filename, auth)
        config = code2config(code, name, handler, ext)

    elif ext == '.yaml':
        code, config = load_config(filename)
        ext = get_lang_ext(config)

    #todo: support rebuild of zip

    else:
        raise ValueError('illegal filename or extension: '+filename)

    if not code:
        code_buf = config['spec']['build'].get('functionSourceCode')
        code = b64decode(code_buf).decode('utf-8')
    if spec:
        spec.merge(config)

    if output.endswith('/'):
        output += name
    if is_zip or url_target:
        zip_path = output
        if url_target:
            zip_path = mktemp('.zip')
        if not is_zip:
            output += '.zip'
        build_zip(zip_path, config, code, files, ext)
        if url_target:
            upload_file(zip_path, output, auth, True)
            config = get_archive_config(name, output, auth=auth)
    elif output:
        with open(output + '.yaml', 'wb') as fp:
            fp.write(yaml.dump(config, default_flow_style=False))
            fp.close()
        if no_embed:
            with open(output + ext, 'wb') as fp:
                fp.write(code)
                fp.close()

    return name, config, code


def build_notebook(nb_file, handler='', no_embed=False, tag=""):
    env = environ.copy()  # Pass argument to exporter via environment
    yaml_path = mktemp('.yaml')
    py_path = ''
    code = ''
    if no_embed:
        py_path = mktemp('.py')
        env[env_keys.code_target_path] = py_path

    if handler:
        env[env_keys.handler_name] = handler
    if tag:
        env[env_keys.function_tag] = tag
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
        raise Exception('cannot convert notebook')

    if not path.isfile(yaml_path):
        raise Exception('failed to convert, tmp file %s not found', yaml_path)

    with open(yaml_path) as yp:
        config_data = yp.read()
    config = yaml.safe_load(config_data)
    os.remove(yaml_path)

    if py_path:
        with open(py_path) as pp:
            code = pp.read()
            os.remove(py_path)

    return config, code


def code2config(code, name, handler='', ext='.py'):
    config = new_config()
    if not name:
        raise Exception('function name must be specified')
    if not handler:
        handler = 'handler'

    config['metadata']['name'] = normalize_name(name)
    config['spec']['handler'] = 'handler:' + handler
    if ext == '.go':
        config['spec']['runtime'] = 'golang'
    elif ext == '.js':
        config['spec']['runtime'] = 'nodejs'
    elif ext == '.java':
        config['spec']['runtime'] = 'java'

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
    else:
        raise ValueError('illegal ')
    return ext
