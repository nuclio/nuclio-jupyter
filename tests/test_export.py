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

from subprocess import check_output
from tempfile import mkdtemp
from os.path import abspath, dirname

import pytest
import yaml

from nuclio import export


here = dirname(abspath(__file__))


def test_export():
    cmd = [
        'jupyter', 'nbconvert',
        '--to', 'nuclio.export.NuclioExporter',
        '--stdout', 'tests/handler.ipynb',
    ]
    out = check_output(cmd).decode('utf-8')

    # Check we added handler
    assert export.handler_decl in out


def test_install():
    venv = mkdtemp()
    check_output(['virtualenv', venv])
    python = '{}/bin/python'.format(venv)
    check_output([python, 'setup.py', 'install'])

    # Required for nbconvert to run
    check_output(['{}/bin/pip'.format(venv), 'install', 'notebook'])

    py_cmd = 'import nbconvert.exporters as e; print(e.get_export_names())'
    out = check_output([python, '-c', py_cmd]).decode('utf-8')
    assert 'nuclio' in out


def iter_convert():
    with open('{}/convert_cases.yml'.format(here)) as fp:
        for case in yaml.load_all(fp):
            yield pytest.param(case, id=case['name'])


@pytest.mark.parametrize('case', iter_convert())
def test_convert(case):
    exp = export.NuclioExporter()
    out = exp.convert(case['in'])
    assert out.strip() == case['out'].strip()


@pytest.mark.skip(reason='TODO')
def test_print_handler_code():
    pass  # FIXME
