from os import environ
from os.path import abspath, dirname

here = dirname(abspath(__file__))
environ['ENV_FILE'] = '{}/env.txt'.format(here)
