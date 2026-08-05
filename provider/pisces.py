import base64
import hashlib
import json
import threading
import time

import requests
import urllib3
from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# One session per process, so calls to the same host reuse the TCP/TLS connection.
_http = requests.Session()

# Tokens are cached per credential set until just before the JWT's own expiry;
# without this cache every single tool call hit /login.
_TOKEN_TTL_FALLBACK = 600  # seconds, when the token carries no readable exp claim
_TOKEN_EXPIRY_SKEW = 60  # re-login this long before the token actually expires
_token_cache: dict[str, tuple[str, float]] = {}
# Logins are serialized so a cold cache produces one login, not a stampede. Warm reads
# never take the lock, so a slow /login only blocks threads that must log in too.
_token_lock = threading.Lock()


class PiscesError(Exception):
    """A Pisces API call could not be completed — the login was refused, or the
    request never reached the server."""


def _cache_key(base_url: str, username: str, password: str) -> str:
    """Cache key for one credential set — hashed so no password sits in a dict key."""
    return hashlib.sha256("\0".join([base_url, username, password]).encode()).hexdigest()


def _expires_at(token: str) -> float:
    """When `token` expires, from its own exp claim. The payload is decoded but never
    verified — the server validates it; anything unreadable falls back to a short TTL."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)  # restore the stripped base64 padding
        exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        if exp:
            return float(exp)
    except Exception:
        pass
    return time.time() + _TOKEN_TTL_FALLBACK


def error_message(resp: requests.Response) -> str:
    """The most specific message the server gave for a failed response."""
    try:
        body = resp.json() if resp.content else {}
    except ValueError:
        return resp.text
    return body.get("error_message") or body.get("error") or resp.text


def _login(base_url: str, username: str, password: str) -> str:
    """Log in to Pisces and return a fresh access_token. Raises PiscesError on failure."""
    try:
        resp = _http.post(
            f"{base_url}/login",
            json={"username": username, "password": password},
            timeout=10,
            verify=False,
        )
    except requests.exceptions.RequestException as e:
        raise PiscesError(str(e))

    if not resp.ok:
        raise PiscesError(f"Login failed ({resp.status_code}): {error_message(resp)}")

    token = resp.json().get("access_token")
    if not token:
        raise PiscesError(
            f"Login succeeded but no access_token was returned. Response: {resp.text}"
        )
    return token


def get_token(base_url: str, username: str, password: str, force_refresh: bool = False) -> str:
    """A valid access_token for these credentials, reusing the cached one when it still
    has life left. Pass force_refresh after the server has rejected a cached token."""
    key = _cache_key(base_url, username, password)

    def usable(entry) -> bool:
        return bool(entry) and entry[1] - _TOKEN_EXPIRY_SKEW > time.time()

    cached = _token_cache.get(key)
    if not force_refresh and usable(cached):
        return cached[0]

    with _token_lock:
        # Another thread may have logged in while we waited for the lock.
        cached = _token_cache.get(key)
        if not force_refresh and usable(cached):
            return cached[0]
        token = _login(base_url, username, password)
        _token_cache[key] = (token, _expires_at(token))
        return token


def pisces_request(method: str, path: str, credentials: dict, **kwargs) -> requests.Response:
    """Call the Pisces API at `path` (e.g. "/iocs") with a cached bearer token. A 401 means
    the token was rejected early; a rejected request never ran, so replaying it once is safe."""
    base_url = (credentials.get("base_url") or "").rstrip("/")
    username = credentials.get("username", "")
    password = credentials.get("password", "")
    url = f"{base_url}{path}"

    kwargs.setdefault("timeout", 30)
    kwargs.setdefault("verify", False)

    def send(token: str) -> requests.Response:
        try:
            return _http.request(
                method, url, headers={"Authorization": f"Bearer {token}"}, **kwargs
            )
        except requests.exceptions.RequestException as e:
            raise PiscesError(str(e))

    resp = send(get_token(base_url, username, password))
    if resp.status_code != 401:
        return resp
    return send(get_token(base_url, username, password, force_refresh=True))


class PiscesProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict) -> None:
        base_url = (credentials.get("base_url") or "").rstrip("/")
        username = credentials.get("username", "")
        password = credentials.get("password", "")

        if not base_url:
            raise ToolProviderCredentialValidationError("API Base URL is required.")
        if not username:
            raise ToolProviderCredentialValidationError("Username is required.")
        if not password:
            raise ToolProviderCredentialValidationError("Password is required.")

        # A real login, which also primes the cache.
        try:
            get_token(base_url, username, password, force_refresh=True)
        except PiscesError as e:
            raise ToolProviderCredentialValidationError(str(e)) from e
