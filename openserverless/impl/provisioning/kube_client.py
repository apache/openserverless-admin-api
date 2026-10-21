# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#

"""Bounded Kubernetes operations for provisioning; never log response bodies."""
import requests

from openserverless.common.kube_api_client import KubeApiClient


class ProvisioningError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


class ProvisioningKubeClient(KubeApiClient):
    NAMESPACE = "openserverless"
    USERS = "/apis/openserverless.org/v1/namespaces/openserverless/whisksusers"
    INGRESS = "/apis/networking.k8s.io/v1/namespaces/openserverless/ingresses"
    MIDDLEWARE = "/apis/traefik.io/v1alpha1/namespaces/openserverless/middlewares"
    CORE = "/api/v1/namespaces/openserverless"

    def _request(self, method, path, body=None, missing_ok=False):
        try:
            response = requests.request(
                method, self.host + path,
                headers={"Authorization": self.token}, json=body,
                verify=self.ssl_ca_cert, timeout=(5, 20),
            )
        except requests.RequestException:
            raise ProvisioningError("Provisioning dependency unavailable") from None
        if response.status_code == 404 and missing_ok:
            return None
        if method == "POST" and response.status_code == 409:
            raise ProvisioningError("Resource already exists", 409)
        if response.status_code not in (200, 201, 202):
            raise ProvisioningError("Provisioning dependency unavailable")
        try:
            result = response.json()
        except ValueError:
            raise ProvisioningError("Invalid provisioning dependency response") from None
        if not isinstance(result, dict):
            raise ProvisioningError("Invalid provisioning dependency response")
        return result

    def provisioning_secret(self):
        return self._request("GET", self.CORE + "/secrets/openserverless-user-provisioning-token", missing_ok=True)

    def cluster(self):
        return self._request("GET", "/apis/openserverless.org/v1/namespaces/openserverless/whisks/controller")

    def apihost_ingress(self):
        return self._request("GET", self.INGRESS + "/apihost")

    def streamer_service(self):
        return self._request("GET", self.CORE + "/services/openserverless-streamer-api", missing_ok=True)

    def existing_user(self, name):
        return self._request("GET", self.USERS + "/" + name, missing_ok=True)

    def create_user(self, body):
        return self._request("POST", self.USERS, body)

    def create_route(self, body):
        path = self.MIDDLEWARE if body["kind"] == "Middleware" else self.INGRESS
        return self._request("POST", path, body)
