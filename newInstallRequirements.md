# Requirements for the next installer rebuild

Recorded: 13 October 2026.

This document tracks requirements for the next GlueMapper installer. These are
planned requirements, not confirmation that the current installer implements them.

## Original KCD1 cinematics: external video encoder

The cinematic conversion workflow needs RAD Video Tools to encode extracted KCD1
video for playback in KCD2. GlueMapper's extraction, conversion orchestration and
packaging code can remain open source; the RAD encoder is a separate proprietary
dependency and is not covered by GlueMapper's MIT licence.

### Distribution and licence handling

- Do not bundle or mirror RAD Video Tools in the repository or release archives.
  The downloaded tool's EULA prohibits redistribution and directs users to the
  official website.
- Use the [official RAD download page](https://www.radgametools.com/bnkdown.htm)
  as the source for the dependency. Recheck its download details and licence when
  implementing or updating the installer; direct download availability does not
  itself establish permission for unattended installation.
- Identify the dependency and offer **Download and install video converter**
  before downloading or launching it.
- Launch the official installer with its licence and installation prompts visible.
  Do not silently accept the licence on the user's behalf. Use unattended setup
  only if the applicable terms and supported installer options have been verified.
- Keep extracted and converted game assets local to the user's installation;
  do not include original or converted KCD1 cinematics in GlueMapper releases.

### Required setup flow

- [ ] Detect an existing RAD Video Tools installation and validate the encoder.
- [ ] Provide **Locate existing installation** for manual and offline setup.
- [ ] Download from the official HTTPS source when the user chooses installation.
- [ ] Validate the downloaded archive against reviewed release metadata before
      extracting or running it. Fail clearly if verification fails or the upstream
      package changes; do not execute an unexpected download.
- [ ] Support the official archive format and published archive password. Keep
      those details maintainable rather than assuming they never change.
- [ ] Run the official installer and handle cancellation without reporting success.
- [ ] Locate and validate the installed encoder before continuing conversion.
- [ ] Report download, installation and conversion failures with a retry or manual
      selection path. Never mark cinematics installed after a failed conversion.
- [ ] Reuse completed conversions when the source files and conversion settings
      match, avoiding repeated downloads and encoding on subsequent setup runs.

### Conversion and verification requirements

- [ ] Read cinematics from the user's KCD1 installation and select the requested
      language audio explicitly.
- [ ] Preserve the original resolution, frame timing and complete movie duration;
      do not package the temporary low-resolution codec probe as the final intro.
- [ ] Invoke the encoder through its documented command-line interface, wait for
      completion, and validate the output before installing it. RAD documents the
      `/#` option to exit after encoding instead of waiting for the Done button:
      [RAD batch-processing documentation](https://www.radgametools.com/binkfaq.htm).
- [ ] Record source provenance, encoder version, settings and output validation in
      the conversion report.
- [ ] Verify playback in KCD2, including audio, completion and skipping. File
      conversion success alone does not prove that the New Game sequence works.
- [ ] Verify the original intro starts before visible gameplay and hands off to
      the intended KCD1 opening. Keep remaining scene and dialogue conversion gaps
      explicit rather than marking the complete prologue supported.

The current compatibility experiment uses Bink 1 encoding with KCD2's existing
decoder. Do not describe it as Bink 2 encoding or assume that a successful short
probe validates the full cinematic pipeline.
