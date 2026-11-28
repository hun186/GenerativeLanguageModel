# WEB-07A1 private-interface mutual TLS (read-only)

Default remains GLM_UI_MODE=auto and loopback-only plain HTTP when Web is
selected. GLM_WEB_REMOTE=mtls explicitly enables certificate-authenticated
HTTPS, bound to one literal RFC1918 IPv4 address or 127.0.0.1. No wildcard,
public interface, DNS bind, IPv6 or Windows remote ACL support. Set absolute
GLM_WEB_TLS_CERT, GLM_WEB_TLS_KEY, GLM_WEB_CLIENT_CA paths. The POSIX server
key must be a regular owner-only file owned by the GLM service user. Use a
server cert with the exact address IP SAN and an operator-only client CA;
browser must trust server CA and present an enrolled client certificate.
TLS >=1.2, client cert required before HTTP, exact Host/Origin, read-only
routes. No password/token, no browser path locator, no raw repair data.
No plaintext fallback on TLS/config/bind failure; GLM continues without GUI.
Use firewall restrictions and dedicated short-lived operator certificates;
any valid certificate chaining to the configured operator CA is authorized.
No per-user RBAC, CRL/OCSP checking, certificate hot reload, Internet-facing
hardening or protection against malicious local filesystem edits. Revocation
requires replacing the trusted CA/credentials and restarting as appropriate.
Local SSH port forwarding remains an alternative; Windows can be the client.
Real disposable OpenSSL PKI integration test on POSIX (explicit skip if CLI
unavailable); Windows remote server remains disabled. Physical LAN/browser
certificate installation, firewall and load acceptance not yet performed.
Project memory and API context synchronization before ready/merge.
