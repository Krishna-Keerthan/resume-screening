# Stack

Every dependency has exactly one job (CLAUDE.md, Dependency policy). One row per technology:
its single job, where it is used, what it overlaps with, and the verdict. Adding a
dependency needs its row here first.

The full inventory of the existing dependencies is a Phase 4b task. Until then this file
lists the dependencies changed since Phase 3 began.

| Technology | Single job | Used in | Overlaps with | Verdict |
|---|---|---|---|---|
| `httpx` 0.28.1 | Synchronous HTTP client. Groq's SDK already uses it; the Supabase Storage backend calls the Storage REST API through it. | `app/services/storage_service.py` (Supabase backend); `groq` (indirectly) | `requests` (installed only because `huggingface-hub` needs it) and the `urllib` calls in the old Cloudinary download. Neither is used by app code for HTTP any more. | **Keep.** Declared as a direct dependency in `requirements.in` at the version the lock already held, so nothing new is installed. |
| `supabase` / `storage3` client libraries | Would wrap the same REST calls. | not used | `httpx` | **Not added.** Compared with REST-via-`httpx`: `supabase` adds 13 packages and about +4 to +6 MB RSS, `storage3` adds 8 packages and about +2 to +5 MB, `httpx` adds none. The instance has about 9 MB of headroom on 512 MB. |
| `cloudinary` 1.46.3 | Résumé file storage (authenticated raw uploads, signed URLs). | `app/services/storage_service.py` | Supabase Storage (replaces it) | **Remove.** Replaced by Supabase Storage in the same change. |
