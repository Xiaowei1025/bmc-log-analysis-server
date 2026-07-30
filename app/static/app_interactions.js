(() => {
  const navToggle = document.getElementById('nav-toggle');
  const mainNav = document.getElementById('main-nav');
  const navScrim = document.getElementById('nav-scrim');
  const setNavOpen = open => {
    if (!navToggle || !mainNav || !navScrim) return;
    mainNav.classList.toggle('is-open', open);
    navToggle.setAttribute('aria-expanded', String(open));
    navToggle.setAttribute('aria-label', open ? '收起主导航' : '展开主导航');
    navScrim.hidden = !open;
    document.body.classList.toggle('nav-open', open);
    if (!open) navToggle.focus();
  };
  navToggle?.addEventListener('click', () => setNavOpen(!mainNav.classList.contains('is-open')));
  navScrim?.addEventListener('click', () => setNavOpen(false));
  mainNav?.querySelectorAll('a').forEach(link => link.addEventListener('click', () => setNavOpen(false)));
  window.addEventListener('keydown', event => {
    if (event.key === 'Escape' && mainNav?.classList.contains('is-open')) setNavOpen(false);
  });
  window.matchMedia('(min-width:1101px)').addEventListener?.('change', event => {
    if (event.matches && mainNav?.classList.contains('is-open')) setNavOpen(false);
  });

  const confirmDialog = document.getElementById('confirm-dialog');
  const confirmTitle = document.getElementById('confirm-title');
  const confirmMessage = document.getElementById('confirm-message');
  const confirmAccept = document.getElementById('confirm-accept');
  let pendingConfirmation = null;
  const closeConfirmation = () => {
    const trigger = pendingConfirmation?.submitter;
    pendingConfirmation = null;
    confirmDialog?.close();
    trigger?.focus();
  };
  document.querySelectorAll('form[data-confirm]').forEach(form => {
    form.addEventListener('submit', event => {
      if (form.dataset.confirmed === 'true') {
        delete form.dataset.confirmed;
        return;
      }
      if (form.dataset.confirmValue && event.submitter?.value !== form.dataset.confirmValue) return;
      event.preventDefault();
      pendingConfirmation = {form, submitter: event.submitter};
      if (confirmTitle) confirmTitle.textContent = form.dataset.confirmTitle || '确认此操作';
      if (confirmMessage) confirmMessage.textContent = form.dataset.confirm || '是否继续？';
      if (confirmAccept) confirmAccept.textContent = form.dataset.confirmAction || event.submitter?.textContent?.trim() || '确认';
      confirmDialog?.showModal();
    });
  });
  document.querySelectorAll('[data-confirm-cancel]').forEach(button => button.addEventListener('click', closeConfirmation));
  confirmAccept?.addEventListener('click', () => {
    if (!pendingConfirmation) return;
    const {form, submitter} = pendingConfirmation;
    pendingConfirmation = null;
    form.dataset.confirmed = 'true';
    confirmDialog?.close();
    form.requestSubmit(submitter || undefined);
  });
  confirmDialog?.addEventListener('click', event => {
    if (event.target === confirmDialog) closeConfirmation();
  });
  confirmDialog?.addEventListener('cancel', event => {
    event.preventDefault();
    closeConfirmation();
  });

  const postForms = document.querySelectorAll('form[method="post"]:not([data-no-pending])');
  postForms.forEach(form => {
    form.addEventListener('submit', event => {
      if (event.defaultPrevented) return;
      if (form.dataset.submitting === 'true') {
        event.preventDefault();
        return;
      }
      const button = event.submitter || form.querySelector('button[type="submit"],button:not([type])');
      if (!button) return;
      form.dataset.submitting = 'true';
      form.setAttribute('aria-busy', 'true');
      button.dataset.idleLabel = button.textContent;
      button.textContent = form.dataset.pendingLabel || '正在处理…';
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
    });
  });

  document.querySelectorAll('[data-conversation-switch]').forEach(select => {
    select.addEventListener('change', () => {
      const template = select.dataset.urlTemplate || '';
      if (template && select.value) window.location.href = template.replace('{id}', encodeURIComponent(select.value));
    });
  });
  document.querySelectorAll('[data-conversation-rename-open]').forEach(trigger => {
    const dialog = document.getElementById(trigger.getAttribute('aria-controls'));
    if (!dialog) return;
    const input = dialog.querySelector('input[name="title"]');
    trigger.addEventListener('click', () => {
      dialog.showModal();
      window.setTimeout(() => {
        input?.focus();
        input?.select();
      }, 0);
    });
    dialog.querySelectorAll('[data-conversation-rename-cancel]').forEach(button => {
      button.addEventListener('click', () => dialog.close());
    });
    dialog.addEventListener('click', event => {
      if (event.target === dialog) dialog.close();
    });
    dialog.addEventListener('close', () => trigger.focus());
  });

  const pendingDraftKey = sessionStorage.getItem('bmc-pending-draft-clear');
  if (pendingDraftKey) {
    if (!document.querySelector('.notice.error')) localStorage.removeItem(pendingDraftKey);
    sessionStorage.removeItem('bmc-pending-draft-clear');
  }
  const draftControls = form => [...form.querySelectorAll('input[name],textarea[name],select[name]')]
    .filter(control => !['csrf_token'].includes(control.name) && !['file', 'password', 'submit'].includes(control.type) && !control.disabled);
  const serializeDraft = form => {
    const values = {};
    draftControls(form).forEach(control => {
      values[control.name] ||= [];
      values[control.name].push({
        type: control.type,
        value: control.value,
        checked: control.checked,
        selected: control.multiple ? [...control.options].filter(option => option.selected).map(option => option.value) : [],
      });
    });
    return {savedAt: Date.now(), values};
  };
  const restoreDraft = (form, draft) => {
    const targetCount = draft.values?.file_patterns?.length || 0;
    const addCondition = document.getElementById('add-condition');
    while (addCondition && form.querySelectorAll('[name="file_patterns"]').length < targetCount) addCondition.click();
    Object.entries(draft.values || {}).forEach(([name, entries]) => {
      const controls = [...form.querySelectorAll(`[name="${CSS.escape(name)}"]`)];
      controls.forEach((control, index) => {
        const value = entries[index];
        if (!value) return;
        if (control.type === 'checkbox' || control.type === 'radio') control.checked = Boolean(value.checked);
        else if (control.multiple) [...control.options].forEach(option => { option.selected = value.selected.includes(option.value); });
        else control.value = value.value;
        control.dispatchEvent(new Event('input', {bubbles: true}));
        control.dispatchEvent(new Event('change', {bubbles: true}));
      });
    });
  };
  document.querySelectorAll('form[data-draft-key]').forEach(form => {
    const storageKey = `bmc-form-draft:${form.dataset.draftKey}`;
    const label = form.dataset.draftLabel || '表单草稿';
    const indicator = document.createElement('div');
    const status = document.createElement('span');
    const clear = document.createElement('button');
    indicator.className = 'draft-status';
    status.textContent = `${label} · 自动保存已开启`;
    clear.type = 'button';
    clear.className = 'text-button';
    clear.textContent = '清除草稿';
    indicator.append(status, clear);
    form.prepend(indicator);
    let restored = false;
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
      if (saved?.values) {
        restored = true;
        restoreDraft(form, saved);
        status.textContent = `${label} · 已恢复 ${new Date(saved.savedAt).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})} 的内容`;
      }
    } catch (_) {
      localStorage.removeItem(storageKey);
    }
    let timer = null;
    const save = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        localStorage.setItem(storageKey, JSON.stringify(serializeDraft(form)));
        status.textContent = `${label} · 已自动保存`;
      }, 350);
    };
    form.addEventListener('input', save);
    form.addEventListener('change', save);
    clear.addEventListener('click', () => {
      localStorage.removeItem(storageKey);
      status.textContent = `${label} · 草稿已清除，后续输入仍会自动保存`;
      clear.focus();
    });
    form.addEventListener('submit', event => {
      if (!event.defaultPrevented) sessionStorage.setItem('bmc-pending-draft-clear', storageKey);
    });
    if (!restored) status.textContent = `${label} · 自动保存已开启`;
  });

  const notices = document.querySelectorAll('.notice[data-transient]');
  notices.forEach(notice => {
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'notice-close';
    close.setAttribute('aria-label', '关闭提示');
    close.textContent = '×';
    close.addEventListener('click', () => notice.remove());
    notice.append(close);
  });
  const successNotices = document.querySelectorAll('.notice.success[data-transient]');
  if (successNotices.length) {
    window.setTimeout(() => successNotices.forEach(notice => notice.classList.add('notice-leaving')), 5200);
    window.setTimeout(() => successNotices.forEach(notice => notice.remove()), 5800);
  }
  if (notices.length) {
    const url = new URL(window.location.href);
    url.searchParams.delete('notice');
    url.searchParams.delete('error');
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
  }
})();
