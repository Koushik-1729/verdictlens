# Existing code here...
from fastapi import FastAPI
app = FastAPI()

# New endpoint for health check
@app.get("/health")
def health_check():
    return {"status": "ok"}