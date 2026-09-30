"""Virus scanning with ClamAV (optional).

Set CLAMAV_HOST (and CLAMAV_PORT) to a running clamd (e.g. the `clamav/clamav` Docker
image). Files are streamed to it with the INSTREAM command after upload; infected files
are deleted and marked "rejected". Without CLAMAV_HOST files are not scanned.

Honest note: ClamAV needs about 1-1.5 GB of RAM for its signatures. On a small server,
run it only when your product accepts files from people you don't know.
"""

import socket
import struct
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings


class ScannerUnavailableError(Exception):
    """clamd could not be reached or answered with an error (try again later)."""


@dataclass(frozen=True)
class ScanResult:
    """Clean, or the name of what was found."""

    clean: bool
    signature: str | None = None


class VirusScanner(Protocol):
    """Scans a stream of bytes (tests use a fake)."""

    def scan(self, chunks: Iterable[bytes]) -> ScanResult:
        """Scan everything in `chunks`."""
        ...


class ClamdScanner:
    """Talks the clamd INSTREAM protocol over TCP."""

    def __init__(self, host: str, port: int = 3310, timeout: float = 60.0) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout

    def scan(self, chunks: Iterable[bytes]) -> ScanResult:
        """Send the data in pieces, then read clamd's verdict."""
        try:
            with socket.create_connection((self._host, self._port), timeout=self._timeout) as conn:
                conn.sendall(b"zINSTREAM\0")
                for chunk in chunks:
                    for start in range(0, len(chunk), 64 * 1024):
                        part = chunk[start : start + 64 * 1024]
                        conn.sendall(struct.pack(">I", len(part)) + part)
                conn.sendall(struct.pack(">I", 0))
                reply = b""
                while not reply.endswith(b"\0"):
                    data = conn.recv(4096)
                    if not data:
                        break
                    reply += data
        except OSError as exc:
            raise ScannerUnavailableError(f"clamd not reachable: {exc}") from exc
        return parse_reply(reply.rstrip(b"\0").decode("utf-8", "replace"))


def parse_reply(text: str) -> ScanResult:
    """ "stream: OK" -> clean. "stream: Eicar-Signature FOUND" -> infected."""
    text = text.strip()
    if text.endswith(" OK"):
        return ScanResult(clean=True)
    if text.endswith(" FOUND"):
        name = text.removeprefix("stream:").removesuffix(" FOUND").strip()
        return ScanResult(clean=False, signature=name[:100] or "unknown")
    # "INSTREAM size limit exceeded. ERROR" and similar: clamd could not decide.
    raise ScannerUnavailableError(f"clamd error: {text[:200]}")


def scanner_for(settings: Settings) -> VirusScanner | None:
    """The configured scanner, or None (files are not scanned)."""
    if not settings.clamav_host:
        return None
    return ClamdScanner(settings.clamav_host, settings.clamav_port)
