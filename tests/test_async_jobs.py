import unittest

from app.services.async_jobs import AsyncJobStore


class TestAsyncJobStore(unittest.TestCase):
    def test_create_and_get_job_with_mock_backend(self):
        store = AsyncJobStore(
            redis_url="redis://127.0.0.1:6379/0",
            ttl_seconds=60,
            use_mock=True,
        )

        job_id = store.create()
        payload = store.get(job_id)

        self.assertIsNotNone(payload)
        self.assertEqual(payload["job_id"], job_id)
        self.assertEqual(payload["status"], "queued")
        self.assertIsNone(payload["result"])
        self.assertIsNone(payload["error"])

    def test_update_status_writes_result_and_error(self):
        store = AsyncJobStore(
            redis_url="redis://127.0.0.1:6379/0",
            ttl_seconds=60,
            use_mock=True,
        )

        job_id = store.create()
        ok = store.update_status(
            job_id,
            "succeeded",
            result={"raw_response": "RAW"},
            error=None,
        )

        self.assertTrue(ok)
        payload = store.get(job_id)
        self.assertEqual(payload["status"], "succeeded")
        self.assertEqual(payload["result"]["raw_response"], "RAW")

    def test_update_status_missing_job_returns_false(self):
        store = AsyncJobStore(
            redis_url="redis://127.0.0.1:6379/0",
            ttl_seconds=60,
            use_mock=True,
        )

        ok = store.update_status("does-not-exist", "failed", error={"code": "x"})
        self.assertFalse(ok)

    def test_mock_backend_is_shared_across_instances(self):
        first = AsyncJobStore(
            redis_url="redis://127.0.0.1:6379/9",
            ttl_seconds=60,
            use_mock=True,
        )
        second = AsyncJobStore(
            redis_url="redis://127.0.0.1:6379/9",
            ttl_seconds=60,
            use_mock=True,
        )

        job_id = first.create()
        payload = second.get(job_id)

        self.assertIsNotNone(payload)
        self.assertEqual(payload["job_id"], job_id)


if __name__ == "__main__":
    unittest.main()
