"""Create the file storage bucket (if missing) and allow browser uploads from the app.

    make storage-setup

Locally SeaweedFS creates the bucket itself when it starts (S3_BUCKET in
docker-compose.dev.yml), so you don't need this. In production run it once after setting
S3_*: it creates the bucket, sets the CORS rule to APP_URL (needed for direct browser
uploads) and a rule that deletes staged uploads after a day.
"""

from app.core.config import get_settings
from app.services.storage import S3Storage


def main() -> None:
    """Entry point."""
    settings = get_settings()
    if not settings.files_enabled:
        print("S3_ENDPOINT is empty: file uploads are switched off. Nothing to do.")
        return
    origins = sorted({settings.app_url.rstrip("/"), *settings.cors_origins})
    created = S3Storage(settings).ensure_bucket(cors_origins=origins)
    word = "created" if created else "already exists"
    print(
        f"Bucket {settings.s3_bucket!r} {word}. Browser uploads allowed from: {', '.join(origins)}"
    )


if __name__ == "__main__":
    main()
