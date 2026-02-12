from __future__ import annotations

import os

from locust import HttpUser, between, task


class DocaroSmokeUser(HttpUser):
    wait_time = between(0.5, 2.0)

    @task(5)
    def health(self) -> None:
        self.client.get("/health", name="/health")

    @task(1)
    def home(self) -> None:
        self.client.get("/", name="/")


# Example:
# DOCARO_LOAD_HOST=http://127.0.0.1:5001 locust -f loadtests/locustfile.py
if host := os.getenv("DOCARO_LOAD_HOST"):
    DocaroSmokeUser.host = host
