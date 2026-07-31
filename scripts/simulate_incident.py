"""Trigger a demo incident against a running API.

python scripts/simulate_incident.py deployment-regression
python scripts/simulate_incident.py recover
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

SCENARIOS = ("high-latency", "error-spike", "database-timeout", "deployment-regression", "recover")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=SCENARIOS)
    parser.add_argument("--api-url", default="http://localhost:8000")
    args = parser.parse_args()

    path = "recover" if args.scenario == "recover" else f"incidents/{args.scenario}"
    url = f"{args.api_url}/api/v1/simulator/{path}"

    request = urllib.request.Request(url, method="POST")  # noqa: S310 - local, operator-supplied
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            print(json.dumps(json.loads(response.read()), indent=2))
    except urllib.error.URLError as exc:
        print(f"Could not reach {url}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
