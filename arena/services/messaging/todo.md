# Friends and messaging remaining work

- Fix native live invitation refresh: the new body reaches the guest database but appears in New Messages only after Launcher restart. Logout/login in the same process does not refresh it.
- Fix the sender's live friend-list refresh after reacceptance. The recipient displays the friend and reciprocal grants persist, but the online sender still shows Add a Friend until its roster is reloaded.
- Add further native dialect operations only from observed client requirements; federation and full XEP-0013 are not implemented.
