from frontend.auth import password_matches


def test_public_demo_password_comparison():
    assert password_matches("correct horse battery staple", "correct horse battery staple")
    assert not password_matches("incorrect password", "correct horse battery staple")
    assert not password_matches("", "correct horse battery staple")
