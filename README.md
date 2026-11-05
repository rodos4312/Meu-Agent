# Meu Agent

<img src="https://raw.githubusercontent.com/rodos4312/Meu-Agent/bd5872478b7b683e7b809e70239acd26f0e9fb1e/apps/desktop/public/meu-icon.png" alt="Meu logo" width="72">

**Meu Agent** is a privacy-focused desktop AI agent and personal assistant for Windows. It works with your files and projects, recalls past conversations with persistent memory, and coordinates multiple agents on complex tasks. Use your preferred cloud LLM provider or connect a local model.

[Download for Windows](#download-for-windows-x64) · [Report a bug](https://github.com/rodos4312/Meu-Agent/issues/new/choose) · [Questions, ideas and feedback](https://github.com/rodos4312/Meu-Agent/discussions)

**Privacy starts on your PC.** A local Meu installation stores your chat history, memory, and skills on your own computer. You can use Meu without a central account or a Meu-hosted portal. When you use a cloud model or a web tool, the service handling the request receives the data sent for that task. Update checks contact GitHub.

## Download for Windows x64

**[Download the latest Meu release for Windows x64](https://github.com/rodos4312/Meu-Agent/releases)** · Preview releases

Open the newest release and download its `Meu-<version>-win-x64.exe` installer.

See [Meu releases](https://github.com/rodos4312/Meu-Agent/releases) for release notes and installers.

After installation, configure your provider in **Settings → Providers** and select your model in **Settings → Model → Main model**. Check for app updates in **Settings → About → Version & updates**.

We retain the current release and up to **two previous releases**, based on version count rather than age. If your installed version is no longer available for automatic recovery, download and run the latest installer over your existing installation. Keep your Meu data folder. See the [release retention policy](docs/meu/RELEASE_RETENTION.md).

## What Meu can do

- **Choose your model provider.** Options include Anthropic, DeepSeek, Gemini, OpenAI Codex, and OpenRouter. You can also connect a local model through a compatible endpoint such as Ollama.
- **Switch between DeepSeek Flash and Pro automatically.** With DeepSeek configured, **Auto · Flash / Pro** picks a model based on the task. You can also select a model from the chat.
- **Coordinate project work.** The optional **Meu Coordinator · General** splits work into assignments, saves progress, and can delegate independent review and repair. Helpers stay on the current conversation's provider, with optional model choices for light and heavy tasks. **Meu Coordinator · DeepSeek** offers Flash and Pro routing for DeepSeek sessions. Choose a coordinator in **Settings → Model → Subagents**, then start a new chat.
- **Keep project notes locally.** Open a project in the sidebar and choose **Project notes** to view, add, edit or delete its saved decisions and preferences. Notes persist across restarts and apply to new conversations in that project. The Coordinator can pass selected notes to individual helpers; each attempt records which notes it used. See [Project memory](docs/meu/PROJECT_MEMORY.md) for scope, storage and history.

## Feedback and community

Meu is in preview. Try it on a real task and tell us what worked and what needs improvement.

- **Bugs and installation problems:** [open an issue](https://github.com/rodos4312/Meu-Agent/issues/new/choose). Include your Meu version, the steps you took and what you expected to happen.
- **Questions, ideas and general feedback:** [start a discussion](https://github.com/rodos4312/Meu-Agent/discussions). English and Greek feedback are welcome.
- **Downloads and changes:** [browse Meu releases](https://github.com/rodos4312/Meu-Agent/releases).

Review screenshots and log excerpts before posting. Remove API keys, tokens, private conversations and personal information. Feedback is public; Meu does not upload diagnostic files automatically for an issue report.

## Development and credits

Active development takes place on [`dev/meu-foundation`](https://github.com/rodos4312/Meu-Agent/tree/dev/meu-foundation).

Meu is maintained as an independent repository. The previous fork is retained at [Meu-Agent-Legacy](https://github.com/rodos4312/Meu-Agent-Legacy) for historical CI runs and repository records. Current development, downloads, issues and discussions belong in this repository.

Meu is based on [Hermes Agent by Nous Research](https://github.com/NousResearch/hermes-agent). See the [MIT license](LICENSE) for license and copyright details.
