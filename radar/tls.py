import os
import ssl
import urllib.request


def _candidate_ca_files():
    seen = set()
    for path in (
        os.environ.get("SSL_CERT_FILE"),
        "/etc/ssl/cert.pem",
        "/private/etc/ssl/cert.pem",
        "/opt/homebrew/etc/ca-certificates/cert.pem",
        "/usr/local/etc/ca-certificates/cert.pem",
        "/opt/homebrew/etc/openssl@3/cert.pem",
        "/usr/local/etc/openssl@3/cert.pem",
    ):
        if path and path not in seen:
            seen.add(path)
            yield path


def ssl_context():
    """Return a verified TLS context, preferring explicit/macOS CA bundles.

    Some third-party Python builds on macOS ship with an OpenSSL runtime whose
    default CA path is empty or stale. We never disable verification; instead we
    select an available trusted CA bundle explicitly and fall back to Python's
    verified default context.
    """
    for path in _candidate_ca_files():
        if os.path.isfile(path):
            try:
                return ssl.create_default_context(cafile=path)
            except (OSError, ssl.SSLError):
                continue
    return ssl.create_default_context()


def urlopen(request, timeout=15):
    return urllib.request.urlopen(request, timeout=timeout, context=ssl_context())
