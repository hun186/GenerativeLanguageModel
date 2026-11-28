"""Explicit private-LAN mutual TLS configuration for the read-only monitor.

No public bind, password storage, automatic fallback, or HTTP credentials.
Operator-managed certificates and trusted local filesystem are prerequisites.
"""
from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path
import ssl
import stat

_PRIVATE = tuple(ipaddress.ip_network(net) for net in
                 ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def _valid_bind(host):
    if not isinstance(host, str):
        return False
    try:
        ip = ipaddress.IPv4Address(host)
    except ValueError:
        return False
    # Explicit interface address only; loopback mTLS is also useful with SSH.
    return (str(ip) == host and
            (host == "127.0.0.1" or any(ip in net for net in _PRIVATE)))


@dataclass(frozen=True)
class MonitorTLS:
    host: str
    cert: str
    key: str
    client_ca: str

    def __post_init__(self):
        if not _valid_bind(self.host):
            raise ValueError("unsupported TLS bind")
        for value in (self.cert, self.key, self.client_ca):
            if (not isinstance(value, str) or not value or len(value) > 4096
                    or "\x00" in value or not Path(value).is_absolute()):
                raise ValueError("invalid TLS file locator")

    def context(self):
        # Initial remote release is POSIX-only; Windows private-key ACLs
        # require a separate validation path. Do not guess ACL safety.
        if os.name != "posix":
            raise ValueError("TLS deployment requires POSIX key permissions")
        for path in (self.cert, self.key, self.client_ca):
            info = Path(path).stat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("TLS source must be regular")
        key = Path(self.key)
        info = key.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077):
            raise ValueError("TLS key must be owner-only")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_verify_locations(cafile=self.client_ca)
        # A password callback avoids an interactive passphrase prompt in
        # the child. Encrypted keys are not supported by this initial mode.
        context.load_cert_chain(self.cert, self.key, password=lambda: b"")
        context.options |= getattr(ssl, "OP_NO_RENEGOTIATION", 0)
        return context


def tls_from_environ(env):
    host = env.get("GLM_WEB_HOST", "127.0.0.1")
    mode = env.get("GLM_WEB_REMOTE", "off")
    if mode == "off":
        if host != "127.0.0.1":
            raise ValueError("nonlocal bind requires explicit mTLS")
        return None
    if mode != "mtls":
        raise ValueError("unknown monitor remote mode")
    return MonitorTLS(host, env.get("GLM_WEB_TLS_CERT", ""),
                      env.get("GLM_WEB_TLS_KEY", ""),
                      env.get("GLM_WEB_CLIENT_CA", ""))
