import test from 'node:test';
import assert from 'node:assert/strict';
import { parseEventList, makeChatRequest, parseChatResponse, parseTtsResponse } from './backendContract.js';

const record = { id: 5, user_id: 1, type: 'meeting', title: 'Обсуждение', datetime: '2026-10-23T15:45:00', created_at: '2026-10-21T09:00:00', status: 'pending' };
test('backend RecordList items + datetime becomes frontend event', () => {
  const [event] = parseEventList({ items: [record], count: 1 });
  assert.equal(event.type, 'meeting');
  assert.equal(event.title, 'Обсуждение');
  assert.equal(event.date, '2026-10-23');
  assert.equal(event.time, '15:45');
});
test('chat request matches ChatRequest and carries history', () => {
  assert.deepEqual(makeChatRequest('Привет', 'abc', [{role:'assistant',text:'Добрый день',welcome:true},{role:'user',text:'Встреча'}]), {
    user_id:1,session_id:'abc',text:'Привет',history:[{role:'user',content:'Встреча'}]
  });
});
test('chat response adapts reply_text and action.records', () => {
  const response = parseChatResponse({session_id:'abc', reply_text:'Готово', needs_clarification:false, action:{type:'list',status:'ok',records:[record]}},'abc');
  assert.equal(response.reply, 'Готово');
  assert.equal(response.events[0].time, '15:45');
});
test('tts json uses audio_url and rejects stub', () => {
  assert.equal(parseTtsResponse({audio_url:'/static/tts/speech.mp3'}),'/static/tts/speech.mp3');
  assert.throws(()=>parseTtsResponse({audio_url:'/static/tts/stub.mp3'}),/заглушку/);
});
