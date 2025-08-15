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
def env_to_dict(user_data, key="env"):
    """
    extract env from user_data and return it as a dict

    Keyword arguments:
    key -- the key to extract the env from

    >>> env_to_dict({"env": [{"key": "VAR1", "value": "value1"}, {"key": "VAR2", "value": "value2"}]})
    {'VAR1': 'value1', 'VAR2': 'value2'}
    >>> env_to_dict({"env": []})
    {}
    >>> env_to_dict({"other_key": [{"key": "VAR1", "value": "value1"}]}, key="other_key")
    {'VAR1': 'value1'}
    >>> env_to_dict({"env": [{"key": "VAR1", "value": "value1"}]}, key="env")
    {'VAR1': 'value1'}
    >>> env_to_dict({"env": [{"key": "VAR1", "value": "value1"}, {"key": "VAR2", "value": "value2"}]}, key="non_existent_key")
    {}
    >>> env_to_dict({"env": [{"key": "VAR1", "value": "value1"}]}, key="env")
    {'VAR1': 'value1'}
    """
    body = {}
    if key in user_data:
        envs = list(user_data[key])
    else:
        envs = []

    for env in envs:
        body[env['key']] = env['value']

    return body


def dict_to_env(env):
    """
    converts an env to a key/pair suitable for user_data storage

    >>> dict_to_env({"VAR1": "value1", "VAR2": "value2"})
    [{'key': 'VAR1', 'value': 'value1'}, {'key': 'VAR2', 'value': 'value2'}]
    >>> dict_to_env({})
    []
    """
    body = []
    for key in env:
        body.append({"key": key, "value": env[key]})

    return body

def join_host_port(host, port):
    """
    Join host and port into a URL format.
    >>> join_host_port("localhost", "8080")
    'localhost:8080'
    >>> join_host_port("localhost", 8080)
    'localhost:8080'
    >>> join_host_port("localhost", "80")
    'localhost:80'
    >>> join_host_port("localhost", "abcd")
    Traceback (most recent call last):
        ...
    ValueError: Port must be numeric

    """
    template = "%s:%s"
    try:
        port_int = int(port)
        port = str(port_int)
    except (ValueError, TypeError):
        raise ValueError("Port must be numeric")
    
    host_requires_bracketing = ":" in host or "%" in host
    if host_requires_bracketing:
        template = "[%s]:%s"
    return template % (host, port)