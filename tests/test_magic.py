from contextlib import redirect_stdout
from io import StringIO
from nuclio import magic

from test_export import here


def test_print_handler_code():
    fname = '{}/handler.ipynb'.format(here)
    io = StringIO()
    with redirect_stdout(io):
        magic.print_handler_code(fname)

    assert 'def handler' in io.getvalue()
