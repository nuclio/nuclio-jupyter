# Copyright 2021 Iguazio
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
import pytest

from nuclio.triggers import HttpTrigger, V3IOStreamTrigger, KafkaTrigger, Constants


def test_access_key_must_be_set():
    with pytest.raises(ValueError):
        V3IOStreamTrigger(url="some-url", access_key=None)

    V3IOStreamTrigger(url="some-url", access_key="set")


def test_create_v3io_stream_trigger():
    v3io_stream_trigger = V3IOStreamTrigger(url="some-url", access_key="123")
    assert v3io_stream_trigger.get_url == "some-url"

    v3io_stream_trigger = V3IOStreamTrigger(access_key="abc")
    assert v3io_stream_trigger.get_url == Constants.default_webapi_address


def test_create_v3io_stream_trigger_with_explicit_ack_mode():
    for explicit_ack_mode in [
        None,
        "enable",
        "explicitOnly",
    ]:
        if not explicit_ack_mode:
            trigger = V3IOStreamTrigger(
                url="some-url",
                access_key="123",
            )
            assert not trigger._struct.get("explicitAckMode", None)
        else:
            trigger = V3IOStreamTrigger(
                url="some-url",
                access_key="123",
                explicit_ack_mode=explicit_ack_mode,
            )
            assert trigger._struct.get("explicitAckMode") == explicit_ack_mode


def test_create_kafka_trigger_with_explicit_ack_mode():
    for explicit_ack_mode in [
        None,
        "enable",
        "explicitOnly",
    ]:
        if not explicit_ack_mode:
            trigger = KafkaTrigger(
                brokers="some-brokers",
                topics=["some-topic"],
            )
            assert not trigger._struct.get("explicitAckMode", None)
        else:
            trigger = KafkaTrigger(
                brokers="some-brokers",
                topics=["some-topic"],
                explicit_ack_mode=explicit_ack_mode,
            )
            assert trigger._struct.get("explicitAckMode") == explicit_ack_mode


def test_cast_http_trigger_port_to_int():
    http_trigger = HttpTrigger(port='9009')
    assert http_trigger.get_port == 9009


def test_http_trigger_no_port():
    http_trigger = HttpTrigger()
    assert http_trigger.get_port is None


def test_http_trigger_workers_to_int():
    http_trigger = HttpTrigger(host='something')
    http_trigger.workers('123')
    assert http_trigger.get_workers == 123


def test_http_trigger_host():
    http_trigger = HttpTrigger(host='something', paths=['/here'])
    assert http_trigger.get_ingresses['0'].get('host') == 'something'
    assert http_trigger.get_ingresses['0'].get('paths') == ['/here']


def test_http_trigger_extra():
    http_trigger = HttpTrigger(annotations={"x": "123"}, extra_attributes={"y": "456"})
    assert http_trigger._struct["annotations"]["x"] == "123"
    assert http_trigger._struct["attributes"]["y"] == "456"


def test_renamed_deprecated_values_old_names():
    trigger = V3IOStreamTrigger(seekTo="test",
                                access_key="abc",
                                maxWorkers=5,
                                workerAllocationMode="static",
                                consumerGroup="cg1",
                                readBatchSize=128,
                                sessionTimeout="11s",
                                sequenceNumCommitInterval="2s",
                                heartbeatInterval="5s",
                                pollingIntervalMS=100,
                                )
    assert trigger._struct["attributes"]["seekTo"] == "test"
    assert trigger._struct["attributes"]["workerAllocationMode"] == "static"
    assert trigger._struct["attributes"]["consumerGroup"] == "cg1"
    assert trigger._struct["attributes"]["readBatchSize"] == 128
    assert trigger._struct["attributes"]["sessionTimeout"] == "11s"
    assert trigger._struct["attributes"]["sequenceNumberCommitInterval"] == "2s"
    assert trigger._struct["attributes"]["heartbeatInterval"] == "5s"
    assert trigger._struct["attributes"]["pollingIntervalMs"] == 100
    assert trigger._struct["maxWorkers"] == 5


def test_renamed_deprecated_values_new_names():
    trigger = V3IOStreamTrigger(seek_to="test",
                                access_key="abc",
                                maxWorkers=5,
                                worker_allocation_mode="static",
                                consumer_group="cg1",
                                read_batch_size=128,
                                session_timeout="11s",
                                sequence_num_commit_interval="2s",
                                heartbeat_interval="5s",
                                polling_interval_ms=100,
                                )
    assert trigger._struct["attributes"]["seekTo"] == "test"
    assert trigger._struct["attributes"]["workerAllocationMode"] == "static"
    assert trigger._struct["attributes"]["consumerGroup"] == "cg1"
    assert trigger._struct["attributes"]["readBatchSize"] == 128
    assert trigger._struct["attributes"]["sessionTimeout"] == "11s"
    assert trigger._struct["attributes"]["sequenceNumberCommitInterval"] == "2s"
    assert trigger._struct["attributes"]["heartbeatInterval"] == "5s"
    assert trigger._struct["attributes"]["pollingIntervalMs"] == 100
    assert trigger._struct["maxWorkers"] == 5
