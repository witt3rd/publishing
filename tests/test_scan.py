from publishing.scan import scan, uncovered


def test_clean_text_passes():
    assert scan("A plain sentence about the plan, with numbers 1–2 and “quotes”.") == []


def test_generic_secrets_are_caught():
    for secret in ["ghp_" + "a" * 36, "github_pat_" + "B" * 30, "sk-" + "x" * 20, "AKIA" + "A" * 16,
                   "xoxb-123456789012-abc", "-----BEGIN OPENSSH PRIVATE KEY-----", "dp.st.prd." + "z" * 30]:
        assert any(p.startswith("secret") for p in scan(f"token {secret} here")), secret


def test_host_details_are_caught():
    assert scan("see /home/dt/src")[0].startswith("host detail")
    assert scan("mail me@example.com")[0].startswith("host detail")


def test_day_words_can_be_turned_off():
    assert scan("we did it today")[0].startswith("relative day word")
    assert scan("we did it today", days=False) == []


def test_project_words_and_allow():
    assert scan("in janus-infra", words=["janus-?infra"])[0].startswith("project word")
    assert scan("in janus-infra", words=["janus-?infra"], allow=["janus-infra"]) == []


def test_glyphs_outside_the_vendored_fonts():
    assert uncovered("arrows → ↔ ≤ ✓ ⚒ and text") == []
    assert uncovered("an emoji 🐓") == ["🐓"]
    assert any(p.startswith("glyph outside") for p in scan("an emoji 🐓"))
