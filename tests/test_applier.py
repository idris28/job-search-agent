from jobagent.applier import is_bayt, read_outcome, read_posting

POSTING = "Java Developer\nCaliberly\nDubai, UAE\nJob description ..."


def test_posting_is_only_clickable_for_easy_apply():
    assert read_posting(POSTING, "Easy Apply") is None
    assert read_posting(POSTING, "Apply on company site").status == "external"
    assert read_posting(POSTING, "Applied").status == "already_applied"
    assert read_posting(POSTING, None).status == "closed"
    assert read_posting("This job is no longer available", None).status == "closed"
    assert read_posting("Please complete the CAPTCHA to continue", "Easy Apply").status == "blocked"
    # What Bayt's Cloudflare page says to an automated browser: a bot check, not a closed job.
    assert read_posting("Performing security verification\nverifies you are not a bot", None).status == "blocked"


def test_outcome_counts_only_an_explicit_confirmation():
    assert read_outcome("Your application was sent to the employer", "https://www.bayt.com/x").status == "applied"
    assert read_outcome("Sign in", "https://www.bayt.com/en/login/?next=x").status == "login_needed"
    assert read_outcome("Verify you are human", "https://www.bayt.com/x").status == "blocked"
    assert read_outcome("Answer these questions from the employer", "https://www.bayt.com/x").status == "needs_you"


def test_is_bayt():
    assert is_bayt("https://www.bayt.com/en/uae/jobs/java-developer-1/")
    assert not is_bayt("https://www.naukri.com/job-listings-1")
