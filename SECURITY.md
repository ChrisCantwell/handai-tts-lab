# Security Policy

## Local-only tool

HandAI TTS Lab is intended for trusted local/private use. Do not expose the Web UI directly to the public internet.

The application can:

- run local synthesis/transcription/enhancement jobs,
- call local helper scripts,
- read and write files under the TTS Lab workspace,
- store configuration and token files locally,
- launch local desktop applications such as Audacity or the system file opener,
- call a video downloader helper when configured.

Bind it to `127.0.0.1` unless you are deliberately placing it behind your own trusted access controls.

## Sensitive files

Do not commit local runtime data, model caches, references, generated media, transcripts, tokens, Conda environments, or logs.

The repository `.gitignore` is designed to avoid common accidental commits, but users remain responsible for checking `git status` before publishing.

## Reporting issues

For now, report security concerns privately to the maintainer if you have a direct channel. Otherwise, open a GitHub issue with non-sensitive reproduction details and omit private files, tokens, media, or credentials.
