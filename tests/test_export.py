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
from subprocess import run
from sys import executable
import tempfile

import pytest
import yaml

from conftest import here
from nuclio import export
from nuclio.utils import env_keys
from nuclio.config import load_config, load_config_data


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
    out_dir = tempfile.mkdtemp(prefix='nuclio-jupyter-export-')
    cmd = [
        executable, '-m', 'nbconvert',
        '--to', 'nuclio.export.NuclioExporter',
        '--output-dir', out_dir,
        '{}/handler.ipynb'.format(here),
    ]
    run(cmd, check=True)

    files = glob('{}/*.yaml'.format(out_dir))
    assert len(files) == 1, 'wrong # of YAML files in {}'.format(files)
    code, config = load_config(files[0])
    # Check we added handler
    assert 'def handler(' in code, 'no handler in code'


def cases_from_yml_file(file_path: str):
    with open(file_path) as f:
        for case in yaml.load_all(f):
            yield pytest.param(case, id=case["name"])


def export_notebook(nb, resources=None):
    resources = {} if resources is None else resources
    exp = export.NuclioExporter()
    out, _ = exp.from_notebook_node(nb, resources)
    code, config = load_config_data(out)
    return code, config


@pytest.mark.parametrize(
    'case', cases_from_yml_file(f"{here}/convert_cases.yml")
)
def test_convert(case, clean_handlers):
    nb = gen_nb([case['in']])
    code, _ = export_notebook(nb)
    code = code[code.find('\n'):].strip()  # Trim first line
    assert code == case['out'].strip()


@pytest.mark.parametrize(
    "case", cases_from_yml_file(f"{here}/annotations_test_cases.yml")
)
@pytest.mark.parametrize("keyword", ["mlrun", "nuclio"])
def test_converter_annotations(case: dict, keyword: str):
    notebook = {
        "cells": [
            {"source": code.format(keyword=keyword), "cell_type": "code"}
            for code in case["cells"]
        ],
    }
    code, _ = export_notebook(notebook)

    # Trim first line
    code = "\n".join(code.splitlines()[1:])
    assert code.strip() == case["expected"].strip()


def test_config():
    key, value = 'build.commands', '"apt install -y libyaml-dev"'
    nb = gen_nb(['%nuclio config {} = {}'.format(key, value)])
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
    assert args == 'a=b', 'bad args'

    out = export.parse_magic_line('a = 2')
    assert out is None, 'bad parse of non magic'

    with pytest.raises(export.MagicError):
        export.parse_magic_line('%nuclio')


def test_multi_magic():
    nb = gen_nb(['%nuclio cmd ls\n%nuclio cmd hi'])
    _, config = export_notebook(nb)
    cmds = config['spec']['build']['commands']
    assert len(cmds) == 2, 'bad # of commands'


def test_ignore_comment():
    nb_code = 'x = 1'
    nb = gen_nb(['#%nuclio cmd ls', nb_code])
    code, config = export_notebook(nb)
    commands = config['spec']['build']['commands']
    assert len(commands) == 0, 'commented magic not ignored'
    assert nb_code in code, 'missing code'


@pytest.mark.parametrize(
    "case", cases_from_yml_file(f"{here}/code_generation_test_cases.yml")
)
def test_converter_code_generation(case: dict):
    notebook = {
        "cells": [
            {"source": code, "cell_type": "code"}
            for code in case["cells"]
        ],
    }
    function_name = case["function name"]
    kw = {env_keys.function_name: function_name}
    with temp_env(kw):
        code, _ = export_notebook(notebook)

        # Trim first line
        code = "\n".join(code.splitlines()[1:])
        assert code.strip() == case["expected"].strip()


def test_expand_env():
    cell = '%nuclio cmd ls ${HOME}'
    nb = gen_nb([cell])
    _, config = export_notebook(nb)
    cmds = config['spec']['build']['commands']
    assert environ['HOME'] in cmds[0], '${HOME} not expanded'


def test_multiple_starts():
    cells = [
        'a = 1',
        '# nuclio: start-code my-function',
        'b = 2',
        '# nuclio: start-code my-function',
        'd = 4',
        'e = 2',
        '# nuclio: end-code my-function',
    ]
    kw = {env_keys.function_name: 'my-function'}
    with temp_env(kw):
        nb = gen_nb(cells)
        with pytest.raises(export.MagicError):
            code, _ = export_notebook(nb)


def test_multiple_ends():
    cells = [
        'a = 1',
        'b = 2',
        '# nuclio: end-code my-function',
        'd = 4',
        'e = 2',
        '# nuclio: end-code my-function',
    ]
    kw = {env_keys.function_name: 'my-function'}
    with temp_env(kw):
        nb = gen_nb(cells)
        with pytest.raises(export.MagicError):
            code, _ = export_notebook(nb)


def test_end_and_then_start():
    cells = [
        'b = 2',
        '# nuclio: end-code my-function\n'
        'd = 4\n'
        '# nuclio: start-code my-function\n',
        'a = 1',
    ]
    kw = {env_keys.function_name: 'my-function'}
    with temp_env(kw):
        nb = gen_nb(cells)
        with pytest.raises(export.MagicError):
            code, _ = export_notebook(nb)


@pytest.mark.parametrize(
    "case", cases_from_yml_file(f"{here}/cell_and_line_magic_test_cases.yml")
)
def test_converter_cell_and_line_magic(case: dict):
    notebook = {
        "cells": [
            {"source": code, "cell_type": "code"}
            for code in case["cells"]
        ],
    }
    _, config = export_notebook(notebook)
    cmds = config['spec']['build']['commands']
    assert environ['HOME'] in cmds[0], '${HOME} not expanded'


def test_commented_out_line_magic():
    cells = [
        'd = 4\n'
        '# %%nuclio cmd ls ${HOME}\n',
        'a = 1',
    ]
    notebook = {
        "cells": [
            {"source": code, "cell_type": "code"}
            for code in cells
        ],
    }
    _, config = export_notebook(notebook)
    cmds = config['spec']['build']['commands']
    assert len(cmds) == 0, 'parsed commented out magic'
