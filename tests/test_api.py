from fastapi.testclient import TestClient

from app.main import create_app


def test_full_mock_happy_path_and_report(settings) -> None:
    with TestClient(create_app(settings)) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json() == {
            "status": "ok",
            "mode": "mock",
            "model": "test-model",
            "analysis_provider": "mock",
            "transcription_provider": "mock",
            "airgap_mode": False,
        }

        presets = client.get("/api/v1/presets")
        assert presets.status_code == 200
        assert len(presets.json()) == 4

        quota = client.get("/api/v1/quota")
        assert quota.status_code == 200
        assert quota.json()["rpm_remaining"] == 5
        assert quota.json()["rpd_remaining"] == 20

        response = client.post(
            "/api/v1/analyze",
            json={"text": "Зафиксирован новый вход", "language": "ru"},
        )
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "ok"
        assert result["provider"] == "mock"
        assert result["grounded"] is True

        audit = client.get(f"/api/v1/audit/{result['trace_id']}")
        assert audit.status_code == 200
        assert audit.json()["input_sha256"]
        assert "Зафиксирован новый вход" in audit.json()["masked_excerpt"]

        report = client.get(f"/api/v1/report/{result['trace_id']}")
        assert report.status_code == 200
        assert report.headers["content-type"].startswith("text/markdown")
        assert result["trace_id"] in report.text
        assert "VERIFIED" in report.text

        pdf = client.get(f"/api/v1/export/{result['trace_id']}/pdf")
        assert pdf.status_code == 200
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content.startswith(b"%PDF")


def test_unknown_preset_returns_422(settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/analyze",
            json={"text": "Обычный текст", "preset_id": "missing"},
        )
    assert response.status_code == 422


def test_all_four_presets_complete_offline(settings) -> None:
    with TestClient(create_app(settings)) as client:
        presets = client.get("/api/v1/presets").json()
        outcomes = []
        for preset in presets:
            response = client.post(
                "/api/v1/analyze",
                json={
                    "text": preset["text"],
                    "language": preset["language"],
                    "preset_id": preset["id"],
                },
            )
            assert response.status_code == 200
            outcomes.append(response.json()["status"])

    assert outcomes == ["ok", "ok", "ok", "blocked"]


def test_missing_audit_and_report_return_404(settings) -> None:
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/audit/not-found").status_code == 404
        assert client.get("/api/v1/report/not-found").status_code == 404
