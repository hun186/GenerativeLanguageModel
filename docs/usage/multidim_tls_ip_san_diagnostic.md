# MultiDim read-only ES diagnostics: temporary IP SAN exception

The GET-only Mapping probe (`scripts/audit_multidim_es_mapping_readonly.py`)
and nested-candidate sample (`scripts/audit_multidim_structured_sample_readonly.py`)
normally require HTTPS CA-chain and hostname/IP identity verification.

For a **verified legacy certificate whose IP Subject Alternative Name
does not match the literal IP address of the operator-controlled ES
instance**, `--allow-ip-san-mismatch` is a **temporary diagnostic
exception**. The flag:
- Is accepted only for a literal IPv4 or bracketed IPv6 **HTTPS origin**,
  without path, query, credentials or redirect.
- Is refused for named hosts such as DNS names or `localhost` using fixed
  code `TLS_SAN_EXCEPTION_IP_LITERAL_REQUIRED`, **before requesting
  credentials or attempting any network connection**.
- Keeps `ssl.CERT_REQUIRED`, the trusted CA-chain check and certificate
  validity. It suppresses only hostname/IP SAN equality for that
  explicitly declared diagnostic, and reports a TLS exception instead of
  an unqualified PASS.
- Is *not* an alternative to replacing/renewing the actual ES certificate
  with a SAN matching the host clients use. Operator identity and real
  private-network routing are still the operator's responsibility.

Neither probe mutates ES Mapping, `news_test`, source documents,
Scheduler, GLM tasks, LLM, Queue or Rerun. Tests substitute a fake
HTTPS response and reserved `192.0.2.10` address; no external ES system
is contacted in CI.
