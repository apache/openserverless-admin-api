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

import logging
import os
import openserverless.common.validation as validation
import openserverless.common.response_builder as res_builder
from openserverless.common.kube_api_client import KubeApiClient


class UserValidation:

    def __init__(self, environ=os.environ):
        self._environ = environ
        self._kube_client = KubeApiClient()

    def validate(self, namespace):
        """
        Action to be invoked to validate the username. It checks that it respects nuvolaris rules and
        that there is no user on current nuvolaris setup with that namespace assigned.
        """

        try:
            if not validation.is_valid_username(namespace):
                return res_builder.build_error_message(
                    message=f"Account namespace {namespace} is not valid. ",
                    status_code=400,
                )

            # check that there is no wsk user already existing with the same namespace
            existing_whisk_user = self._kube_client.get_whisk_user(namespace)

            if existing_whisk_user:
                return res_builder.build_error_message(
                    message=f"Namespace {namespace} already exists on domain.",
                    status_code=409,
                )

            return res_builder.build_response_message(
                f"Username {namespace} is valid and available"
            )
        except Exception as ex:
            logging.error(ex)

        return res_builder.build_response_message(
            "Un-expected error detected attempting to setup you free account. If problem persists please get in touch with us info@nuvolaris.io"
        )
