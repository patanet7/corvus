"""Fake Home Assistant REST API server for contract tests.

Serves realistic HA API responses using BaseHTTPRequestHandler.
Runs on a random free port in a background thread for test isolation.

Endpoints:
    GET  /api/states                      → all entity states
    GET  /api/states/{entity_id}          → single entity state (404 if unknown)
    POST /api/services/{domain}/{service} → record service call, return result

Auth: Bearer token required on all endpoints (401 if missing/invalid).
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

FAKE_TOKEN = "test-ha-token-abc123"

SAMPLE_ENTITIES: list[dict[str, Any]] = [
    {
        "entity_id": "light.living_room",
        "state": "on",
        "attributes": {
            "friendly_name": "Living Room Light",
            "brightness": 255,
            "color_mode": "brightness",
            "supported_features": 1,
        },
        "last_changed": "2026-02-27T10:00:00+00:00",
        "last_updated": "2026-02-27T10:00:00+00:00",
    },
    {
        "entity_id": "light.bedroom",
        "state": "off",
        "attributes": {
            "friendly_name": "Bedroom Light",
            "brightness": 0,
            "color_mode": "brightness",
            "supported_features": 1,
        },
        "last_changed": "2026-02-27T09:30:00+00:00",
        "last_updated": "2026-02-27T09:30:00+00:00",
    },
    {
        "entity_id": "switch.kitchen",
        "state": "off",
        "attributes": {
            "friendly_name": "Kitchen Switch",
            "device_class": "outlet",
        },
        "last_changed": "2026-02-27T08:00:00+00:00",
        "last_updated": "2026-02-27T08:00:00+00:00",
    },
    {
        "entity_id": "sensor.outdoor_temp",
        "state": "42.5",
        "attributes": {
            "friendly_name": "Outdoor Temperature",
            "unit_of_measurement": "°F",
            "device_class": "temperature",
            "state_class": "measurement",
        },
        "last_changed": "2026-02-27T10:05:00+00:00",
        "last_updated": "2026-02-27T10:05:00+00:00",
    },
    {
        "entity_id": "sensor.humidity",
        "state": "65",
        "attributes": {
            "friendly_name": "Indoor Humidity",
            "unit_of_measurement": "%",
            "device_class": "humidity",
            "state_class": "measurement",
        },
        "last_changed": "2026-02-27T10:05:00+00:00",
        "last_updated": "2026-02-27T10:05:00+00:00",
    },
    {
        "entity_id": "climate.thermostat",
        "state": "heat",
        "attributes": {
            "friendly_name": "Thermostat",
            "temperature": 72,
            "current_temperature": 69.5,
            "hvac_action": "heating",
            "hvac_modes": ["off", "heat", "cool", "auto"],
        },
        "last_changed": "2026-02-27T09:00:00+00:00",
        "last_updated": "2026-02-27T09:00:00+00:00",
    },
]

# Index by entity_id for fast lookup
_ENTITY_MAP: dict[str, dict[str, Any]] = {e["entity_id"]: e for e in SAMPLE_ENTITIES}


class FakeHAHandler(BaseHTTPRequestHandler):
    """Handler serving fake Home Assistant REST API responses."""

    # Class-level list to record service calls across requests
    service_calls: list[dict[str, Any]] = []

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Suppress request logging in test output."""

    def _check_auth(self) -> bool:
        """Validate Bearer token. Returns False and sends 401 if invalid."""
        auth = self.headers.get("Authorization", "")
        if auth != f"Bearer {FAKE_TOKEN}":
            self._send_json(
                {"message": "Unauthorized"},
                status=401,
            )
            return False
        return True

    def _send_json(self, data: Any, status: int = 200) -> None:
        """Send a JSON response."""
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._check_auth():
            return

        # GET /api/states — all entities
        if self.path == "/api/states":
            self._send_json(SAMPLE_ENTITIES)
            return

        # GET /api/states/{entity_id} — single entity
        if self.path.startswith("/api/states/"):
            entity_id = self.path[len("/api/states/") :]
            entity = _ENTITY_MAP.get(entity_id)
            if entity:
                self._send_json(entity)
            else:
                self._send_json(
                    {"message": f"Entity not found: {entity_id}"},
                    status=404,
                )
            return

        self._send_json({"message": "Not found"}, status=404)

    def do_POST(self) -> None:
        if not self._check_auth():
            return

        # POST /api/services/{domain}/{service}
        if self.path.startswith("/api/services/"):
            parts = self.path[len("/api/services/") :].split("/", 1)
            if len(parts) != 2:
                self._send_json(
                    {"message": "Invalid service path"},
                    status=400,
                )
                return

            domain, service = parts

            # Read request body
            content_length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(content_length)) if content_length > 0 else {}

            # Record the service call
            call_record = {
                "domain": domain,
                "service": service,
                "data": body,
            }
            FakeHAHandler.service_calls.append(call_record)

            # Return success response matching HA API format
            result = [{"entity_id": body.get("entity_id", f"{domain}.unknown")}]
            self._send_json(result)
            return

        self._send_json({"message": "Not found"}, status=404)


def start_fake_ha_server() -> tuple[HTTPServer, str]:
    """Start a fake HA API server on a random port.

    Returns:
        Tuple of (server_instance, base_url).
        The server runs in a daemon thread and stops when the test process exits.
    """
    FakeHAHandler.service_calls.clear()

    server = HTTPServer(("127.0.0.1", 0), FakeHAHandler)
    port = server.server_address[1]
    base_url = f"http://127.0.0.1:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    return server, base_url
