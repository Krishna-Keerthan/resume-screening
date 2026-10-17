"""
A fake Supabase Storage server for tests: an httpx.MockTransport that keeps objects in
memory, records every request, and answers the way the real Storage API does for the calls
the backend makes (see https://supabase.com/docs/reference/python/storage-from-upload and
the REST routes the supabase-py client uses):

    POST   /storage/v1/object/{bucket}/{path}         upload, multipart "file" part
    POST   /storage/v1/object/sign/{bucket}/{path}    {"expiresIn": seconds} -> {"signedURL": ...}
    DELETE /storage/v1/object/{bucket}                {"prefixes": [paths]}
    GET    /storage/v1/object/{bucket}/{path}         authenticated download
    GET    /storage/v1/object/public/{bucket}/{path}  refused: the bucket is private

Like the real API it reports a missing object as HTTP 400 with {"statusCode": "404"}, which
is why the backend treats that as "not found" too.
"""
import json
from email import message_from_bytes
from email.policy import default as email_policy
from typing import NamedTuple

import httpx

URL = "https://project.supabase.co"
BUCKET = "resumes"
SERVICE_KEY = "service-role-key-0123456789-DO-NOT-LEAK"


class Call(NamedTuple):
    method: str
    path: str
    headers: dict
    body: object        # parsed JSON, the multipart file part, or None


class FakeSupabase:
    def __init__(self, bucket: str = BUCKET, service_key: str = SERVICE_KEY):
        self.bucket = bucket
        self.service_key = service_key
        self.objects: dict[str, bytes] = {}
        self.calls: list[Call] = []
        self.signed: list[tuple[str, int]] = []
        self.fail_with: int | None = None            # make every request answer this status
        self.transport = httpx.MockTransport(self._handle)

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _json(status: int, payload) -> httpx.Response:
        return httpx.Response(status, json=payload)

    def _not_found(self) -> httpx.Response:
        return self._json(400, {"statusCode": "404", "error": "not_found", "message": "Object not found"})

    @staticmethod
    def _file_part(request: httpx.Request) -> dict:
        raw = b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.content
        message = message_from_bytes(raw, policy=email_policy)
        for part in message.iter_parts():
            if part.get_param("name", header="content-disposition") == "file":
                return {
                    "filename": part.get_filename(),
                    "content_type": part.get_content_type(),
                    "bytes": part.get_payload(decode=True),
                }
        raise AssertionError("no file part in the upload")

    # ── the API ───────────────────────────────────────────────────────────────

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode().split("?")[0]
        headers = {k.lower(): v for k, v in request.headers.items()}
        body = None
        if request.content and headers.get("content-type", "").startswith("application/json"):
            body = json.loads(request.content)
        elif request.content and headers.get("content-type", "").startswith("multipart/"):
            body = self._file_part(request)
        self.calls.append(Call(request.method, path, headers, body))

        if self.fail_with is not None:
            return self._json(self.fail_with, {"statusCode": str(self.fail_with), "error": "boom", "message": "Internal"})
        if headers.get("authorization") != f"Bearer {self.service_key}":
            return self._json(401, {"statusCode": "401", "error": "Unauthorized", "message": "Invalid token"})

        prefix = "/storage/v1/object/"
        assert path.startswith(prefix), path
        rest = path[len(prefix):]

        if rest.startswith("public/"):                   # a private bucket has no public URLs
            return self._not_found()

        if request.method == "POST" and rest.startswith("sign/"):
            _, bucket, key = rest.split("/", 2)
            if bucket != self.bucket or key not in self.objects:
                return self._not_found()
            self.signed.append((key, int(body["expiresIn"])))
            return self._json(200, {"signedURL": f"/object/sign/{bucket}/{key}?token=tok-{len(self.signed)}"})

        if request.method == "DELETE":
            for key in body["prefixes"]:
                self.objects.pop(key, None)
            return self._json(200, [{"name": key} for key in body["prefixes"]])

        bucket, key = rest.split("/", 1)
        if bucket != self.bucket:
            return self._json(400, {"statusCode": "404", "error": "Bucket not found", "message": "Bucket not found"})
        if request.method == "POST":
            if key in self.objects and headers.get("x-upsert") != "true":
                return self._json(400, {"statusCode": "409", "error": "Duplicate", "message": "The resource already exists"})
            self.objects[key] = body["bytes"]
            return self._json(200, {"Key": f"{bucket}/{key}", "Id": "object-id"})
        if request.method == "GET":
            if key not in self.objects:
                return self._not_found()
            return httpx.Response(200, content=self.objects[key])
        raise AssertionError(f"unexpected call {request.method} {path}")
