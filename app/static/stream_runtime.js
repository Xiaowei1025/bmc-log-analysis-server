window.BmcStream = (() => {
  function mountAll() {
    document.querySelectorAll('[data-stream-url]').forEach(button => {
      if (button.dataset.streamMounted) return;
      button.dataset.streamMounted = '1';
      const idleLabel = button.textContent.trim();
      let controller = null;
      let reader = null;
      let stopping = false;
      const setState = state => {
        button.textContent = state === 'running' ? '停止' : state === 'stopping' ? '正在停止…' : idleLabel;
        button.classList.toggle('primary', state === 'idle');
        button.classList.toggle('stop-button', state !== 'idle');
        button.disabled = state === 'stopping';
        button.setAttribute('aria-label', state === 'running' ? '停止生成' : button.textContent);
      };
      const stop = () => {
        if (!controller) return;
        stopping = true;
        setState('stopping');
        controller.abort();
        if (reader) reader.cancel().catch(() => {});
      };
      const run = async () => {
        const target = document.getElementById(button.dataset.streamTarget);
        if (!target || controller) return;
        target.setAttribute('role', 'status');
        target.setAttribute('aria-live', 'polite');
        controller = new AbortController();
        stopping = false;
        setState('running');
        target.setAttribute('aria-busy', 'true');
        BmcMarkdown.renderTo(target, '正在连接模型…');
        let text = '';
        try {
          const response = await fetch(button.dataset.streamUrl, {signal: controller.signal});
          if (!response.ok) throw new Error('请求失败');
          reader = response.body.getReader();
          const decoder = new TextDecoder();
          while (true) {
            const chunk = await reader.read();
            if (chunk.done) break;
            text += decoder.decode(chunk.value, {stream: true});
            BmcMarkdown.renderTo(target, text);
            target.scrollTop = target.scrollHeight;
          }
          text += decoder.decode();
          BmcMarkdown.renderTo(target, text);
        } catch (error) {
          if (stopping || error.name === 'AbortError') {
            BmcMarkdown.renderTo(target, `${text}\n\n> 已停止生成。`);
          } else {
            BmcMarkdown.renderTo(target, `**分析失败：** ${error.message}\n\n请检查网络或模型配置后重试。`);
          }
        } finally {
          controller = null;
          reader = null;
          stopping = false;
          target.setAttribute('aria-busy', 'false');
          setState('idle');
        }
      };
      setState('idle');
      button.addEventListener('click', () => controller ? stop() : run());
    });
  }
  return {mountAll};
})();
