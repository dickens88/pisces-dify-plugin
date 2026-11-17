from collections.abc import Mapping
from typing import Any

from dify_plugin.errors.tool import ToolProviderCredentialValidationError
from dify_plugin.interfaces.datasource import DatasourceProvider

from provider.pisces_client import PiscesError, get_token, proxies_for


class PiscesDatasourceProvider(DatasourceProvider):
    def _validate_credentials(self, credentials: Mapping[str, Any]) -> None:
        base_url = (credentials.get("base_url") or "").rstrip("/")
        if not base_url or not credentials.get("username") or not credentials.get("password"):
            raise ToolProviderCredentialValidationError("API Base URL, username and password are required.")
        try:
            get_token(base_url, credentials["username"], credentials["password"], force_refresh=True,
                      proxies=proxies_for(dict(credentials)))
        except PiscesError as e:
            raise ToolProviderCredentialValidationError(str(e)) from e
