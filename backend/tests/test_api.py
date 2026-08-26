from fastapi.testclient import TestClient
from backend.app.main import app

client=TestClient(app)

def test_health():
    response=client.get("/api/health")
    assert response.status_code==200
    assert response.json()["status"]=="ok"

def test_dashboard_requires_login():
    response=client.get("/api/dashboard")
    assert response.status_code==401

def test_login_rejects_invalid_credentials():
    response=client.post("/api/auth/login",json={"username":"missing-user","password":"Invalid12345"})
    assert response.status_code==401
