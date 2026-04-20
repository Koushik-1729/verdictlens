import logging
from fastapi.testclient import TestClient
from app.main import create_app


def test_request_logging_middleware_get(caplog):
    """Test that GET requests are logged with method, path, status code, and response time."""
    app = create_app()
    client = TestClient(app)
    caplog.set_level(logging.INFO, logger="verdictlens")
    # Use an endpoint that likely does not exist to avoid interference with other logs
    response = client.get("/nonexistent-test-endpoint")
    # Ensure we have at least one log from the middleware
    assert len(caplog.records) >= 1
    # Find the log record for our request (could be multiple due to startup logs)
    found = False
    for record in caplog.records:
        message = record.getMessage()
        if f'method="GET"' in message and 'path="/nonexistent-test-endpoint"' in message:
            found = True
            assert f'status_code={response.status_code}' in message
            assert "response_time_ms=" in message
            break
    assert found, f"No log record found for GET /nonexistent-test-endpoint. Logs: {[r.getMessage() for r in caplog.records]}"


def test_request_logging_middleware_post(caplog):
    """Test that POST requests are logged."""
    app = create_app()
    client = TestClient(app)
    caplog.set_level(logging.INFO, logger="verdictlens")
    response = client.post("/nonexistent-test-endpoint", json={"test": "data"})
    assert len(caplog.records) >= 1
    found = False
    for record in caplog.records:
        message = record.getMessage()
        if f'method="POST"' in message and 'path="/nonexistent-test-endpoint"' in message:
            found = True
            assert f'status_code={response.status_code}' in message
            assert "response_time_ms=" in message
            break
    assert found, f"No log record found for POST /nonexistent-test-endpoint. Logs: {[r.getMessage() for r in caplog.records]}"


def test_request_logging_middleware_with_query_params(caplog):
    """Test that query parameters are not included in the path (only the path)."""
    app = create_app()
    client = TestClient(app)
    caplog.set_level(logging.INFO, logger="verdictlens")
    response = client.get("/items?skip=0&limit=10")
    assert len(caplog.records) >= 1
    found = False
    for record in caplog.records:
        message = record.getMessage()
        if f'method="GET"' in message and 'path="/items"' in message:
            found = True
            assert f'status_code={response.status_code}' in message
            assert "response_time_ms=" in message
            break
    assert found, f"No log record found for GET /items. Logs: {[r.getMessage() for r in caplog.records]}"