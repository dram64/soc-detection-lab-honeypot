# SOC Detection Lab — Zeek local site config
# Enables policy modules useful for SOC visibility

@load base/protocols/conn
@load base/protocols/dns
@load base/protocols/http
@load base/protocols/ssl
@load base/protocols/ssh
@load base/protocols/smb

@load policy/protocols/conn/known-hosts
@load policy/protocols/conn/known-services
@load policy/protocols/ssl/known-certs
@load policy/protocols/ssl/validate-certs
@load policy/protocols/http/header-names
@load policy/protocols/dns/auth-addl
@load policy/frameworks/files/hash-all-files
@load policy/frameworks/files/extract-all-files

# Detect long DNS names (potential DGA / tunneling)
@load policy/protocols/dns/auth-addl

# JSON output for SIEM ingestion
redef LogAscii::use_json = T;

# Tag every log with sensor name
redef Log::default_logdir = "/usr/local/zeek/logs/current";
