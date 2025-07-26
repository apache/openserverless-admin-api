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
import re


def is_valid_username(username):
    """
    Verifies the given username follows nuvolaris rule
    """
    pat = re.compile(r"^[a-z0-9]{5,60}(?:[a-z0-9])?$")
    if re.fullmatch(pat, username):
        return True
    else:
        return False


def is_empty_arg(args, arg_name):
    """
    Takes in input actions args parameter, and verify that it contains the given argument and that it non empty
    param: args
    param: arg_name
    return: True if the argument is not contained in the input args array or if it is an empty string value
    """

    if arg_name not in args:
        return True

    # bool returns False for empty string, True otherwise
    return not bool(args[arg_name])
