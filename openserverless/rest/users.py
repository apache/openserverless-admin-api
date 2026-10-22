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

"""Administrative user provisioning with a separately managed capability."""
import logging

from flask import request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from openserverless import app
from openserverless.common import response_builder
from openserverless.error.config_exception import ConfigException
from openserverless.impl.provisioning.admission import provisioning_authorizer
from openserverless.impl.provisioning.kube_client import ProvisioningError, ProvisioningKubeClient
from openserverless.impl.provisioning.user_service import UserProvisioningService, bearer_token


@app.route("/system/api/v1/users", methods=["POST"])
def create_user():
    """
    Create an OPS tenant (asynchronous provisioning).
    ---
    tags: [User provisioning]
    operationId: createUser
    security:
      - provisioningBearer: []
    consumes: [application/json]
    parameters:
      - in: header
        name: Authorization
        required: true
        type: string
        description: Bearer token from the externally managed provisioning Secret.
      - in: body
        name: user
        required: true
        schema:
          type: object
          additionalProperties: false
          required: [user, password, email]
          properties:
            user: {type: string, minLength: 5, maxLength: 61}
            password: {type: string, format: password}
            email: {type: string, format: email}
            services: {type: string, default: all}
    responses:
      202: {description: "WhiskUser created; provisioning pending, not a readiness guarantee."}
      400: {description: Invalid payload or unavailable requested service.}
      401: {description: Missing or invalid provisioning token.}
      409: {description: User exists or namespace is retained; no update performed.}
      413: {description: Request body exceeds 16 KiB.}
      415: {description: Content-Type must be application/json.}
      503: {description: "Provisioning configuration or Kubernetes dependency unavailable."}
      500: {description: Unexpected internal error.}
    """
    try:
        token = bearer_token(request.headers.get("Authorization"))
        provisioning_authorizer.authorize(token)
        service = UserProvisioningService(ProvisioningKubeClient())
        if not request.is_json:
            raise ProvisioningError("Content-Type must be application/json", 415)
        request.max_content_length = 16384
        body = request.get_json()
        result = service.provision(body)
        return response_builder.build_response_with_data(result, 202)
    except ProvisioningError as exc:
        response = response_builder.build_error_message(str(exc), exc.status)
        if exc.status == 503:
            response.headers["Retry-After"] = "1"
        return response
    except BadRequest:
        return response_builder.build_error_message("Invalid JSON payload", 400)
    except RequestEntityTooLarge:
        return response_builder.build_error_message("Request body exceeds 16 KiB", 413)
    except (ConfigException, OSError):
        return response_builder.build_error_message("Provisioning dependency unavailable", 503)
    except Exception as exc:
        # Exception messages/tracebacks may contain caller data; log only type.
        logging.error("User provisioning failed (%s)", type(exc).__name__)
        return response_builder.build_error_message("User provisioning failed", 500)
