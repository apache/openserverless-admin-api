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
import requests as req
import json
import os
import logging

from base64 import b64decode
from .validation import is_empty_arg

from openserverless.config.app_config import AppConfig
from openserverless.error.config_exception import ConfigException

SERVICE_HOST_ENV_NAME = "KUBERNETES_SERVICE_HOST"
SERVICE_PORT_ENV_NAME = "KUBERNETES_SERVICE_PORT"
SERVICE_TOKEN_FILENAME = "/var/run/secrets/kubernetes.io/serviceaccount/token"
SERVICE_CERT_FILENAME = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"


def _join_host_port(host, port):
    template = "%s:%s"
    host_requires_bracketing = ":" in host or "%" in host
    if host_requires_bracketing:
        template = "[%s]:%s"
    return template % (host, port)


class KubeApiClient:

    def __init__(self, environ=os.environ):
        self._environ = environ
        self.SERVICE_TOKEN_FILENAME = self._environ.get("KUBERNETES_TOKEN_FILENAME") or SERVICE_TOKEN_FILENAME
        self.SERVICE_CERT_FILENAME = self._environ.get("KUBERNETES_CERT_FILENAME") or SERVICE_CERT_FILENAME
        self._load_incluster_config()

    def _parse_b64(self, encoded_str):
        """
        Decode b64 encoded string
        param: encoded_str a Base64 encoded string
        return: decoded string
        """
        try:
            return b64decode(encoded_str).decode()
        except:
            raise ConfigException("Could not decode base64 encoded value")

    def _load_incluster_config(self):
        """
        Use the service account kubernetes gives to pods to connect to kubernetes
        cluster. It's intended for clients that expect to be running inside a pod
        running on kubernetes. It will raise an exception if called from a process
        not running in a kubernetes environment.
        """
        if (
            SERVICE_HOST_ENV_NAME not in self._environ
            or SERVICE_PORT_ENV_NAME not in self._environ
        ):
            raise ConfigException("Service host/port is not set.")

        self.host = "https://" + _join_host_port(
            self._environ.get(SERVICE_HOST_ENV_NAME),
            self._environ.get(SERVICE_PORT_ENV_NAME),
        )

        self._read_token_file()

        with open(self.SERVICE_CERT_FILENAME) as f:
            if not f.read():
                raise ConfigException("Cert file exists but empty.")

        self.ssl_ca_cert = self.SERVICE_CERT_FILENAME

    def _read_token_file(self):
        with open(self.SERVICE_TOKEN_FILENAME) as f:
            content = f.read()
            if not content:
                raise ConfigException("Token file exists but empty.")
            self.token = "Bearer " + content

    def create_whisk_user(self, whisk_user_dict, namespace="nuvolaris"):
        """ "
        Creates a whisk user using a POST operation
        param: whisk_user_dict a dictionary representing the whisksusers resource to create
        param: namespace default to nuvolaris
        return: True if the operation is successfully, False otherwise
        """
        url = f"{self.host}/apis/nuvolaris.org/v1/namespaces/{namespace}/whisksusers"
        headers = {"Authorization": self.token}

        try:
            logging.info("POST request to %s", url)
            response = None
            response = req.post(
                url,
                headers=headers,
                data=json.dumps(whisk_user_dict),
                verify=self.ssl_ca_cert,
            )

            if response.status_code in [200, 201, 202]:
                logging.debug(
                    "POST to %s succeeded with %s. Body %s",
                    url,
                    response.status_code,
                    response.text,
                )
                return True

            logging.error(
                "POST to %s failed with %s. Body %s",
                url,
                response.status_code,
                response.text,
            )
            return False
        except Exception as ex:
            logging.error("create_whisk_user %s", ex)
            return False

    def delete_whisk_user(self, username, namespace="nuvolaris"):
        """ "
        Delete a whisk user using a DELETE operation
        param: username of the whisksusers resource to delete
        param: namespace default to nuvolaris
        return: True if the operation is successfully, False otherwise
        """
        url = f"{self.host}/apis/nuvolaris.org/v1/namespaces/{namespace}/whisksusers/{username}"
        headers = {"Authorization": self.token}

        try:
            logging.info(f"DELETE request to {url}")
            response = None
            response = req.delete(url, headers=headers, verify=self.ssl_ca_cert)

            if response.status_code in [200, 202]:
                logging.debug(
                    f"DELETE to {url} succeeded with {response.status_code}. Body {response.text}"
                )
                return True

            logging.error(
                f"DELETE to {url} failed with {response.status_code}. Body {response.text}"
            )
            return False
        except Exception as ex:
            logging.error(f"delete_whisk_user {ex}")
            return False

    def get_whisk_user(self, username, namespace="nuvolaris"):
        """ "
        Get a whisk user using a GET operation
        param: username of the whisksusers resource to delete
        param: namespace default to nuvolaris
        return: a dictionary representing the existing user, None otherwise
        """
        url = f"{self.host}/apis/nuvolaris.org/v1/namespaces/{namespace}/whisksusers/{username}"
        headers = {"Authorization": self.token}

        try:
            logging.info(f"GET request to {url}")
            response = None
            response = req.get(url, headers=headers, verify=self.ssl_ca_cert)

            if response.status_code in [200, 202]:
                logging.debug(
                    f"GET to {url} succeeded with {response.status_code}. Body {response.text}"
                )
                return json.loads(response.text)

            logging.error(
                f"GET to {url} failed with {response.status_code}. Body {response.text}"
            )
            return None
        except Exception as ex:
            logging.error(f"get_whisk_user {ex}")
            return None

    def update_whisk_user(self, whisk_user_dict, namespace="nuvolaris"):
        """ "
        Updates a whisk user using a PUT operation
        param: whisk_user_dict a dictionary representing the whisksusers resource to update
        param: namespace default to nuvolaris
        return: True if the operation is successfully, False otherwise
        """
        url = f"{self.host}/apis/nuvolaris.org/v1/namespaces/{namespace}/whisksusers/{whisk_user_dict['metadata']['name']}"
        headers = {"Authorization": self.token}

        try:
            logging.error(f"PUT request to {url}")
            response = None
            response = req.put(
                url,
                headers=headers,
                data=json.dumps(whisk_user_dict),
                verify=self.ssl_ca_cert,
            )

            if response.status_code in [200, 201, 202]:
                logging.debug(
                    f"PUT to {url} succeeded with {response.status_code}. Body {response.text}"
                )
                return True

            logging.error(
                f"PUT to {url} failed with {response.status_code}. Body {response.text}"
            )
            return False
        except Exception as ex:
            logging.error(f"update_whisk_user {ex}")
            return False
