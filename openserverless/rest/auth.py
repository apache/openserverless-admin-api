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
    Update the user password patching the corresponding wsku/<login> entry.
    ---
    tags: 
      - Authentication Api
    summary: Login an OpenServerless user using login/password payload
    operationId: patchOpsUser
    security:
        - openwhiskBasicAuth: []
    consumes:
        - application/json
    definitions:
      LoginUpdateData:
        type: object
        properties:
          password:
            type: string
          new_password:
            type: string
        required:
        - password
        - new_password
      MessageData:
        type: object
        properties:
          message:
            type: object
          status: 
            type: string
      Message:
        type: object
        properties:
          message:
            type: string
          status: 
            type: string
    parameters:
    - in: path
      name: login
      description: The username requiring the password update.
      required: true
      schema:
       type: string   
    - in: body
      name: User
      description: the password update payload.
      required: true
      schema:
        $ref: '#/definitions/LoginUpdateData'                                         
    responses:
      200:
        description: Logged in User data
        schema:
          $ref: '#/definitions/MessageData'
      401:
        description: Access denied due to wrong credentials.
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
    Perform the user Authentication relying on wsku metadata stored into internal CouchDB.
    ---
    tags: 
      - Authentication Api
    summary: Login an OpenServerless user using login/password payload
    operationId: loginOpsUser
    consumes:
        - application/json
    parameters:
    - in: body
      name: User
      description: The user to login.
      required: true
      schema:
        $ref: '#/definitions/LoginData'                                         
    responses:
      200:
        description: Logged in User data
        schema:
          $ref: '#/definitions/MessageData'
      401:
        description: Access denied due to wrong credentials.
        schema:
          $ref: '#/definitions/Message'         
    """    
    login_data = request.get_json()
    auth_service = AuthService()
    return auth_service.login(login_data['login'], login_data['password'])
    