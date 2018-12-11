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

from ast import literal_eval
from io import BytesIO
from glob import glob
from os.path import abspath, dirname
from subprocess import run
from sys import executable
from tempfile import mkdtemp
from zipfile import ZipFile

import pytest
import yaml

from nuclio import export

here = dirname(abspath(__file__))


def test_export():
    out_dir = mkdtemp(prefix='nuclio-jupyter-export-')
    cmd = [
        executable, '-m', 'nbconvert',
        '--to', 'nuclio.export.NuclioExporter',
        '--output-dir', out_dir,
        'tests/handler.ipynb',
    ]
    run(cmd, check=True)

    files = glob('{}/*.zip'.format(out_dir))
    assert len(files) == 1, 'wrong # of zip files in {}'.format(files)

    with ZipFile(files[0]) as zf:
        names = zf.namelist()
        code = zf.read('handler.py').decode('utf-8')
        config = zf.read('function.yaml')

    assert set(names) == {'function.yaml', 'handler.py'}, 'bad files'
    # Check we added handler
    assert export.handler_decl in code, 'no handler in code'
    yaml.load(config)  # Make sure it's valid YAML


@pytest.mark.install
def test_install():
    venv = mkdtemp()
    run(['virtualenv', '-p', executable, venv], check=True)
    python = '{}/bin/python'.format(venv)
    run([python, 'setup.py', 'install'], check=True)

    # Required for nbconvert to run
    run([python, '-m', 'pip', 'install', 'notebook'], check=True)

    py_cmd = 'import nbconvert.exporters as e; print(e.get_export_names())'
    out = run([python, '-c', py_cmd], capture_output=True, check=True)
    out = out.stdout.decode('utf-8')
    assert 'nuclio' in out


def iter_convert():
    with open('{}/convert_cases.yml'.format(here)) as fp:
        for case in yaml.load_all(fp):
            yield pytest.param(case, id=case['name'])


def export_notebook(nb):
    exp = export.NuclioExporter()
    out, _ = exp.from_notebook_node(nb, {})
    with ZipFile(BytesIO(out)) as zf:
        handler = zf.read('handler.py').decode('utf-8')
        config = yaml.load(zf.read('function.yaml'))

    return handler, config


@pytest.mark.parametrize('case', iter_convert())
def test_convert(case):
    nb = {'cells': [
        {
            'source': case['in'],
            'cell_type': 'code',
            }
        ],
    }

    code, _ = export_notebook(nb)
    code = code[code.find('\n'):].strip()  # Trim first line
    assert code == case['out'].strip()


def test_update_in():
    obj = {}
    export.update_in(obj, 'a.b.c', 2)
    assert obj['a']['b']['c'] == 2
    export.update_in(obj, 'a.b.c', 3)
    assert obj['a']['b']['c'] == 3

    export.update_in(obj, 'a.b.d', 3, append=True)
    assert obj['a']['b']['d'] == [3]
    export.update_in(obj, 'a.b.d', 4, append=True)
    assert obj['a']['b']['d'] == [3, 4]


def test_config():
    key, value = 'build.commands', '"apt install -y libyaml-dev"'
    nb = {'cells': [
        {
            'source': '%nuclio config {} = {!r}'.format(key, value),
            'cell_type': 'code',
            }
        ],
    }

    _, config = export_notebook(nb)
    value = literal_eval(value)
    assert get_in(config, key.split('.')) == value, "bad config"


def get_in(obj, keys):
    if not keys:
        return obj
    return get_in(obj[keys[0]], keys[1:])
