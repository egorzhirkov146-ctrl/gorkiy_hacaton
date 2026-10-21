import test from 'node:test';
import assert from 'node:assert/strict';
import { fromCsv, filterEvents, getRange, toDateKey } from './events.js';

test('CSV has no invented type/status', () => {
  assert.deepEqual(fromCsv({id:'4',date:'2026-10-21',time:'12:00',text:'Проверить документ'}), {
    id: 'csv-4', title: 'Проверить документ', date:'2026-10-21', time:'12:00',
    type:'event',status:null,source:'csv',
  });
});

test('week starts Monday, ends Sunday and respects local calendar', () => {
  const range = getRange('week', new Date(2026, 9, 21));
  assert.deepEqual(range,{from:'2026-10-19',to:'2026-10-25'});
  assert.equal(toDateKey(new Date(2026, 0, 1)), '2026-01-01');
});

test('period, type and search are combined', () => {
  const list = [
    {id:'1',date:'2026-10-21',time:'10:00',title:'Иван',type:'meeting'},
    {id:'2',date:'2026-10-21',time:'09:00',title:'Иван',type:'task'},
    {id:'3',date:'2026-10-22',time:'10:00',title:'Иван',type:'meeting'},
  ];
  assert.deepEqual(filterEvents(list,{period:'today',type:'meeting',search:'иван'},new Date(2026,9,21)).map(e=>e.id),['1']);
});
