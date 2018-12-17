#!/usr/bin/env python
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

"""Cut a release"""

import re
from argparse import ArgumentParser
from subprocess import run
from os import environ

is_valid_version = re.compile(r'\d+\.\d+\.\d+$').match
init_file = 'nuclio/__init__.py'


def git_branch():
    branch = environ.get('TRAVIS_BRANCH')
    if branch:
        return branch

    cmd = ['git', 'rev-parse', '--abbrev-ref', 'HEAD']
    out = run(cmd, capture_output=True)
    if out.returncode != 0:
        return ''

    return out.stdout.decode('utf-8').strip()


def change_version(version):
    with open(init_file) as fp:
        data = fp.read()

    # __version__ = '0.3.0'
    new_version = '__version__ = {!r}'.format(version)
    data = re.sub(r'__version__\s*=.*', new_version, data)

    with open(init_file, 'w') as out:
        out.write(data)


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('version')
    args = parser.parse_args()

    if git_branch() != 'master':
        raise SystemExit('error: not on "master" branch')

    version = args.version
    if not is_valid_version(version):
        raise SystemExit('error: bad version (should be major.minor.patch)')

    change_version(version)
    run(['git', 'add', init_file])
    run(['git', 'commit', '-m', 'version {}'.format(version)])
    run(['git', 'tag', 'v{}'.format(version)])
    run(['git', 'push'])
    run(['git', 'push', '--tags'])
