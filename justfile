
# https://just.systems
# CMake build system

set dotenv-load := true
set export := true

default:
    @just --list

build:
  docker buildx build -t ghcr.io/icicle-ai/ai-studio:latest .

start:
  docker run -it -p 8000:8000 --env-file=.env --name ai-studio ghcr.io/icicle-ai/ai-studio:latest

rm:
  docker rm ai-studio

stop:
  docker stop ai-studio

