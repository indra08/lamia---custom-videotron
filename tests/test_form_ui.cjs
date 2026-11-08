const {test}=require('node:test');
const assert=require('node:assert/strict');
const dates=require('../static/date-picker.js');
const form=require('../static/form-utils.js');

test('WIB conversion does not depend on the browser timezone',()=>{
  assert.equal(dates.toISO('2026-11-12T09:30'),'2026-11-12T02:30:00.000Z');
  assert.equal(dates.wibValue(new Date('2026-11-12T02:30:00Z')),'2026-11-12T09:30');
  assert.equal(dates.plusHours('2026-12-31T22:15',24),'2027-01-01T22:15');
});
test('minimum starts at least 24 hours ahead and rounds to a quarter hour',()=>{
  const now=new Date('2026-11-09T10:14:30Z');
  const min=dates.minimum(now);
  assert.equal(min,'2026-11-10T17:30');
  assert.ok(new Date(dates.toISO(min))-now>=86400000);
});
test('calendar has a Monday-first layout and handles leap days and year boundaries',()=>{
  const feb=dates.monthDays(2028,1);
  assert.equal(feb[0],null);
  assert.equal(feb[1],'2028-02-01');
  assert.equal(feb.filter(Boolean).length,29);
  assert.ok(feb.includes('2028-02-29'));
  assert.equal(dates.monthDays(2027,0).filter(Boolean)[0],'2027-01-01');
});
test('reject invalid calendar dates, missing values and short campaign windows',()=>{
  assert.throws(()=>dates.toISO('2026-02-30T09:00'),/tidak valid/);
  assert.throws(()=>dates.toISO(''),/Pilih tanggal/);
  const now=new Date('2026-11-09T00:00:00Z');
  assert.deepEqual(dates.validate('2026-11-10T07:00','2026-11-11T07:00',now),{});
  assert.match(dates.validate('2026-11-09T23:00','2026-11-11T07:00',now).start,/24 jam/);
  assert.match(dates.validate('2026-11-10T07:00','2026-11-10T19:00',now).end,/24 jam/);
  assert.deepEqual(Object.keys(dates.validate('','',now)),['start','end']);
});
test('NPWP checks digits while allowing punctuation and preserves leading zeroes',()=>{
  assert.match(form.npwpError('23402348992304'),/saat ini 14 digit/);
  assert.equal(form.npwpError('012345678901234'),'');
  assert.equal(form.npwpError('0123456789012345'),'');
  assert.equal(form.npwpError('01.234.567.8-901.234'),'');
  assert.match(form.npwpError('abc012345678901234'),/hanya boleh/);
});
test('the reported FastAPI 422 becomes an Indonesian field error',()=>{
  const error=form.apiError({detail:[{type:'string_too_short',loc:['body','company','npwp'],input:'23402348992304',ctx:{min_length:15}}]});
  assert.equal(error.fields.npwp,'NPWP harus 15 atau 16 digit; saat ini 14 digit.');
  assert.equal(error.message,error.fields.npwp);
  assert.equal(form.apiError({detail:'Slot sudah terisi'}).message,'Slot sudah terisi');
});


test('development calendar permits the current minute and a short test campaign',()=>{
  dates.configure({immediate_start:true,minimum_lead_minutes:0,minimum_duration_minutes:24,start_grace_seconds:300});
  try {
    const now=new Date('2026-11-09T10:14:30Z');
    assert.equal(dates.minimum(now),'2026-11-09T17:14');
    assert.equal(dates.minimumEnd('2026-11-09T17:14'),'2026-11-09T17:38');
    assert.deepEqual(dates.validate('2026-11-09T17:14','2026-11-09T17:44',now),{});
    assert.match(dates.validate('2026-11-09T17:14','2026-11-09T17:30',now).end,/24 menit/);
    assert.match(dates.validate('2026-11-09T17:08','2026-11-09T17:44',now).start,/5 menit/);
  } finally {dates.configure();}
  assert.equal(dates.durationLabel(),'24 jam');
});
