# A throwaway box for the benchmark, so --bypass can skip permission checks safely.
#   docker build -t clarity-bench -f bench/token-savings/Dockerfile .
#   docker run --rm -e ANTHROPIC_API_KEY -v "$PWD:/repo:ro" -v "$PWD/../bench-runs:/runs" clarity-bench all --bypass --out /runs/r1
# The repo is read-only and the runs live outside it. An agent that reads the repo anyway shows up
# in the report as an escape; CI goes further and gives each arm its own runner.
FROM node:22-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @anthropic-ai/claude-code \
    && curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
USER node
WORKDIR /repo
ENTRYPOINT ["python3", "bench/token-savings/run.py"]
