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
import openserverless.common.response_builder as res_builder

from functools import wraps
from openserverless.common.openwhisk_authorize import OpenwhiskAuthorize
from flask import request


def validate_ow_auth(ow_subject="whisk-system"):
    """
    Decorator to be applied when a rest API endpoints must be validated against the
    OpenServerless OpenWhisk whisk_system namespace using the Authorization headers, or anyway it is known in advance
    what OW authorization must be checked.
    """

    def decorator(func, **kwargs):

        @wraps(func)
        def decorated(*args, **kwargs):
            logging.info("**** validate_ow_auth start ****")
            if "authorization" not in request.headers:
                return res_builder.build_error_message(
                    "No valid authorization headers found", 401
                )

            ow_auth = OpenwhiskAuthorize()
            try:
                subject = ow_auth.subject_login(request.headers.get("authorization"))
                if ow_subject not in subject["subject"]:
                    return res_builder.build_error_message(
                        f"Invalid authorization for subject {ow_subject}. Access denied.",
                        401,
                    )

                return func(*args, **kwargs)
            except Exception as ex:
                return res_builder.build_error_message(
                    f"Could not validate authorization headers. Reason {ex}", 401
                )

        return decorated

    return decorator
