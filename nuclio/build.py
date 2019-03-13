import shutil
from os import path, environ
from tempfile import mkdtemp
from sys import executable, stderr
from subprocess import run, PIPE
from base64 import b64encode

from nuclio.utils import update_in, download_http, is_url, normalize_name
from .archive import upload_file
from .config import new_config

handler_name = 'NUCLIO_HANDLER_NAME'


def build_notebook(nb_file, name='', handler='', targetdir='',
                   auth=None, verbose=False):
    tmp_dir = targetdir
    url_target = (targetdir != '' and is_url(targetdir))
    if not targetdir or url_target:
        tmp_dir = mkdtemp()

    basename = path.basename(nb_file)
    filebase, ext = path.splitext(basename)
    if is_url(nb_file):
        content = download_http(nb_file, auth)
        nb_file = '{}/{}'.format(tmp_dir, basename)
        with open(nb_file, "wb") as fp:
            fp.write(content)

    env = environ.copy()  # Pass argument to exporter via environment
    if handler:
        env[handler_name] = handler

    cmd = [
        executable, '-m', 'nbconvert',
        '--to', 'nuclio.export.NuclioExporter',
        '--output-dir', tmp_dir,
        nb_file,
    ]
    out = run(cmd, env=env, stdout=PIPE, stderr=PIPE)
    if out.returncode != 0:
        print(out.stdout.decode('utf-8'))
        print(out.stderr.decode('utf-8'), file=stderr)
        raise Exception('cannot convert notebook')

    returned_name = '{}/{}'.format(tmp_dir, filebase)
    if path.isfile(returned_name + '.zip'):
        file_ext = '.zip'
    elif path.isfile(returned_name + '.yaml'):
        file_ext = '.yaml'
    else:
        raise Exception('cannot convert notebook, %s yaml/zip files not found',
                        returned_name)

    file_path = returned_name + file_ext
    if url_target:
        if name:
            filebase = name
        if not targetdir.endswith('/'):
            targetdir += '/'
        upload_path = targetdir + filebase + file_ext
        upload_file(file_path, upload_path, auth, False)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        file_path = upload_path

    return file_path, file_ext, url_target


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

    data = b64encode(code.encode('utf-8')).decode('utf-8')
    update_in(config, 'spec.build.functionSourceCode', data)
    return config
