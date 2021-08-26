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

from glob import glob
from os import path
from shutil import rmtree
from subprocess import PIPE, run
from sys import executable
import tempfile

from conftest import here, is_travis

import pytest

root_dir = path.dirname(here)
dist_dir = '{}/dist'.format(root_dir)


@pytest.mark.skipif(not is_travis, reason='not under travis')
def test_install():
    if path.isdir(dist_dir):
        rmtree(dist_dir)
    cmd = [executable, '{}/setup.py'.format(root_dir), 'bdist_wheel']
    run(cmd, check=True)
    wheels = glob('{}/*.whl'.format(dist_dir))
    assert len(wheels) == 1, 'bad number of wheels'

    venv_dir = tempfile.mkdtemp(prefix='nuclio-jupyter-venv-')
    print('venv = {}'.format(venv_dir))
    run(['virtualenv', '-p', executable, venv_dir], check=True)

    venv_bin = '{}/bin'.format(venv_dir)
    run(['{}/pip'.format(venv_bin), 'install', wheels[0]], check=True)
    out = run(['{}/nuclio'.format(venv_bin), '-h'], check=True, stdout=PIPE)

    help_out = out.stdout.decode('utf-8')
    assert 'deploy' in help_out, 'no deploy'
