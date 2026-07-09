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

from openserverless import app

from openserverless.impl.auth.auth_service import AuthService
from openserverless.impl.auth.oidc_device_flow_service import OidcDeviceFlowService
from openserverless.security.ow_authorize import ow_authorize
from flask import request
import openserverless.common.response_builder as res_builder
from flasgger import swag_from
from urllib.parse import urlparse


def _extract_bearer_token():
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()

    body = request.get_json(silent=True) or {}
    return body.get("access_token")


def _requested_namespace_from_origin(origin, api_host):
    if not origin:
        return None

    origin_host = urlparse(origin).hostname
    if not origin_host:
        return None

    api_hostname = (api_host or "").split(":", 1)[0]
    suffix = f".{api_hostname}"
    if origin_host == api_hostname or not origin_host.endswith(suffix):
        return None

    candidate = origin_host[: -len(suffix)]
    if "." in candidate or not candidate:
        return None

    return candidate

@app.route('/system/api/v1/auth/<login>',methods=['PATCH'])
@ow_authorize(pass_user_data=True)
def password(login, **kwargs):
    """
    Update User Password
    ---
    tags:
      - Authentication Api
    summary: Update user password
    description: Update the user password by patching the corresponding WhiskUser entry
    operationId: updateUserPassword
    security:
        - openwhiskBasicAuth: []
    consumes:
        - application/json
    parameters:
    - in: path
      name: login
      description: The username requiring the password update
      required: true
      type: string
    - in: body
      name: PasswordUpdate
      description: Password update payload containing current and new password
      required: true
      schema:
        $ref: '#/definitions/LoginUpdateData'
    responses:
      200:
        description: Password updated successfully
        schema:
          $ref: '#/definitions/MessageData'
      400:
        description: Bad request. Missing required fields.
        schema:
          $ref: '#/definitions/Message'
      401:
        description: Unauthorized. Invalid credentials or authorization token.
        schema:
          $ref: '#/definitions/Message'
    """     
    update_data = request.get_json()

    if 'ow-auth-user' in kwargs:
        authorized_data = kwargs['ow-auth-user']
        if login not in authorized_data['login']:
            return res_builder.build_error_message(f"invalid AUTH token for user {login}", 401)

    auth_service = AuthService()
    return auth_service.update_password(login,update_data['password'],update_data['new_password'])

@app.route('/system/api/v1/auth',methods=['POST'])
def login():
    """
    User Authentication
    ---
    tags:
      - Authentication Api
    summary: Authenticate user with login credentials
    description: Perform user authentication using credentials stored in CouchDB metadata
    operationId: authenticateUser
    consumes:
        - application/json
    parameters:
    - in: body
      name: LoginCredentials
      description: User login credentials
      required: true
      schema:
        $ref: '#/definitions/LoginData'
    responses:
      200:
        description: Authentication successful. Returns user data including environment variables and quota.
        schema:
          $ref: '#/definitions/MessageData'
      400:
        description: Bad request. Missing login or password.
        schema:
          $ref: '#/definitions/Message'
      401:
        description: Unauthorized. Invalid credentials.
        schema:
          $ref: '#/definitions/Message'
    """    
    login_data = request.get_json()
    auth_service = AuthService()
    return auth_service.login(login_data['login'], login_data['password'])

@app.route('/system/api/v1/auth/oidc',methods=['POST'])
def login_oidc():
    """
    User Authentication with OIDC
    ---
    tags:
      - Authentication Api
    summary: Authenticate user with an OIDC access token
    description: Validate a Keycloak OIDC token and map it to an existing OpenServerless namespace.
    operationId: authenticateUserOidc
    consumes:
        - application/json
    parameters:
    - in: header
      name: Authorization
      description: Bearer token issued by the configured OIDC provider
      required: false
      type: string
    - in: body
      name: OidcCredentials
      description: Optional JSON payload containing access_token when Authorization header is not used
      required: false
      schema:
        type: object
        properties:
          access_token:
            type: string
    responses:
      200:
        description: Authentication successful. Returns OpenServerless user data.
        schema:
          $ref: '#/definitions/MessageData'
      401:
        description: Unauthorized. Invalid or missing OIDC token.
        schema:
          $ref: '#/definitions/Message'
      403:
        description: Forbidden. Token is valid but required group is missing.
        schema:
          $ref: '#/definitions/Message'
      404:
        description: OIDC user is valid but no OpenServerless namespace is provisioned.
        schema:
          $ref: '#/definitions/Message'
    """
    auth_service = AuthService()
    return auth_service.login_oidc(_extract_bearer_token())


@app.route('/system/api/v1/auth/oidc/device/start', methods=['POST'])
def start_oidc_device_login():
    """
    Start backend-managed OIDC Device Authorization login
    ---
    tags:
      - Authentication Api
    summary: Start an SSO login flow managed by admin-api
    description: admin-api uses cluster SSO configuration to start OIDC device login and returns only an opaque flow id and user verification data.
    operationId: startOidcDeviceLogin
    responses:
      200:
        description: SSO device login flow started.
        schema:
          type: object
      502:
        description: admin-api could not start login with the configured OIDC provider.
        schema:
          $ref: '#/definitions/Message'
    """
    body = request.get_json(silent=True) or {}
    requested_namespace = body.get("namespace") or _requested_namespace_from_origin(
        request.headers.get("Origin"),
        request.host,
    )
    return OidcDeviceFlowService().start(requested_namespace=requested_namespace)


@app.route('/system/api/v1/auth/oidc/device/poll', methods=['POST'])
def poll_oidc_device_login():
    """
    Poll backend-managed OIDC Device Authorization login
    ---
    tags:
      - Authentication Api
    summary: Poll an SSO login flow managed by admin-api
    description: admin-api exchanges device credentials with the configured OIDC provider, validates the token and returns OpenServerless namespace data. OIDC tokens are not returned to the browser.
    operationId: pollOidcDeviceLogin
    consumes:
        - application/json
    parameters:
    - in: body
      name: OidcDevicePoll
      required: true
      schema:
        type: object
        properties:
          flow_id:
            type: string
    responses:
      200:
        description: Authentication successful. Returns OpenServerless user data.
        schema:
          $ref: '#/definitions/MessageData'
      202:
        description: Login is still pending at the identity provider.
        schema:
          type: object
      400:
        description: Login flow expired.
        schema:
          $ref: '#/definitions/Message'
      401:
        description: SSO login failed.
        schema:
          $ref: '#/definitions/Message'
      404:
        description: Unknown login flow or namespace not provisioned.
        schema:
          $ref: '#/definitions/Message'
    """
    body = request.get_json(silent=True) or {}
    return OidcDeviceFlowService().poll(body.get("flow_id"))
