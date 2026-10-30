#!/usr/bin/env python3
"""Fail if Terraform files look like they contain real secret values or secret versions.

Heuristic guard (no dependencies); it complements, not replaces, the repository secret scan.
Usage: python check_no_secrets.py [dir]   (default: directory of this script)
"""
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).parent
files = [p for p in root.rglob("*") if p.is_file() and ".terraform" not in p.parts
         and (p.suffix in (".tf", ".hcl") or p.name.endswith(".tfvars.example") or p.name.endswith(".hcl.example"))]

PATTERNS = {
    "secret version resource": re.compile(r'resource\s+"google_secret_manager_secret_version"'),
    "secret_data attribute": re.compile(r"\bsecret_data(_wo)?\s*="),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "service account key resource": re.compile(r'resource\s+"google_service_account_key"'),
    "google api key": re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    "openai/openrouter style key": re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    "github token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "bearer/jwt": re.compile(r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}\."),
    # Any secret version is already rejected above; these also catch proxy-secret values by name.
    "proxy secret version": re.compile(r"secret_version.*proxy|proxy.*secret_version", re.I),
    "PROXY_SHARED_SECRET value": re.compile(r"\bPROXY_SHARED_SECRET\b\s*[=:]\s*\"?(?!REPLACE)[^\s\"#]"),
    "proxy secret value assignment": re.compile(r"(?i)\bproxy[_-]?(shared[_-]?)?secret\b\s*=\s*\"(?!REPLACE)[^\"]+\""),
    "local dispatcher token": re.compile(r"KS_DISPATCHER_LOCAL_TOKEN"),
    "inline credentials url": re.compile(r"postgres(?:ql)?(?:\+\w+)?://[^\s\"':@]+:[^\s\"'@]+@"),
    "quoted secret assignment": re.compile(
        r'(?i)\b(password|token|api_key|apikey|secret|signing_key)\b\s*=\s*"(?!REPLACE)[^"$]{8,}"'
    ),
}

bad = []
for f in files:
    for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if line.lstrip().startswith(("#", "//")):
            continue
        for name, rx in PATTERNS.items():
            if rx.search(line):
                bad.append(f"{f}:{n}: {name}")

if bad:
    print("check_no_secrets: FAIL")
    print("\n".join(bad))
    sys.exit(1)
print(f"check_no_secrets: OK ({len(files)} files scanned)")
