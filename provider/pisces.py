import requests
from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError


def get_token(base_url: str, username: str, password: str) -> str:
    """Login to Pisces and return a fresh access_token. Raises on failure."""
    try:
        resp = requests.post(
            f"{base_url}/login",
            json={"username": username, "password": password},
            timeout=10,
        )
    except requests.exceptions.ConnectionError:
        raise ToolProviderCredentialValidationError(
            f"Cannot connect to Pisces API at {base_url}. Please check the URL."
        )
    except requests.exceptions.Timeout:
        raise ToolProviderCredentialValidationError(
            f"Connection to {base_url} timed out."
        )

    if resp.status_code == 401:
        raise ToolProviderCredentialValidationError(
            "Wrong credentials. Please check your username and password."
        )
    if resp.status_code == 402:
        raise ToolProviderCredentialValidationError(
            "This user does not have permission to access Pisces."
        )
    if not resp.ok:
        raise ToolProviderCredentialValidationError(
            f"Login failed ({resp.status_code}): {resp.text}"
        )

    token = resp.json().get("access_token")
    if not token:
        raise ToolProviderCredentialValidationError(
            "Login succeeded but no access_token was returned."
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
