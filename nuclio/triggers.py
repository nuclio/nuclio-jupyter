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
        extra_attributes=None,
    ):
        super(KafkaTrigger, self).__init__(
            {
                "kind": self.kind,
                "maxWorkers": 1,
                "attributes": {
                    "topics": topics,
                    "brokers": brokers,
                    "consumerGroup": consumer_group,
                    "initialOffset": initial_offset,
                    "sessionTimeout": "10s",
                    "heartbeatInterval": "3s",
                    "workerAllocationMode": "pool",
                    "fetchDefault": 1048576,
                },
            }
        )
        partitions = partitions or []
        if partitions:
            self._struct["attributes"]["partitions"] = partitions
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
        seekTo: str = "latest",
        partitions: list = None,
        pollingIntervalMS: int = 500,
        readBatchSize: int = 64,
        maxWorkers: int = 1,
        access_key: str = None,
        sessionTimeout: str = "10s",
        name: str = None,
        container: str = None,
        path: str = None,
        workerAllocationMode: str = "pool",
        webapi: str = Constants.default_webapi_address,
        consumerGroup: str = "default",
        sequenceNumCommitInterval: str = "1s",
        heartbeatInterval: str = "3s",
        extra_attributes=None,
    ):
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
                "attributes": {
                    "containerName": container,
                    "streamPath": path,
                    "consumerGroup": consumerGroup,
                    "sequenceNumberCommitInterval": sequenceNumCommitInterval,
                    "workerAllocationMode": workerAllocationMode,
                    "sessionTimeout": sessionTimeout,
                    "heartbeatInterval": heartbeatInterval,
                },
            }

            if name:
                struct["name"] = name

        if maxWorkers:
            struct["maxWorkers"] = maxWorkers
        if seekTo:
            struct["attributes"]["seekTo"] = seekTo
        if readBatchSize:
            struct["attributes"]["readBatchSize"] = readBatchSize
        if partitions:
            struct["attributes"]["partitions"] = partitions
        if pollingIntervalMS:
            struct["attributes"]["pollingIntervalMs"] = pollingIntervalMS
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
