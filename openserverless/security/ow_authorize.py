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


def ow_authorize(pass_user_data=False, kwargs_field_name="ow-auth-user"):
    """
    Decorator to be applied when a rest API endpoints must be validated against
    an OpenServerless OpenWhisk namespace credentials.
    param: pass_user_data, set to true to pass the authenticated nuvolaris
           namespace subject details into the wrapper function into the **kwargs
           dictionary
    param: kwargs_field_name, pass here the custom element name for the subject
           details into the kwargs dictionary.
    """

    def decorator(func, **kwargs):

        @wraps(func)
        def decorated(*args, **kwargs):
            logging.info("**** ow_authorize start ****")
            if "authorization" not in request.headers:
                return res_builder.build_error_message(
                    "No valid authorization headers found", 401
                )

            logging.info(args)

            ow_auth = OpenwhiskAuthorize()
            try:
                user_data = ow_auth.login(request.headers.get("authorization"))

                if not user_data:
                    return res_builder.build_error_message(
                        f"Invalid authorization header. Access denied.", 401
                    )

                if pass_user_data:
                    kwargs[kwargs_field_name] = user_data

                return func(*args, **kwargs)
            except Exception as ex:
                return res_builder.build_error_message(
                    f"Could not validate authorization headers. Reason {ex}", 401
                )

        return decorated

    return decorator
