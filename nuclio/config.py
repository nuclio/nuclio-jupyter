from copy import deepcopy

_function_config = {
    'apiVersion': 'nuclio.io/v1',
    'kind': 'Function',
    'metadata': {
        'name': 'notebook',
    },
    'spec': {
        'runtime': 'python:3.6',
        'handler': None,
        'env': [],
        'volumes': [],
        'build': {
            'commands': [],
            'noBaseImagesPull': True,
        },
    },
}


def new_config():
    return deepcopy(_function_config)
