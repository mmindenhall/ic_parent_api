"""Test InfiniteCampusApiClient cookies support."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager

import pytest

from ic_parent_api.ic_api_client import InfiniteCampusApiClient
from ic_parent_api.errors.ic_error import InfiniteCampusError


def test_client_stores_cookies_on_init():
    """InfiniteCampus with cookies={'a':'b'} stores cookies on its client."""
    client = InfiniteCampusApiClient(
        base_url="http://localhost",
        username="user",
        secret="pass",
        district="dist",
        cookies={"a": "b"}
    )
    assert client._cookies == {"a": "b"}


def test_get_request_with_cookies_skips_authenticate(monkeypatch):
    """With cookies, _get_request does NOT call authenticate."""
    client = InfiniteCampusApiClient(
        base_url="http://localhost",
        username="user",
        secret="pass",
        district="dist",
        cookies={"a": "b"}
    )

    # Mock authenticate to raise if called
    authenticate_mock = AsyncMock(side_effect=AssertionError("authenticate should not be called"))
    monkeypatch.setattr(client, "authenticate", authenticate_mock)

    # Mock aiohttp.ClientSession
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.text = AsyncMock(return_value='{"result": "ok"}')
    mock_response.json = AsyncMock(return_value={"result": "ok"})

    @asynccontextmanager
    async def mock_get(*args, **kwargs):
        yield mock_response

    @asynccontextmanager
    async def mock_session(*args, **kwargs):
        session = MagicMock()
        session.get = mock_get
        yield session

    with patch("ic_parent_api.ic_api_client.aiohttp.ClientSession", new=mock_session):
        result = asyncio.run(client._get_request("/campus/api/test"))

    # Verify authenticate was not called
    authenticate_mock.assert_not_called()
    # Verify the response was returned
    assert result == {"result": "ok"}


def test_get_request_with_cookies_uses_cookies_in_session(monkeypatch):
    """ClientSession is constructed with the stored cookies."""
    client = InfiniteCampusApiClient(
        base_url="http://localhost",
        username="user",
        secret="pass",
        district="dist",
        cookies={"a": "b"}
    )

    # Track the cookies passed to ClientSession
    session_cookies = []

    @asynccontextmanager
    async def mock_session(*args, **kwargs):
        session_cookies.append(kwargs.get("cookies"))
        session = MagicMock()

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value='[]')
        mock_response.json = AsyncMock(return_value=[])

        @asynccontextmanager
        async def mock_get(*args, **kwargs):
            yield mock_response

        session.get = mock_get
        yield session

    with patch("ic_parent_api.ic_api_client.aiohttp.ClientSession", new=mock_session):
        asyncio.run(client._get_request("/campus/api/test"))

    # Verify cookies were passed to ClientSession
    assert len(session_cookies) == 1
    assert session_cookies[0] == {"a": "b"}


def test_authenticate_raises_infinite_campus_error_on_saml_login(monkeypatch):
    """authenticate raises InfiniteCampusError with 'SSO' when response contains 'samlLoginThruCampus'."""
    client = InfiniteCampusApiClient(
        base_url="http://localhost",
        username="user",
        secret="pass",
        district="dist"
    )

    # Mock session.post to return SAML login response
    mock_response = MagicMock()
    mock_response.text = AsyncMock(return_value="<form action='samlLoginThruCampus'>...</form>")

    @asynccontextmanager
    async def mock_post(*args, **kwargs):
        yield mock_response

    mock_session = MagicMock()
    mock_session.post = mock_post

    with pytest.raises(InfiniteCampusError) as exc_info:
        asyncio.run(client.authenticate(mock_session))

    # Verify the error message contains 'SSO'
    assert "SSO" in str(exc_info.value.message)


def test_infinite_campus_error_with_exception_text():
    """InfiniteCampusError(400, ValueError('x')) has str-able text and does not raise."""
    exc = InfiniteCampusError(400, ValueError("x"))

    # Should not raise when converting to string
    error_str = str(exc._text)
    assert "ValueError" in error_str or "x" in error_str

    # Verify the properties work
    assert exc.status == 400
    assert len(exc.message) > 0


def test_get_terms_requests_correct_path(monkeypatch):
    """get_terms(1234) requests the path containing 'structureID=1234'."""
    client = InfiniteCampusApiClient(
        base_url="http://localhost",
        username="user",
        secret="pass",
        district="dist",
        cookies={"a": "b"}
    )

    # Track the URL requested
    requested_urls = []

    async def mock_get_request(url):
        requested_urls.append(url)
        return []

    monkeypatch.setattr(client, "_get_request", mock_get_request)

    result = asyncio.run(client.get_terms(1234))

    # Verify the correct URL was requested
    assert len(requested_urls) == 1
    assert "structureID=1234" in requested_urls[0]
    # Verify empty response
    assert result == []


def test_get_terms_default_structure_id(monkeypatch):
    """get_terms() with no argument uses default structure ID."""
    client = InfiniteCampusApiClient(
        base_url="http://localhost",
        username="user",
        secret="pass",
        district="dist",
        cookies={"a": "b"}
    )

    # Track the URL requested
    requested_urls = []

    async def mock_get_request(url):
        requested_urls.append(url)
        return []

    monkeypatch.setattr(client, "_get_request", mock_get_request)

    result = asyncio.run(client.get_terms())

    # Verify the default structure ID was used
    assert len(requested_urls) == 1
    assert "structureID=1210" in requested_urls[0]
