
# https://just.systems
# CMake build system

set dotenv-load
set export

default:
    @just --list

build:
    nerdctl build --build-arg PYTHON_VERSION=3.14 -t ai-studio-orchestrator:latest .

start:
    nerdctl run -it -p 8000:8000 --env-file=.env --name ai-studio ghcr.io/icicle-ai/ai-studio:latest

rm:
    nerdctl rm ai-studio

stop:
    nerdctl stop ai-studio
