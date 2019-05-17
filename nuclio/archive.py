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

import io
import zipfile
from base64 import b64encode
import yaml
import requests
from os import path, remove, environ
import shlex
from argparse import ArgumentParser
import boto3
from urllib.parse import urlparse, ParseResult
from shutil import copyfile


def build_zip(zip_path, config, code, files=[], ext='.py', handler='handler'):
    z = zipfile.ZipFile(zip_path, "w")
    config['spec']['build'].pop("functionSourceCode", None)
    config['metadata'].pop("name", None)
    z.writestr(handler + ext, code)
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


def upload_file(file_path, url, del_file=False):
    url2repo(url).upload(file_path)
    if del_file:
        remove(file_path)


def put_data(url, data):
    url2repo(url).put(data)


def get_archive_config(name, zip_url):
    repo = url2repo(zip_url)
    zip_path, headers, workdir = repo.archive_cfg()
    spec = {
        'apiVersion': 'nuclio.io/v1',
        'kind': 'Function',
        'metadata': {
            'name': name,
            'labels': {},
            'annotations': {},
        },
        'spec': {
            'env': [],
            'volumes': [],
            'build': {
                'codeEntryAttributes': {
                    'headers': headers,
                    'workDir': workdir,
                },
                'codeEntryType': 'archive',
                'path': zip_path
            },
        },
    }

    if repo.kind == 'git':
        spec['spec']['build']['codeEntryType'] = 'github'
        spec['spec']['build']['codeEntryAttributes']['branch'] = repo.branch

    return spec


def parse_archive_line(args):
    parser = ArgumentParser(prog='%nuclio', add_help=False)
    parser.add_argument('--file', '-f', default=[], action='append')
    parser.add_argument(
        '--add-notebook', '-n', action='store_true', default=False)
    if isinstance(args, str):
        args = path.expandvars(args)
        args = shlex.split(args)

    return parser.parse_known_args(args)


def is_archive(url):
    p = urlparse(url)
    val = p.path.endswith('.zip') or p.scheme.lower() == 'git'
    if val and '://' not in url:
        raise ValueError('load from archive require a remote path')
    return val


def url2repo(url=''):
    if '://' not in url:
        return FileRepo(url)
    p = urlparse(url)
    scheme = p.scheme.lower()
    if scheme == 's3':
        return S3Repo(p)
    elif scheme == 'git':
        return GitRepo(p)
    elif scheme == 'http' or scheme == 'https':
        return HttpRepo(p)
    elif scheme == 'v3io' or scheme == 'v3ios':
        return V3ioRepo(p)
    else:
        raise ValueError('unsupported repo scheme ({})'.format(scheme))


class ExternalRepo:
    def __init__(self, urlobj: ParseResult):
        self.urlobj = urlobj
        self.kind = ''

    def get(self):
        pass

    def put(self, data):
        pass

    def download(self, target_path):
        text = self.get()
        with open(target_path, 'w') as fp:
            fp.write(text)
            fp.close()

    def upload(self, src_path):
        pass

    def archive_cfg(self):
        # return (path, headers {}, workdir)
        raise Exception('unimplemented (nuclio cant load zip from this repo)')


class FileRepo(ExternalRepo):
    def __init__(self, path=''):
        self.path = path
        self.kind = 'file'

    def get(self):
        with open(self.path, 'r') as fp:
            return fp.read()

    def put(self, data):
        with open(self.path, 'w') as fp:
            fp.write(data)
            fp.close()

    def download(self, target_path):
        copyfile(self.path, target_path)

    def upload(self, src_path):
        copyfile(src_path, self.path)


class S3Repo(ExternalRepo):
    def __init__(self, urlobj: ParseResult):
        self.kind = 's3'
        self.bucket = urlobj.hostname
        self.key = urlobj.path[1:]
        region = None
        if urlobj.username or urlobj.password:
            self.s3 = boto3.resource('s3', region_name=region,
                                     aws_access_key_id=urlobj.username,
                                     aws_secret_access_key=urlobj.password)
        else:
            self.s3 = boto3.resource('s3', region_name=region)

    def upload(self, src_path):
        self.s3.Object(self.bucket, self.key).put(Body=open(src_path, 'rb'))

    def get(self):
        obj = self.s3.Object(self.bucket, self.key)
        return obj.get()['Body'].read()

    def put(self, data):
        self.s3.Object(self.bucket, self.key).put(Body=data)

    def archive_cfg(self):
        raise Exception('unimplemented (nuclio load from private s3)')


def basic_auth_header(user, password):
    username = user.encode('latin1')
    password = password.encode('latin1')
    base = b64encode(b':'.join((username, password))).strip()
    authstr = 'Basic ' + base.decode('ascii')
    return {'Authorization': authstr}


def http_get(url, headers=None, auth=None):
    try:
        resp = requests.get(url, headers=headers, auth=auth)
    except OSError:
        raise OSError('error: cannot connect to {}'.format(url))

    if not resp.ok:
        raise OSError('failed to read file in {}'.format(url))
    return resp.text


def http_put(url, data, headers=None, auth=None):
    try:
        resp = requests.put(url, data=data, headers=headers, auth=auth)
    except OSError:
        raise OSError('error: cannot connect to {}'.format(url))
    if not resp.ok:
        raise OSError(
            'failed to upload to {} {}'.format(url, resp.status_code))


def http_upload(url, file_path, headers=None, auth=None):
    with open(file_path, 'rb') as data:
        http_put(url, data, headers, auth)


class HttpRepo(ExternalRepo):
    def __init__(self, urlobj: ParseResult):
        self.kind = 'http'
        host = urlobj.hostname
        if urlobj.port:
            host += ':{}'.format(urlobj.port)
        self.url = '{}://{}{}'.format(urlobj.scheme, host, urlobj.path)
        if urlobj.username or urlobj.password:
            self.auth = (urlobj.username, urlobj.password)
            self.nuclio_header = basic_auth_header(urlobj.username,
                                                   urlobj.password)
        else:
            self.auth = None
            self.nuclio_header = None

        self.path = urlobj.path
        self.workdir = urlobj.fragment

    def upload(self, src_path):
        raise ValueError('unimplemented')

    def put(self, data):
        raise ValueError('unimplemented')

    def get(self):
        return http_get(self.url, None, self.auth)

    def archive_cfg(self):
        # return path, headers {}, workdir
        return self.url, self.nuclio_header, self.workdir


class V3ioRepo(ExternalRepo):
    def __init__(self, urlobj: ParseResult):
        self.kind = 'v3io'
        host = urlobj.hostname or environ.get('V3IO_API')
        if urlobj.port:
            host += ':{}'.format(urlobj.port)
        self.url = 'http://{}{}'.format(host, urlobj.path)

        token = environ.get('V3IO_ACCESS_KEY')

        username = urlobj.username or environ.get('V3IO_USERNAME')
        password = urlobj.password or environ.get('V3IO_PASSWORD')

        self.headers = None
        self.auth = None
        if (not urlobj.username and urlobj.password) or token:
            token = urlobj.password or token
            self.headers = {'X-v3io-session-key': token}
        elif username and password:
            self.headers = basic_auth_header(username, password)

        self.path = urlobj.path
        self.workdir = urlobj.fragment

    def upload(self, src_path):
        http_upload(self.url, src_path, self.headers, None)

    def get(self):
        return http_get(self.url, self.headers, None)

    def put(self, data):
        http_put(self.url, data, self.headers, None)

    def archive_cfg(self):
        # return path, headers {}, workdir
        return self.url, self.headers, self.workdir


class GitRepo(ExternalRepo):
    def __init__(self, urlobj: ParseResult):
        self.kind = 'git'
        host = urlobj.hostname or 'github.com'
        if urlobj.port:
            host += ':{}'.format(urlobj.port)
        self.path = 'https://{}{}'.format(host, urlobj.path)

        self.headers = {'Authorization': ''}
        token = urlobj.username or environ.get('GIT_ACCESS_TOKEN')
        if token:
            self.headers = {'Authorization': 'token '.format(token)}

        # format: git://[token@]github.com/org/repo#master[:<workdir>]
        self.branch = 'master'
        self.workdir = None
        if urlobj.fragment:
            parts = urlobj.fragment.split(':')
            if parts[0]:
                self.branch = parts[0]
            if len(parts) > 1:
                self.workdir = parts[1]

    def upload(self, src_path):
        raise ValueError('unimplemented, use git push instead')

    def get(self):
        raise ValueError('unimplemented, use git pull instead')

    def put(self, data):
        raise ValueError('unimplemented, use git push instead')

    def archive_cfg(self):
        # return path, headers {}, workdir
        return self.path, self.headers, self.workdir
