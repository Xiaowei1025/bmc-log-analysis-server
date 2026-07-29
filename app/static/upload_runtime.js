(() => {
  const form = document.querySelector('[data-upload-form]');
  if (!form) return;
  const input = form.querySelector('input[type="file"][multiple]');
  const dropZone = form.querySelector('.upload-drop-zone');
  const selection = document.getElementById('upload-selection');
  const list = document.getElementById('upload-file-list');
  const summary = document.getElementById('upload-selection-summary');
  const clear = document.getElementById('upload-clear');
  const submit = document.getElementById('upload-submit');
  const errorBox = document.getElementById('upload-error');
  const processing = document.getElementById('upload-processing');
  const processingCopy = document.getElementById('upload-processing-copy');
  const allowed = ['.tar.gz', '.tgz', '.tar', '.zip', '.gz', '.log', '.txt'];
  const maxBytes = Number(input?.dataset.maxMb || 200) * 1024 * 1024;

  const formatSize = bytes => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  };
  const validationError = file => {
    const name = file.name.toLowerCase();
    if (!allowed.some(suffix => name.endsWith(suffix))) return '不支持的文件格式';
    if (file.size > maxBytes) return `超过 ${input.dataset.maxMb || 200} MB`;
    if (!file.size) return '文件为空';
    return '';
  };
  const replaceFiles = files => {
    if (typeof DataTransfer === 'undefined') return;
    const transfer = new DataTransfer();
    [...files].forEach(file => transfer.items.add(file));
    input.files = transfer.files;
  };
  const render = () => {
    const files = [...(input.files || [])];
    const invalid = files.map(file => ({file, error: validationError(file)})).filter(item => item.error);
    selection.hidden = files.length === 0;
    list.replaceChildren();
    files.forEach((file, index) => {
      const item = document.createElement('li');
      const copy = document.createElement('div');
      const name = document.createElement('strong');
      const meta = document.createElement('small');
      const remove = document.createElement('button');
      const issue = validationError(file);
      name.textContent = file.name;
      meta.textContent = `${formatSize(file.size)}${issue ? ` · ${issue}` : ' · 可以分析'}`;
      if (issue) item.classList.add('invalid');
      copy.append(name, meta);
      remove.type = 'button';
      remove.className = 'text-button';
      remove.textContent = '移除';
      remove.setAttribute('aria-label', `移除 ${file.name}`);
      remove.addEventListener('click', () => {
        replaceFiles(files.filter((_, current) => current !== index));
        render();
        input.focus();
      });
      item.append(copy, remove);
      list.append(item);
    });
    const total = files.reduce((sum, file) => sum + file.size, 0);
    summary.textContent = files.length ? `${files.length} 个文件 · 共 ${formatSize(total)}` : '';
    errorBox.hidden = invalid.length === 0;
    errorBox.textContent = invalid.length ? `有 ${invalid.length} 个文件不能上传，请移除或更换后再继续。` : '';
    submit.disabled = files.length === 0 || invalid.length > 0;
  };

  input?.addEventListener('change', render);
  clear?.addEventListener('click', () => {
    replaceFiles([]);
    render();
    input.focus();
  });
  dropZone?.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      input.click();
    }
  });
  ['dragenter', 'dragover'].forEach(type => dropZone?.addEventListener(type, event => {
    event.preventDefault();
    dropZone.classList.add('is-dragging');
  }));
  ['dragleave', 'drop'].forEach(type => dropZone?.addEventListener(type, event => {
    event.preventDefault();
    dropZone.classList.remove('is-dragging');
  }));
  dropZone?.addEventListener('drop', event => {
    if (event.dataTransfer?.files?.length) {
      replaceFiles(event.dataTransfer.files);
      render();
    }
  });
  form.addEventListener('submit', event => {
    const files = [...(input.files || [])];
    if (!files.length || files.some(validationError)) {
      event.preventDefault();
      render();
      errorBox.hidden = false;
      errorBox.textContent = '请先选择有效的日志文件。';
      return;
    }
    form.dataset.pendingLabel = `正在分析 ${files.length} 份日志…`;
    processing.hidden = false;
    processingCopy.textContent = `${files.length} 份日志正在上传并逐份解析，请保持页面打开。`;
    dropZone.classList.add('is-processing');
  });
  render();
})();
