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
import base64
import json
import datetime


class HumanReadableFormatter(logging.Formatter):

    def __init__(self):
        super(HumanReadableFormatter, self).__init__()

    def format(self, record):
        record_with = getattr(record, 'with', {})
        if record_with:
            more = ': {0}'.format(record_with)
        else:
            more = ''

        return 'Python> {0} [{1}] {2}{3}'.format(
            self.formatTime(record, self.datefmt),
            record.levelname.lower(),
            record.getMessage(),
            more)


class Context(object):
    """Wrapper around nuclio_sdk.Context to make automatically create
    logger"""
    def __init__(self, logger=None, worker_id=None, trigger_name=None):
        self.logger = logger
        self.user_data = lambda: None
        self.worker_id = worker_id
        self.trigger_name = trigger_name

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


class Logger(object):

    def __init__(self, level):
        self._logger = logging.getLogger('nuclio_sdk')
        self._logger.setLevel(level)
        self._handlers = {}

    def set_handler(self, handler_name, file, formatter):

        # check if there's a handler by this name
        if handler_name in self._handlers:

            # log that we're removing it
            self.info_with('Replacing logger output')

            self._logger.removeHandler(self._handlers[handler_name])

        # create a stream handler from the file
        stream_handler = logging.StreamHandler(file)

        # set the formatter
        stream_handler.setFormatter(formatter)

        # add the handler to the logger
        self._logger.addHandler(stream_handler)

        # save as the named output
        self._handlers[handler_name] = stream_handler

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


class TriggerInfo(object):

    def __init__(self, klass='', kind=''):
        self.klass = klass
        self.kind = kind


class Event(object):

    def __init__(self,
                 body=None,
                 content_type=None,
                 trigger=None,
                 fields=None,
                 headers=None,
                 _id=None,
                 method=None,
                 path=None,
                 size=None,
                 timestamp=None,
                 url=None,
                 _type=None,
                 type_version=None,
                 version=None):
        self.body = body
        self.content_type = content_type
        self.trigger = trigger or TriggerInfo(klass='', kind='')
        self.fields = fields or {}
        self.headers = headers or {}
        self.id = _id
        self.method = method
        self.path = path or '/'
        self.size = size
        self.timestamp = timestamp or 0
        self.url = url
        self.type = _type
        self.type_version = type_version
        self.version = version

    def to_json(self):
        obj = vars(self).copy()
        obj['trigger'] = {
            'class': self.trigger.klass,
            'kind': self.trigger.kind,
        }
        return json.dumps(obj)

    def get_header(self, header_key):
        for key, value in self.headers.items():
            if key.lower() == header_key.lower():
                return value

    @staticmethod
    def from_json(data):
        """Decode event encoded as JSON by processor"""

        parsed_data = json.loads(data)
        trigger = TriggerInfo(
            parsed_data['trigger']['class'],
            parsed_data['trigger']['kind'],
        )

        # extract content type, needed to decode body
        content_type = parsed_data['content_type']

        return Event(body=Event.decode_body(parsed_data['body'], content_type),
                     content_type=content_type,
                     trigger=trigger,
                     fields=parsed_data.get('fields'),
                     headers=parsed_data.get('headers'),
                     _id=parsed_data['id'],
                     method=parsed_data['method'],
                     path=parsed_data['path'],
                     size=parsed_data['size'],
                     timestamp=datetime.datetime.utcfromtimestamp(
                         parsed_data['timestamp']),
                     url=parsed_data['url'],
                     _type=parsed_data['type'],
                     type_version=parsed_data['type_version'],
                     version=parsed_data['version'])

    @staticmethod
    def decode_body(body, content_type):
        """Decode event body"""

        if isinstance(body, dict):
            return body
        else:
            try:
                decoded_body = base64.b64decode(body)
            except Exception:
                return body

            if content_type == 'application/json':
                try:
                    return json.loads(decoded_body)
                except Exception:
                    pass

            return decoded_body

    def __repr__(self):
        return self.to_json()


def inject_context():
    # add context, only if not inside nuclio
    if not os.environ.get('NUCLIO_FUNCTION_INSTANCE'):
        import builtins
        builtins.context = Context()
