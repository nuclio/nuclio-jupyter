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

import pytest

from nuclio import config


def get_env_var_from_list_by_key(env, key):
    for env_var in env:
        if env_var['name'] == key:
            return env_var
    return None


def test_update_env_var_missing_value():
    config_dict = {'spec': {'env': []}}
    with pytest.raises(Exception, match='either value or value_from required for env var: name'):
        config.create_or_update_env_var(config_dict, 'name')


def test_create_or_update_env_var_existing_key():
    config_dict = {'spec': {
            'env': [
                {'name': 'key', 'value': 'value1'},
                {'name': 'key2', 'value': 'value1'},
            ]
        }
    }
    config.create_or_update_env_var(config_dict, 'key', value='value2')
    assert get_env_var_from_list_by_key(config_dict['spec']['env'], 'key')['value'] == 'value2',\
        'env var was not updated'

    value_from = {"secretKeyRef": {"name": "secret1", "key": "secret-key1"}}
    config.create_or_update_env_var(config_dict, 'key2', value_from=value_from)
    assert get_env_var_from_list_by_key(config_dict['spec']['env'], 'key2')['valueFrom'] == value_from,\
        'env var was not updated'


def test_create_or_update_env_var_new_key():
    config_dict = {'spec': {'env': []}}
    config.create_or_update_env_var(config_dict, 'key', value='value2')
    assert get_env_var_from_list_by_key(config_dict['spec']['env'], 'key')['value'] == 'value2',\
        'env var was not added'

    value_from = {"secretKeyRef": {"name": "secret1", "key": "secret-key1"}}
    config.create_or_update_env_var(config_dict, 'key2', value_from=value_from)
    assert get_env_var_from_list_by_key(config_dict['spec']['env'], 'key2')['valueFrom'] == value_from,\
        'env var was not added'


def test_set_external_source_env_dict():
    config_dict = {'spec': {'env': []}}
    secrets = {
        'name1': {"secretKeyRef": {"name": "secret1", "key": "secret-key1"}},
        'name2': {"secretKeyRef": {"name": "secret2", "key": "secret-key2"}},
        'name3': {"configMapKeyRef": {"name": "config-map1", "key": "config-map-key1"}},
    }
    config.set_external_source_env_dict(config_dict, secrets)

    assert get_env_var_from_list_by_key(config_dict['spec']['env'], 'name1')['valueFrom'] == secrets['name1']
    assert get_env_var_from_list_by_key(config_dict['spec']['env'], 'name2')['valueFrom'] == secrets['name2']
    assert get_env_var_from_list_by_key(config_dict['spec']['env'], 'name3')['valueFrom'] == secrets['name3']
