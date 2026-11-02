# Security Policy

## Supported versions

Dragonfly has no stable release yet. Security fixes go to the `main` branch.

## Reporting a vulnerability

**Please do not open a public issue, discussion or pull request for a security problem.**

Report it privately through GitHub: open the **Security** tab of this repository and choose **Report a vulnerability**. Only the maintainers can see the report.

Please include:

- What the problem is and where it lives (file, module, endpoint)
- Steps to reproduce, or a minimal proof of concept
- The impact you expect

We aim to acknowledge reports within 7 days and to agree a disclosure date with you once a fix is ready.

## What must never be committed

This repository is public. The following must never appear in code, history, issues, pull requests, logs, screenshots or test fixtures:

- Credentials of any kind: passwords, API keys, tokens, private keys, certificates
- Personal information: names, home addresses, phone numbers, personal email addresses, precise personal locations
- Operational details that could be misused: real radar station addresses, IP addresses, hostnames, coordinates of real sites, network layouts, or recorded data from real deployments
- Anything covered by a non-disclosure agreement or export restriction

Use environment variables for configuration, placeholders from the documentation ranges (for example `192.0.2.0/24`, `example.com`) in docs and tests, and synthetic data in fixtures.

## How the repository protects itself

- Secret scanning with push protection blocks known credential formats at push time
- A gitleaks scan runs on every pull request and on every push to `main`
- A local pre-commit hook runs the same scanner before each commit
- `main` is protected: changes go through reviewed pull requests with passing checks

## If a secret is leaked

1. **Revoke or rotate the secret immediately.** Assume it is compromised the moment it is pushed, even if the commit is removed.
2. Report it privately as described above.
3. A maintainer will purge it from history if needed. Deleting the file in a new commit is not enough.
