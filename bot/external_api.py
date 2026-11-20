"""External API client with retries and error handling."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from bot.config import settings
from bot.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class APIResponse:
    """Standardized API response."""

    success: bool
    data: Any = None
    error: Optional[str] = None
    status_code: Optional[int] = None


class ExternalAPIError(Exception):
    """Custom exception for API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class ExternalAPIClient:
    """Async HTTP client for external API with retries."""

    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None
        self._base_url = settings.external_api_base_url.rstrip("/")
        self._api_key = settings.external_api_key
        self._timeout = aiohttp.ClientTimeout(total=settings.external_api_timeout)

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            headers = {}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            headers["User-Agent"] = "TelegramBot/1.0"
            self._session = aiohttp.ClientSession(
                timeout=self._timeout,
                headers=headers,
            )
        return self._session

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    @retry(
        wait=wait_exponential_jitter(initial=1, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError, ExternalAPIError)),
        reraise=True,
    )
    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[dict] = None,
        json_data: Optional[dict] = None,
    ) -> APIResponse:
        """Make HTTP request with retries."""
        session = await self._get_session()
        url = f"{self._base_url}{endpoint}"

        try:
            async with session.request(method, url, params=params, json=json_data) as response:
                response_text = await response.text()
                logger.debug(
                    "api_request",
                    method=method,
                    url=url,
                    status=response.status,
                )

                if response.status >= 400:
                    raise ExternalAPIError(
                        f"API error: {response_text}",
                        status_code=response.status,
                    )

                try:
                    data = await response.json()
                except aiohttp.ContentTypeError:
                    data = response_text

                return APIResponse(
                    success=True,
                    data=data,
                    status_code=response.status,
                )

        except asyncio.TimeoutError:
            logger.warning("api_timeout", method=method, url=url)
            raise ExternalAPIError("Request timeout")
        except aiohttp.ClientError as e:
            logger.warning("api_client_error", method=method, url=url, error=str(e))
            raise ExternalAPIError(f"Client error: {e}")

    async def get(self, endpoint: str, params: Optional[dict] = None) -> APIResponse:
        """GET request."""
        return await self._request("GET", endpoint, params=params)

    async def post(self, endpoint: str, json_data: dict) -> APIResponse:
        """POST request."""
        return await self._request("POST", endpoint, json_data=json_data)

    async def put(self, endpoint: str, json_data: dict) -> APIResponse:
        """PUT request."""
        return await self._request("PUT", endpoint, json_data=json_data)

    async def delete(self, endpoint: str) -> APIResponse:
        """DELETE request."""
        return await self._request("DELETE", endpoint)

    # Example API methods - customize for your actual API
    async def get_user_info(self, user_id: int) -> APIResponse:
        """Example: Get user info from external API."""
        return await self.get(f"/users/{user_id}")

    async def create_record(self, data: dict) -> APIResponse:
        """Example: Create a record via external API."""
        return await self.post("/records", data)

    async def health_check(self) -> APIResponse:
        """Check API health."""
        return await self.get("/health")


# Global client instance
_api_client: Optional[ExternalAPIClient] = None


def get_api_client() -> ExternalAPIClient:
    """Get or create the global API client."""
    global _api_client
    if _api_client is None:
        _api_client = ExternalAPIClient()
    return _api_client


async def close_api_client() -> None:
    """Close the global API client."""
    global _api_client
    if _api_client:
        await _api_client.close()
        _api_client = None