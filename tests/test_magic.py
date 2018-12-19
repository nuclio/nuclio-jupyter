# Copyright 2018 Iguazio
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from contextlib import redirect_stdout
from glob import glob
from io import StringIO

from conftest import here
from nuclio import magic


def test_print_handler_code():
    fname = '{}/handler.ipynb'.format(here)
    io = StringIO()
    with redirect_stdout(io):
        magic.print_handler_code(fname)

    assert 'def handler' in io.getvalue()


def test_export():
    nb = '{}/handler.ipynb'.format(here)
    line = '--notebook {}'.format(nb)
    dir_name = magic.export(line, None, return_dir=True)
    files = glob('{}/*'.format(dir_name))
    assert len(files) == 1, 'bad number of files'
