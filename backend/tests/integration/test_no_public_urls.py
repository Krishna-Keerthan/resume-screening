"""
Résumés live in a private bucket: no code path returns, builds or even calls a public bucket URL.

The only way to a stored file is a signed URL from an ownership-checked route, which expires.
Checked three ways: the real upload and download routes run end to end on the fake Supabase
server and every request it received is inspected; the application source contains no public-URL
builder; and the backend class has no method that could make one.
"""
import os
import re
from types import SimpleNamespace

import pytest

from app.services import storage_service
from app.services.storage_service import SupabaseStorageBackend
from tests.integration.test_candidates import _pdf
from tests.unit.fake_supabase import BUCKET, SERVICE_KEY, URL, FakeSupabase

_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "app")
_PUBLIC = re.compile(r"object/public|get_public_url|getPublicUrl|public_url|publicUrl", re.I)


@pytest.fixture()
def store(app, monkeypatch, mock_services):
    fake = FakeSupabase()
    monkeypatch.setitem(app.config, "STORAGE_PROVIDER", "supabase")
    monkeypatch.setitem(
        storage_service._BUILDERS, "supabase",
        lambda cfg: SupabaseStorageBackend(URL, SERVICE_KEY, BUCKET, transport=fake.transport),
    )
    mock_services.resume_parser.parse_bytes.return_value = SimpleNamespace(success=False, parse_error="stubbed")
    return fake


def test_upload_then_download_only_ever_touches_authenticated_and_signed_routes(
    client, db, store, candidate_a, headers_for
):
    headers = headers_for(candidate_a)

    uploaded = client.post(f"/api/v1/candidates/{candidate_a.id}/resumes", data=_pdf(),
                           content_type="multipart/form-data", headers=headers)
    assert uploaded.status_code == 201, uploaded.get_json()
    resume_id = uploaded.get_json()["data"]["id"]

    listing = client.get(f"/api/v1/candidates/{candidate_a.id}/resumes", headers=headers)
    detail = client.get(f"/api/v1/resumes/{resume_id}", headers=headers)
    download = client.get(f"/api/v1/resumes/{resume_id}/download", headers=headers)
    assert download.status_code == 200, download.get_json()

    url = download.get_json()["data"]["url"]
    assert url.startswith(f"{URL}/storage/v1/object/sign/{BUCKET}/") and "token=" in url
    assert download.get_json()["data"]["expires_in"] == 300
    assert store.signed and store.signed[0][1] == 300

    # every request the backend made went to an authenticated or signing route
    paths = [call.path for call in store.calls]
    assert paths and not any("/object/public/" in p for p in paths)
    # and no other response hands the client a storage URL
    for response in (uploaded, listing, detail):
        assert URL not in response.get_data(as_text=True)
        assert SERVICE_KEY not in response.get_data(as_text=True)


def test_the_signed_url_comes_only_after_the_ownership_check(
    client, db, store, candidate_a, candidate_b, headers_for
):
    headers = headers_for(candidate_a)
    resume_id = client.post(f"/api/v1/candidates/{candidate_a.id}/resumes", data=_pdf(),
                            content_type="multipart/form-data", headers=headers).get_json()["data"]["id"]
    store.signed.clear()

    other = client.get(f"/api/v1/resumes/{resume_id}/download", headers=headers_for(candidate_b))
    anonymous = client.get(f"/api/v1/resumes/{resume_id}/download")

    assert other.status_code == 403 and anonymous.status_code == 401
    assert store.signed == []                        # nothing was signed for them


def test_the_application_source_contains_no_public_url_builder():
    offenders = []
    for root, _, files in os.walk(_APP):
        for name in files:
            if name.endswith(".py"):
                path = os.path.join(root, name)
                with open(path, encoding="utf-8") as f:
                    for number, line in enumerate(f, 1):
                        if _PUBLIC.search(line):
                            offenders.append(f"{os.path.relpath(path, _APP)}:{number}: {line.strip()}")

    assert offenders == []


def test_the_supabase_backend_has_no_method_that_could_build_a_public_url():
    assert [m for m in dir(SupabaseStorageBackend) if "public" in m.lower()] == []
