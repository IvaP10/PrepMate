import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("ENVIRONMENT", "test")

import learning_engine


class _EvidenceStore:
    def __init__(self):
        self.identities = set()
        self.mastery_writes = 0
        self.evidence_queries = []


class _Cursor:
    def __init__(self, store):
        self.store = store
        self.result = None

    def execute(self, query, params=None):
        if "INSERT INTO SkillEvidenceEvents" in query:
            self.store.evidence_queries.append(query)
            identity = (params[0], params[3], params[7], params[8], params[9])
            if identity in self.store.identities:
                self.result = None
            else:
                self.store.identities.add(identity)
                self.result = (len(self.store.identities),)
            return
        if "INSERT INTO LearnerSkillStates" in query:
            self.store.mastery_writes += 1
            self.result = (params[3], 18, self.store.mastery_writes, datetime.now(timezone.utc))
            return
        raise AssertionError(f"Unexpected persistence query: {query}")

    def fetchone(self):
        return self.result

    def close(self):
        return None


class _Connection:
    def __init__(self, store):
        self.store = store
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _Cursor(self.store)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class EvidenceIdentityTests(unittest.IsolatedAsyncioTestCase):
    def test_evidence_hash_is_canonical(self):
        first = learning_engine._canonical_evidence_hash(72, {"flags": ["vague"], "score": 72})
        reordered = learning_engine._canonical_evidence_hash(72, {"score": 72, "flags": ["vague"]})

        self.assertEqual(first, reordered)
        self.assertEqual(len(first), 64)

    def test_technical_source_id_is_server_derived_and_stable(self):
        evidence = {
            "round_id": "round-1",
            "code_hash": "code-hash",
            "exit_code": 1,
            "output_hash": "output-hash",
        }

        first = learning_engine._server_evidence_source_id(
            source_type="technical_run",
            interview_id="interview-1",
            response_id=None,
            evidence=evidence,
        )
        repeated = learning_engine._server_evidence_source_id(
            source_type="technical_run",
            interview_id="interview-1",
            response_id=None,
            evidence=dict(reversed(list(evidence.items()))),
        )

        self.assertEqual(first, repeated)
        self.assertTrue(first.startswith("round-1:"))

    async def test_replayed_response_advances_mastery_once(self):
        store = _EvidenceStore()
        connection = _Connection(store)
        evidence = {
            "question": "Describe the retry design.",
            "answer_excerpt": "I added bounded retries and idempotency keys.",
            "score": 81,
        }

        with patch.object(learning_engine, "get_db_connection", return_value=connection), patch.object(
            learning_engine,
            "return_db_connection",
            return_value=None,
        ):
            first = await learning_engine._insert_skill_evidence(
                "user-1",
                "interview-1",
                "response-1",
                "technical:reliability",
                "interview_turn",
                81,
                evidence,
            )
            replay = await learning_engine._insert_skill_evidence(
                "user-1",
                "interview-1",
                "response-1",
                "technical:reliability",
                "interview_turn",
                79,
                {**evidence, "score": 79},
            )

        self.assertTrue(first["inserted"])
        self.assertFalse(replay["inserted"])
        self.assertEqual(first["source_id"], "response-1")
        self.assertEqual(store.mastery_writes, 1)
        self.assertEqual(len(store.identities), 1)
        self.assertTrue(all("ON CONFLICT" in query for query in store.evidence_queries))
        self.assertEqual(connection.rollbacks, 0)


if __name__ == "__main__":
    unittest.main()
