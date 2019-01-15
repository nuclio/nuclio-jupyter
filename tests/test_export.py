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
from contextlib import contextmanager
from glob import glob
from os import environ
from subprocess import run, PIPE
from sys import executable
from tempfile import mkdtemp

import pytest
import yaml

from conftest import here
from nuclio import export
from nuclio.utils import env_keys, load_config


@contextmanager
def temp_env(kw):
    old = {k: environ.get(k) for k in kw}
    environ.update(kw)
    try:
        yield
    finally:
        for key, value in old.items():
            if value:
                environ[key] = value
            else:
                del environ[key]


def test_export():
    out_dir = mkdtemp(prefix='nuclio-jupyter-export-')
    cmd = [
        executable, '-m', 'nbconvert',
        '--to', 'nuclio.export.NuclioExporter',
        '--output-dir', out_dir,
        '{}/handler.ipynb'.format(here),
    ]
    run(cmd, check=True)

    files = glob('{}/*.yaml'.format(out_dir))
    assert len(files) == 1, 'wrong # of YAML files in {}'.format(files)
    with open(files[0]) as fp:
        code, config = load_config(fp)
    # Check we added handler
    assert 'def handler(' in code, 'no handler in code'


@pytest.mark.install
def test_install():
    venv = mkdtemp()
    run(['virtualenv', '-p', executable, venv], check=True)
    python = '{}/bin/python'.format(venv)
    run([python, 'setup.py', 'install'], check=True)

    # Required for nbconvert to run
    run([python, '-m', 'pip', 'install', 'notebook'], check=True)

    py_cmd = 'import nbconvert.exporters as e; print(e.get_export_names())'
    out = run([python, '-c', py_cmd], stdout=PIPE, check=True)
    out = out.stdout.decode('utf-8')
    assert 'nuclio' in out


def iter_convert():
    with open('{}/convert_cases.yml'.format(here)) as fp:
        for case in yaml.load_all(fp):
            yield pytest.param(case, id=case['name'])


def export_notebook(nb, resources=None):
    resources = {} if resources is None else resources
    exp = export.NuclioExporter()
    out, _ = exp.from_notebook_node(nb, resources)
    code, config = load_config(out)
    return code, config


@pytest.mark.parametrize('case', iter_convert())
def test_convert(case, clean_handlers):
    nb = gen_nb([case['in']])
    code, _ = export_notebook(nb)
    code = code[code.find('\n'):].strip()  # Trim first line
    assert code == case['out'].strip()


def test_config():
    key, value = 'build.commands', '"apt install -y libyaml-dev"'
    nb = gen_nb(['%nuclio config {} = {!r}'.format(key, value)])
    _, config = export_notebook(nb)
    value = literal_eval(value)
    assert get_in(config, key.split('.')) == value, "bad config"


def get_in(obj, keys):
    if not keys:
        return obj
    return get_in(obj[keys[0]], keys[1:])


def gen_nb(code_cells):
    return {
        'cells': [
            {'source': code, 'cell_type': 'code'} for code in code_cells
        ],
    }


def test_env():
    key, value = 'user', 'daffy'
    nb = gen_nb(['%nuclio env {}={}'.format(key, value)])

    _, config = export_notebook(nb)
    env = config['spec']['env']
    assert env == [{'name': key, 'value': value}], 'bad env'


def test_named_handler():
    name = 'lassie'
    code = '''%%nuclio handler {}

    'Hello ' + event.name  # nuclio: return
    '''.format(name)
    nb = gen_nb([code])
    code, _ = export_notebook(nb)

    decl = 'def {}('.format(name)
    assert decl in code, 'bad export'


def test_handler_name():
    assert export.handler_name() == 'handler:handler'

    name = 'lassie'
    kw = {env_keys.handler_name: name}
    with temp_env(kw):
        assert export.handler_name() == 'handler:{}'.format(name)

    module = 'face'
    handler_path = '/path/to/{}.py'.format(module)
    kw[env_keys.handler_path] = handler_path
    with temp_env(kw):
        assert export.handler_name() == '{}:{}'.format(module, name)


def test_meta_name():
    name = 'iguazio'
    resources = {
        'metadata': {
            'name': name,
        },
    }
    _, config = export_notebook(gen_nb([]), resources)
    assert config['metadata']['name'] == name, 'wrong name'


def test_parse_magic_line():
    cmd, args = export.parse_magic_line('%nuclio config a=b')
    assert cmd == 'config', 'bad command'
    assert args == ['a=b'], 'bad args'

    out = export.parse_magic_line('a = 2')
    assert out is None, 'bad parse of non magic'

    with pytest.raises(export.MagicError):
        export.parse_magic_line('%nuclio')
