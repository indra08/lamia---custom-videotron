(function (root, factory) {
  const picker = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = picker;
  else root.VistaraDates = picker;
})(globalThis, function () {
  const DAY = 86400000;
  const defaultPolicy = {immediate_start:false,minimum_lead_minutes:1440,minimum_duration_minutes:1440,start_grace_seconds:0};
  let policy = {...defaultPolicy};
  function configure(settings={}) {policy={...defaultPolicy,...settings};}
  function durationLabel() {return policy.minimum_duration_minutes < 60 ? policy.minimum_duration_minutes+' menit' : policy.minimum_duration_minutes/60+' jam';}
  function minimumEnd(value) {return plusHours(value,policy.minimum_duration_minutes/60);}
  const WIB = 7 * 3600000;
  const pad = n => String(n).padStart(2, '0');
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  function wibValue(date = new Date()) {return new Date(date.getTime() + WIB).toISOString().slice(0, 16);}
  function toISO(value) {
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value || '')) throw Error('Pilih tanggal dan jam tayang terlebih dahulu.');
    const parsed = new Date(value + ':00+07:00');
    if (!Number.isFinite(parsed.getTime()) || wibValue(parsed) !== value) throw Error('Tanggal atau jam tayang tidak valid.');
    return parsed.toISOString();
  }
  function plusHours(value, hours) {return wibValue(new Date(new Date(toISO(value)).getTime() + hours * 3600000));}
  function minimum(now = new Date()) {return policy.immediate_start ? wibValue(now) : wibValue(new Date(Math.ceil((now.getTime() + policy.minimum_lead_minutes*60000 + 60000) / 900000) * 900000));}
  function validate(start, end, now = new Date()) {
    const errors = {};
    let s, e;
    try {s = new Date(toISO(start));} catch (error) {errors.start = error.message;}
    try {e = new Date(toISO(end));} catch (error) {errors.end = error.message;}
    if (s && s.getTime() < now.getTime()+policy.minimum_lead_minutes*60000-policy.start_grace_seconds*1000) errors.start = policy.immediate_start?'Mode development: pilih waktu saat ini (toleransi 5 menit).':'Mulai tayang paling cepat 24 jam dari sekarang.';
    if (s && e && e.getTime() - s.getTime() < policy.minimum_duration_minutes*60000) errors.end = 'Selesai tayang harus minimal '+durationLabel()+' setelah mulai.';
    if(e && e.getTime()<=now.getTime())errors.end='Selesai tayang harus setelah waktu sekarang.';
    return errors;
  }
  function monthDays(year, month) {
    const offset = (new Date(Date.UTC(year, month, 1)).getUTCDay() + 6) % 7;
    const count = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
    return Array.from({length: Math.ceil((offset + count) / 7) * 7}, (_, i) => i >= offset && i < offset + count ? `${year}-${pad(month + 1)}-${pad(i - offset + 1)}` : null);
  }
  function format(value) {
    if (!value) return '';
    try {return new Intl.DateTimeFormat('id-ID', {timeZone:'Asia/Jakarta', day:'numeric', month:'short', year:'numeric'}).format(new Date(toISO(value)));}
    catch {return '';}
  }
  const records = new WeakMap();
  let dialog, current;
  function paintTrigger(input) {
    const record = records.get(input);
    if (!record) return;
    const value = format(input.value);
    record.button.innerHTML = `<span class="date-trigger-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3.5" y="5" width="17" height="16" rx="3"/><path d="M7.5 3v4m9-4v4M3.5 10h17M8 14h.01M12 14h.01M16 14h.01M8 17h.01M12 17h.01"/></svg></span><span class="date-trigger-copy"><span class="${value ? '' : 'muted'}">${escape(value || 'Pilih tanggal tayang')}</span><small>${value ? escape(input.value.slice(11).replace(':', '.')) + ' WIB' : 'Tanggal & waktu · WIB'}</small></span><span class="date-trigger-arrow" aria-hidden="true">⌄</span>`;
    record.button.setAttribute('aria-label', record.label + (value ? ': ' + value + ', ' + input.value.slice(11) + ' WIB' : ', pilih tanggal dan jam'));
    record.button.setAttribute('aria-invalid', input.getAttribute('aria-invalid') || 'false');
  }
  function mount(root = document) {
    root.querySelectorAll('input[data-date-picker]').forEach(input => {
      if (!records.has(input)) {
        const button = document.createElement('button');
        button.type = 'button';
        button.id = input.id + '-picker';
        button.className = 'date-trigger';
        button.setAttribute('aria-haspopup', 'dialog');
        button.setAttribute('aria-controls', 'vistara-date-dialog');
        if (input.getAttribute('aria-describedby')) button.setAttribute('aria-describedby', input.getAttribute('aria-describedby'));
        const label = input.closest('.field')?.querySelector('label');
        if (label) label.htmlFor = button.id;
        input.type = 'hidden';
        input.after(button);
        records.set(input, {button, label: label?.textContent || 'Jadwal tayang'});
        button.onclick = () => open(input);
      }
      paintTrigger(input);
    });
  }
  function refresh(root = document) {root.querySelectorAll('input[data-date-picker]').forEach(paintTrigger);}
  function ensureDialog() {
    if (dialog) return;
    dialog = document.createElement('dialog');
    dialog.id = 'vistara-date-dialog';
    dialog.className = 'date-dialog';
    dialog.setAttribute('aria-labelledby', 'date-dialog-title');
    document.body.append(dialog);
    dialog.addEventListener('click', event => {
      const target = event.target.closest('button');
      if (!target) return;
      if (target.dataset.day) {
        current.day = target.dataset.day;
        const value = current.day + 'T' + current.time;
        if (current.input.min && value < current.input.min) current.time = current.input.min.slice(11);
        renderCalendar(target.dataset.day);
      } else if (target.dataset.month) {
        current.month += Number(target.dataset.month);
        const date = new Date(Date.UTC(current.year, current.month, 1));
        current.year = date.getUTCFullYear();current.month = date.getUTCMonth();
        renderCalendar();
      } else if (target.dataset.quickMinutes) {
        const start=current.input.form?.elements.start?.value || minimum();
        const base=plusHours(start,Number(target.dataset.quickMinutes)/60);
        current.day=base.slice(0,10);current.time=base.slice(11);
        current.year=Number(base.slice(0,4));current.month=Number(base.slice(5,7))-1;
        renderCalendar();
      } else if (target.dataset.quick) {
        const start = current.input.form?.elements.start?.value;
        const base = current.input.name === 'end' && start ? plusHours(start, Number(target.dataset.quick) * 24) : minimum();
        current.day = base.slice(0, 10);current.time = base.slice(11);
        current.year = Number(base.slice(0, 4));current.month = Number(base.slice(5, 7)) - 1;
        renderCalendar();
      } else if (target.dataset.action === 'close') dialog.close();
      else if (target.dataset.action === 'apply') apply();
    });
    dialog.addEventListener('change', event => {
      if (event.target.id !== 'calendar-hour' && event.target.id !== 'calendar-minute') return;
      current.time = dialog.querySelector('#calendar-hour').value + ':' + dialog.querySelector('#calendar-minute').value;
      updateSummary();
    });
    dialog.addEventListener('keydown', event => {
      if (event.key === 'Enter' && event.target.tagName === 'SELECT') {event.preventDefault();apply();return;}
      const target = event.target.closest('[data-day]');
      if (!target) return;
      const offsets = {ArrowLeft:-1, ArrowRight:1, ArrowUp:-7, ArrowDown:7};
      if (!(event.key in offsets)) return;
      event.preventDefault();
      const date = new Date(target.dataset.day + 'T12:00:00Z');
      date.setUTCDate(date.getUTCDate() + offsets[event.key]);
      const day = date.toISOString().slice(0, 10);
      if (current.input.min && day < current.input.min.slice(0, 10)) return;
      current.year = date.getUTCFullYear();current.month = date.getUTCMonth();
      renderCalendar(day);
    });
    dialog.addEventListener('close', () => {if(current)records.get(current.input)?.button.focus();});
  }
  function open(input) {
    ensureDialog();
    if (input.name === 'start') input.min = minimum();
    const initial = input.value || input.min || minimum();
    current = {input, day:initial.slice(0, 10), time:initial.slice(11, 16), year:Number(initial.slice(0, 4)), month:Number(initial.slice(5, 7)) - 1};
    if (input.min && initial < input.min) {
      current.day=input.min.slice(0,10);current.time=input.min.slice(11,16);
      current.year=Number(input.min.slice(0,4));current.month=Number(input.min.slice(5,7))-1;
    }
    renderCalendar();
    dialog.showModal();
    dialog.querySelector(`[data-day="${current.day}"]`)?.focus();
  }
  function calendar(year, month) {
    const date = new Date(Date.UTC(year, month, 1));
    const title = new Intl.DateTimeFormat('id-ID', {timeZone:'UTC',month:'long',year:'numeric'}).format(date);
    const min = current.input.min?.slice(0, 10) || '';
    const today = wibValue().slice(0, 10);
    const start = current.input.form?.elements.start?.value?.slice(0,10);
    const end = current.input.form?.elements.end?.value?.slice(0,10);
    return `<section class="calendar-month" aria-label="${title}"><h3>${title}</h3><div class="calendar-weekdays" aria-hidden="true">${['Sen','Sel','Rab','Kam','Jum','Sab','Min'].map(day=>`<span>${day}</span>`).join('')}</div><div class="calendar-days" role="group" aria-label="Tanggal ${title}">${monthDays(year,month).map(day=>day?`<button type="button" class="calendar-day ${day===current.day?'selected':''} ${day===today?'today':''} ${start&&end&&day>start&&day<end?'in-range':''}" data-day="${day}" ${day<min?'disabled':''} aria-pressed="${day===current.day}" ${day===today?'aria-current="date"':''} aria-label="${new Intl.DateTimeFormat('id-ID',{timeZone:'UTC',weekday:'long',day:'numeric',month:'long',year:'numeric'}).format(new Date(day+'T12:00:00Z'))}">${Number(day.slice(-2))}</button>`:'<span class="calendar-blank" aria-hidden="true"></span>').join('')}</div></section>`;
  }
  function renderCalendar(focusDay) {
    const second = new Date(Date.UTC(current.year,current.month+1,1));
    const minMonth = current.input.min?.slice(0,7) || '';
    const shown = `${current.year}-${pad(current.month+1)}`;
    const endPicker = current.input.name === 'end' && current.input.form?.elements.start?.value;
    const minutes = [...new Set(['00','15','30','45',current.time.slice(3)])].sort();
    dialog.innerHTML = `<div class="date-dialog-heading"><div><div class="eyebrow">JADWAL KAMPANYE</div><h2 id="date-dialog-title">${escape(records.get(current.input).label)}</h2><p>Pilih tanggal dan jam penayangan Anda.</p></div><button type="button" class="date-close" data-action="close" aria-label="Tutup pemilih tanggal">×</button></div><div class="date-quick"><span>${endPicker?'Durasi kampanye':'Pilihan cepat'}</span>${endPicker?(policy.immediate_start?`<button type="button" data-quick-minutes="${policy.minimum_duration_minutes}">${durationLabel()}</button>`:'')+[1,3,7,14].map(n=>`<button type="button" data-quick="${n}">${n} hari</button>`).join(''):`<button type="button" data-quick="1">${policy.immediate_start?'Sekarang':'Paling awal tersedia'}</button>`}<span class="date-zone">WIB · UTC+7</span></div><div class="calendar-navigation"><button type="button" class="calendar-nav" data-month="-1" aria-label="Bulan sebelumnya" ${shown<=minMonth?'disabled':''}>←</button><span>Pilih tanggal</span><button type="button" class="calendar-nav" data-month="1" aria-label="Bulan berikutnya">→</button></div><div class="calendar-months">${calendar(current.year,current.month)}${calendar(second.getUTCFullYear(),second.getUTCMonth())}</div><div class="date-time-row"><div><b>Jam penayangan</b><p>Seluruh jadwal menggunakan Waktu Indonesia Barat.</p></div><div class="date-time-controls"><label for="calendar-hour" class="sr-only">Jam</label><select id="calendar-hour">${Array.from({length:24},(_,h)=>`<option value="${pad(h)}" ${pad(h)===current.time.slice(0,2)?'selected':''}>${pad(h)}</option>`).join('')}</select><span>:</span><label for="calendar-minute" class="sr-only">Menit</label><select id="calendar-minute">${minutes.map(m=>`<option value="${m}" ${m===current.time.slice(3)?'selected':''}>${m}</option>`).join('')}</select><span class="micro">WIB</span></div></div><p id="calendar-error" class="field-error" role="alert"></p><div class="date-dialog-footer"><div><span class="micro">Pilihan Anda</span><p id="calendar-selection" aria-live="polite"></p></div><div class="actions"><button type="button" class="btn ghost" data-action="close">Batal</button><button type="button" class="btn" data-action="apply">Terapkan tanggal →</button></div></div>`;
    updateSummary();
    if(focusDay) dialog.querySelector(`[data-day="${focusDay}"]`)?.focus();
  }
  function updateSummary() {
    const value=current.day+'T'+current.time;
    const invalid=current.input.min && value<current.input.min;
    dialog.querySelector('#calendar-error').textContent=invalid?'Pilih waktu paling cepat '+format(current.input.min)+' pukul '+current.input.min.slice(11)+' WIB.':'';
    dialog.querySelector('#calendar-selection').textContent=format(value)+' · '+current.time.replace(':','.')+' WIB';
    dialog.querySelector('[data-action="apply"]').disabled=!!invalid;
  }
  function apply() {
    const value=current.day+'T'+current.time;
    if(current.input.min&&value<current.input.min)return;
    current.input.value=value;
    paintTrigger(current.input);
    current.input.dispatchEvent(new Event('input',{bubbles:true}));
    current.input.dispatchEvent(new Event('change',{bubbles:true}));
    dialog.close();
  }
  return {mount,refresh,toISO,wibValue,plusHours,minimum,minimumEnd,validate,monthDays,format,configure,durationLabel};
});
