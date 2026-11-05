# Meu 0.1.0-dev.22

## Project notes

Meu now keeps durable project decisions and preferences separate from your general
profile. Enter a project in the sidebar and choose **Project notes** to view, add,
edit or delete its notes. **Open notes folder** reveals the local notes file.
Changes apply to new conversations in that project.

If notes change while you are editing them, Meu keeps your draft and refuses to
overwrite the newer version. Existing local memory history and restore commands
remain available. Your current memory approval settings are preserved.

## Coordinator context

The Coordinator can select relevant project notes for each helper. Helpers receive
only those selected facts. Each attempt records which notes it used, and a changed
or removed note must be selected again before work starts. Model selection continues
to stay within the provider of the parent conversation.

Project notes are stored locally in the owning profile. Selected facts are processed
by your chosen LLM as conversation context. No additional API key is required.

## Updates

This release uses the existing Meu update channel and update-key verification.
The Windows upgrade rehearsal starts from the public dev.21 installer. User data
remains outside the source checkout. The test pipeline also checks failed-startup
recovery before a release is published.
