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
import datetime
import json
import os
import logging
import openserverless.common.response_builder as res_builder
import openserverless.couchdb.bcrypt_util as bu

from openserverless.couchdb.couchdb_util import CouchDB
from openserverless.common.kube_api_client import KubeApiClient

USER_META_DBN = "users_metadata"


class AuthService:

    def __init__(self, environ=os.environ):
        self._environ = environ
        self.couch_db = CouchDB()
        self.kube_client = KubeApiClient()

    def fetch_user_data(self, login: str):
        logging.info(f"searching for user {login} data")
        try:
            selector = {"selector": {"login": {"$eq": login}}}
            response = self.couch_db.find_doc(USER_META_DBN, json.dumps(selector))

            if response["docs"]:
                docs = list(response["docs"])
                if len(docs) > 0:
                    return docs[0]

            logging.warning(f"OpenServerless metadata for user {login} not found!")
            return None
        except Exception as e:
            logging.error(
                f"failed to query OpenServerless metadata for user {login}. Reason: {e}"
            )
            return None
    
    def env_to_dict(self, user_data, key="env"):
        """
        extract env from user_data and return it as a dict

        Keyword arguments:
        key -- the key to extract the env from
        """
        body = {}
        if key in user_data:
            envs = list(user_data[key])
        else:
            envs = []

        for env in envs:
            body[env['key']] = env['value']

        return body

    def map_data(self, user_data):
        """
        Map the internal nuvolaris user_data records to the auth response
        """
        resp = {}
        resp["login"] = user_data["login"]
        resp["email"] = user_data["email"]

        if "env" in user_data:
            resp["env"] = user_data["env"]

        if "quota" in user_data:
            resp["quota"] = user_data["quota"]

        return resp

    def login(self, login, password):
        user_data = self.fetch_user_data(login)

        if user_data:
            if bu.verify_password(password, user_data["password"]):
                # if(password == user_data['password']):
                return res_builder.build_response_with_data(self.map_data(user_data))
            else:
                logging.warning(f"password mismatch for user {login}")
                return res_builder.build_error_message(f"Invalid credentials", 401)
        else:
            logging.warning(f"no user {login} found")
            return res_builder.build_error_message(f"Invalid credentials", 401)
    
    
    def update_password(self, login, old_password, new_password):
        user_data = self.fetch_user_data(login)

        if user_data:
            if bu.verify_password(old_password, user_data["password"]):
                whisk_user = self.kube_client.get_whisk_user(user_data["login"])

                whisk_user["spec"]["password"] = new_password
                # whisk_user['spec']['password_timestamp'] = datetime.now().isoformat()
                self.kube_client.update_whisk_user(whisk_user)

                return res_builder.build_response_with_data(
                    {"status": "ok", "message": "Password updated"}
                )
            else:
                return res_builder.build_error_message(
                    f"password mismatch for user {login}", 401
                )
        else:
            return res_builder.build_error_message(f"no user {login} found", 401)
