// ═══════════════════════════════════════════════════════════════════════
// PRESET CARD SELECTION
// ═══════════════════════════════════════════════════════════════════════
const OVERLAY_PRESETS = window.OVERLAY_PRESETS || {};

function setupCardSelection(gridId) {
  const grid = document.getElementById(gridId);
  if (!grid) return;
  grid.querySelectorAll('label').forEach(card => {
    card.addEventListener('click', () => {
      grid.querySelectorAll('label').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
    });
  });
}
setupCardSelection('cropGrid');
setupCardSelection('qualityGrid');
setupCardSelection('subtitleGrid');
setupCardSelection('sourceGrid');
setupCardSelection('overlayPresetGrid');
setupCardSelection('translateTargetGrid');

const overlayPresetInput = document.getElementById('overlayPresetInput');
const overlayPresetGrid = document.getElementById('overlayPresetGrid');

function markOverlayPresetCustom() {
  if (!overlayPresetInput || !overlayPresetGrid) return;
  overlayPresetInput.value = 'custom';
  overlayPresetGrid.querySelectorAll('label').forEach((el) => el.classList.remove('selected'));
  overlayPresetGrid.querySelectorAll('input[type="radio"]').forEach((el) => {
    el.checked = false;
  });
}

function applyOverlayPreset(presetKey) {
  const cfg = OVERLAY_PRESETS[presetKey];
  if (!cfg) return;

  document.getElementById('subtitleFontSize').value = cfg.subtitle_font_size;
  document.getElementById('subtitleBottomMargin').value = cfg.subtitle_bottom_margin;
  document.getElementById('subtitleMaxChars').value = cfg.subtitle_max_chars;
  document.getElementById('sourceTagScale').value = Number(cfg.source_tag_scale).toFixed(2);
  document.getElementById('sourceTagPosition').value = cfg.source_tag_position;

  overlayPresetInput.value = presetKey;
  overlayPresetGrid.querySelectorAll('label').forEach((card) => {
    card.classList.toggle('selected', card.getAttribute('data-overlay-preset') === presetKey);
  });
  overlayPresetGrid.querySelectorAll('input[type="radio"]').forEach((radio) => {
    radio.checked = radio.value === presetKey;
  });

  updateSliderLabels();
  updateOverlaySimulator();
}

if (overlayPresetGrid) {
  overlayPresetGrid.addEventListener('click', (event) => {
    const card = event.target.closest('label[data-overlay-preset]');
    if (!card) return;
    const presetKey = card.getAttribute('data-overlay-preset');
    if (!presetKey) return;
    applyOverlayPreset(presetKey);
  });
}

// ═══════════════════════════════════════════════════════════════════════
// TOGGLE SECTIONS
// ═══════════════════════════════════════════════════════════════════════
document.getElementById('useSubtitle').addEventListener('change', function() {
  document.getElementById('subtitleOptions').style.display = this.checked ? '' : 'none';
  updateOverlaySimulator();
});
document.getElementById('useSourceTag').addEventListener('change', function() {
  document.getElementById('sourceOptions').style.display = this.checked ? '' : 'none';
  updateOverlaySimulator();
});

const translateSubtitleEl = document.getElementById('translateSubtitle');
if (translateSubtitleEl) {
  translateSubtitleEl.addEventListener('change', function() {
    document.getElementById('translateOptions').style.display = this.checked ? '' : 'none';
  });
}

function updateSliderLabels() {
  const intervalSlider = document.getElementById('sourceInterval');
  const subtitleFontSize = document.getElementById('subtitleFontSize');
  const subtitleBottomMargin = document.getElementById('subtitleBottomMargin');
  const subtitleMaxChars = document.getElementById('subtitleMaxChars');
  const sourceTagScale = document.getElementById('sourceTagScale');
  const previewTime = document.getElementById('previewTime');

  if (intervalSlider) {
    document.getElementById('intervalValue').textContent = intervalSlider.value + 's';
  }
  if (subtitleFontSize) {
    document.getElementById('subtitleFontSizeValue').textContent = subtitleFontSize.value + 'px';
  }
  if (subtitleBottomMargin) {
    document.getElementById('subtitleBottomMarginValue').textContent = subtitleBottomMargin.value + 'px';
  }
  if (subtitleMaxChars) {
    document.getElementById('subtitleMaxCharsValue').textContent = subtitleMaxChars.value;
  }
  if (sourceTagScale) {
    document.getElementById('sourceTagScaleValue').textContent = Number(sourceTagScale.value).toFixed(2) + 'x';
  }
  if (previewTime) {
    document.getElementById('previewTimeValue').textContent = previewTime.value + 's';
  }
}

['sourceInterval', 'subtitleFontSize', 'subtitleBottomMargin', 'subtitleMaxChars', 'sourceTagScale', 'previewTime'].forEach((id) => {
  const input = document.getElementById(id);
  if (!input) return;
  input.addEventListener('input', () => {
    if (id !== 'previewTime') {
      markOverlayPresetCustom();
    }
    updateSliderLabels();
    updateOverlaySimulator();
  });
});

['sourceTagPosition', 'video_title', 'previewSubtitleText'].forEach((id) => {
  const input = document.getElementById(id);
  if (!input) return;
  input.addEventListener('change', () => {
    if (id === 'sourceTagPosition') {
      markOverlayPresetCustom();
    }
    updateOverlaySimulator();
  });
  input.addEventListener('input', () => {
    if (id === 'sourceTagPosition') {
      markOverlayPresetCustom();
    }
    updateOverlaySimulator();
  });
});

document.querySelectorAll('input[name="subtitle_style"]').forEach((el) => {
  el.addEventListener('change', updateOverlaySimulator);
});
document.querySelectorAll('input[name="source_style"]').forEach((el) => {
  el.addEventListener('change', updateOverlaySimulator);
});

// Collapsible settings
const settingsToggle = document.getElementById('settingsToggle');
const settingsBody = document.getElementById('settingsBody');
settingsToggle.addEventListener('click', () => {
  settingsToggle.classList.toggle('open');
  settingsBody.classList.toggle('open');
});

updateSliderLabels();

// ═══════════════════════════════════════════════════════════════════════
// VIDEO INFO FETCH
// ═══════════════════════════════════════════════════════════════════════
let currentVideoId = null;

const btnFetch = document.getElementById('btnFetch');
const urlInput = document.getElementById('url');
const videoInfoPanel = document.getElementById('videoInfo');

async function fetchVideoInfo() {
  const url = urlInput.value.trim();
  if (!url) return;

  btnFetch.classList.add('loading');
  btnFetch.textContent = '⏳';

  try {
    const res = await fetch(`/api/video-info?url=${encodeURIComponent(url)}`);
    const data = await res.json();

    if (data.error) {
      alert(data.error);
      return;
    }

    currentVideoId = data.video_id;

    document.getElementById('thumbImg').src = data.thumbnail;
    document.getElementById('videoTitle').textContent = data.title;
    document.getElementById('channelChip').textContent = '📺 ' + data.channel;
    document.getElementById('durationChip').textContent = '⏱ ' + formatDuration(data.duration);
    document.getElementById('viewsChip').textContent = '👁 ' + formatViews(data.view_count);

    const previewBg = document.getElementById('previewBgImage');
    if (previewBg && data.thumbnail) {
      previewBg.src = data.thumbnail;
      previewBg.style.display = '';
    }
    document.getElementById('previewSourceText').textContent = `Source: ${data.channel || 'Channel'}`;

    videoInfoPanel.classList.add('visible');

    // Pre-fill title if empty
    const titleInput = document.getElementById('video_title');
    if (!titleInput.value.trim()) {
      titleInput.value = data.title;
    }

    const previewSubtitleInput = document.getElementById('previewSubtitleText');
    if (previewSubtitleInput && !previewSubtitleInput.value.trim()) {
      previewSubtitleInput.value = `Potongan viral dari ${data.title}`;
    }

    updateOverlaySimulator();
  } catch (err) {
    console.error(err);
    alert('Failed to fetch video info.');
  } finally {
    btnFetch.classList.remove('loading');
    btnFetch.textContent = '🔍';
  }
}

btnFetch.addEventListener('click', fetchVideoInfo);

// Also trigger on Enter in URL field
urlInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey) {
    // Don't prevent default submit if there's already info
    if (!videoInfoPanel.classList.contains('visible')) {
      e.preventDefault();
      fetchVideoInfo();
    }
  }
});

function formatDuration(seconds) {
  if (!seconds) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function formatViews(count) {
  if (!count) return '—';
  if (count >= 1e6) return (count / 1e6).toFixed(1) + 'M';
  if (count >= 1e3) return (count / 1e3).toFixed(1) + 'K';
  return count.toLocaleString();
}

function wrapPreviewText(text, maxChars) {
  const clean = (text || '').replace(/\s+/g, ' ').trim();
  const limit = Math.max(16, Math.min(64, Number(maxChars || 30)));
  if (clean.length <= limit) {
    return clean;
  }

  const words = clean.split(' ');
  const lines = [];
  let current = '';

  words.forEach((word) => {
    const next = current ? `${current} ${word}` : word;
    if (next.length <= limit) {
      current = next;
      return;
    }
    if (current) {
      lines.push(current);
    }
    current = word;
  });

  if (current) {
    lines.push(current);
  }

  return lines.join('\n');
}

function getSelectedRadioValue(name, fallback) {
  const checked = document.querySelector(`input[name="${name}"]:checked`);
  return checked ? checked.value : fallback;
}

function updateOverlaySimulator() {
  const subtitleEl = document.getElementById('previewSubtitle');
  const sourceEl = document.getElementById('previewSourceTag');
  if (!subtitleEl || !sourceEl) return;

  const useSubtitle = document.getElementById('useSubtitle').checked;
  const useSourceTag = document.getElementById('useSourceTag').checked;

  subtitleEl.style.display = useSubtitle ? '' : 'none';
  sourceEl.style.display = useSourceTag ? '' : 'none';

  const subtitleSize = Number(document.getElementById('subtitleFontSize').value || 12);
  const subtitleBottom = Number(document.getElementById('subtitleBottomMargin').value || 28);
  const subtitleMaxChars = Number(document.getElementById('subtitleMaxChars').value || 30);
  const subtitleStyle = getSelectedRadioValue('subtitle_style', 'modern');
  const previewSubtitleInput = document.getElementById('previewSubtitleText');
  const previewSubtitleText = (previewSubtitleInput ? previewSubtitleInput.value : '').trim();
  const fallbackSubtitle = 'Ini contoh subtitle untuk mengecek ukuran, posisi, dan kepadatan baris.';

  subtitleEl.style.fontSize = `${subtitleSize}px`;
  subtitleEl.style.bottom = `${subtitleBottom}px`;
  subtitleEl.dataset.style = subtitleStyle;
  subtitleEl.textContent = wrapPreviewText(
    previewSubtitleText || fallbackSubtitle,
    subtitleMaxChars
  );

  const sourceScale = Number(document.getElementById('sourceTagScale').value || 1);
  const sourcePos = document.getElementById('sourceTagPosition').value || 'top-left';
  const sourceStyle = getSelectedRadioValue('source_style', 'classic');

  sourceEl.style.transform = `scale(${sourceScale.toFixed(2)})`;
  sourceEl.style.transformOrigin = sourcePos.includes('right') ? 'top right' : 'top left';

  sourceEl.style.top = sourcePos.includes('top') ? '14px' : 'auto';
  sourceEl.style.bottom = sourcePos.includes('bottom') ? '14px' : 'auto';
  sourceEl.style.left = sourcePos.includes('left') ? '14px' : 'auto';
  sourceEl.style.right = sourcePos.includes('right') ? '14px' : 'auto';

  if (sourceStyle === 'minimal') {
    sourceEl.style.background = 'rgba(15, 23, 42, 0.32)';
    sourceEl.style.borderColor = 'rgba(255, 255, 255, 0.10)';
  } else if (sourceStyle === 'glass') {
    sourceEl.style.background = 'rgba(255, 255, 255, 0.2)';
    sourceEl.style.borderColor = 'rgba(255, 255, 255, 0.25)';
  } else if (sourceStyle === 'neon') {
    sourceEl.style.background = 'rgba(15, 23, 42, 0.78)';
    sourceEl.style.borderColor = 'rgba(0, 255, 136, 0.55)';
  } else {
    sourceEl.style.background = 'rgba(16, 24, 40, 0.75)';
    sourceEl.style.borderColor = 'rgba(255, 255, 255, 0.12)';
  }
}

let accuratePreviewController = null;

async function renderAccuratePreview() {
  if (document.body.classList.contains('ui-busy')) {
    return;
  }

  const button = document.getElementById('btnAccuratePreview');
  const image = document.getElementById('accuratePreviewImage');
  const placeholder = document.getElementById('accuratePreviewPlaceholder');
  const formData = new FormData(document.getElementById('mainForm'));

  if (accuratePreviewController) {
    accuratePreviewController.abort();
  }
  accuratePreviewController = new AbortController();

  button.disabled = true;
  button.textContent = 'Rendering...';

  try {
    const response = await fetch('/api/preview/frame', {
      method: 'POST',
      body: formData,
      signal: accuratePreviewController.signal,
    });

    if (!response.ok) {
      let errorText = 'Failed to render accurate preview.';
      try {
        const payload = await response.json();
        errorText = payload.error || errorText;
      } catch (_) {
        // Keep default message if response is not JSON.
      }
      throw new Error(errorText);
    }

    const blob = await response.blob();
    const blobUrl = URL.createObjectURL(blob);
    image.src = blobUrl;
    image.style.display = '';
    placeholder.style.display = 'none';
  } catch (err) {
    if (err.name !== 'AbortError') {
      setRuntimeStatus('error', err.message || 'Failed to render accurate preview.');
    }
  } finally {
    button.disabled = false;
    button.textContent = 'Render Accurate Preview';
  }
}

document.getElementById('btnAccuratePreview').addEventListener('click', renderAccuratePreview);

// ═══════════════════════════════════════════════════════════════════════
// VIDEO PREVIEW MODAL
// ═══════════════════════════════════════════════════════════════════════
const modal = document.getElementById('videoModal');
const modalPlayer = document.getElementById('modalPlayer');
const modalTitleInput = document.getElementById('modalTitleInput');
const modalCloseBtn = document.getElementById('modalClose');

function openModal() {
  if (!currentVideoId) return;
  modalPlayer.src = `https://www.youtube.com/embed/${currentVideoId}?autoplay=1`;
  modalTitleInput.value = document.getElementById('video_title').value || document.getElementById('videoTitle').textContent;
  document.getElementById('modalTitle').textContent = document.getElementById('videoTitle').textContent || 'Video Preview';
  modal.classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  modal.classList.remove('open');
  modalPlayer.src = '';
  document.body.style.overflow = '';

  // Sync title back
  const newTitle = modalTitleInput.value.trim();
  if (newTitle) {
    document.getElementById('video_title').value = newTitle;
  }
}

document.getElementById('btnPreview').addEventListener('click', openModal);
document.getElementById('videoThumb').addEventListener('click', openModal);
modalCloseBtn.addEventListener('click', closeModal);

modal.addEventListener('click', (e) => {
  if (e.target === modal) closeModal();
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && modal.classList.contains('open')) closeModal();
});

// Keep title synced live while editing in modal.
modalTitleInput.addEventListener('input', () => {
  document.getElementById('video_title').value = modalTitleInput.value;
});

function escapeHtml(text) {
  return (text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function getEditableTitle(item) {
  const explicit = (item.video_title || '').trim();
  if (explicit) {
    return explicit;
  }

  const filename = (item.filename || '').replace(/\.mp4$/i, '');
  return filename.replace(/_clip_\d+$/i, '');
}

function setUiBusy(isBusy) {
  document.body.classList.toggle('ui-busy', isBusy);
  document.querySelectorAll('button').forEach((el) => {
    el.disabled = isBusy;
  });

  document.querySelectorAll('[data-busy-lock="1"]').forEach((el) => {
    el.style.pointerEvents = isBusy ? 'none' : '';
    el.style.opacity = isBusy ? '0.6' : '';
  });
}

function renderHistoryItem(item) {
  const mp4 = item.filename;
  const srt = item.subtitle_filename || mp4.replace(/\.mp4$/i, '.srt');
  const subtitleText = item.subtitle_text || 'No subtitle content available.';
  const translatedSrt = item.translated_subtitle_filename || '';
  const editableTitle = getEditableTitle(item);

  const translatedBtn = translatedSrt
    ? `<a data-busy-lock="1" href="/clips/${encodeURIComponent(translatedSrt)}" download class="btn-download" style="background: var(--bg-elevated); color: var(--text-primary); border: 1px solid var(--border-default);">🌐 Download Translated SRT</a>`
    : '';

  return `
    <div class="result-item">
      <video controls preload="metadata" playsinline>
        <source src="/clips/${encodeURIComponent(mp4)}" type="video/mp4">
      </video>
      <div class="result-info">
        <div class="filename">${escapeHtml(mp4)}</div>
        <div class="result-actions">
          <a data-busy-lock="1" href="/clips/${encodeURIComponent(mp4)}" download class="btn-download">⬇ Download MP4</a>
          <a data-busy-lock="1" href="/clips/${encodeURIComponent(srt)}" download class="btn-download" style="background: var(--bg-elevated); color: var(--text-primary); border: 1px solid var(--border-default);">📄 Download SRT</a>
          ${translatedBtn}
        </div>
        <div class="result-title-row">
          <input class="result-title-input" type="text" value="${escapeHtml(editableTitle)}" data-title-input="1" data-filename="${escapeHtml(mp4)}">
          <button type="button" class="btn-download" data-rename-btn="1" data-filename="${escapeHtml(mp4)}">💾 Save Title</button>
          <button type="button" class="btn-download btn-danger" data-delete-btn="1" data-filename="${escapeHtml(mp4)}">🗑 Delete</button>
        </div>
        <div class="subtitle-panel">
          <div class="subtitle-header">Subtitle Text (.srt)</div>
          <pre class="subtitle-pre">${escapeHtml(subtitleText)}</pre>
        </div>
      </div>
    </div>
  `;
}

async function refreshHistory() {
  const grid = document.getElementById('historyGrid');
  try {
    const response = await fetch('/api/history');
    const data = await response.json();

    if (!Array.isArray(data) || data.length === 0) {
      grid.innerHTML = '<div class="result-empty">No generated clips yet.</div>';
      return;
    }

    grid.innerHTML = data.map(renderHistoryItem).join('');
  } catch (err) {
    console.error(err);
  }
}

document.getElementById('historyGrid').addEventListener('click', async (event) => {
  const renameBtn = event.target.closest('[data-rename-btn="1"]');
  if (renameBtn) {
    const filename = renameBtn.getAttribute('data-filename') || '';
    const parent = renameBtn.closest('.result-title-row');
    const input = parent ? parent.querySelector('[data-title-input="1"]') : null;
    const newTitle = input ? input.value.trim() : '';

    if (!filename || !newTitle) {
      setRuntimeStatus('error', 'Title baru tidak boleh kosong.');
      return;
    }

    try {
      setUiBusy(true);
      const res = await fetch('/api/history/rename', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename, new_title: newTitle }),
      });
      const data = await res.json();

      if (!res.ok || !data.ok) {
        throw new Error(data.message || 'Failed to rename clip');
      }

      await refreshHistory();
      setRuntimeStatus('success', `Judul berhasil diubah menjadi ${data.new_filename}`);
    } catch (err) {
      setRuntimeStatus('error', err.message || 'Failed to rename clip.');
    } finally {
      setUiBusy(false);
    }
    return;
  }

  const deleteBtn = event.target.closest('[data-delete-btn="1"]');
  if (deleteBtn) {
    const filename = deleteBtn.getAttribute('data-filename') || '';
    if (!filename) {
      return;
    }

    const confirmDelete = window.confirm(`Hapus clip ini secara permanen?\n${filename}`);
    if (!confirmDelete) {
      return;
    }

    try {
      setUiBusy(true);
      const res = await fetch(`/api/history/${encodeURIComponent(filename)}`, {
        method: 'DELETE',
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.message || 'Failed to delete clip');
      }

      await refreshHistory();
      setRuntimeStatus('success', `${filename} berhasil dihapus.`);
    } catch (err) {
      setRuntimeStatus('error', err.message || 'Failed to delete clip.');
    } finally {
      setUiBusy(false);
    }
  }
});

function setRuntimeStatus(kind, text) {
  const box = document.getElementById('runtimeStatus');
  box.style.display = '';
  box.classList.remove('error', 'success');

  if (kind === 'error') {
    box.classList.add('error');
    box.textContent = '⚠️ ' + text;
  } else {
    box.classList.add('success');
    box.textContent = '✅ ' + text;
  }
}

let lastJobLogs = '';

function renderJobLogs(logsText, errorText = '', forceShow = false) {
  const logsCard = document.getElementById('jobLogsCard');
  const logsViewer = document.getElementById('jobLogsViewer');
  if (!logsCard || !logsViewer) {
    return;
  }

  const normalized = (logsText || '').trim();
  const errorLine = (errorText || '').trim();
  let composed = normalized;

  if (errorLine) {
    composed = composed ? `${composed}\n\n[ERROR] ${errorLine}` : `[ERROR] ${errorLine}`;
  }

  if (forceShow || composed) {
    logsCard.style.display = '';
  }

  if (!composed && !forceShow) {
    return;
  }

  if (composed !== lastJobLogs) {
    logsViewer.textContent = composed || 'Log sistem akan tampil di sini...';
    logsViewer.scrollTop = logsViewer.scrollHeight;
    lastJobLogs = composed;
  }
}

async function pollJob(jobId) {
  const progressCard = document.getElementById('jobProgressCard');
  const fill = document.getElementById('jobProgressFill');
  const text = document.getElementById('jobProgressText');
  progressCard.style.display = '';
  renderJobLogs('', '', true);

  const interval = setInterval(async () => {
    try {
      const response = await fetch(`/api/jobs/${jobId}`);
      const data = await response.json();

      if (data.error) {
        clearInterval(interval);
        renderJobLogs('', data.error, true);
        setRuntimeStatus('error', data.error);
        return;
      }

      const progress = Number(data.progress || 0);
      fill.style.width = `${Math.max(0, Math.min(100, progress))}%`;
      text.textContent = data.message || data.status || 'Processing...';
      renderJobLogs(data.logs || '', data.error || '', true);

      if (data.status === 'completed') {
        clearInterval(interval);
        fill.style.width = '100%';
        renderJobLogs(data.logs || '', '', true);
        setRuntimeStatus('success', data.message || 'Background job completed.');
        await refreshHistory();
        setUiBusy(false);
        document.getElementById('btnSubmit').textContent = '🚀 Process Video';
      }

      if (data.status === 'failed') {
        clearInterval(interval);
        renderJobLogs(data.logs || '', data.error || data.message || 'Background job failed.', true);
        setRuntimeStatus('error', data.error || data.message || 'Background job failed.');
        setUiBusy(false);
        document.getElementById('btnSubmit').textContent = '🚀 Process Video';
      }
    } catch (err) {
      clearInterval(interval);
      renderJobLogs('', 'Failed to read background job status.', true);
      setRuntimeStatus('error', 'Failed to read background job status.');
      setUiBusy(false);
      document.getElementById('btnSubmit').textContent = '🚀 Process Video';
    }
  }, 2000);
}

// ═══════════════════════════════════════════════════════════════════════
// FORM SUBMIT — async background enqueue
// ═══════════════════════════════════════════════════════════════════════
document.getElementById('mainForm').addEventListener('submit', async (event) => {
  event.preventDefault();

  if (document.body.classList.contains('ui-busy')) {
    return;
  }

  if (modal.classList.contains('open')) {
    const newTitle = modalTitleInput.value.trim();
    document.getElementById('video_title').value = newTitle;
  }

  // Capture form values before disabling buttons.
  const formData = new FormData(document.getElementById('mainForm'));

  setUiBusy(true);
  document.getElementById('btnSubmit').textContent = '⏳ Queueing...';
  lastJobLogs = '';
  renderJobLogs('Queueing job...', '', true);

  try {
    const response = await fetch('/api/jobs/submit', {
      method: 'POST',
      body: formData,
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || 'Failed to submit background job');
    }

    setRuntimeStatus('success', `Job queued (${data.mode}). Processing in background...`);
    document.getElementById('btnSubmit').textContent = '⏳ Processing...';
    renderJobLogs(`Job queued in mode: ${data.mode}`, '', true);
    await pollJob(data.job_id);
  } catch (err) {
    renderJobLogs('', err.message || 'Failed to submit background job.', true);
    setRuntimeStatus('error', err.message || 'Failed to submit background job.');
    setUiBusy(false);
    document.getElementById('btnSubmit').textContent = '🚀 Process Video';
  }
});

// Keep history always up-to-date after page load/refresh.
updateOverlaySimulator();
refreshHistory();