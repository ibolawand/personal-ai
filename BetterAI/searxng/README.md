# Web search without API keys

Aria searches the web through [SearXNG](https://docs.searxng.org/), an open-source search engine that runs here
in Docker. It asks the usual search engines and gives Aria the results. No account, no key, and it's only
reachable from this computer.

    ./start.sh          # first time: creates config/settings.yml and starts it (restarts by itself after reboots)
    docker compose down # stop it

When it isn't running, Aria falls back to Wikipedia and DuckDuckGo instant answers. Those are fine for facts,
but not for anything recent. Ask her "are your systems okay?" to see which one she's using.
