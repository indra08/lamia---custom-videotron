/* Progressive enhancement: keep native values, forms, and change handlers intact. */
(function () {
  const records = new WeakMap();
  let openRecord = null, sequence = 0, search = '', searchTimer;
  const arrow = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m6 8 4 4 4-4" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function labelFor(select) {
    const label = Array.from(select.labels || [])[0];
    return {label, name: select.getAttribute('aria-label') || label?.textContent.trim() || 'Pilih opsi'};
  }

  function sync(record) {
    const {select, button, text} = record;
    text.textContent = select.selectedOptions[0]?.textContent || 'Pilih opsi';
    button.disabled = select.disabled;
    button.setAttribute('aria-invalid', select.getAttribute('aria-invalid') || 'false');
    button.setAttribute('aria-required', String(select.required));
    if (select.getAttribute('aria-describedby')) button.setAttribute('aria-describedby', select.getAttribute('aria-describedby'));
    if (openRecord === record && select.disabled) close();
    if (openRecord === record) {
      record.active = select.selectedIndex;
      renderOptions(record);
    }
  }

  function close(restoreFocus = false) {
    if (!openRecord) return;
    const record = openRecord;
    openRecord = null;
    record.button.setAttribute('aria-expanded', 'false');
    record.button.removeAttribute('aria-activedescendant');
    record.wrapper.classList.remove('is-open');
    if (record.menu.hasAttribute('popover')) record.menu.hidePopover();
    record.menu.remove();
    record.menu = null;
    clearTimeout(searchTimer);search = '';
    if (restoreFocus && record.button.isConnected) record.button.focus();
  }

  function disabled(option) {
    return option.disabled || option.hidden || (option.parentElement?.tagName === 'OPTGROUP' && option.parentElement.disabled);
  }

  function renderOptions(record) {
    const menu = record.menu;
    menu.replaceChildren();
    let group = null;
    Array.from(record.select.options).forEach((option, index) => {
      if (option.hidden) return;
      const parent = option.parentElement;
      if (parent.tagName === 'OPTGROUP' && group !== parent) {
        group = parent;
        const heading = document.createElement('div');
        heading.className = 'dropdown-group';heading.textContent = parent.label;
        heading.setAttribute('role', 'presentation');menu.append(heading);
      }
      const row = document.createElement('div');
      row.id = record.id + '-option-' + index;
      row.className = 'dropdown-option';
      row.dataset.index = index;
      row.setAttribute('role', 'option');
      row.setAttribute('aria-selected', String(index === record.select.selectedIndex));
      if (disabled(option)) row.setAttribute('aria-disabled', 'true');
      const caption = document.createElement('span');caption.textContent = option.textContent;
      const check = document.createElement('span');check.className = 'dropdown-check';check.textContent = '✓';check.setAttribute('aria-hidden', 'true');
      row.append(caption, check);menu.append(row);
    });
    if (!menu.children.length) {
      const empty = document.createElement('div');empty.className = 'dropdown-empty';empty.textContent = 'Belum ada pilihan';menu.append(empty);
    }
    highlight(record, record.active);
  }

  function highlight(record, index) {
    if (index < 0 || !record.select.options[index] || disabled(record.select.options[index])) return;
    record.active = index;
    record.menu.querySelectorAll('[data-index]').forEach(row => row.classList.toggle('is-highlighted', Number(row.dataset.index) === index));
    const option = document.getElementById(record.id + '-option-' + index);
    if (!option) return;
    record.button.setAttribute('aria-activedescendant', option.id);
    // Scroll only the option list, not the underlying form or dialog.
    if (option.offsetTop < record.menu.scrollTop) record.menu.scrollTop = option.offsetTop;
    else if (option.offsetTop + option.offsetHeight > record.menu.scrollTop + record.menu.clientHeight) record.menu.scrollTop = option.offsetTop + option.offsetHeight - record.menu.clientHeight;
  }

  function position(record) {
    const rect = record.button.getBoundingClientRect();
    const width = Math.min(Math.max(rect.width, 132), window.innerWidth - 24);
    const below = window.innerHeight - rect.bottom - 16;
    const above = rect.top - 16;
    const up = below < 180 && above > below;
    const height = Math.min(280, Math.max(70, up ? above : below));
    record.menu.style.width = width + 'px';
    record.menu.style.maxHeight = height + 'px';
    record.menu.style.left = Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)) + 'px';
    record.menu.style.top = (up ? rect.top - Math.min(record.menu.scrollHeight, height) - 6 : rect.bottom + 6) + 'px';
    record.menu.classList.toggle('opens-up', up);
  }

  function open(record) {
    if (record.select.disabled) return;
    close();
    openRecord = record;
    record.active = record.select.selectedIndex;
    if (record.active < 0 || disabled(record.select.options[record.active])) record.active = Array.from(record.select.options).findIndex(option => !disabled(option));
    const menu = document.createElement('div');
    record.menu = menu;
    menu.id = record.id + '-list';menu.className = 'dropdown-menu';
    menu.setAttribute('role', 'listbox');menu.setAttribute('aria-label', record.name);
    // The top layer keeps options visible above the calendar and admin dialogs.
    if (typeof menu.showPopover === 'function') menu.setAttribute('popover', 'manual');
    (record.select.closest('dialog') || document.body).append(menu);
    menu.addEventListener('pointerdown', event => event.preventDefault());
    menu.addEventListener('pointermove', event => {
      if (event.pointerType === 'touch') return;
      const row = event.target.closest('[data-index]');
      if (row) highlight(record, Number(row.dataset.index));
    });
    menu.addEventListener('click', event => {
      const row = event.target.closest('[data-index]');
      if (row) choose(record, Number(row.dataset.index));
    });
    record.wrapper.classList.add('is-open');
    record.button.setAttribute('aria-expanded', 'true');
    renderOptions(record);
    if (menu.hasAttribute('popover')) menu.showPopover();
    position(record);
    highlight(record, record.active);
  }

  function choose(record, index) {
    const option = record.select.options[index];
    if (!option || disabled(option)) return;
    const changed = record.select.selectedIndex !== index;
    record.select.selectedIndex = index;
    close(true);
    sync(record);
    if (changed) {
      record.select.dispatchEvent(new Event('input', {bubbles:true}));
      record.select.dispatchEvent(new Event('change', {bubbles:true}));
    }
  }

  function move(record, step) {
    const options = Array.from(record.select.options);
    let index = record.active;
    for (let i = 0; i < options.length; i++) {
      index += step;
      if (index < 0 || index >= options.length) return;
      if (!disabled(options[index])) {highlight(record, index);return;}
    }
  }

  function keydown(record, event) {
    const isOpen = openRecord === record;
    if (event.key === 'Tab') {close();return;}
    if (event.key === 'Escape') {if(isOpen){event.preventDefault();event.stopPropagation();close(true);}return;}
    if (['ArrowDown','ArrowUp','Home','End','Enter',' '].includes(event.key)) {
      event.preventDefault();event.stopPropagation();
      if (!isOpen) {open(record);return;}
      if (event.key === 'Enter' || event.key === ' ') {choose(record, record.active);return;}
      if (event.key === 'Home' || event.key === 'End') {
        const options = Array.from(record.select.options);
        const index = event.key === 'Home' ? options.findIndex(option => !disabled(option)) : options.findLastIndex(option => !disabled(option));
        highlight(record, index);
      } else move(record, event.key === 'ArrowDown' ? 1 : -1);
      return;
    }
    if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();if(!isOpen)open(record);
      search += event.key.toLocaleLowerCase('id-ID');
      clearTimeout(searchTimer);searchTimer=setTimeout(()=>{search='';},700);
      const index=Array.from(record.select.options).findIndex(option=>!disabled(option)&&option.textContent.trim().toLocaleLowerCase('id-ID').startsWith(search));
      if(index>=0)highlight(record,index);
    }
  }

  function enhance(select) {
    if (select.multiple || select.size > 1 || select.hasAttribute('data-native-select')) return;
    if (records.has(select)) {sync(records.get(select));return;}
    const {label, name} = labelFor(select);
    const id = 'vistara-select-' + (++sequence);
    const wrapper=document.createElement('span');wrapper.className='custom-select';
    const button=document.createElement('button');button.type='button';button.className='dropdown-trigger';button.id=id;
    button.setAttribute('role','combobox');button.setAttribute('aria-label',name);
    button.setAttribute('aria-haspopup','listbox');button.setAttribute('aria-controls',id+'-list');button.setAttribute('aria-expanded','false');
    const text=document.createElement('span');text.className='dropdown-value';
    const icon=document.createElement('span');icon.className='dropdown-chevron';icon.innerHTML=arrow;
    button.append(text,icon);
    select.before(wrapper);wrapper.append(select,button);
    select.classList.add('enhanced-select-native');select.tabIndex=-1;select.setAttribute('aria-hidden','true');
    if (label) label.htmlFor=button.id;
    const record={select,button,text,wrapper,id,name,menu:null,active:-1};records.set(select,record);
    button.onclick=()=>openRecord===record?close(true):open(record);
    button.onkeydown=event=>keydown(record,event);
    button.onblur=()=>{if(openRecord===record)close();};
    select.addEventListener('change',()=>sync(record));
    select.addEventListener('invalid',event=>{event.preventDefault();button.setAttribute('aria-invalid','true');button.focus();});
    select.form?.addEventListener('reset',()=>queueMicrotask(()=>sync(record)));
    sync(record);
  }

  function mount(root=document) {
    if(root.matches?.('select'))enhance(root);
    root.querySelectorAll?.('select').forEach(enhance);
  }

  document.addEventListener('pointerdown',event=>{if(openRecord&&!openRecord.wrapper.contains(event.target)&&!openRecord.menu.contains(event.target))close();},true);
  document.addEventListener('scroll',event=>{if(openRecord&&!openRecord.menu.contains(event.target))close();},true);
  window.addEventListener('resize',()=>close());
  document.addEventListener('close',()=>{if(openRecord&&!openRecord.select.closest('dialog')?.open)close();},true);
  const observer=new MutationObserver(changes=>{
    if(openRecord&&!openRecord.select.isConnected)close();
    for(const change of changes){
      if(change.target.tagName==='SELECT'&&records.has(change.target)){sync(records.get(change.target));continue;}
      if(change.target.tagName==='OPTION'){
        const select=change.target.closest('select');if(select&&records.has(select))sync(records.get(select));
      }
      change.addedNodes?.forEach(node=>{if(node.nodeType===1)mount(node);});
    }
  });
  mount();
  observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['disabled','selected','required','aria-invalid','aria-describedby']});
  window.VistaraDropdown={mount,close};
})();
