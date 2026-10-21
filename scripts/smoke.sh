#!/usr/bin/env bash
set -e

BASE_URL="${1:-http://127.0.0.1:8000}"

echo "=========================================="
echo "SMOKE TEST: Voice Assistant API"
echo "Target: ${BASE_URL}"
echo "=========================================="

echo -n "1. Checking /health ... "
HEALTH_RESP=$(curl -s "${BASE_URL}/health")
echo "${HEALTH_RESP}" | grep -q '"status":"ok"' && echo "OK" || (echo "FAIL: ${HEALTH_RESP}"; exit 1)

echo -n "2. Checking /chat (create meeting) ... "
CHAT_RESP=$(curl -s -X POST "${BASE_URL}/chat" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "smoke_1", "text": "Добавь встречу с командой завтра в 15:00"}')
echo "${CHAT_RESP}" | grep -q '"type":"create_meeting"' && echo "OK" || (echo "FAIL: ${CHAT_RESP}"; exit 1)

echo -n "3. Checking /chat (clarification dialog) ... "
CLARIFY_RESP=$(curl -s -X POST "${BASE_URL}/chat" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "smoke_2", "text": "Поставь встречу с Иваном завтра"}')
echo "${CLARIFY_RESP}" | grep -q '"needs_clarification":true' && echo "OK" || (echo "FAIL: ${CLARIFY_RESP}"; exit 1)

echo -n "4. Checking /events (list) ... "
EVENTS_RESP=$(curl -s "${BASE_URL}/events")
echo "${EVENTS_RESP}" | grep -q '"items":' && echo "OK" || (echo "FAIL: ${EVENTS_RESP}"; exit 1)

echo -n "5. Checking /events/search ... "
SEARCH_RESP=$(curl -s -G "${BASE_URL}/events/search" --data-urlencode "q=команда")
echo "${SEARCH_RESP}" | grep -q '"items":' && echo "OK" || (echo "FAIL: ${SEARCH_RESP}"; exit 1)

echo -n "6. Checking /tts ... "
TTS_RESP=$(curl -s -X POST "${BASE_URL}/tts" \
  -H "Content-Type: application/json" \
  -d '{"text": "Привет! Это проверка синтеза речи."}')
echo "${TTS_RESP}" | grep -q '"audio_url":' && echo "OK" || (echo "FAIL: ${TTS_RESP}"; exit 1)

echo "=========================================="
echo "ALL SMOKE TESTS PASSED SUCCESSFULLY!"
echo "=========================================="
