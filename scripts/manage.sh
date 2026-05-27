#!/usr/bin/env bash
# ============================================================
# MindMap System — Management Script
# ============================================================
set -e

COMPOSE_CMD="docker compose"
ENV_FILE=".env"

check_env() {
    if [ ! -f "$ENV_FILE" ]; then
        echo "⚠  .env not found. Copying from .env.example..."
        cp .env.example .env
        echo "✏  Edit .env and set your API keys, then re-run."
        exit 1
    fi
    # Warn if BOTH cloud keys are still placeholders
    # (Ollama alone will work, but cloud keys give better quality)
    if grep -q "^GEMINI_API_KEY=your_gemini_api_key_here" "$ENV_FILE" && \
       grep -q "^GROQ_API_KEY=your_groq_api_key_here" "$ENV_FILE"; then
        echo "ℹ  No cloud API keys set — will use Ollama (local) only."
        echo "   For better quality add keys:"
        echo "   Gemini: https://aistudio.google.com/apikey"
        echo "   Groq:   https://console.groq.com/keys"
    fi
}

cmd_start() {
    check_env
    echo "🚀 Starting MindMap system..."
    echo "   Note: Ollama will download the model on first run (~2GB). This may take a few minutes."
    $COMPOSE_CMD up -d --build
    echo ""
    echo "✅ Services started!"
    echo "   Frontend:    http://localhost:3000"
    echo "   API Gateway: http://localhost:8000"
    echo "   API Docs:    http://localhost:8000/docs"
    echo "   Ollama:      http://localhost:11434"
    echo ""
    echo "   Watch Ollama download: docker compose logs -f ollama"
}

cmd_stop() {
    echo "🛑 Stopping all services..."
    $COMPOSE_CMD down
}

cmd_restart() {
    $COMPOSE_CMD down
    $COMPOSE_CMD up -d --build
}

cmd_logs() {
    $COMPOSE_CMD logs -f --tail=100 ${2:-}
}

cmd_status() {
    echo "📊 Service status:"
    $COMPOSE_CMD ps
    echo ""
    echo "📊 Ollama models downloaded:"
    docker exec $(docker ps -q -f name=mindmap-fixed-ollama-1 2>/dev/null || \
                  docker ps -q -f name=mindmap_fixed_ollama_1 2>/dev/null || \
                  echo "ollama") ollama list 2>/dev/null || echo "  (ollama not running)"
}

cmd_demo() {
    echo "📄 Uploading sample document..."
    RESPONSE=$(curl -s -X POST http://localhost:8000/api/v1/documents/upload \
        -F "file=@docs/sample_document.txt")
    echo "Response: $RESPONSE"
    DOC_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['document_id'])" 2>/dev/null)
    if [ -n "$DOC_ID" ]; then
        echo "Document ID: $DOC_ID"
        echo "Watch progress at: http://localhost:3000"
        echo "Or poll: curl http://localhost:8000/api/v1/documents/$DOC_ID/status"
    fi
}

cmd_test() {
    echo "🧪 Running unit tests..."
    pip install pytest --quiet 2>/dev/null
    python -m pytest tests/unit/ -v
}

cmd_clean() {
    echo "🧹 Removing all containers and volumes (including Ollama model)..."
    $COMPOSE_CMD down -v --rmi local
    echo "Done."
}

cmd_pull_model() {
    MODEL=${2:-llama3.2}
    echo "📥 Pulling Ollama model: $MODEL"
    docker exec $(docker ps -q -f name=ollama) ollama pull $MODEL
    echo "✅ Model ready: $MODEL"
}

case "${1:-help}" in
    start)     cmd_start ;;
    stop)      cmd_stop ;;
    restart)   cmd_restart ;;
    logs)      cmd_logs "$@" ;;
    status)    cmd_status ;;
    demo)      cmd_demo ;;
    test)      cmd_test ;;
    clean)     cmd_clean ;;
    pull-model) cmd_pull_model "$@" ;;
    help|*)
        echo ""
        echo "  MindMap AI — Management Script"
        echo ""
        echo "  Commands:"
        echo "    start          Build and start all services"
        echo "    stop           Stop all services"
        echo "    restart        Rebuild and restart"
        echo "    logs [service] Tail logs (all or specific)"
        echo "    status         Show service + Ollama model status"
        echo "    demo           Upload sample document"
        echo "    test           Run unit tests"
        echo "    clean          Remove everything including model cache"
        echo "    pull-model [name]  Pull a different Ollama model"
        echo ""
        echo "  LLM cascade: Gemini → Groq → Ollama (local, no rate limits)"
        echo ""
        ;;
esac
