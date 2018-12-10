# Copyright 2018 Iguazio
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Upload packages to PyPI"""

from argparse import ArgumentParser
from glob import glob
from os import environ, path
from shutil import rmtree
from subprocess import run
from sys import executable


def git_branch():
    branch = environ.get('TRAVIS_BRANCH')
    if branch:
        return branch

    cmd = ['git', 'rev-parse', '--abbrev-ref', 'HEAD']
    out = run(cmd, capture_output=True)
    if out.returncode != 0:
        return ''

    return out.stdout.decode('utf-8').strip()


def should_upload():
    repo = environ.get('TRAVIS_REPO_SLUG')
    if repo != 'nuclio/nuclio-jupyter':
        return False

    return git_branch() == 'master'


def git_sha():
    out = run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True)
    if out.returncode != 0:
        return ''
    return out.stdout.decode('utf-8').strip()


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        '--force', '-f', help='force upload', action='store_true')
    parser.add_argument(
        '--user', '-u', help='pypi user (or PYPI_USER)', default='')
    parser.add_argument(
        '--password', '-p', help='pypi password (or PYPI_PASSWORD)',
        default='')
    args = parser.parse_args()

    ok = args.force or should_upload()
    if not ok:
        raise SystemExit('error: wrong branch or repo (try with --force)')

    if path.exists('dist'):
        rmtree('dist')

    for dist in ('sdist', 'bdist_wheel'):
        out = run([executable, 'setup.py', dist])
        if out.returncode != 0:
            raise SystemExit('error: cannot build {}'.format(dist))

    user = args.user or environ.get('PYPI_USER')
    passwd = args.password or environ.get('PYPI_PASSWORD')

    if not (user and passwd):
        print('warning: missing login information - skipping upload')
        raise SystemExit()

    cmd = [
        'twine', 'upload',
        '--user', user,
        '--password', passwd,
    ] + glob('dist/nuclio-jupyter-*')
    out = run(cmd)
    if out.returncode != 0:
        raise SystemExit('error: cannot upload to pypi')
