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


def should_upload():
    if environ.get('TRAVIS_REPO_SLUG') != 'nuclio/nuclio-jupyter':
        return False

    return environ.get('TRAVIS_TAG')


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
        raise SystemExit('error: wrong repo or no tag (try with --force)')

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
