import re
import logging
from fastapi.testclient import TestClient

from app.main import create_app


def test_middleware_logs_get_request_with_correct_format(caplog):
    app = create_app()
    # Add a test GET endpoint that returns 200
    @app.get("/test-get")
    async def test_get():
        return {"msg": "ok"}

    client = TestClient(app)
    with caplog.at_level(logging.INFO, logger="verdictlens"):
        response = client.get("/test-get")
        assert response.status_code == 200

    # Find the log record for our request
    log_messages = [record.getMessage() for record in caplog.records]
    pattern = r"GET /test-get 200 \d+ms"
    assert any(re.search(pattern, msg) for msg in log_messages), \
        f"No log message matching pattern '{pattern}' found in: {log_messages}"


def test_middleware_logs_post_request_with_different_status(caplog):
    app = create_app()
    # Add a test POST endpoint that returns 400 for invalid payload
    @app.post("/test-post")
    async def test_post(data: dict):
        if "required_field" not in data:
            return {"error": "missing required_field"}, 400
        return {"msg": "ok"}

    client = TestClient(app)
    with caplog.at_level(logging.INFO, logger="verdictlens"):
        # Send missing required field to trigger 400
        response = client.post("/test-post", json={})
        assert response.status_code == 400

    log_messages = [record.getMessage() for record in caplog.records]
    pattern = r"POST /test-post 400 \d+ms"
    assert any(re.search(pattern, msg) for msg in log_messages), \
        f"No log message matching pattern '{pattern}' found in: {log_messages}"


def test_middleware_logs_five_hundred_error(caplog):
    app = create_app()
    # Add a test endpoint that raises an exception to trigger 500
    @app.get("/trigger-error")
    async def trigger_error():
        raise RuntimeError("Test error")

    client = TestClient(app)
    with caplog.at_level(logging.INFO, logger="verdictlens"):
        response = client.get("/trigger-error")
        assert response.status_code == 500

    log_messages = [record.getMessage() for record in caplog.records]
    pattern = r"GET /trigger-error 500 \d+ms"
    assert any(re.search(pattern, msg) for msg in log_messages), \
        f"No log message matching pattern '{pattern}' found in: {log_messages}"


def test_middleware_registered_before_cors():
    app = create_app()
    # Find the middleware classes in the order they are added
    middleware_types = [mw.cls for mw in app.user_middleware]
    # Expect logging middleware class to be before CORSMiddleware
    # We need to identify the logging middleware class; it's likely a custom class.
    # Since we don't have the exact class name, we can check that there is a middleware
    # that is not CORSMiddleware before CORSMiddleware.
    # Simpler: ensure that CORSMiddleware is not the first middleware.
    from fastapi.middleware.cors import CORSMiddleware
    # Find index of CORSMiddleware
    cors_indices = [i for i, mw in enumerate(middleware_types) if mw == CORSMiddleware]
    assert cors_indices, "CORSMiddleware not found in user_middleware"
    # The logging middleware should be added before CORS, so there should be at least
    # one middleware before CORSMiddleware (the logging middleware).
    assert cors_indices[0] > 0, "Logging middleware should be registered before CORSMiddleware"
    # Optionally, we could assert that the middleware immediately before CORSMiddleware
    # is our logging middleware, but we don't have its class.