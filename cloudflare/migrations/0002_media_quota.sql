-- Cloudflare-only media accounting. Reserve before writing KV to enforce the app cap.
CREATE TABLE IF NOT EXISTS media_objects (
    key TEXT PRIMARY KEY,
    size INTEGER NOT NULL CHECK(size >= 0),
    created_at TEXT NOT NULL
);
