from os import environ
from os.path import abspath, dirname

import pytest

import nuclio

here = dirname(abspath(__file__))
environ['ENV_FILE'] = '{}/env.txt'.format(here)


@pytest.fixture
def clean_handlers():
    nuclio.export.handlers.clear()
