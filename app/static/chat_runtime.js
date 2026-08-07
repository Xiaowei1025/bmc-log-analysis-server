window.BmcChat = (() => {
  const nearBottom = element => element.scrollHeight - element.scrollTop - element.clientHeight < 80;
  const SEND_ICON = '<span class="chat-button-glyph" aria-hidden="true"><svg viewBox="0 0 24 24" focusable="false"><path d="M12 19V5m0 0 6 6m-6-6-6 6"/></svg></span>';
  const STOP_ICON = '<span class="chat-button-glyph" aria-hidden="true"><svg viewBox="0 0 24 24" focusable="false"><circle cx="12" cy="12" r="9.25"/><rect x="8.25" y="8.25" width="7.5" height="7.5" rx="1"/></svg></span>';

  function mount(options) {
    const input = document.getElementById(options.inputId);
    const send = document.getElementById(options.buttonId);
    const history = document.getElementById(options.historyId);
    const latest = document.getElementById(options.latestButtonId);
    if (!input || !send || !history) return;

    let controller = null;
    let reader = null;
    let stopRequested = false;
    let followOutput = true;
    const draftKey = `bmc-chat-draft:${options.scope}:${options.conversationId}`;

    const resizeInput = () => {
      input.style.height = 'auto';
      input.style.height = `${Math.min(Math.max(input.scrollHeight, 52), 180)}px`;
    };
    const scrollLatest = (force = false) => {
      if (force) {
        history.style.scrollBehavior = 'auto';
        history.scrollTop = history.scrollHeight;
        requestAnimationFrame(() => { history.style.scrollBehavior = ''; });
      } else if (followOutput) {
        history.scrollTop = history.scrollHeight;
      }
      if (latest) latest.hidden = nearBottom(history);
    };
    const updateIdleButton = () => {
      if (!controller) send.disabled = !input.value.trim();
    };
    const setState = state => {
      const running = state === 'running';
      const stopping = state === 'stopping';
      const label = running ? '停止' : stopping ? '正在停止…' : '发送';
      send.innerHTML = running || stopping ? STOP_ICON : SEND_ICON;
      send.setAttribute('aria-label', running ? '停止生成' : stopping ? '正在停止生成' : '发送');
      send.setAttribute('title', label);
      send.dataset.state = state;
      send.classList.toggle('primary', state === 'idle');
      send.classList.toggle('stop-button', running || stopping);
      send.disabled = stopping || (state === 'idle' && !input.value.trim());
      history.setAttribute('aria-busy', String(running || stopping));
    };
    const stoppedText = text => {
      let value = text;
      if (value.includes('[[BMC_REASONING_START]]') && !value.includes('[[BMC_REASONING_END]]')) {
        value += '[[BMC_REASONING_END]]';
      }
      return `${value}\n\n> 已停止生成。`;
    };
    const addActions = (article, output, question = '') => {
      const actions = document.createElement('div');
      actions.className = 'message-actions';
      const copy = document.createElement('button');
      copy.type = 'button';
      copy.className = 'message-action';
      copy.textContent = '复制';
      copy.onclick = async () => {
        const value = output.dataset.markdownSource || output.textContent || '';
        try {
          await navigator.clipboard.writeText(value);
          copy.textContent = '已复制';
          window.setTimeout(() => { copy.textContent = '复制'; }, 1500);
        } catch (_) {
          copy.textContent = '复制失败';
        }
      };
      actions.append(copy);
      if (question) {
        const retry = document.createElement('button');
        retry.type = 'button';
        retry.className = 'message-action';
        retry.textContent = '重新生成';
        retry.onclick = () => {
          if (controller) return;
          input.value = question;
          resizeInput();
          updateIdleButton();
          ask();
        };
        actions.append(retry);
      }
      article.append(actions);
    };
    const addBubble = (role, text, question = '') => {
      const article = document.createElement('article');
      const label = document.createElement('small');
      const output = document.createElement('div');
      article.className = `chat-bubble ${role}`;
      label.textContent = role === 'user' ? '你' : '运维助手';
      output.className = role === 'assistant' ? 'markdown-output' : 'message-text';
      article.append(label, output);
      if (role === 'assistant') {
        output.dataset.markdownSource = text;
        BmcMarkdown.renderAssistantTo(output, text);
        addActions(article, output, question);
      } else {
        output.textContent = text;
        const edit = document.createElement('button');
        edit.type = 'button';
        edit.className = 'message-action edit-message';
        edit.textContent = '编辑后重问';
        edit.onclick = () => {
          if (controller) return;
          input.value = text;
          input.focus();
          resizeInput();
          updateIdleButton();
        };
        article.append(edit);
      }
      history.append(article);
      scrollLatest();
      return {article, output};
    };
    const decorateHistory = () => {
      const articles = [...history.querySelectorAll('.chat-bubble')];
      articles.forEach((article, index) => {
        const output = article.querySelector('.markdown-output');
        if (output) {
          output.dataset.markdownSource = output.textContent || '';
          BmcMarkdown.renderAssistantTo(output, output.dataset.markdownSource);
          const previous = articles.slice(0, index).reverse().find(item => item.classList.contains('user'));
          addActions(article, output, previous?.querySelector('.message-text')?.textContent || '');
        } else if (article.classList.contains('user')) {
          const text = article.querySelector('.message-text')?.textContent || '';
          const edit = document.createElement('button');
          edit.type = 'button';
          edit.className = 'message-action edit-message';
          edit.textContent = '编辑后重问';
          edit.onclick = () => {
            if (controller) return;
            input.value = text;
            input.focus();
            resizeInput();
            updateIdleButton();
          };
          article.append(edit);
        }
      });
    };
    const stop = () => {
      if (!controller) return;
      stopRequested = true;
      setState('stopping');
      controller.abort();
      if (reader) reader.cancel().catch(() => {});
    };
    async function ask() {
      const question = input.value.trim();
      if (!question || controller) return;
      history.querySelector('.chat-empty')?.remove();
      addBubble('user', question);
      input.value = '';
      sessionStorage.removeItem(draftKey);
      resizeInput();
      stopRequested = false;
      controller = new AbortController();
      setState('running');
      followOutput = true;
      const {article, output} = addBubble('assistant', '正在分析…', question);
      let text = '';
      try {
        const body = new URLSearchParams({
          question,
          conversation_id: String(options.conversationId),
          ...(options.groupId ? {group_id: String(options.groupId)} : {}),
          csrf_token: window.csrfToken || ''
        });
        const response = await fetch(options.endpoint, {
          method: 'POST',
          headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'},
          body,
          signal: controller.signal
        });
        if (!response.ok) throw new Error(response.status === 403 ? '页面已过期，请刷新后重试' : '请求失败');
        reader = response.body.getReader();
        const decoder = new TextDecoder();
        while (true) {
          const chunk = await reader.read();
          if (chunk.done) break;
          text += decoder.decode(chunk.value, {stream: true});
          output.dataset.markdownSource = text;
          BmcMarkdown.renderAssistantTo(output, text, {streaming: true});
          scrollLatest();
        }
        text += decoder.decode();
        if (stopRequested) text = stoppedText(text);
        output.dataset.markdownSource = text;
        BmcMarkdown.renderAssistantTo(output, text);
      } catch (error) {
        if (stopRequested || error.name === 'AbortError') {
          text = stoppedText(text);
          output.dataset.markdownSource = text;
          BmcMarkdown.renderAssistantTo(output, text);
        } else {
          const message = `**生成失败：** ${error.message}\n\n请检查网络或模型配置后点击“重新生成”。`;
          output.dataset.markdownSource = message;
          BmcMarkdown.renderAssistantTo(output, message);
        }
      } finally {
        controller = null;
        reader = null;
        stopRequested = false;
        setState('idle');
        input.focus();
        if (!article.querySelector('.message-actions')) addActions(article, output, question);
        scrollLatest();
      }
    }

    decorateHistory();
    const storedDraft = sessionStorage.getItem(draftKey);
    input.value = input.dataset.contextPrompt === 'true' && input.value.trim()
      ? input.value
      : (storedDraft || input.value);
    resizeInput();
    setState('idle');
    followOutput = true;
    scrollLatest(true);
    requestAnimationFrame(() => scrollLatest(true));
    window.addEventListener('load', () => scrollLatest(true), {once: true});
    window.setTimeout(() => scrollLatest(true), 80);
    input.addEventListener('input', () => {
      sessionStorage.setItem(draftKey, input.value);
      resizeInput();
      updateIdleButton();
    });
    input.addEventListener('keydown', event => {
      // Enter keeps the composer multiline; Ctrl+Enter (Windows/Linux) and
      // Command+Enter (macOS) submit the question.
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        if (!controller) ask();
      }
    });
    history.addEventListener('scroll', () => {
      followOutput = nearBottom(history);
      if (latest) latest.hidden = followOutput;
    });
    if (latest) latest.onclick = () => {
      followOutput = true;
      scrollLatest(true);
    };
    send.onclick = () => controller ? stop() : ask();
  }

  return {mount};
})();
