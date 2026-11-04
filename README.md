# Meu Agent

<img src="https://raw.githubusercontent.com/rodos4312/Meu-Agent/bd5872478b7b683e7b809e70239acd26f0e9fb1e/apps/desktop/public/meu-icon.png" alt="Meu logo" width="72">

**Meu Agent** is a personal AI assistant for Windows. It works with your files and projects, recalls past conversations, and can delegate parts of a complex task to other agents.

## Download for Windows x64

**[Download Meu 0.1.0-dev.18 for Windows x64](https://github.com/rodos4312/Meu-Agent/releases/download/meu-v0.1.0-dev.18/Meu-0.1.0-dev.18-win-x64.exe)** · Preview release

See [Meu releases](https://github.com/rodos4312/Meu-Agent/releases) for release notes and installers.

After installation, configure your provider in **Settings → Providers** and select your model in **Settings → Model → Main model**. Check for app updates in **Settings → About → Version & updates**.

## What Meu can do

- **Choose your model provider.** Options include Anthropic, DeepSeek, Gemini, OpenAI Codex, and OpenRouter. You can also connect a local model through a compatible endpoint such as Ollama.
- **Switch between DeepSeek Flash and Pro automatically.** With DeepSeek configured, **Auto · Flash / Pro** picks a model based on the task. You can also select a model from the chat.
- **Coordinate project work.** The optional **Meu Coordinator** splits work into assignments, saves progress, and can delegate independent review and repair. Its current subagent routing uses DeepSeek Flash and Pro. Enable it in **Settings → Model → Subagents**, then start a new chat.
- **Keep your workspace data locally.** A local installation stores conversations, memory, and skills on your PC. Model and web requests go to the configured providers. Meu removes Nous Portal sign-in and usage reporting to Nous Research.

## Development and credits

Active development takes place on [`dev/meu-foundation`](https://github.com/rodos4312/Meu-Agent/tree/dev/meu-foundation).

Meu is based on [Hermes Agent by Nous Research](https://github.com/NousResearch/hermes-agent). See the [MIT license](LICENSE) for license and copyright details.
