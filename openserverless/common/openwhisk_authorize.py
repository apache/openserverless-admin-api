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
from base64 import b64decode, b64encode
from urllib.parse import quote, unquote
from openserverless.couchdb.couchdb_util import CouchDB
from openserverless.error.api_error import EncodeError, DecodeError, AuthorizationError

import json
import os
import logging

USER_META_DBN = "users_metadata"
SUBJECT_META_DBN = "subjects"


class OpenwhiskAuthorize:

    def __init__(self, environ=os.environ):
        self._db = CouchDB()
        self._environ = environ

    def encode(self, username, password):
        """Returns an HTTP basic authentication encrypted string given a valid
        username and password.
        """
        if ":" in username:
            raise EncodeError

        username_password = f"{quote(username)}:{quote(password)}"
        return f"Basic {b64encode(username_password.encode()).decode()}"

    def _parse_b64(self, encoded_str):
        """
        Parse a base64 encoded string and return the username and password.
        If the string is not base64 encoded, it will try to split it by ':'.
        Raises DecodeError if the string cannot be decoded or parsed.
        >>> oa = OpenwhiskAuthorize()
        >>> oa._parse_b64("dXNlcm5hbWU6cGFzc3dvcmQ=")
        ('username', 'password')
        >>> oa._parse_b64("username:password")
        ('username', 'password')
        >>> oa._parse_b64("invalid_base64_string")
        Traceback (most recent call last):
            ...
        openserverless.error.api_error.DecodeError: authentication token does not seems to be b64 encoded
        """
        username = None
        password = None
        try:
            decoded = b64decode(encoded_str)

            credentials = decoded.decode()
            if credentials.count(":") != 1:
                raise DecodeError("authentication token does not seems to be b64 encoded")
            username, password = credentials.split(":", 1)
        except:
            # fallback in case the token is not bas64 encoded
            if encoded_str.count(":") == 1:
                username, password = encoded_str.split(":", 1)

        if not username or not password:
            raise DecodeError("authentication token does not seems to be b64 encoded")

        return username, password

    def decode(self, encoded_str):
        """Decode an encrypted HTTP basic authentication string. Returns a tuple of
        the form (username, password), and raises a DecodeError exception if
        nothing could be decoded.
        >>> oa = OpenwhiskAuthorize()
        >>> oa.decode("Basic dXNlcm5hbWU6cGFzc3dvcmQ=")
        ('username', 'password')
        >>> oa.decode("dXNlcm5hbWU6cGFzc3dvcmQ=")
        ('username', 'password')
        >>> oa.decode("invalid_base64_string")
        Traceback (most recent call last):
            ...
        openserverless.error.api_error.DecodeError: authentication token does not seems to be b64 encoded
        """
        split = encoded_str.strip().split(" ")

        # If split is only one element, try to decode the username and password
        # directly.
        if len(split) == 1:
            username, password = self._parse_b64(split[0])

        # If there are only two elements, check the first and ensure it says
        # 'basic' so that we know we're about to decode the right thing. If not,
        # bail out.
        elif len(split) == 2:
            if split[0].strip().lower() == "basic":
                username, password = self._parse_b64(split[1])
            else:
                raise DecodeError(
                    "authentication token provides more than 2 elements. could not parse properly"
                )

        # If there are more than 2 elements, something crazy must be happening.
        # Bail.
        else:
            raise DecodeError("unpredictable error parsing authentication token")

        return unquote(username), unquote(password)

    def fetch_subject(self, uuid: str, key: str):
        """
        Query the internal couchdb searching for the subject matching the given uuid, key.
        Normally these stored in wsk or wsku in the form uuid:key
        :param uuid the OW subject uuid
        :param key the OW subject key
        :return a ubject document
        """
        logging.info(f"searching for openwhisk subject {uuid}")
        try:
            selector = {
                "selector": {"namespaces": {"$elemMatch": {"uuid": uuid, "key": key}}}
            }

            response = self._db.find_doc(SUBJECT_META_DBN, json.dumps(selector))

            if response["docs"]:
                docs = list(response["docs"])
                if len(docs) > 0:
                    logging.debug(
                        f"OpenServerless namespace for user {uuid} found. Returning Result."
                    )
                    return docs[0]

            logging.warning(f"OpenServerless metadata for user {uuid} not found!")
            return None
        except Exception as e:
            logging.error(
                f"failed to query OpenServerless metadata for user {uuid}. Reason: {e}"
            )
            return None

    def fetch_user_data(self, username: str):
        """
        Query the internal couchdb searching for the given principal to retrieve all the
        relevant metadata
        """
        logging.info(f"searching for user {username} meta-data")
        try:
            selector = {"selector": {"login": {"$eq": username}}}
            response = self._db.find_doc(USER_META_DBN, json.dumps(selector))

            if response["docs"]:
                docs = list(response["docs"])
                if len(docs) > 0:
                    logging.debug(
                        f"OpenServerless metadata for user {username} found. Returning Result."
                    )
                    return docs[0]

            logging.warning(f"OpenServerless metadata for user {username} not found!")
            return None
        except Exception as e:
            logging.error(
                f"failed to query OpenServerless metadata for user {username}. Reason: {e}"
            )
            return None

    def login(self, authorization: str):
        """
        Attempt to login the user identified by the given Openwhisk authorization AUTH token as base64
        param: authorization a base64 encoded OpenWhisk AUTH entries
        """
        uuid, key = self.decode(authorization)
        subject = self.fetch_subject(uuid, key)

        if not subject:
            raise AuthorizationError("Openwhisk subject not found.")

        user_data = self.fetch_user_data(subject["subject"])

        if user_data:
            return user_data

        raise AuthorizationError("Could not retrieve user metadata.")

    def subject_login(self, authorization: str):
        """
        Attempt to login the user identified by the given Openwhisk authorization AUTH token as base64
        param: authorization a base64 encoded OpenWhisk AUTH entries
        return: the subject entry
        """
        uuid, key = self.decode(authorization)
        subject = self.fetch_subject(uuid, key)

        if not subject:
            raise AuthorizationError("Openwhisk subject not found.")

        return subject
