# Copyright 2018 The Nuclio Authors.
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
#
import typing
from os import environ

from .utils import logger


class Constants(object):
    default_webapi_address = "http://v3io-webapi:8081"


class NuclioTrigger:
    kind = ""

    def __init__(self, struct: typing.Optional[dict] = None):
        self._struct = struct or {}

    def to_dict(self):
        return self._struct

    def disable(self, disabled: bool = True):
        self._struct["disabled"] = disabled
        return self

    def workers(self, workers: int = 4):
        self._struct["maxWorkers"] = int(workers)
        return self

    def _add_extra_attrs(self, extra_attributes):
        if extra_attributes:
            for key, value in extra_attributes.items():
                self._struct["attributes"][key] = value

    @property
    def get_workers(self) -> int:
        return self._struct["maxWorkers"]


class HttpTrigger(NuclioTrigger):
    kind = "http"

    def __init__(
        self,
        workers=8,
        port=0,
        host=None,
        paths=None,
        canary=None,
        secret=None,
        annotations=None,
        extra_attributes=None,
    ):
        super(HttpTrigger, self).__init__(
            {
                "kind": self.kind,
                "maxWorkers": int(workers),
                "attributes": {"ingresses": {}},
                "annotations": annotations or {},
            }
        )
        if port:

            # if port is a string for some reason, cast it
            if not isinstance(port, int):
                port = int(port)
            self._struct["attributes"]["port"] = port
        if host:
            self._ingress(host, paths, canary, secret=secret)
        self._add_extra_attrs(extra_attributes)

    def ingress(
        self, host, paths=None, canary=None, name="0", secret=None,
    ):
        return self._ingress(host, paths, canary, name, secret)

    @property
    def get_port(self) -> typing.Optional[int]:
        return self._struct["attributes"].get("port")

    @property
    def get_ingresses(self) -> typing.Optional[typing.Dict[str, dict]]:
        return self._struct["attributes"]["ingresses"]

    def _ingress(
        self, host, paths=None, canary=None, name="0", secret=None,
    ):
        if paths and not isinstance(paths, list):
            raise ValueError('paths must be a list of paths e.g. ["/x"]')
        if not paths:
            paths = ["/"]
        if "IGZ_NAMESPACE_DOMAIN" in environ:
            host = "{}.{}".format(host, environ["IGZ_NAMESPACE_DOMAIN"])
        self._struct["attributes"]["ingresses"][name] = {
            "host": host,
            "paths": paths,
        }
        if secret is not None:
            if not isinstance(secret, str):
                raise ValueError("secret must be a Kubernetes secret name")
            self._struct["attributes"]["ingresses"][name]["secretName"] = secret

        if canary is not None:
            if not isinstance(canary, int) or canary > 100 or canary < 0:
                raise ValueError("canary must ve an int between 0 to 100")
            self._struct["annotations"]["nginx.ingress.kubernetes.io/canary"] = "true"
            self._struct["annotations"][
                "nginx.ingress.kubernetes.io/canary-weight"
            ] = str(canary)

        return self


class CronTrigger(NuclioTrigger):
    kind = "cron"

    def __init__(
        self, interval="", schedule="", body="", headers=None, extra_attributes=None
    ):
        """Attach cron trigger to nuclio function
        :param interval:    e.g. '1h', '30m', '10s'
        :param schedule:    Regular cron string as per https://pypi.org/project/croniter/
        :param body:        Set project and workflow nuclio event body
        :param headers:     Set nuclio event headers

        Examples::
        fn = mlrun.new_function('fn_name', kind='nuclio', image='mlrun/mlrun')
        fn.add_trigger(
            'trigger_name',
            CronTrigger(
                schedule='* * 1 * *',
                body=json.dumps({'project_url': '~/project.yaml', 'workflow': 'main'}),
                headers={'X-Nuclio-Target': 'fn_name'}
        ))
        """
        super(CronTrigger, self).__init__(
            {"kind": self.kind, "attributes": {}}
        )
        headers = headers or {}
        if interval:
            self._struct["attributes"]["interval"] = interval
        elif schedule:
            self._struct["attributes"]["schedule"] = schedule
        else:
            raise ValueError("interval or schedule must be specified")
        if body or headers:
            self._struct["attributes"]["event"] = {
                "body": body,
                "headers": headers,
            }
        self._add_extra_attrs(extra_attributes)


class KafkaTrigger(NuclioTrigger):
    kind = "kafka-cluster"

    def __init__(
        self,
        brokers,
        topics,
        partitions=None,
        consumer_group="kafka",
        initial_offset="earliest",
        explicit_ack_mode=None,
        extra_attributes=None,
        session_timeout: str = "10s",
        heartbeat_interval: str = "3s",
        worker_allocation_mode: str = "pool",
        fetch_default: int = 1048576,
        max_workers: int = 1,
        worker_termination_timeout: str = "10s",
    ):
        super(KafkaTrigger, self).__init__(
            {
                "kind": self.kind,
                "maxWorkers": max_workers,
                "workerTerminationTimeout": worker_termination_timeout,
                "attributes": {
                    "topics": topics,
                    "brokers": brokers,
                    "consumerGroup": consumer_group,
                    "initialOffset": initial_offset,
                    "sessionTimeout": session_timeout,
                    "heartbeatInterval": heartbeat_interval,
                    "workerAllocationMode": worker_allocation_mode,
                    "fetchDefault": fetch_default,
                },
            }
        )
        partitions = partitions or []
        if partitions:
            self._struct["attributes"]["partitions"] = partitions
        if explicit_ack_mode:
            self._struct["explicitAckMode"] = explicit_ack_mode
            # workerAllocationMode conflicts with explicit_ack_mode, so we should force static one in that case
            if not extra_attributes:
                extra_attributes = {}
            extra_attributes.setdefault("workerAllocationMode", "static")
            logger.warn("workerAllocationMode was automatically set to 'static' because explicitAckMode is enabled")

        self._add_extra_attrs(extra_attributes)

    def sasl(self, user="", password=""):
        self._struct["attributes"]["sasl"] = {
            "enable": True,
            "user": user,
            "password": password,
        }
        return self


class V3IOStreamTrigger(NuclioTrigger):
    kind = "v3ioStream"

    def __init__(
        self,
        url: str = None,
        seek_to: str = "latest",
        partitions: list = None,
        polling_interval_ms: int = 500,
        read_batch_size: int = 64,
        max_workers: int = 1,
        access_key: str = None,
        session_timeout: str = "10s",
        name: str = None,
        container: str = None,
        path: str = None,
        worker_allocation_mode: str = "pool",
        webapi: str = Constants.default_webapi_address,
        consumer_group: str = "default",
        sequence_num_commit_interval: str = "1s",
        heartbeat_interval: str = "3s",
        explicit_ack_mode: str = None,
        extra_attributes=None,
        worker_termination_timeout: str = "10s",
        **deprecated_kwargs,
    ):
        # TODO: delete deprecated arguments in 0.10.0
        deprecation_warning_template = "Using deprecated argument '{old_arg_name}' will be removed in 0.10.0 version." \
                                       "Please use '{new_arg_name}' instead."

        if "seekTo" in deprecated_kwargs:
            logger.warn(deprecation_warning_template.format(old_arg_name="seekTo",
                                                            new_arg_name="seek_to"))
            seek_to = deprecated_kwargs.get("seekTo")
        if "pollingIntervalMS" in deprecated_kwargs:
            logger.warn(deprecation_warning_template.format(old_arg_name="pollingIntervalMS",
                                                            new_arg_name="polling_interval_ms"))
            polling_interval_ms = deprecated_kwargs.get("pollingIntervalMS")
        if "readBatchSize" in deprecated_kwargs:
            logger.warn(deprecation_warning_template.format(old_arg_name="readBatchSize",
                                                            new_arg_name="read_batch_size"))
            read_batch_size = deprecated_kwargs.get("readBatchSize")
        if "maxWorkers" in deprecated_kwargs:
            logger.warn(deprecation_warning_template.format(old_arg_name="maxWorkers",
                                                            new_arg_name="max_workers"))
            max_workers = deprecated_kwargs.get("maxWorkers")
        if "sessionTimeout" in deprecated_kwargs:
            logger.warn(deprecation_warning_template.format(old_arg_name="sessionTimeout",
                                                            new_arg_name="session_timeout"))
            session_timeout = deprecated_kwargs.get("sessionTimeout")
        if "workerAllocationMode" in deprecated_kwargs:
            logger.warn(deprecation_warning_template.format(old_arg_name="workerAllocationMode",
                                                            new_arg_name="worker_allocation_mode"))
            worker_allocation_mode = deprecated_kwargs.get("workerAllocationMode")
        if "consumerGroup" in deprecated_kwargs:
            logger.warn(deprecation_warning_template.format(old_arg_name="consumerGroup",
                                                            new_arg_name="consumer_group"))
            consumer_group = deprecated_kwargs.get("consumerGroup")
        if "sequenceNumCommitInterval" in deprecated_kwargs:
            logger.warn(deprecation_warning_template.format(old_arg_name="sequenceNumCommitInterval",
                                                            new_arg_name="sequence_num_commit_interval"))
            sequence_num_commit_interval = deprecated_kwargs.get("sequenceNumCommitInterval")
        if "heartbeatInterval" in deprecated_kwargs:
            logger.warn(deprecation_warning_template.format(old_arg_name="heartbeatInterval",
                                                            new_arg_name="heartbeat_interval"))
            heartbeat_interval = deprecated_kwargs.get("heartbeatInterval")

        if url and not container and not path:
            struct = {
                "kind": self.kind,
                "url": url,
                "attributes": {},
            }
        else:
            struct = {
                "kind": self.kind,
                "url": webapi,
                "workerTerminationTimeout": worker_termination_timeout,
                "attributes": {
                    "containerName": container,
                    "streamPath": path,
                    "consumerGroup": consumer_group,
                    "sequenceNumberCommitInterval": sequence_num_commit_interval,
                    "workerAllocationMode": worker_allocation_mode,
                    "sessionTimeout": session_timeout,
                    "heartbeatInterval": heartbeat_interval,
                },
            }

            if name:
                struct["name"] = name

        if max_workers:
            struct["maxWorkers"] = max_workers
        if seek_to:
            struct["attributes"]["seekTo"] = seek_to
        if read_batch_size:
            struct["attributes"]["readBatchSize"] = read_batch_size
        if partitions:
            struct["attributes"]["partitions"] = partitions
        if polling_interval_ms:
            struct["attributes"]["pollingIntervalMs"] = polling_interval_ms
        if explicit_ack_mode:
            struct["explicitAckMode"] = explicit_ack_mode
            # workerAllocationMode conflicts with explicit_ack_mode, so we should force static one in that case
            if not extra_attributes:
                extra_attributes = {}
            extra_attributes.setdefault("workerAllocationMode", "static")
            logger.warn("workerAllocationMode was automatically set to 'static' because explicitAckMode is enabled")

        access_key = access_key if access_key else environ.get("V3IO_ACCESS_KEY")
        if not access_key:
            raise ValueError(
                "access_key must be set (via argument or environ V3IO_ACCESS_KEY)"
            )
        struct["password"] = access_key

        super(V3IOStreamTrigger, self).__init__(struct)
        self._add_extra_attrs(extra_attributes)

    @property
    def get_url(self):
        return self._struct["url"]
