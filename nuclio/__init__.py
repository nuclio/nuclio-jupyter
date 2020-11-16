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

from .request import Context, Event, inject_context as _inject_context  # noqa
from . import magic  # noqa
from .deploy import deploy_code, deploy_file, delete_func, deploy_model  # noqa
from .config import Volume, ConfigSpec  # noqa
from .build import build_file  # noqa
from .triggers import HttpTrigger, CronTrigger, KafkaTrigger  # noqa

__version__ = '0.8.8'

_inject_context()
del _inject_context


# Allow %load_ext nuclio
def load_ipython_extension(ipython):
    # Nothing to do, nuclio/magic.py does the registration
    pass
