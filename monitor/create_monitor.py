import argparse
import json
import os
import sys
from typing import Optional, Dict, Any, List

import httpx
from monitor.manage_monitor_db import register_monitor


PARALLEL_API_BASE = "https://api.parallel.ai/v1alpha"


def create_monitor(
    api_key: str,
    query: str,
    cadence: str,
    webhook_url: str,
    event_types: List[str],
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create a Parallel Monitor (offline / one-time setup).

    Docs: https://docs.parallel.ai/monitor-api/monitor-quickstart
    """
    url = f"{PARALLEL_API_BASE}/monitors"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
    }

    payload: Dict[str, Any] = {
        "query": query,
        "cadence": cadence,
        "webhook": {
            "url": webhook_url,
            "event_types": event_types,
        },
    }
    if metadata:
        payload["metadata"] = metadata

    resp = httpx.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def main():
    parser = argparse.ArgumentParser(description="Create a Parallel Monitor (offline setup).")
    parser.add_argument(
        "--username",
        required=True,
        help="Username owning this monitor (will be placed into webhook metadata)",
    )
    parser.add_argument("--query", required=True, help="Natural language monitor query")
    parser.add_argument(
        "--cadence",
        required=True,
        choices=["hourly", "daily", "weekly"],
        help="Monitor cadence",
    )
    parser.add_argument("--webhook_url", required=True, help="Webhook URL to receive monitor events")
    parser.add_argument(
        "--event_types",
        default="monitor.event.detected",
        help="Comma-separated event types (default: monitor.event.detected)",
    )
    parser.add_argument(
        "--metadata_json",
        default=None,
        help='Optional metadata as JSON string, e.g. \'{"key":"value","env":"prod"}\'',
    )
    parser.add_argument(
        "--api_key_env",
        default="PARALLEL_API_KEY",
        help="Env var name containing Parallel API key (default: PARALLEL_API_KEY)",
    )

    args = parser.parse_args()

    api_key = os.getenv(args.api_key_env)
    if not api_key:
        raise SystemExit(f"Missing API key env var: {args.api_key_env}")

    metadata = json.loads(args.metadata_json) if args.metadata_json else None
    metadata = metadata or {}
    # Ensure webhook payload echoes username so the server can store events per user.
    metadata["username"] = args.username
    event_types = [s.strip() for s in args.event_types.split(",") if s.strip()]

    created = create_monitor(
        api_key=api_key,
        query=args.query,
        cadence=args.cadence,
        webhook_url=args.webhook_url,
        event_types=event_types,
        metadata=metadata,
    )
    
    # Register the monitor_id -> username mapping so webhooks can look up username
    monitor_id = created.get("monitor_id")
    if monitor_id:
        registered = register_monitor(args.username, monitor_id)
        if registered:
            print(f"Registered monitor {monitor_id} for user {args.username}", file=sys.stderr)
        else:
            print(f"Warning: Could not register monitor {monitor_id} (may already be registered)", file=sys.stderr)
    else:
        print("Warning: No monitor_id in response, cannot register monitor", file=sys.stderr)
    
    print(json.dumps(created, indent=2))


if __name__ == "__main__":
    main()

