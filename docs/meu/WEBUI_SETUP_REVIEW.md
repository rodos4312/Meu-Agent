# Hermes WebUI site review — 2026-11-07

Reviewed the [home page](https://get-hermes.ai/) and
[cross-device setup guide](https://get-hermes.ai/setup/), plus the linked
[Android client](https://github.com/hermes-webui/hermes-android) and
[extensions library](https://github.com/hermes-webui/hermes-webui-extensions).
This records ideas for the existing Meu roadmap; it does not install their
software, replace Meu clients or publish a new website/distribution.

## Useful patterns

The home page separates product, installation, learning and community, with a
clear start action, screenshot gallery and examples of practical work. The
setup guide explains the execution owner before describing server startup,
network reachability and client sign-in. Its URL table and troubleshooting
steps make the same-machine versus remote-device distinction concrete.

The linked Android project describes a native shell around a server's web
frontend. That is a remote client architecture. Meu's autonomous Android/PRoot
preview is a separate execution mode and still needs physical-device acceptance.

The guide's outside-home paths require Tailscale, SSH forwarding or Cloudflare
Tunnel. They are documented connection choices, not evidence of a built-in
relay that works without network setup. No tunnel or third-party account was
created during this review.

## Adaptation priorities for Meu

| Priority | Candidate | Existing Meu foundation and remaining work |
| --- | --- | --- |
| 1 | A short setup chooser: Windows agent, connect to a PC, autonomous Android preview | The apps already distinguish execution owners. Public setup instructions should explain each path and when the PC must remain running. |
| 2 | Platform download cards with release and preview labels | Windows releases exist; Android candidate acceptance remains pending. Link only admitted artifacts, with matching versioned screenshots. |
| 3 | A connection assistant: runtime health → reachability → sign-in → session/tools | Retain QR pairing and canonical gateway diagnostics. Keep manual URL entry as recovery; a connected socket alone must not mean that tools or history sync passed. |
| 4 | A task-oriented gallery | Show the existing navigation, deliverable preview and Coordinator acceptance/review cards using sanitized screenshots from the grouped release candidate. |
| 5 | Clear extension origins and requirements | Reuse existing skills/plugins/MCP screens. Show source, local/network execution, required credentials and install state without new routine approval prompts. |

The extension library's documented trust model is useful: extensions execute
application code and should disclose network/filesystem/native dependencies.
Compatibility with Meu needs verification per extension; a listing alone is
not proof.

Keep Meu's existing precise privacy wording: local storage is distinct from
requests sent to the user's selected model or enabled tools. Marketing claims,
comparison tables and feature counts need their own verification before reuse.
The new distribution remains grouped at the end of the current roadmap.
