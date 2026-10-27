from datetime import datetime, timedelta

from missive.domain import Address, Message, base_subject, clean_html, group, link_targets, text_of


def msg(uid, subject, sent, mid="", reply="", refs=(), sender="a@x.org", folder="INBOX"):
    return Message(1, folder, uid, subject, Address(sender, sender.split("@")[0]), sent,
                   message_id=mid, in_reply_to=reply, references=tuple(refs))


T0 = datetime(2026, 10, 1, 9, 0)


def test_subjects_lose_their_reply_prefixes():
    assert base_subject("Re: Re: Fwd: Hello  ") == "Hello"
    assert base_subject("RE[2]: Hello") == "Hello"
    assert base_subject("Aw: Hallo") == "Hallo"
    assert base_subject("Revenue report") == "Revenue report"  # "Re" inside a word is not a prefix


def test_replies_join_their_thread_by_message_id_and_threads_sort_newest_first():
    a = msg(1, "Plan", T0, "<a>")
    b = msg(2, "Re: Plan", T0 + timedelta(hours=1), "<b>", "<a>", ["<a>"], "b@x.org")
    c = msg(3, "Re: Re: Plan", T0 + timedelta(hours=2), "<c>", "<b>", ["<a>", "<b>"])
    other = msg(4, "Lunch?", T0 + timedelta(days=1), "<d>")
    threads = group([c, other, a, b])
    assert [t.subject for t in threads] == ["Lunch?", "Plan"]
    plan = threads[1]
    assert [m.uid for m in plan.messages] == [1, 2, 3]  # oldest first
    assert plan.latest.uid == 3 and plan.unread == 3
    assert [p.email for p in plan.participants] == ["a@x.org", "b@x.org"]


def test_a_reply_without_references_still_joins_by_subject_but_plain_subjects_do_not():
    a = msg(1, "Hello there", T0, "<a>")
    stripped = msg(2, "Re: Hello there", T0 + timedelta(hours=1), "<b>")  # a client dropped the headers
    unrelated_same_subject = msg(3, "Hello there", T0 + timedelta(hours=2), "<c>")
    threads = group([a, stripped, unrelated_same_subject])
    sizes = sorted(len(t.messages) for t in threads)
    assert sizes == [1, 2]  # the reply joined the first; the later fresh mail is its own thread


def test_html_is_cleaned_scripts_forms_and_remote_pictures_are_removed():
    dirty = ('<p onclick="x()">Hi <b>there</b></p><script>steal()</script><style>p{}</style>'
             '<img src="https://t.example/p.gif"><a href="javascript:evil()">bad</a>'
             '<a href="https://ok.example/page">good</a><form action="/x"><input></form>')
    safe, blocked = clean_html(dirty)
    assert "script" not in safe and "steal" not in safe and "onclick" not in safe
    assert "<form" not in safe and "javascript:" not in safe and "t.example" not in safe
    assert blocked == 1 and "[image]" in safe
    assert 'href="https://ok.example/page"' in safe and 'title="https://ok.example/page"' in safe
    assert "<b>there</b>" in safe
    loaded, blocked_now = clean_html(dirty, load_images=True)
    assert "t.example/p.gif" in loaded and blocked_now == 0
    assert link_targets(dirty) == ["https://ok.example/page"]


def test_unclosed_and_broken_html_is_closed_and_text_extracted():
    safe, _ = clean_html("<p>one <b>two")
    assert safe == "<p>one <b>two</b></p>"
    assert text_of("<p>Hello</p><script>x</script><div>World &amp; all</div>") == "Hello World & all"


# ---- pictures in mail ----

import pytest  # noqa: E402

from missive.domain import clean_html, image_urls, remote_image_allowed  # noqa: E402

PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


@pytest.mark.parametrize("url, ok", [
    ("https://cdn.example.com/a.png", True), ("http://news.example.org/x.gif", True), ("https://8.8.8.8/a.png", True),
    ("http://localhost/a.png", False), ("http://127.0.0.1/a.png", False), ("http://192.168.1.1/reboot", False),
    ("http://10.0.0.5/a.png", False), ("http://169.254.169.254/latest/meta-data", False), ("http://[::1]/a.png", False),
    ("http://nas.lan/a.png", False), ("http://printer.local/a.png", False), ("http://intranet/a.png", False),
    ("https://user:pass@cdn.example.com/a.png", False), ("ftp://cdn.example.com/a.png", False),
    ("file:///etc/passwd", False), ("javascript:alert(1)", False), ("", False),
])
def test_a_message_can_only_make_the_computer_fetch_from_the_public_internet(url, ok):
    assert remote_image_allowed(url) is ok


def test_pictures_inside_the_message_show_at_once_and_internet_ones_wait_for_the_user():
    html = f'<p>Hi</p><img src="{PNG}" alt="logo"><img src="https://cdn.example.com/a.png">'
    shown, blocked = clean_html(html)
    assert PNG in shown and "cdn.example.com" not in shown and blocked == 1  # only the internet one waits
    shown, blocked = clean_html(html, load_images=True)
    assert PNG in shown and 'src="https://cdn.example.com/a.png"' in shown and blocked == 0


def test_loading_pictures_still_never_reaches_the_users_own_network():
    html = '<img src="http://192.168.1.1/reboot"><img src="http://localhost/x"><img src="https://cdn.example.com/a.png">'
    shown, blocked = clean_html(html, load_images=True)
    assert "192.168.1.1" not in shown and "localhost" not in shown and "cdn.example.com" in shown
    assert image_urls(html) == ["https://cdn.example.com/a.png"]


def test_unresolved_and_odd_pictures_become_a_placeholder_never_an_address():
    shown, _ = clean_html('<img src="cid:logo@x" alt="Logo"><img src="data:text/html;base64,PHNjcmlwdD4="><img>', True)
    assert "cid:" not in shown and "data:text" not in shown and shown.count("[image") == 3 and "[image: Logo]" in shown


def test_the_list_of_pictures_to_fetch_has_no_repeats_and_a_limit():
    html = "".join(f'<img src="https://cdn.example.com/{i % 60}.png">' for i in range(200))
    urls = image_urls(html)
    assert len(urls) == 40 and len(set(urls)) == 40
