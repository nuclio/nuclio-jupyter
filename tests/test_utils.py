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

from nuclio import utils


def test_update_in():
    obj = {}
    utils.update_in(obj, 'a.b.c', 2)
    assert obj['a']['b']['c'] == 2
    utils.update_in(obj, 'a.b.c', 3)
    assert obj['a']['b']['c'] == 3

    utils.update_in(obj, 'a.b.d', 3, append=True)
    assert obj['a']['b']['d'] == [3]
    utils.update_in(obj, 'a.b.d', 4, append=True)
    assert obj['a']['b']['d'] == [3, 4]
