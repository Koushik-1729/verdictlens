import logging
import re
from fastapi.testclient import TestClient

from app.main import create_app


def test_middleware_logs_get_request_with_correct_format(caplog):
    """Test that GET requests are logged with method, path, status code, and response time."""
    app = create_app()
    # Add a test GET endpoint that returns 200
    @app.get("/test-get")
    async def test_get():
        return {"message": "ok"}

    client = TestClient(app)
    caplog.set_level(logging.INFO, logger="verdictlens")

    response = client.get("/test-get")
    assert response.status_code == 200
    assert response.json() == {"message": "ok"}

    # Check that exactly one log record was emitted from our logger
    verdictlens_logs = [record for record in caplog.records if record.name == "verdictlens"]
    assert len(verdictlens_logs) == 1
    log_message = verdictlens_logs[0].getMessage()
    # Pattern: METHOD PATH STATUS_CODE RESPONSE_TIMEms
    # Example: GET /test-get 200 12.34ms
    pattern = r"^GET /test-get 200 \d+\.\d{2}ms$"
    assert re.match(pattern, log_message), f"Log message '{log_message}' does not match pattern {pattern}"


def test_middleware_logs_post_request_with_status_code(caplog):
    """Test that POST requests are logged with correct method, path, status code (201), and response time."""
    app = create_app()
    # Add a test POST endpoint that returns 201
    @app.post("/test-post", status_code=201)
    async def test_post():
        return {"created": True}

    client = TestClient(app)
    caplog.set_level(logging.INFO, logger="verdictlens")

    response = client.post("/test-post", json={})
    assert response.status_code == 201
    assert response.json() == {"created": True}

    verdictlens_logs = [record for record in caplog.records if record.name == "verdictlens"]
    assert len(verdictlens_logs) == 1
    log_message = verdictlens_logs[0].getMessage()
    # Should start with POST /test-post 201 and end with something like 12.34ms
    assert log_message.startswith("POST /test-post 201 "), f"Log message '{log_message}' does not start with 'POST /test-post 201 '"
    assert log_message.endswith("ms"), f"Log message '{log_message}' does not end with 'ms'"
    # Extract the numeric part between the status code and 'ms'
    # Format: POST /test-post 201 12.34ms
    try:
        # Remove the prefix and suffix
        middle = log_message[len("POST /test-post 201 "):-2]
        float(middle)  # Should be a float representing milliseconds
    except (ValueError, IndexError) as e:
        raise AssertionError(f"Log message '{log_message}' does not have a valid response time format") from e