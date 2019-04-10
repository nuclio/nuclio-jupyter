from nuclio.build import build_file
from nuclio.config import ConfigSpec, meta_keys, get_in
from conftest import here


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
    assert envs[0].get('name') == 'MYENV', 'build failed, env err'.format(envs)


def test_build_file_nb():
    filepath = '{}/handler.ipynb'.format(here)
    filepath = filepath.replace("\\", "/")  # handle windows
    spec = ConfigSpec(config={'spec.maxReplicas': 2})
    name, config, code = build_file(filepath, spec=spec)

    assert name == 'handler', 'build failed, name doesnt match={}'.format(name)
    assert config.get('spec'), 'build failed, config={}'.format(config)

    maxRep = get_in(config, 'spec.maxReplicas')
    assert maxRep == 2, 'failed to set replicas, {}'.format(maxRep)


def test_build_url():
    filepath = 'https://raw.githubusercontent.com/nuclio/nuclio/master/hack/' \
               + 'examples/java/empty/EmptyHandler.java'

    name, config, code = build_file(filepath, name='javatst', output_dir='.')

    assert name == 'javatst', 'build failed, name doesnt match={}'.format(name)
    assert config.get('spec'), 'build failed, config={}'.format(config)
    assert get_in(config, 'spec.runtime') == 'java', 'not java runtime'


def test_build_file_zip():
    filepath = '{}/handler.py'.format(here)
    filepath = filepath.replace("\\", "/")  # handle windows
    spec = ConfigSpec(env={'MYENV': 'text'})
    name, config, code = build_file(filepath, name='hw', spec=spec,
                                    archive=True, project='p1', tag='v7',
                                    output_dir='.')

    assert name == 'hw', 'build failed, name doesnt match={}'.format(name)
    assert config.get('spec'), 'build failed, config={}'.format(config)
