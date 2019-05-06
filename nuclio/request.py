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

import logging
import os
from sys import stdout

from nuclio_sdk import Context as _Context, Logger
from nuclio_sdk.logger import HumanReadableFormatter
from nuclio_sdk import Event  # noqa


class Context(_Context):
    """Wrapper around nuclio_sdk.Context to make automatically create
    logger"""
    def __getattribute__(self, attr):
        value = object.__getattribute__(self, attr)
        if value is None and attr == 'logger':
            value = self.logger = Logger(level=logging.INFO)
            value.set_handler(
                'nuclio-jupyter', stdout, HumanReadableFormatter())
        return value

    def set_logger_level(self, verbose=False):
        if verbose:
            level = logging.DEBUG
        else:
            level = logging.INFO
        value = self.logger = Logger(level=level)
        value.set_handler('nuclio-jupyter', stdout, HumanReadableFormatter())


def inject_context():
    # add context, only if not inside nuclio
    if not os.environ.get('NUCLIO_FUNCTION_INSTANCE'):
        import builtins
        builtins.context = Context()
