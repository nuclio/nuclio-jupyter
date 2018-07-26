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
import logging
from datetime import datetime
from sys import stdout

from traitlets import HasTraits, Int, Unicode, Instance, Dict, default, Any


class TriggerInfo(HasTraits):
    """Mock Trigger information

    Attributes:
        klass (str): trigger class
        kind (str): trigger kind
    """
    klass = Unicode()
    kind = Unicode()


class Event(HasTraits):
    """Mock nuclio event

    Attributes:
        body: Event body
        content_type (string): body content type
        trigger (TriggerInfo): trigger information
        fields (dict): event fields
        headers (dict): event headers
        id: event ID
        method (str): event method (e.g. 'POST')
        path (str): event path (e.g. '/handler')
        size (int): body length in bytes
        timestamp (datetime): event time
        url (str): event URL (e.g. 'http://nuclio.io')
        type (str): event type
        type_version (str): event type version
        version (str): event version
    """
    body = Unicode()
    content_type = Unicode('text/plain')
    trigger = Instance(TriggerInfo)
    fields = Dict()
    headers = Dict()
    id = Unicode()
    method = Unicode('POST')
    path = Unicode('/')
    size = Int()
    timestamp = Instance(datetime)
    url = Unicode('http://nuclio.io')
    type = Unicode()
    type_version = Unicode()
    version = Unicode()

    @default('timestamp')
    def _timestamp_default(self):
        return datetime.now()


class Response(HasTraits):
    """Mock nuclio response

    Args:
        headers (dict): Response headers
        body: Response body
        status_code (int): Response status code (usually HTTP response code)
        content_type (str): Response content type (e.g. text/plain)
    """
    headers = Dict()
    body = Any()
    status_code = Int(200)
    content_type = Unicode('text/plain')


class _Formatter(logging.Formatter):
    def format(self, record):
        """Format log record a string. We're trying to simulate what the nuclio
        logger does.
        """
        timestamp = self.formatTime(record)
        name = record.name
        level = record.levelname[0]
        message = record.getMessage()
        with_data = getattr(record, 'with', None)
        if with_data:
            message = '{} {}'.format(message, json.dumps(with_data))

        return '{} {} ({}) {}'.format(timestamp, name, level, message)


class _Logger:
    def __init__(self, log_format=''):
        handler = logging.StreamHandler(stdout)
        handler.setFormatter(_Formatter())
        self._logger = logger = logging.getLogger('nuclio')
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

    def debug(self, message, *args):
        self._logger.debug(message, *args)

    def info(self, message, *args):
        self._logger.info(message, *args)

    def warn(self, message, *args):
        self._logger.warning(message, *args)

    def error(self, message, *args):
        self._logger.error(message, *args)

    def debug_with(self, message, *args, **kw_args):
        self._logger.debug(message, *args, extra={'with': kw_args})

    def info_with(self, message, *args, **kw_args):
        self._logger.info(message, *args, extra={'with': kw_args})

    def warn_with(self, message, *args, **kw_args):
        self._logger.warning(message, *args, extra={'with': kw_args})

    def error_with(self, message, *args, **kw_args):
        self._logger.error(message, *args, extra={'with': kw_args})


class Context(HasTraits):
    """Mock nuclio context

    Attributes:
        platform: nuclio platform
        logger: nuclio logger
        user_data: User data
    """
    platform = Unicode('local')
    logger = Instance(_Logger, args=())  # args=() means default instance
    user_data = Any(lambda: None)

    Response = Response
