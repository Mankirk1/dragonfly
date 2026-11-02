# Contributing to Dragonfly

Thanks for helping. This guide explains how we work.

## Ground rules

- **Never commit secrets, personal information or real operational data.** See [SECURITY.md](SECURITY.md#what-must-never-be-committed). This is the one rule with no exceptions.
- Be kind. Everyone here follows the [Code of Conduct](CODE_OF_CONDUCT.md).
- Discuss large changes in an issue before writing a lot of code.

## Setting up

```bash
pip install -e ".[dev]"
pre-commit install
```

`pre-commit install` is required. It runs the secret scanner, a private key check and the linters before every commit.

Turn on GitHub's email privacy so your personal address doesn't end up in commits: **Settings → Emails → Keep my email addresses private**, then use your `@users.noreply.github.com` address with `git config user.email`.

## Workflow

1. Outside contributors **fork** the repository. Collaborators create a branch named `feature/<short-name>` or `fix/<short-name>`.
2. Keep commits small and focused, with clear messages in the imperative mood ("Add range filter", not "Added stuff").
3. Run the checks locally:
   ```bash
   ruff check .
   ruff format --check .
   pytest
   ```
4. Open a pull request against `main` and fill in the template.
5. A pull request merges once CI passes and a code owner approves it. New pushes dismiss earlier approvals.

`main` is protected. Direct pushes, force pushes and branch deletion are blocked.

## Coding standards

- Python 3.11+, formatted and linted with [ruff](https://docs.astral.sh/ruff/)
- Type hints on public functions
- Tests for new behaviour and bug fixes, using synthetic data only
- Configuration through environment variables, documented in `.env.example`

## Reporting bugs and requesting features

Use the issue templates. For anything security related, follow [SECURITY.md](SECURITY.md) instead.

## License

By contributing, you agree that your contributions are licensed under the [Apache License 2.0](LICENSE).
