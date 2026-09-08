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
from openserverless.security.ow_authorize import ow_authorize
from flask import request
import openserverless.common.response_builder as res_builder
from flasgger import swag_from

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
    