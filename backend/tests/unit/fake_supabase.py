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
    GET    /storage/v1/bucket/{bucket}                bucket info, with its "public" flag
    GET    /storage/v1/object/sign/{bucket}/{path}?token=...   the signed URL itself: no
                                                      Authorization header, valid until it expires

Time comes from `now` (default: the real clock), so a test can move it forward instead of
waiting for a signed URL to expire.

Like the real API it reports a missing object as HTTP 400 with {"statusCode": "404"}, which
is why the backend treats that as "not found" too.
"""
import json
import time
from email import message_from_bytes
from email.policy import default as email_policy
from typing import NamedTuple

import httpx

URL = "https://project.supabase.co"
BUCKET = "resumes"
# The new-style secret key (not a JWT) and the legacy service_role key (a JWT).
SERVICE_KEY = "sb_secret_0123456789-DO-NOT-LEAK"
JWT_SERVICE_KEY = "eyJhbGciOiJIUzI1NiJ9.service-role-0123456789-DO-NOT-LEAK.signature"


class Call(NamedTuple):
    method: str
    path: str
    headers: dict
    body: object        # parsed JSON, the multipart file part, or None


class FakeSupabase:
    def __init__(self, bucket: str = BUCKET, service_key: str = SERVICE_KEY, now=time.time):
        self.bucket = bucket
        self.service_key = service_key
        self.now = now
        self.public = False                          # the bucket's public flag
        self.objects: dict[str, bytes] = {}
        self.calls: list[Call] = []
        self.signed: list[tuple[str, int]] = []
        self._tokens: dict[str, tuple[str, float]] = {}      # token -> (key, expires_at)
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

    def _download_signed(self, request: httpx.Request, path: str) -> httpx.Response:
        self.calls.append(Call("GET", path, {k.lower(): v for k, v in request.headers.items()}, None))
        bucket, key = path[len("/storage/v1/object/sign/"):].split("/", 1)
        token = request.url.params.get("token")
        entry = self._tokens.get(token or "")
        if entry is None or entry[0] != key or bucket != self.bucket:
            return self._json(400, {"statusCode": "400", "error": "InvalidJWT", "message": "Invalid token"})
        if self.now() >= entry[1]:
            return self._json(400, {"statusCode": "400", "error": "InvalidJWT", "message": "exp claim timestamp check failed"})
        if key not in self.objects:
            return self._not_found()
        return httpx.Response(200, content=self.objects[key])

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

        if request.method == "GET" and path.startswith("/storage/v1/object/sign/"):
            return self._download_signed(request, path)

        if self.fail_with is not None:
            return self._json(self.fail_with, {"statusCode": str(self.fail_with), "error": "boom", "message": "Internal"})
        if self.service_key not in (headers.get("apikey"), (headers.get("authorization") or "").removeprefix("Bearer ")):
            return self._json(401, {"statusCode": "401", "error": "Unauthorized", "message": "Invalid token"})

        if request.method == "GET" and path == f"/storage/v1/bucket/{self.bucket}":
            return self._json(200, {"id": self.bucket, "name": self.bucket, "public": self.public})

        prefix = "/storage/v1/object/"
        assert path.startswith(prefix), path
        rest = path[len(prefix):]

        if rest.startswith("public/"):                   # a private bucket has no public URLs
            _, bucket, key = rest.split("/", 2)
            if self.public and bucket == self.bucket and key in self.objects:
                return httpx.Response(200, content=self.objects[key])
            return self._not_found()

        if request.method == "POST" and rest.startswith("sign/"):
            _, bucket, key = rest.split("/", 2)
            if bucket != self.bucket or key not in self.objects:
                return self._not_found()
            self.signed.append((key, int(body["expiresIn"])))
            token = f"tok-{len(self.signed)}"
            self._tokens[token] = (key, self.now() + int(body["expiresIn"]))
            return self._json(200, {"signedURL": f"/object/sign/{bucket}/{key}?token={token}"})

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
