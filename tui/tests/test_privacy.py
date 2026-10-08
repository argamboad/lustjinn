"""The client's own trust and route: public authorities only, interception named, the proxy a
choice. A machine with a TLS-inspecting proxy's root certificate installed (iBoss, on the owner's
laptop) must not be able to read the client's traffic without the client saying so."""

import ssl
from collections.abc import Callable
from pathlib import Path

import certifi
import httpx2
import pytest

from lustjinn_tui.api import Api, InterceptedError, UnreachableError, public_trust
from lustjinn_tui.app import LustjinnApp
from lustjinn_tui.config import Config, TokenStore, load
from lustjinn_tui.waking import WakingScreen


def refusing(error: BaseException) -> httpx2.MockTransport:
    def handle(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("handshake failed", request=request) from error

    return httpx2.MockTransport(handle)


def test_the_client_trusts_the_public_authorities_and_nothing_else() -> None:
    trusted = public_trust().get_ca_certs()
    bundled = Path(certifi.where()).read_text(encoding="utf-8").count("BEGIN CERTIFICATE")
    assert len(trusted) == bundled  # certifi's list, not the machine's store on top of it
    assert "iboss" not in str(trusted).lower()  # the inspecting proxy's root is not among them


async def test_a_refused_certificate_is_named_as_interception(tmp_path: Path) -> None:
    verify = ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] self-signed")
    api = Api("https://api.test", TokenStore(tmp_path / "t"), transport=refusing(verify))
    with pytest.raises(InterceptedError) as caught:
        await api.health()
    assert "intercepted" in str(caught.value)
    assert 'proxy = "none"' in str(caught.value)
    await api.aclose()


async def test_any_other_failure_is_still_just_unreachable(tmp_path: Path) -> None:
    api = Api("https://api.test", TokenStore(tmp_path / "t"), transport=refusing(OSError("down")))
    with pytest.raises(UnreachableError) as caught:
        await api.health()
    assert not isinstance(caught.value, InterceptedError)
    await api.aclose()


def test_the_proxy_is_the_systems_unless_the_config_says_none(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    assert load(path, environ={}).proxy == "system"
    path.write_text('proxy = "None"\n', encoding="utf-8")
    assert load(path, environ={}).proxy == "none"
    path.write_text('proxy = "sideways"\n', encoding="utf-8")
    assert load(path, environ={}).proxy == "system"  # anything else is the safe default


def test_direct_ignores_the_machines_proxy_settings(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "t")
    assert Api("https://api.test", store)._client.trust_env  # pyright: ignore[reportPrivateUsage]
    assert not Api("https://api.test", store, direct=True)._client.trust_env  # pyright: ignore[reportPrivateUsage]


async def test_the_lamp_says_intercepted_instead_of_asleep(tmp_path: Path) -> None:
    verify = ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED]")
    api = Api("https://api.test", TokenStore(tmp_path / "t"), transport=refusing(verify))
    app = LustjinnApp(Config(server="https://api.test"), api, wake_waits=(0.02,))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.2)
        screen = app.screen
        assert isinstance(screen, WakingScreen)
        shown: Callable[[str], str] = lambda wid: str(screen.query_one(wid).render())  # noqa: E731
        assert shown("#lamp") == "The connection was intercepted."
        assert "no public authority issued" in shown("#why")
