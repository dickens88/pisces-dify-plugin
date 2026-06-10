import requests
import urllib3
from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def get_token(base_url: str, username: str, password: str) -> str:
    """Login to Pisces and return a fresh access_token. Raises on failure."""
    try:
        resp = requests.post(
            f"{base_url}/login",
            json={"username": username, "password": password},
            timeout=10,
            verify=False,
        )
    except requests.exceptions.RequestException as e:
        raise ToolProviderCredentialValidationError(str(e))

    if not resp.ok:
        body = resp.json() if resp.content else {}
        msg = body.get("error_message") or body.get("error") or resp.text
        raise ToolProviderCredentialValidationError(
            f"Login failed ({resp.status_code}): {msg}"
        )

    token = resp.json().get("access_token")
    if not token:
        raise ToolProviderCredentialValidationError(
            f"Login succeeded but no access_token was returned. Response: {resp.text}"
        )
    return token


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

        # Validate by actually logging in
        get_token(base_url, username, password)
