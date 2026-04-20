import logging
from fastapi.testclient import TestClient

from app.main import create_app


def test_request_logging_middleware(caplog):
    """Test that the middleware logs method, path, status code, and response time."""
    app = create_app()
    client = TestClient(app)

    # Set log level to INFO to capture our logs
    caplog.set_level(logging.INFO, logger="verdictlens")

    # Make a request to a non-existent path to trigger middleware logging
    response = client.get("/nonexistent")
    # Expect 404 from FastAPI's default handling
    assert response.status_code == 404

    # Verify that a log line was produced for this request
    log_found = False
    for record in caplog.records:
        if record.levelno == logging.INFO and "GET" in record.message and "/nonexistent" in record.message:
            log_found = True
            # Check that status code is present
            assert "404" in record.message
            # Check that response time is present and is a number followed by 'ms'
            parts = record.message.split()
            for part in parts:
                if part.endswith("ms"):
                    # Extract numeric part and ensure it's a float
                    try:
                        float(part[:-2])
                    except ValueError:
                        raise AssertionError(f"Response time not a number: {part}")
                    break
            else:
                raise AssertionError(f"No response time found in log message: {record.message}")
            break
    assert log_found, f"Expected log line not found. Captured logs:\n{caplog.text}"


def test_request_logging_middleware_on_existing_endpoint(caplog):
    """Test middleware logs on an existing endpoint if any."""
    app = create_app()
    client = TestClient(app)

    caplog.set_level(logging.INFO, logger="verdictlens")

    # Try to hit the root path; if it doesn't exist, we still get middleware log
    response = client.get("/")
    # We don't care about the status code for this test; middleware should log anyway
    # But we'll assert it's a valid HTTP status
    assert 100 <= response.status_code < 600

    # Find log line for this request
    for record in caplog.records:
        if record.levelno == logging.INFO and "GET" in record.message:
            # Check that the path is logged (could be "/" or something else)
            assert '"GET /' in record.message or "GET /" in record.message
            assert str(response.status_code) in record.message
            # Check response time format
            parts = record.message.split()
            for part in parts:
                if part.endswith("ms"):
                    try:
                        float(part[:-2])
                    except ValueError:
                        raise AssertionError(f"Response time not a number: {part}")
                    break
            else:
                raise AssertionError(f"No response time found in log message: {record.message}")
            return
    raise AssertionError(f"No GET log line found. Captured logs:\n{caplog.text}")