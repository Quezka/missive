"""The OAuth client against pretend providers: a fake browser and a fake token server, so no real account or
network is ever touched. The loopback listener is real (127.0.0.1) because that is the part worth testing."""
import base64
import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from missive.application.errors import SourceError
from missive.infrastructure.oauth import ClientIds, OAuthClient, endpoints, load_client_ids, pkce_pair, xoauth2

IDS = {"google": ClientIds("g-id", "g-secret"), "microsoft": ClientIds("m-id", tenant="consumers")}


class Provider:
    """Records what the app sent and answers like a token endpoint would."""

    def __init__(self, replies=None):
        self.posts = []
        self.replies = list(replies or [])

    def post(self, url, data):
        self.posts.append((url, dict(data)))
        if self.replies:
            return self.replies.pop(0)
        return {"access_token": f"access-{len(self.posts)}", "refresh_token": "refresh-1", "expires_in": 3600}


def browser(answer, sent=None, reply_first_with_wrong_state=False):
    """A fake open_url: parses the authorization URL, then 'approves' by calling the redirect back from a thread."""

    def open_url(url):
        parts = urllib.parse.urlparse(url)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query).items()}
        if sent is not None:
            sent.update(query, base=f"{parts.scheme}://{parts.netloc}{parts.path}")
        redirect = query["redirect_uri"].replace("localhost", "127.0.0.1")

        def visit():
            def get(extra):
                try:
                    urllib.request.urlopen(f"{redirect}/?{urllib.parse.urlencode(extra)}", timeout=5).read()
                except urllib.error.HTTPError:
                    pass
            if reply_first_with_wrong_state:
                get({"code": "stolen", "state": "not-the-state"})
            get({**answer, "state": query["state"]})
        threading.Thread(target=visit, daemon=True).start()
        return True
    return open_url


def test_pkce_challenge_is_the_sha256_of_the_verifier():
    verifier, challenge = pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected and 43 <= len(verifier) <= 128 and pkce_pair()[0] != verifier


def test_google_sign_in_sends_pkce_and_the_hint_then_returns_the_refresh_token():
    sent, provider = {}, Provider()
    client = OAuthClient(IDS, open_url=browser({"code": "the-code"}, sent), post=provider.post, wait=10)
    assert client.authorize("google", "me@gmail.com") == "refresh-1"
    assert sent["base"] == "https://accounts.google.com/o/oauth2/v2/auth"
    assert sent["client_id"] == "g-id" and sent["response_type"] == "code" and sent["scope"] == "https://mail.google.com/"
    assert sent["code_challenge_method"] == "S256" and sent["login_hint"] == "me@gmail.com"
    assert sent["access_type"] == "offline" and sent["redirect_uri"].startswith("http://127.0.0.1:")
    url, data = provider.posts[0]
    assert url == "https://oauth2.googleapis.com/token"
    assert data["code"] == "the-code" and data["grant_type"] == "authorization_code" and data["client_secret"] == "g-secret"
    assert data["redirect_uri"] == sent["redirect_uri"]
    verifier = data["code_verifier"]  # the app proves it is the one that started the request
    assert base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode() == sent["code_challenge"]


def test_microsoft_sign_in_uses_its_tenant_localhost_and_no_secret():
    sent, provider = {}, Provider()
    client = OAuthClient(IDS, open_url=browser({"code": "c"}, sent), post=provider.post, wait=10)
    client.authorize("microsoft", "me@outlook.com")
    assert sent["base"] == "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize"
    assert sent["redirect_uri"].startswith("http://localhost:")
    assert "IMAP.AccessAsUser.All" in sent["scope"] and "offline_access" in sent["scope"]
    url, data = provider.posts[0]
    assert url == "https://login.microsoftonline.com/consumers/oauth2/v2.0/token" and "client_secret" not in data


def test_a_visit_with_the_wrong_state_is_ignored_and_the_real_answer_still_works():
    provider = Provider()
    client = OAuthClient(IDS, open_url=browser({"code": "right"}, reply_first_with_wrong_state=True),
                         post=provider.post, wait=10)
    client.authorize("google", "me@gmail.com")
    assert [d["code"] for _u, d in provider.posts] == ["right"]  # "stolen" never reached the token server


def test_declining_in_the_browser_is_a_clear_cancellation():
    client = OAuthClient(IDS, open_url=browser({"error": "access_denied"}), post=Provider().post, wait=10)
    with pytest.raises(SourceError, match="cancelled"):
        client.authorize("google", "me@gmail.com")


def test_another_provider_error_is_passed_on():
    client = OAuthClient(IDS, open_url=browser({"error": "server_error", "error_description": "try later"}),
                         post=Provider().post, wait=10)
    with pytest.raises(SourceError, match="try later"):
        client.authorize("google", "me@gmail.com")


def test_waiting_gives_up_when_nobody_answers():
    client = OAuthClient(IDS, open_url=lambda url: True, post=Provider().post, wait=0.4)
    started = time.time()
    with pytest.raises(SourceError, match="in time"):
        client.authorize("google", "me@gmail.com")
    assert time.time() - started < 5


def test_the_wait_can_be_cancelled_from_another_thread():
    client = OAuthClient(IDS, open_url=lambda url: True, post=Provider().post, wait=60)
    threading.Timer(0.3, client.cancel).start()
    started = time.time()
    with pytest.raises(SourceError, match="cancelled"):
        client.authorize("google", "me@gmail.com")
    assert time.time() - started < 10


def test_a_browser_that_cannot_open_is_reported():
    client = OAuthClient(IDS, open_url=lambda url: False, post=Provider().post, wait=5)
    with pytest.raises(SourceError, match="browser"):
        client.authorize("google", "me@gmail.com")


def test_no_refresh_token_means_the_provider_would_not_let_us_stay_signed_in():
    provider = Provider([{"access_token": "a", "expires_in": 3600}])
    client = OAuthClient(IDS, open_url=browser({"code": "c"}), post=provider.post, wait=10)
    with pytest.raises(SourceError, match="refresh token"):
        client.authorize("google", "me@gmail.com")


def test_the_first_access_token_is_reused_then_renewed_before_it_runs_out():
    now = [1000.0]
    provider = Provider()
    client = OAuthClient(IDS, open_url=browser({"code": "c"}), post=provider.post, clock=lambda: now[0], wait=10)
    refresh = client.authorize("google", "me@gmail.com")
    assert client.access_token("google", refresh) == "access-1" and len(provider.posts) == 1  # from sign-in
    now[0] += 3000
    assert client.access_token("google", refresh) == "access-1"
    now[0] += 600  # inside the safety margin of the one-hour expiry
    assert client.access_token("google", refresh) == "access-2"
    url, data = provider.posts[1]
    assert data["grant_type"] == "refresh_token" and data["refresh_token"] == "refresh-1"
    assert data["client_secret"] == "g-secret" and "scope" not in data


def test_microsoft_refresh_sends_the_scope_and_follows_a_rotated_refresh_token():
    provider = Provider([{"access_token": "a1", "refresh_token": "r2", "expires_in": 10},
                         {"access_token": "a2", "expires_in": 10}])
    ticks = iter(range(0, 10000, 1000))  # every call to the clock is a long time later: tokens always expire
    client = OAuthClient(IDS, post=provider.post, clock=lambda: next(ticks))
    assert client.access_token("microsoft", "r1") == "a1"
    assert provider.posts[0][1]["scope"].endswith("offline_access") and provider.posts[0][1]["refresh_token"] == "r1"
    assert client.access_token("microsoft", "r1") == "a2"
    assert provider.posts[1][1]["refresh_token"] == "r2"  # the newer one, while the original stays in the keyring


def test_a_revoked_token_asks_to_add_the_account_again():
    client = OAuthClient(IDS, post=Provider([{"error": "invalid_grant"}]).post)
    with pytest.raises(SourceError, match="add it again"):
        client.access_token("google", "old")


def test_without_a_client_id_nothing_starts():
    client = OAuthClient({"google": ClientIds(), "microsoft": ClientIds("m")}, open_url=lambda u: pytest.fail("opened"))
    assert not client.available("google") and client.available("microsoft") and not client.available("yahoo")
    with pytest.raises(SourceError, match="OAUTH.md"):
        client.authorize("google", "me@gmail.com")
    with pytest.raises(SourceError, match="OAUTH.md"):
        client.access_token("google", "r")


def test_an_unknown_provider_has_no_endpoints():
    with pytest.raises(SourceError):
        endpoints("yahoo", ClientIds("x"))


def test_client_ids_come_from_the_file_and_the_environment_wins(tmp_path):
    path = tmp_path / "oauth.json"
    path.write_text(json.dumps({"google": {"client_id": "file-g", "client_secret": "file-s"},
                                "microsoft": {"client_id": "file-m", "tenant": "organizations"}}))
    ids = load_client_ids(path, environ={"MISSIVE_GOOGLE_CLIENT_ID": "env-g"})
    assert ids["google"] == ClientIds("env-g", "file-s") and ids["microsoft"] == ClientIds("file-m", "", "organizations")
    nothing = load_client_ids(tmp_path / "missing.json", environ={})
    assert nothing["google"] == ClientIds() and nothing["microsoft"].tenant == "common"
    path.write_text("not json")
    assert load_client_ids(path, environ={})["google"].client_id == ""  # a broken file is just "not set up"


def test_the_xoauth2_response_has_the_shape_imap_servers_expect():
    assert xoauth2("me@x.org", "tok") == b"user=me@x.org\x01auth=Bearer tok\x01\x01"
