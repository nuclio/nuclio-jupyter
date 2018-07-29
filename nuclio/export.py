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

import json
import re
from os.path import abspath, dirname, join
from subprocess import check_output
from textwrap import indent
from urllib.parse import urlencode, urljoin
from urllib.request import urlopen

import ipykernel
from nbconvert.exporters.html import HTMLExporter
from nbconvert.filters import ipython2python
from notebook.notebookapp import list_running_servers

here = dirname(abspath(__file__))

#  '# nuclio: ignore'
is_ignore = re.compile('#\s*nuclio:\s*ignore').search
#  '# nuclio: handler'
is_handler = re.compile('^\s*#\s*nuclio:\s*handler').search
#  '# nuclio: return'
is_return = re.compile('#\s*nuclio:\s*return').search
handler_decl = 'def handler(context, event):'
indent_prefix = '    '


class NuclioExporter(HTMLExporter):
    """Export to nuclio handler"""

    # Add "File -> Download as" menu in the notebook
    export_from_notebook = 'Nuclio'

    def _file_extension_default(self):
        """Return default file extension"""
        return '.py'

    @property
    def template_path(self):
        """Add our own templates directory to the template path"""
        return super().template_path + [join(here, 'templates')]

    def _template_file_default(self):
        """Name of default template"""
        return 'nuclio'

    def default_filters(self):
        for pair in super().default_filters():
            yield pair

        yield ('nuclio', self.convert)

    def convert(self, text):
        code = ipython2python(text)

        if is_ignore(code):
            return indent(code, '# ')

        if not is_handler(code):
            return code

        lines = [handler_decl]
        code = indent(code, indent_prefix)
        for line in code.splitlines():
            if is_return(line):
                line = self.add_return(line)
            lines.append(line)

        # Add return to last code line (if not there)
        last_idx = len(lines) - 1
        for i, line in enumerate(reversed(lines[1:])):
            if not self.is_code_line(line):
                continue

            if 'return' not in line:
                lines[last_idx-i] = self.add_return(line)
            break

        return '\n'.join(lines)

    def is_code_line(self, line):
        """A code line is a non empty line that don't start with #"""
        line = line.strip()
        return line and line[0] != '#'

    def add_return(self, line, prefix=indent_prefix):
        """Add return to a line"""
        return line.replace(prefix, prefix + 'return ', 1)


# Based on
# https://github.com/jupyter/notebook/issues/1000#issuecomment-359875246
def notebook_file_name():
    """
    Return the full path of the jupyter notebook.
    """
    kernel_id = re.search('kernel-(.*).json',
                          ipykernel.connect.get_connection_file()).group(1)
    servers = list_running_servers()
    for srv in servers:
        query = {'token': srv.get('token', '')}
        url = urljoin(srv['url'], 'api/sessions') + '?' + urlencode(query)
        for session in json.load(urlopen(url)):
            if session['kernel']['id'] == kernel_id:
                relative_path = session['notebook']['path']
                return join(srv['notebook_dir'], relative_path)


def print_handler_code():
    """Prints handler code (as it was exported)"""
    cmd = [
        'jupyter', 'nbconvert',
        '--to', 'nuclio.export.NuclioExporter',
        '--stdout',
        notebook_file_name(),
    ]
    out = check_output(cmd).decode('utf-8')
    print(out)
