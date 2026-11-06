#!/usr/bin/env bash
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
# Reinstala as dependencias so quando requirements.txt mudar (ex.: depois de uma atualizacao).
if ! cmp -s requirements.txt .venv/requirements.installed; then
  .venv/bin/pip install -q -r requirements.txt && cp requirements.txt .venv/requirements.installed
fi
exec .venv/bin/python run.py
