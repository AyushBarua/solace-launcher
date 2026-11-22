"""
App-wide switches.

REQUIRE_LOGIN
    False (current): there is no sign-in screen. Solace opens straight into the
    profile chooser ("Who's Playing?"), or directly into the only profile when
    there is just one.
    True: the email / Google sign-in screen comes back. Its code is untouched.
"""

REQUIRE_LOGIN = False
