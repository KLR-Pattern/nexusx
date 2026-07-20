#!/bin/bash
# Start all nexusx demo services, grouped by the README's two-pillar model:
#   1. Query surface       — SQLModel entities → GraphQL / MCP
#   2. Core API            — DefineSubset DTOs + Resolver (REST)
#   3. Business-logic      — UseCaseService → REST / MCP
#   4. Visualization       — Voyager (ER + service graphs)
#
# Press Ctrl+C to stop all services.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Colors ────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── Ports (numbers kept stable; names now reflect the README pillars) ─────
# Query surface (SQLModel entities)
PORT_BLOG_GQL=8000          # Blog GraphQL — entity query surface
PORT_BLOG_GQL_PAG=8015      # Blog GraphQL — pagination enabled
                            # (8015, not 8005: Windows reserves 8005 for
                            #  Windows Hello auth, which makes browsers pop a
                            #  "sign in" dialog on that port)
PORT_AUTH_GQL=8002          # Auth GraphQL — entities + FromContext
PORT_AUTH_MCP=8003          # entity → single-app MCP
PORT_MULTI_MCP=8004         # entity → multi-app MCP gateway
# Core API (DefineSubset DTOs + Resolver)
PORT_CORE_API=8001
# Business-logic surface (UseCaseService)
PORT_USECASE_REST=8007      # UseCaseService → FastAPI REST + OpenAPI
PORT_USECASE_MCP=8006       # UseCaseService → MCP (4-layer)
# Visualization (Voyager)
PORT_VOYAGER_USECASE=8008   # Voyager — UseCase service graph
PORT_VOYAGER_ER=8009        # Voyager — ER + enterprise schema

# ── Group titles (README pillars) ─────────────────────────────────────────
GROUP_ORDER=("query" "core_api" "business" "viz")
declare -A GROUP_TITLE=(
  [query]="Query surface (SQLModel entities → GraphQL / MCP)"
  [core_api]="Core API (DefineSubset DTOs + Resolver)"
  [business]="Business-logic surface (UseCaseService → REST / MCP)"
  [viz]="Visualization (Voyager)"
)

# ── Service registry ──────────────────────────────────────────────────────
# Each record: group | name | port | url path | start command (%PORT% → port)
# Add a demo by appending one line here; start/wait/table all derive from this.
SERVICES=(
  # ── Query surface: SQLModel entities exposed as GraphQL / MCP ──
  "query|Blog GraphQL|$PORT_BLOG_GQL|GraphQL|/graphql,/schema|uv run uvicorn demo.blog.app:app --port %PORT%"
  "query|Blog GraphQL (paginated)|$PORT_BLOG_GQL_PAG|GraphQL|/graphql,/schema|uv run uvicorn demo.blog.app_paginated:app --port %PORT%"
  "query|Auth GraphQL|$PORT_AUTH_GQL|GraphQL|/graphql,/schema|uv run uvicorn demo.auth.app:app --port %PORT%"
  "query|Auth MCP (entity → MCP)|$PORT_AUTH_MCP|MCP|/mcp|PORT=%PORT% uv run python -m demo.auth.mcp_server"
  "query|Multi-app MCP (gateway)|$PORT_MULTI_MCP|MCP|/mcp|PORT=%PORT% uv run python -m demo.multi_app.mcp_server"
  # ── Core API: DefineSubset DTOs + Resolver served via REST ──
  "core_api|Core API REST|$PORT_CORE_API|REST|/api/sprints,/api/tasks,/api/er-diagram|uv run uvicorn demo.core_api.app:app --port %PORT%"
  # ── Business-logic: one UseCaseService signature → REST / MCP ──
  "business|UseCase REST (FastAPI + OpenAPI)|$PORT_USECASE_REST|REST|/api/sprints,/api/tasks,/api/users|uv run uvicorn demo.use_case.fastapi:app --port %PORT%"
  "business|UseCase MCP (4-layer)|$PORT_USECASE_MCP|MCP|/mcp|PORT=%PORT% uv run --with fastmcp python -m demo.use_case.mcp_server --http"
  # ── Visualization: Voyager ──
  "viz|Voyager — UseCase service graph|$PORT_VOYAGER_USECASE|Voyager, REST|/voyager,/api/users,/api/sprints|uv run uvicorn demo.use_case.voyager_demo:app --port %PORT%"
  "viz|Voyager — ER + enterprise schema|$PORT_VOYAGER_ER|Voyager|/voyager|uv run uvicorn demo.enterprise_voyager.voyager_demo:app --port %PORT%"
)

# Derive ALL_PORTS from the registry (single source of truth).
ALL_PORTS=()
for record in "${SERVICES[@]}"; do
  ALL_PORTS+=("$(printf '%s' "$record" | cut -d'|' -f3)")
done

PIDS=()

# ── Helpers ───────────────────────────────────────────────────────────────
clear_existing_ports() {
  echo -e "${YELLOW}Freeing demo ports...${NC}"
  for port in "${ALL_PORTS[@]}"; do
    local existing
    existing=$(lsof -ti:"$port" 2>/dev/null || true)
    if [ -n "$existing" ]; then
      echo -e "  ${YELLOW}Port $port in use, stopping old process(es):${NC} $existing"
      kill "$existing" 2>/dev/null || true
      sleep 0.3
      lsof -ti:"$port" 2>/dev/null | xargs kill -9 2>/dev/null || true
    fi
  done
}

cleanup() {
  echo ""
  echo -e "${BLUE}Stopping all services...${NC}"
  for pid in "${PIDS[@]}"; do
    kill -0 "$pid" 2>/dev/null && kill "$pid" 2>/dev/null || true
  done
  for port in "${ALL_PORTS[@]}"; do
    lsof -ti:"$port" 2>/dev/null | xargs kill -9 2>/dev/null || true
  done
  wait 2>/dev/null
  echo -e "${GREEN}All services stopped.${NC}"
}

trap cleanup SIGINT EXIT

wait_for_port() {
  local port=$1
  local name=$2
  local max_attempts=40
  local attempt=0
  printf "  %-38s :%s" "$name" "$port"
  while [ $attempt -lt $max_attempts ]; do
    if lsof -i:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      echo -e " ${GREEN}OK${NC}"
      return 0
    fi
    printf "."
    sleep 0.5
    attempt=$((attempt + 1))
  done
  echo -e " ${RED}TIMEOUT${NC}"
  return 1
}

start_service() {
  # args: group name port tags paths command-template
  local name="$2" port="$3" tags="$4" cmd="$6"
  local resolved="${cmd//\%PORT\%/$port}"
  printf "  ${BLUE}▶${NC} %-34s ${YELLOW}(:%s)${NC} ${CYAN}[%s]${NC}\n" "$name" "$port" "$tags"
  eval "$resolved &"
  PIDS+=($!)
}

# ── Boot ──────────────────────────────────────────────────────────────────
echo "=============================================="
echo -e "${CYAN}nexusx Demo Services${NC}"
echo "=============================================="
echo ""

clear_existing_ports
echo ""

current_group=""
for record in "${SERVICES[@]}"; do
  IFS='|' read -r group name port tags paths cmd <<< "$record"
  if [ "$group" != "$current_group" ]; then
    current_group="$group"
    echo -e "${CYAN}── ${GROUP_TITLE[$group]} ──${NC}"
  fi
  start_service "$group" "$name" "$port" "$tags" "$paths" "$cmd"
done
echo ""

# ── Wait for readiness ────────────────────────────────────────────────────
echo -e "${YELLOW}Waiting for services to be ready...${NC}"
for record in "${SERVICES[@]}"; do
  IFS='|' read -r group name port tags paths cmd <<< "$record"
  wait_for_port "$port" "$name" || true
done
echo ""

# ── Status table (grouped, with capability tags + all endpoints) ───────────
echo "=============================================="
echo -e "${CYAN}Service Status${NC}"
echo "=============================================="
current_group=""
for record in "${SERVICES[@]}"; do
  IFS='|' read -r group name port tags paths cmd <<< "$record"
  if [ "$group" != "$current_group" ]; then
    current_group="$group"
    echo -e "${CYAN}── ${GROUP_TITLE[$group]} ──${NC}"
  fi
  printf "  %-34s :%-5s  ${CYAN}[%s]${NC}\n" "$name" "$port" "$tags"
  IFS=',' read -ra path_list <<< "$paths"
  for p in "${path_list[@]}"; do
    printf "      http://localhost:%s%s\n" "$port" "$p"
  done
done
echo "=============================================="
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"
echo ""

# Wait for all background processes
wait
