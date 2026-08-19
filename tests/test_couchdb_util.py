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
import json
import unittest
from unittest.mock import Mock, patch

from openserverless.couchdb.couchdb_util import CouchDB

ENVIRON = {
    "COUCHDB_SERVICE_HOST": "couchdb.test",
    "COUCHDB_SERVICE_PORT": "5984",
    "COUCHDB_ADMIN_USER": "admin",
    "COUCHDB_ADMIN_PASSWORD": "pw",
}


def fake_response(status_code, body=None):
    return Mock(status_code=status_code, text=json.dumps(body) if body is not None else "")


class CouchDBTestCase(unittest.TestCase):

    def setUp(self):
        session_patcher = patch("openserverless.couchdb.couchdb_util.req.Session")
        self.mock_session_class = session_patcher.start()
        self.addCleanup(session_patcher.stop)
        self.mock_session = self.mock_session_class.return_value

        self.db = CouchDB(environ=ENVIRON)


class CheckCreateDeleteDbTest(CouchDBTestCase):

    def test_check_db_true_when_head_returns_200(self):
        self.mock_session.head.return_value = fake_response(200)

        self.assertTrue(self.db.check_db("subjects"))
        self.mock_session.head.assert_called_once_with(
            "http://couchdb.test:5984/nuvolaris_subjects"
        )

    def test_check_db_false_when_not_found(self):
        self.mock_session.head.return_value = fake_response(404)

        self.assertFalse(self.db.check_db("subjects"))

    def test_create_db_true_on_201(self):
        self.mock_session.put.return_value = fake_response(201)

        self.assertTrue(self.db.create_db("subjects"))
        self.mock_session.put.assert_called_once_with(
            "http://couchdb.test:5984/nuvolaris_subjects"
        )

    def test_create_db_false_on_other_status(self):
        self.mock_session.put.return_value = fake_response(412)

        self.assertFalse(self.db.create_db("subjects"))

    def test_delete_db_true_on_200(self):
        self.mock_session.delete.return_value = fake_response(200)

        self.assertTrue(self.db.delete_db("subjects"))

    def test_delete_db_false_on_other_status(self):
        self.mock_session.delete.return_value = fake_response(404)

        self.assertFalse(self.db.delete_db("subjects"))


class RecreateDbTest(CouchDBTestCase):

    def test_recreate_false_and_missing_creates_db(self):
        self.mock_session.head.return_value = fake_response(404)
        self.mock_session.put.return_value = fake_response(201)

        msg = self.db.recreate_db("subjects", recreate=False)

        self.assertIn("created", msg)
        self.assertNotIn("deleted", msg)
        self.mock_session.delete.assert_not_called()
        self.mock_session.put.assert_called_once()

    def test_recreate_false_and_existing_does_nothing(self):
        self.mock_session.head.return_value = fake_response(200)

        msg = self.db.recreate_db("subjects", recreate=False)

        self.assertNotIn("created", msg)
        self.assertNotIn("deleted", msg)
        self.mock_session.delete.assert_not_called()
        self.mock_session.put.assert_not_called()

    def test_recreate_true_and_existing_deletes_then_creates(self):
        self.mock_session.head.return_value = fake_response(200)
        self.mock_session.delete.return_value = fake_response(200)
        self.mock_session.put.return_value = fake_response(201)

        msg = self.db.recreate_db("subjects", recreate=True)

        self.assertIn("deleted", msg)
        self.assertIn("created", msg)
        self.mock_session.delete.assert_called_once()
        self.mock_session.put.assert_called_once()

    def test_recreate_true_and_missing_only_creates(self):
        self.mock_session.head.return_value = fake_response(404)
        self.mock_session.put.return_value = fake_response(201)

        msg = self.db.recreate_db("subjects", recreate=True)

        self.assertNotIn("deleted", msg)
        self.assertIn("created", msg)
        self.mock_session.delete.assert_not_called()


class GetDocTest(CouchDBTestCase):

    def test_returns_doc_on_200(self):
        self.mock_session.get.return_value = fake_response(200, {"_id": "abc", "_rev": "1-x"})

        doc = self.db.get_doc("subjects", "abc")

        self.assertEqual({"_id": "abc", "_rev": "1-x"}, doc)
        self.mock_session.get.assert_called_once_with(
            "http://couchdb.test:5984/nuvolaris_subjects/abc"
        )

    def test_returns_none_on_404(self):
        self.mock_session.get.return_value = fake_response(404)

        self.assertIsNone(self.db.get_doc("subjects", "missing"))

    def test_uses_default_auth_by_default(self):
        self.mock_session.get.return_value = fake_response(200, {"_id": "abc"})

        self.db.get_doc("subjects", "abc")

        self.assertEqual(self.db.db_auth, self.mock_session.auth)

    def test_uses_custom_auth_when_user_provided(self):
        self.mock_session.get.return_value = fake_response(200, {"_id": "abc"})

        self.db.get_doc("subjects", "abc", user="bob", password="secret")

        self.assertNotEqual(self.db.db_auth, self.mock_session.auth)
        self.assertEqual("bob", self.mock_session.auth.username)

    def test_uses_no_auth_when_requested(self):
        self.mock_session.get.return_value = fake_response(200, {"_id": "abc"})

        self.db.get_doc("subjects", "abc", no_auth=True)

        self.assertIsNone(self.mock_session.auth)


class UpdateDocTest(CouchDBTestCase):

    def test_returns_false_without_id(self):
        result = self.db.update_doc("subjects", {"name": "no-id"})

        self.assertFalse(result)
        self.mock_session.put.assert_not_called()
        self.mock_session.get.assert_not_called()

    def test_merges_existing_rev_before_put(self):
        self.mock_session.get.return_value = fake_response(200, {"_id": "abc", "_rev": "1-x"})
        self.mock_session.put.return_value = fake_response(201)

        doc = {"_id": "abc", "name": "updated"}
        result = self.db.update_doc("subjects", doc)

        self.assertTrue(result)
        self.assertEqual("1-x", doc["_rev"])
        put_kwargs = self.mock_session.put.call_args.kwargs
        self.assertEqual(doc, put_kwargs["json"])

    def test_put_happens_even_when_doc_does_not_exist_yet(self):
        self.mock_session.get.return_value = fake_response(404)
        self.mock_session.put.return_value = fake_response(201)

        result = self.db.update_doc("subjects", {"_id": "new-doc"})

        self.assertTrue(result)
        self.mock_session.put.assert_called_once()

    def test_returns_false_on_unexpected_status(self):
        self.mock_session.get.return_value = fake_response(404)
        self.mock_session.put.return_value = fake_response(500)

        self.assertFalse(self.db.update_doc("subjects", {"_id": "new-doc"}))


class DeleteDocTest(CouchDBTestCase):

    def test_deletes_doc_with_rev(self):
        self.mock_session.get.return_value = fake_response(200, {"_id": "abc", "_rev": "1-x"})
        self.mock_session.delete.return_value = fake_response(200)

        result = self.db.delete_doc("subjects", "abc")

        self.assertTrue(result)
        self.mock_session.delete.assert_called_once_with(
            "http://couchdb.test:5984/nuvolaris_subjects/abc?rev=1-x"
        )

    def test_returns_false_when_doc_not_found(self):
        self.mock_session.get.return_value = fake_response(404)

        result = self.db.delete_doc("subjects", "missing")

        self.assertFalse(result)
        self.mock_session.delete.assert_not_called()


class AdminOperationsTest(CouchDBTestCase):

    def test_configure_single_node_true_on_201(self):
        self.mock_session.post.return_value = fake_response(201)

        self.assertTrue(self.db.configure_single_node())

    def test_configure_single_node_false_otherwise(self):
        self.mock_session.post.return_value = fake_response(500)

        self.assertFalse(self.db.configure_single_node())

    def test_configure_no_reduce_limit_true_on_200(self):
        self.mock_session.put.return_value = fake_response(200)

        self.assertTrue(self.db.configure_no_reduce_limit())

    def test_configure_no_reduce_limit_false_otherwise(self):
        self.mock_session.put.return_value = fake_response(500)

        self.assertFalse(self.db.configure_no_reduce_limit())

    def test_add_user_true_on_expected_statuses(self):
        for status in (200, 201, 421):
            with self.subTest(status=status):
                self.mock_session.put.return_value = fake_response(status)
                self.assertTrue(self.db.add_user("bob", "pw"))

    def test_add_user_false_on_unexpected_status(self):
        self.mock_session.put.return_value = fake_response(500)

        self.assertFalse(self.db.add_user("bob", "pw"))

    def test_add_role_true_on_expected_statuses(self):
        self.mock_session.put.return_value = fake_response(200)

        self.assertTrue(self.db.add_role("subjects", members=["bob"], admins=["alice"]))

    def test_add_role_false_on_unexpected_status(self):
        self.mock_session.put.return_value = fake_response(500)

        self.assertFalse(self.db.add_role("subjects"))


class FindDocTest(CouchDBTestCase):

    def test_returns_result_on_200(self):
        self.mock_session.post.return_value = fake_response(200, {"docs": [{"_id": "abc"}]})

        result = self.db.find_doc("subjects", '{"selector": {}}')

        self.assertEqual({"docs": [{"_id": "abc"}]}, result)
        self.mock_session.post.assert_called_once_with(
            "http://couchdb.test:5984/nuvolaris_subjects/_find",
            headers={"Content-Type": "application/json"},
            data='{"selector": {}}',
        )

    def test_returns_none_on_error_status(self):
        self.mock_session.post.return_value = fake_response(400, {"error": "bad_request"})

        self.assertIsNone(self.db.find_doc("subjects", '{"selector": {}}'))


class WaitDbReadyTest(CouchDBTestCase):

    def test_returns_false_immediately_when_max_seconds_is_zero(self):
        self.assertFalse(self.db.wait_db_ready(0))
        self.mock_session.get.assert_not_called()

    def test_returns_true_on_first_successful_check(self):
        self.mock_session.get.return_value = fake_response(200)

        self.assertTrue(self.db.wait_db_ready(5))
        self.mock_session.get.assert_called_once_with(
            "http://couchdb.test:5984/_utils", timeout=5
        )


if __name__ == "__main__":
    unittest.main()
