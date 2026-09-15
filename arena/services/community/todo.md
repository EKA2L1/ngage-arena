# Community HTTP and XMPP remaining work

- Validate remote deployment with a system-trusted certificate and original HTTP Host routing.
- Verify long session expiry and reconnect behavior beyond the recorded availability probes.
- Complete alerts, recovery and unsupported SOAP methods from native contracts.
- Determine the `createUser` status codes behind the Launcher's `ERROR_USERNAME_TAKEN`, `ERROR_IMEI_LINKED`, `ERROR_EMAIL_REGISTERED` and age/date strings; duplicate names still answer with a SOAP fault and surface as the generic creation error.
- Persist the `imei`/`imsi` that registration sends and answer `checkImei` from the stored identities instead of the hardcoded `false`.
