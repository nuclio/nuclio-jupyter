# Copyright 2021 Iguazio
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

import os
import shutil

import pytest

from nuclio.build import build_file
from nuclio.config import ConfigSpec, meta_keys, get_in
from conftest import here


@pytest.fixture()
def url_filepath():
    url_filepath = 'https://raw.githubusercontent.com/nuclio/nuclio/master/' \
                   'hack/examples/java/empty/EmptyHandler.java'
    yield url_filepath
    if os.path.exists('EmptyHandler.java'):
        os.remove('EmptyHandler.java')
    if os.path.exists('function.yaml'):
        os.remove('function.yaml')


@pytest.fixture()
def project():
    project = 'p1'
    yield project
    if os.path.exists(project):
        shutil.rmtree(project)


def test_build_file_py():
    filepath = '{}/handler.py'.format(here)
    filepath = filepath.replace("\\", "/")  # handle windows
    spec = ConfigSpec(env={'MYENV': 'text'})
    name, config, code = build_file(filepath, name='hw', spec=spec, tag='v7')

    assert name == 'hw', 'build failed, name doesnt match={}'.format(name)

    assert config.get('spec'), 'build failed, config={}'.format(config)

    tag = config['metadata']['labels'].get(meta_keys.tag)
    assert tag == 'v7', 'failed, tag not set properly config={}'.format(config)

    envs = config['spec']['env']
    assert_error_message = 'build failed, env err {0}'.format(envs)
    assert envs[0].get('name') == 'MYENV', assert_error_message


def test_build_file_nb():
    filepath = '{}/handler.ipynb'.format(here)
    filepath = filepath.replace("\\", "/")  # handle windows
    spec = ConfigSpec(config={'spec.maxReplicas': 2})
    name, config, code = build_file(filepath, spec=spec)

    assert name == 'handler', 'build failed, name doesnt match={}'.format(name)
    assert config.get('spec'), 'build failed, config={}'.format(config)

    maxRep = get_in(config, 'spec.maxReplicas')
    assert maxRep == 2, 'failed to set replicas, {}'.format(maxRep)


def test_build_file_nb_ignored_tags():
    filepath = '{}/tags-test.ipynb'.format(here)
    filepath = filepath.replace("\\", "/")  # handle windows
    name, config, code = build_file(filepath)
    print("code:", code)
    assert code.find("import nuclio") > 0, "missing code section"
    assert code.find("test1") == -1, "did not ignore 'nuclio-ignore' (default)"

    name, config, code = build_file(filepath, ignored_tags="my-ignore-tag")
    print("code:", code)
    assert code.find("import nuclio") > 0, "missing code section"
    assert code.find("test3") == -1, "did not ignore 'my-ignore-tag'"


def test_build_url(url_filepath):
    name, config, code = build_file(url_filepath,
                                    name='javatst',
                                    output_dir='.')

    assert name == 'javatst', 'build failed, name doesnt match={}'.format(name)
    assert config.get('spec'), 'build failed, config={}'.format(config)
    assert get_in(config, 'spec.runtime') == 'java', 'not java runtime'
    assert os.path.exists('EmptyHandler.java'), \
        'EmptyHandler.java file was not created'
    assert os.path.exists('function.yaml'), \
        'function.yaml file was not created'


def test_build_file_zip(project):
    filepath = '{}/handler.py'.format(here)
    filepath = filepath.replace("\\", "/")  # handle windows
    spec = ConfigSpec(env={'MYENV': 'text'})
    name, config, code = build_file(filepath, name='hw', spec=spec,
                                    archive=True, project=project, tag='v7',
                                    output_dir='.')

    assert name == 'hw', 'build failed, name doesnt match={}'.format(name)
    assert config.get('spec'), 'build failed, config={}'.format(config)
    assert os.path.exists(project), '{} dir was not created'.format(project)
    zip_path = os.path.join(project, 'hw_v7.zip')
    assert os.path.exists(zip_path), '{} dir was not created'.format(zip_path)
