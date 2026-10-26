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
