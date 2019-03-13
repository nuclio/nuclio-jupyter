import io
import zipfile
from requests.auth import HTTPBasicAuth
from base64 import b64encode
import yaml
import requests
import shutil
from os import path
import shlex
from argparse import ArgumentParser
import boto3


def build_zip(zip_path, config, code, files=[]):
    z = zipfile.ZipFile(zip_path, "w")
    config['spec']['build'].pop("functionSourceCode", None)
    config['metadata'].pop("name", None)
    z.writestr('handler.py', code)
    z.writestr('function.yaml', yaml.dump(config, default_flow_style=False))
    for f in files:
        if not path.isfile(f):
            raise Exception('file name {} not found'.format(f))
        z.write(f)
    z.close()


def load_zip_config(zip_path):
    data = get_from_zip(zip_path, ['function.yaml', 'handler.py'])
    return data['handler.py'], data['function.yaml']


def get_from_zip(zip_path, files=[]):
    files_data = {}
    with zipfile.ZipFile(zip_path) as myzip:
        for f in files:
            with io.TextIOWrapper(myzip.open(f)) as zipped:
                files_data[f] = zipped.read()
    return files_data


def upload_file(file_path, url, auth=None, del_file=False):
    if url.startswith('s3://'):
        s3_upload(file_path, url, auth)
    else:
        headers = get_auth_header(auth)
        with open(file_path, 'rb') as data:
            try:
                resp = requests.put(url, data=data, headers=headers)
            except OSError:
                raise OSError('error: cannot connect to {}'.format(url))
            if not resp.ok:
                raise OSError(
                    'failed to upload to {} {}'.format(url, resp.status_code))
    if del_file:
        shutil.rmtree(file_path, ignore_errors=True)


def s3_upload(file_path, url, auth=None, region=None):
    path_parts = url.replace("s3://", "").split("/")
    bucket = path_parts.pop(0)
    key = "/".join(path_parts)
    if auth:
        access, secret = auth
        s3 = boto3.client('s3', region_name=region, aws_access_key_id=access,
                          aws_secret_access_key=secret)
    else:
        s3 = boto3.client('s3', region_name=region)

    s3.meta.client.upload_file(file_path, bucket, key)


def get_archive_config(name, zip_url, auth=None, workdir=''):
    headers = get_auth_header(auth)
    return {
        'apiVersion': 'nuclio.io/v1',
        'kind': 'Function',
        'metadata': {
            'name': name,
        },
        'spec': {
            'build': {
                'codeEntryAttributes': {
                    'headers': headers,
                    'workDir': workdir,
                },
                'codeEntryType': 'archive',
                'path': zip_url
            },
        },
    }


def get_auth_header(auth):
    headers = {}
    if auth and isinstance(auth, str):
        headers['X-v3io-session-key'] = auth
    elif auth:
        if isinstance(auth, tuple):
            username, password = auth
        elif isinstance(auth, HTTPBasicAuth):
            username = auth.username
            password = auth.password
        else:
            raise Exception('unsupported authentication method')

        username = username.encode('latin1')
        password = password.encode('latin1')
        base = b64encode(b':'.join((username, password))).strip()
        authstr = 'Basic ' + base.decode('ascii')
        headers['Authorization'] = authstr

    return headers


def args2auth(url, key, username, secret):
    if not url:
        return None
    elif username:
        return (username, secret)
    elif url.startswith('s3://') and key:
        return (key, secret)
    elif key:
        return key
    return None


def parse_archive_line(args):
    parser = ArgumentParser(prog='%nuclio', add_help=False)
    parser.add_argument('--file', '-f', default=[], action='append')

    if isinstance(args, str):
        args = path.expandvars(args)
        args = shlex.split(args)

    return parser.parse_known_args(args)
