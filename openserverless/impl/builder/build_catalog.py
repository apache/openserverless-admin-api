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

import json
import os
import re


BUILDER_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,62}$")
IMAGE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,511}$")
SUPPORTED_KINDS = {"python", "nodejs", "php", "java", "go", "ruby", "dotnet"}


class BuildCatalogError(ValueError):
    pass


class BuildCatalog:
    """Validated allowlist of images that may be extended by BuildKit."""

    def __init__(self, builders=None, environ=None):
        self.environ = environ if environ is not None else os.environ
        self.builders = self._validate(builders if builders is not None else self._load())

    def _load(self):
        raw = self.environ.get("BUILDER_CATALOG_JSON", "").strip()
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise BuildCatalogError(f"BUILDER_CATALOG_JSON is invalid: {exc.msg}") from exc

        path = self.environ.get(
            "BUILDER_CATALOG_FILE", "/etc/openserverless/builders.json"
        )
        try:
            with open(path, encoding="utf-8") as catalog_file:
                return json.load(catalog_file)
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            raise BuildCatalogError(f"Cannot load builder catalog {path}: {exc}") from exc

    def _validate(self, document):
        if not isinstance(document, dict):
            raise BuildCatalogError("Builder catalog must be a JSON object")
        builders = document.get("builders", document)
        if not isinstance(builders, dict):
            raise BuildCatalogError("Builder catalog 'builders' must be an object")

        validated = {}
        for builder_id, entry in builders.items():
            if not isinstance(builder_id, str) or not BUILDER_ID.fullmatch(builder_id):
                raise BuildCatalogError(f"Invalid builder id: {builder_id!r}")
            if not isinstance(entry, dict):
                raise BuildCatalogError(f"Builder {builder_id} must be an object")
            kind = entry.get("kind")
            source = entry.get("source")
            if kind not in SUPPORTED_KINDS:
                raise BuildCatalogError(f"Builder {builder_id} has unsupported kind {kind!r}")
            if not isinstance(source, str) or not IMAGE_REFERENCE.fullmatch(source):
                raise BuildCatalogError(f"Builder {builder_id} has invalid source image")
            validated[builder_id] = {"kind": kind, "source": source}
        return validated

    def get(self, builder_id):
        try:
            return self.builders[builder_id]
        except KeyError as exc:
            raise BuildCatalogError(f"Unknown builder: {builder_id}") from exc

    def capabilities(self):
        return [
            {"id": builder_id, "kind": entry["kind"]}
            for builder_id, entry in sorted(self.builders.items())
        ]
