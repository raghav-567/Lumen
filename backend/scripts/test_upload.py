"""Test upload script — creates 3 test documents and triggers the full pipeline."""

import time
import json
import os
import sys
import tempfile

import requests

BASE = os.getenv("API_URL", "http://localhost:8000/api/v1")

DOCS = [
    ("Doc1 Baseline.txt",
     "The company policy mandates 2 days in office per week. Remote work is allowed 3 days. "
     "All employees must follow the standard working hours from 9 AM to 5 PM. "
     "Supervised learning involves training a model on labeled data, where each input has a corresponding output."),
    ("Doc2 Partial.txt",
     "The company policy mandates 2 days in office, but IT can work remote 100%. "
     "Standard working hours are 9 AM to 5 PM with flexible options for senior staff. "
     "Supervised learning requires labeled datasets to function properly."),
    ("Doc3 Heavy.txt",
     "The company policy mandates 5 days in office. Remote work is strictly prohibited. "
     "Working hours are from 7 AM to 7 PM with no exceptions. "
     "Unsupervised learning works with unlabeled data to identify patterns."),
]


def main():
    # Register / login
    try:
        resp = requests.post(f"{BASE}/auth/register", json={
            "email": "test@example.com",
            "password": "testpassword123",
            "full_name": "Test User",
            "org_name": "Test Org",
        })
        if resp.status_code == 400:
            resp = requests.post(f"{BASE}/auth/login", json={
                "email": "test@example.com",
                "password": "testpassword123",
            })
        token = resp.json()["access_token"]
    except Exception as e:
        print(f"Auth failed: {e}")
        sys.exit(1)

    headers = {"Authorization": f"Bearer {token}"}

    # Upload docs
    for filename, content in DOCS:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(content)
            f.flush()
            with open(f.name, "rb") as fh:
                r = requests.post(
                    f"{BASE}/documents/upload",
                    files={"file": (filename, fh, "text/plain")},
                    headers=headers,
                )
        print(f"Uploaded {filename}: {r.status_code}")

    print("Waiting for ingestion tasks to finish...")
    time.sleep(10)

    # Trigger drift scan
    print("Triggering drift scan...")
    r = requests.post(f"{BASE}/drift/scan", headers=headers)
    print(f"Drift scan: {r.status_code}")

    print("Waiting for recalculate drift tasks to finish...")
    time.sleep(10)

    # Get scores
    r = requests.get(f"{BASE}/drift/scores", headers=headers)
    print(f"Scores: {r.status_code} ")
    print(json.dumps(r.json(), indent=2) if r.status_code == 200 else r.text)


if __name__ == "__main__":
    main()
