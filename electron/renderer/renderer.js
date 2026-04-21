const fields = [
  { id: 'base', label: 'Base audio file', kind: 'audio', modes: ['four', 'two'], requiredIn: ['four', 'two'] },
  { id: 'vocals', label: 'Vocals MP3', kind: 'mp3', modes: ['four', 'two'], requiredIn: ['four', 'two'] },
  { id: 'bass', label: 'Bass MP3 (4-stem)', kind: 'mp3', modes: ['four'], requiredIn: ['four'] },
  { id: 'drums', label: 'Drums MP3 (4-stem)', kind: 'mp3', modes: ['four'], requiredIn: ['four'] },
  { id: 'melody', label: 'Melody MP3 (4-stem)', kind: 'mp3', modes: ['four'], requiredIn: ['four'] },
  { id: 'instrumental', label: 'Instrumental MP3 (2-stem)', kind: 'mp3', modes: ['two'], requiredIn: ['two'] },
  { id: 'step1_analysis_seconds', label: 'Step 1 Align Analysis (sec)', kind: 'number', modes: ['two'], requiredIn: [] },
  { id: 'step1_max_shift_seconds', label: 'Step 1 Align Max Shift (sec)', kind: 'number', modes: ['two'], requiredIn: [] },
  { id: 'step1_vocal_nudge_seconds', label: 'Step 1 Vocal Nudge (sec)', kind: 'number', modes: ['two'], requiredIn: [] },
  { id: 'stem_delay_ms', label: 'Stem Delay (ms)', kind: 'number', modes: ['four', 'two'], requiredIn: [] },
  { id: 'add_gain_stems', label: 'Add Gain To Stems (+4 dB)', kind: 'toggle', modes: ['four', 'two'], requiredIn: [] },
];

const state = {
  mode: 'two',
  step1Mode: 'extract',
  activeStep: 'extract',
  debugMode: false,
  activeProgressToken: '',
  originalBasePath: '',
  disableBaseMetadataCopy: false,
  values: Object.fromEntries(fields.map((f) => [f.id, ''])),
};
state.values.stem_delay_ms = '0';
state.values.step1_analysis_seconds = '90';
state.values.step1_max_shift_seconds = '30';
state.values.step1_vocal_nudge_seconds = '0';
state.values.add_gain_stems = '1';

const fieldGrid = document.getElementById('fieldGrid');
const sourceContext = document.getElementById('sourceContext');
const statusText = document.getElementById('statusText');
const outputBox = document.getElementById('outputBox');
const debugModeToggle = document.getElementById('debugModeToggle');
const extractProgressWrap = document.getElementById('extractProgressWrap');
const extractProgressBar = document.getElementById('extractProgressBar');
const extractProgressText = document.getElementById('extractProgressText');
const step1ModeCard = document.getElementById('step1ModeCard');
const extractBtn = document.getElementById('extractBtn');
const prepBtn = document.getElementById('prepBtn');
const buildBtn = document.getElementById('buildBtn');
const clearBtn = document.getElementById('clearBtn');
const manualAlignOverlay = document.getElementById('manualAlignOverlay');
const manualAlignCancelBtn = document.getElementById('manualAlignCancelBtn');
const manualAlignConfirmBtn = document.getElementById('manualAlignConfirmBtn');
const manualRuler = document.getElementById('manualRuler');
const manualPlayheadRuler = document.getElementById('manualPlayheadRuler');
const transportRestartBtn = document.getElementById('transport-restart');
const transportPlayToggleBtn = document.getElementById('transport-play-toggle');
const transportTime = document.getElementById('transport-time');

const NUDGE_SECONDS = 1 / 43.066;
const WAVEFORM_POINTS = 1100;

const manualTracks = {
  base: {
    id: 'base',
    lane: document.getElementById('lane-base'),
    clip: document.getElementById('clip-base'),
    wave: document.getElementById('wave-base'),
    playhead: document.getElementById('playhead-base'),
    muteBtn: document.getElementById('mute-base'),
    soloBtn: document.getElementById('solo-base'),
    locked: true,
  },
  vocals: {
    id: 'vocals',
    lane: document.getElementById('lane-vocals'),
    clip: document.getElementById('clip-vocals'),
    wave: document.getElementById('wave-vocals'),
    playhead: document.getElementById('playhead-vocals'),
    muteBtn: document.getElementById('mute-vocals'),
    soloBtn: document.getElementById('solo-vocals'),
    resetBtn: document.getElementById('reset-vocals'),
    locked: false,
  },
  instrumental: {
    id: 'instrumental',
    lane: document.getElementById('lane-instrumental'),
    clip: document.getElementById('clip-instrumental'),
    wave: document.getElementById('wave-instrumental'),
    playhead: document.getElementById('playhead-instrumental'),
    muteBtn: document.getElementById('mute-instrumental'),
    soloBtn: document.getElementById('solo-instrumental'),
    resetBtn: document.getElementById('reset-instrumental'),
    locked: false,
  },
};

const manualAlign = {
  isOpen: false,
  alignFolder: '',
  audioCtx: null,
  buffers: { base: null, vocals: null, instrumental: null },
  waveforms: { base: [], vocals: [], instrumental: [] },
  duration: 1,
  playbackStartAt: 0,
  playbackOffset: 0,
  isPlaying: false,
  rafId: 0,
  selectedTrackId: 'vocals',
  tracks: {
    base: { offset: 0, clipStart: 0, clipEnd: 1, mute: false, solo: false },
    vocals: { offset: 0, clipStart: 0, clipEnd: 1, mute: false, solo: false },
    instrumental: { offset: 0, clipStart: 0, clipEnd: 1, mute: false, solo: false },
  },
  initialTracks: {
    vocals: { offset: 0, clipStart: 0, clipEnd: 1 },
    instrumental: { offset: 0, clipStart: 0, clipEnd: 1 },
  },
  resyncTimer: 0,
};

const rowRefs = new Map();
const buildBanter = [
  'Warming up stem engine...',
  'Teaching the kick drum some manners...',
  'Politely asking the vocals to step forward...',
  'Untangling bass frequencies with tiny scissors...',
  'Checking phase alignment like a perfectionist...',
  'Convincing drums and melody to share the room...',
  'Rendering stems at maximum sauce...',
  'Dusting off metadata and polishing edges...',
  'Labeling folders so future-you stays calm...',
  'Making sure bass is big but lawful...',
  'Negotiating peace between hi-hats and vocals...',
  'Running final vibe inspection...',
];
const spinnerFrames = ['|', '/', '-', '\\'];
let activeBuildTicker = null;

async function getDroppedPath(event) {
  const dt = event.dataTransfer;
  if (!dt) return '';
  if (dt.files && dt.files.length > 0) {
    const first = dt.files[0];
    const viaBridge = await window.stemsApi.getPathForFile(first);
    if (viaBridge) return viaBridge;
    if (first.path) return first.path;
  }
  if (dt.items && dt.items.length > 0) {
    for (const item of dt.items) {
      if (!item || item.kind !== 'file') continue;
      const file = item.getAsFile ? item.getAsFile() : null;
      if (!file) continue;
      const viaBridge = await window.stemsApi.getPathForFile(file);
      if (viaBridge) return viaBridge;
      if (file.path) return file.path;
    }
  }

  const textKeys = [
    'text/uri-list',
    'public.file-url',
    'NSURLPboardType',
    'text/plain',
    'text',
  ];
  for (const key of textKeys) {
    const raw = (dt.getData(key) || '').trim();
    if (!raw) continue;
    const first = raw
      .split('\n')
      .map((x) => x.trim())
      .find((x) => x && !x.startsWith('#'));
    if (!first) continue;
    if (first.startsWith('file://')) return decodeURIComponent(first.replace('file://', ''));
    if (first.startsWith('/')) return first;
  }
  return '';
}

function setProcessing(isProcessing) {
  document.body.classList.toggle('is-processing', Boolean(isProcessing));
}

function setActionHighlight(active) {
  state.activeStep = active;
  document.body.dataset.activeStep = active;
  const extractIsActive = active === 'extract';
  const prepIsActive = active === 'prep';
  const buildIsActive = active === 'build';

  extractBtn.classList.toggle('btn-primary', extractIsActive);
  extractBtn.classList.toggle('btn-secondary', !extractIsActive);
  extractBtn.classList.toggle('btn-guided-active', extractIsActive);

  prepBtn.classList.toggle('btn-primary', prepIsActive);
  prepBtn.classList.toggle('btn-secondary', !prepIsActive);
  prepBtn.classList.toggle('btn-guided-active', prepIsActive);

  buildBtn.classList.toggle('btn-primary', buildIsActive);
  buildBtn.classList.toggle('btn-secondary', !buildIsActive);
  buildBtn.classList.toggle('btn-guided-active', buildIsActive);

  applyMode();
}

function setStatus(text) {
  statusText.textContent = text;
}

function setOutput(text) {
  outputBox.textContent = text;
  outputBox.scrollTop = outputBox.scrollHeight;
}

function appendOutputLine(text = '') {
  if (!state.debugMode) return;
  if (!outputBox.textContent) {
    outputBox.textContent = text;
  } else {
    outputBox.textContent += `\n${text}`;
  }
  outputBox.scrollTop = outputBox.scrollHeight;
}

function setRetailOutput(title, steps = [], notes = []) {
  if (state.debugMode) return;
  const lines = [];
  if (title) lines.push(title);
  if (steps.length) {
    lines.push('');
    steps.forEach((step, idx) => lines.push(`${idx + 1}. ${step}`));
  }
  if (notes.length) {
    lines.push('');
    lines.push('Notes:');
    notes.forEach((note) => lines.push(`- ${note}`));
  }
  setOutput(lines.join('\n'));
}

function setExtractProgress(active, percent = 0, text = '', indeterminate = false) {
  if (!extractProgressWrap || !extractProgressBar || !extractProgressText) return;
  extractProgressWrap.classList.toggle('hidden', !active);
  extractProgressWrap.setAttribute('aria-hidden', active ? 'false' : 'true');
  extractProgressWrap.classList.toggle('is-indeterminate', Boolean(indeterminate));
  if (!indeterminate) {
    const pct = Math.max(0, Math.min(100, Number(percent) || 0));
    extractProgressBar.style.width = `${pct}%`;
    extractProgressBar.style.transform = '';
  }
  if (text) {
    extractProgressText.textContent = text;
  }
}

function handleBuildProgress(progress) {
  if (!progress || typeof progress !== 'object') return;
  const token = String(progress.token || '');
  if (!token || token !== state.activeProgressToken) return;
  const stage = String(progress.stage || '').toLowerCase();
  const stagePct = Math.max(0, Math.min(100, Number(progress.percent) || 0));
  const msg = String(progress.message || '').trim();
  let mappedPct = stagePct;
  if (state.mode === 'four') {
    if (stage === 'kim2') {
      mappedPct = (stagePct * 0.58);
    } else if (stage === 'demucs') {
      mappedPct = 58 + (stagePct * 0.40);
    } else {
      mappedPct = Math.min(98, stagePct);
    }
  }
  const text =
    msg ||
    (stage === 'demucs'
      ? 'Running Demucs instrumental split...'
      : 'Running Kim-2 separation...');
  setExtractProgress(true, mappedPct, text, false);
}

function setFieldValue(fieldId, value) {
  state.values[fieldId] = value || '';
  const input = document.getElementById(`input-${fieldId}`);
  if (input) input.value = state.values[fieldId];
  if (fieldId === 'base') {
    maybeCaptureOriginalBasePath(state.values[fieldId], false);
  }
}

function isInjectorTempBasePath(pathText) {
  if (!pathText) return false;
  const norm = String(pathText).replace(/\\/g, '/');
  return norm.includes('/Music/Custom Stem Injector/');
}

function maybeCaptureOriginalBasePath(pathText, force = false) {
  const candidate = (pathText || '').trim();
  if (!candidate) return;
  if (!force) {
    if (state.originalBasePath) return;
    if (isInjectorTempBasePath(candidate)) return;
  }
  state.originalBasePath = candidate;
}

function applyPreparedOutputs(outputs) {
  if (!outputs || typeof outputs !== 'object') return false;
  if (outputs.base) setFieldValue('base', outputs.base);
  if (outputs.vocals) setFieldValue('vocals', outputs.vocals);
  if (state.mode === 'two') {
    if (outputs.instrumental) setFieldValue('instrumental', outputs.instrumental);
  } else {
    if (outputs.bass) setFieldValue('bass', outputs.bass);
    if (outputs.drums) setFieldValue('drums', outputs.drums);
    if (outputs.melody) setFieldValue('melody', outputs.melody);
  }
  return true;
}

function summarizePayload(payload) {
  const actionLabel = payload.action === 'prepare' ? 'Prepare started.' : 'Build started.';
  const modeLabel = payload.mode === 'four' ? '4 stems' : '2 stems';
  const selected = [
    payload.base ? 'Base audio' : '',
    payload.vocals ? 'Vocals' : '',
    payload.bass ? 'Bass' : '',
    payload.drums ? 'Drums' : '',
    payload.melody ? 'Melody' : '',
    payload.instrumental ? 'Instrumental' : '',
  ].filter(Boolean);
  return [
    actionLabel,
    `Mode: ${modeLabel}`,
    `Inputs detected: ${selected.join(', ') || 'None'}`,
    `Stem delay: ${payload.stem_delay_ms || '0'} ms`,
    '',
  ];
}

function startBuildTicker(payload) {
  if (!state.debugMode) return;
  if (activeBuildTicker) {
    clearInterval(activeBuildTicker.timer);
    activeBuildTicker = null;
  }

  const startedAt = Date.now();
  const lines = summarizePayload(payload);
  let banterIdx = 0;
  let spinIdx = 0;
  setOutput('');
  lines.forEach((line) => appendOutputLine(line));
  appendOutputLine('[0.0s] Build queue accepted. Rolling up sleeves...');

  const timer = setInterval(() => {
    const elapsed = ((Date.now() - startedAt) / 1000).toFixed(1);
    const spinner = spinnerFrames[spinIdx % spinnerFrames.length];
    lines.push(`[${elapsed}s] ${spinner} ${buildBanter[banterIdx % buildBanter.length]}`);
    appendOutputLine(lines[lines.length - 1]);
    banterIdx += 1;
    spinIdx += 1;
  }, 650);

  activeBuildTicker = { timer, startedAt };
}

function stopBuildTicker() {
  if (!activeBuildTicker) return 0;
  clearInterval(activeBuildTicker.timer);
  const elapsedMs = Date.now() - activeBuildTicker.startedAt;
  activeBuildTicker = null;
  return elapsedMs;
}

function createFieldRow(field) {
  const row = document.createElement('div');
  row.className = 'field-row';
  row.dataset.id = field.id;

  const label = document.createElement('label');
  label.textContent = field.label;
  label.setAttribute('for', `input-${field.id}`);

  const input = document.createElement('input');
  input.id = `input-${field.id}`;
  input.value = state.values[field.id] || '';
  if (field.kind === 'toggle') {
    input.type = 'checkbox';
    input.className = 'toggle-checkbox';
    input.checked = Boolean(state.values[field.id]);
    input.addEventListener('change', (e) => {
      state.values[field.id] = e.target.checked ? '1' : '';
    });
  } else {
    input.addEventListener('input', (e) => {
      state.values[field.id] = e.target.value;
      if (field.id === 'base') {
        maybeCaptureOriginalBasePath(e.target.value, false);
      }
    });
  }

  if (field.kind !== 'toggle' && field.kind !== 'number') {
    const onDragOver = (e) => {
      e.preventDefault();
      e.stopPropagation();
      row.classList.add('drop-over');
    };
    const onDragLeave = (e) => {
      e.preventDefault();
      e.stopPropagation();
      row.classList.remove('drop-over');
    };
    const onDrop = async (e) => {
      e.preventDefault();
      e.stopPropagation();
      row.classList.remove('drop-over');
      const dropped = await getDroppedPath(e);
      if (!dropped) return;
      input.value = dropped;
      state.values[field.id] = dropped;
      if (field.id === 'base') {
        maybeCaptureOriginalBasePath(dropped, true);
      }
    };
    row.addEventListener('dragover', onDragOver);
    row.addEventListener('dragleave', onDragLeave);
    row.addEventListener('drop', onDrop);
    input.addEventListener('dragover', onDragOver);
    input.addEventListener('dragleave', onDragLeave);
    input.addEventListener('drop', onDrop);
  }

  const actions = document.createElement('div');
  actions.className = 'row-actions';

  if (field.kind === 'copy') {
    const folderBtn = document.createElement('button');
    folderBtn.className = 'btn btn-secondary';
    folderBtn.textContent = 'Folder';
    folderBtn.type = 'button';
    folderBtn.addEventListener('click', async () => {
      const path = await window.stemsApi.pickFolder();
      if (path) {
        input.value = path;
        state.values[field.id] = path;
        if (field.id === 'base') {
          maybeCaptureOriginalBasePath(path, true);
        }
      }
    });

    const fileBtn = document.createElement('button');
    fileBtn.className = 'btn btn-secondary';
    fileBtn.textContent = 'File';
    fileBtn.type = 'button';
    fileBtn.addEventListener('click', async () => {
      const path = await window.stemsApi.pickSaveFile();
      if (path) {
        input.value = path;
        state.values[field.id] = path;
      }
    });

    actions.append(folderBtn, fileBtn);
  } else if (field.kind === 'number') {
    input.type = 'number';
    input.step = '0.1';
    input.min = '0';
    input.placeholder = '0';
  } else if (field.kind === 'toggle') {
    row.classList.add('field-row-toggle');
    const spacer = document.createElement('span');
    spacer.className = 'row-actions-spacer';
    actions.appendChild(spacer);
  } else {
    const browseBtn = document.createElement('button');
    browseBtn.className = 'btn btn-secondary';
    browseBtn.textContent = 'Browse';
    browseBtn.type = 'button';
    browseBtn.addEventListener('click', async () => {
      const path = await window.stemsApi.pickFile(field.kind);
      if (path) {
        input.value = path;
        state.values[field.id] = path;
      }
    });
    actions.appendChild(browseBtn);
  }

  row.append(label, input, actions);
  fieldGrid.appendChild(row);
  rowRefs.set(field.id, row);
}

function renderFields() {
  fieldGrid.innerHTML = '';
  rowRefs.clear();
  fields.forEach(createFieldRow);
  applyMode();
}

function applyMode() {
  if (step1ModeCard) {
    step1ModeCard.style.display = state.mode === 'two' ? '' : 'none';
  }

  const step = state.activeStep || 'extract';
  const commonStemFields = ['base', 'vocals'];
  const modeStemFields = state.mode === 'two' ? ['instrumental'] : ['bass', 'drums', 'melody'];
  let visibleIds = new Set(commonStemFields);

  if (step === 'extract') {
    visibleIds = new Set(['base']);
    if (state.step1Mode === 'align') {
      visibleIds = new Set([
        'base',
        'vocals',
        'instrumental',
        'step1_analysis_seconds',
        'step1_max_shift_seconds',
        'step1_vocal_nudge_seconds',
      ]);
    }
  } else if (step === 'prep') {
    visibleIds = new Set([...commonStemFields, ...modeStemFields, 'add_gain_stems']);
  } else if (step === 'build') {
    visibleIds = new Set([...commonStemFields, ...modeStemFields, 'stem_delay_ms']);
  }

  fields.forEach((field) => {
    const row = rowRefs.get(field.id);
    if (!row) return;
    const modeAllowed = field.modes.includes(state.mode);
    const stepAllowed = visibleIds.has(field.id);
    row.style.display = modeAllowed && stepAllowed ? 'grid' : 'none';
  });

  applyStep1ModeUI();
  updateSourceContext();
}

function updateSourceContext() {
  if (!sourceContext) return;
  const step = state.activeStep || 'extract';

  if (state.mode === 'four') {
    if (step === 'extract') {
      sourceContext.textContent = 'Step 1 (4-stem): provide base audio only. Extract runs Kim-2 first, then Demucs splits instrumental into bass/drums/melody.';
      return;
    }
    if (step === 'prep') {
      sourceContext.textContent = 'Step 2 (4-stem): choose base + vocals + bass + drums + melody, then prepare Serato-ready files.';
      return;
    }
    if (step === 'build') {
      sourceContext.textContent = 'Step 3 (4-stem): build sidecar from prepared files, optionally set stem delay and copy destination.';
      return;
    }
    sourceContext.textContent = '4-stem mode: use Extract to auto-fill vocals+bass+drums+melody, or provide stems manually then Prepare.';
    return;
  }

  if (step === 'extract') {
    if (state.step1Mode === 'align') {
      sourceContext.textContent = 'Step 1 Align: provide base + vocals + instrumental, tune analysis/max shift if needed, then align.';
      return;
    }
    sourceContext.textContent = 'Step 1 Extract: provide base audio only. Vocals/instrumental will auto-fill after extraction.';
    return;
  }
  if (step === 'prep') {
    sourceContext.textContent = 'Step 2 Prepare: review source files, then prepare Serato-ready files before build.';
    return;
  }
  sourceContext.textContent = 'Step 3 Build: close Serato first (recommended), verify inputs, then build final sidecar.';
}

function setButtonLabel(btn, text) {
  const lbl = btn.querySelector('.btn-label');
  if (lbl) lbl.textContent = text;
  else btn.textContent = text;
}

function applyStep1ModeUI() {
  setButtonLabel(extractBtn, state.step1Mode === 'align' ? 'Align Stems' : 'Extract Stems');
  setButtonLabel(prepBtn, 'Prepare Files');
  setButtonLabel(buildBtn, 'Build .Stem');
}

function ensureOriginalBasePath() {
  const base = (state.values.base || '').trim();
  maybeCaptureOriginalBasePath(base, false);
}

function validate() {
  for (const field of fields) {
    if (!field.requiredIn.includes(state.mode)) continue;
    const value = (state.values[field.id] || '').trim();
    if (!value) {
      return `${field.label} is required.`;
    }
  }
  return '';
}

async function runBuild() {
  ensureOriginalBasePath();
  state.activeProgressToken = '';
  const validationErr = validate();
  if (validationErr) {
    setProcessing(false);
    setStatus('Missing required input');
    setOutput(validationErr);
    return;
  }

  setProcessing(true);
  buildBtn.disabled = true;
  extractBtn.disabled = true;
  prepBtn.disabled = true;
  setStatus('Building stems file...');
  setRetailOutput(
    'Building final stem package...',
    [
      'Close Serato before Build .Stem (recommended).',
      'Wait for build completion.',
      'When complete, use the final base audio and matching .serato-stems sidecar together.',
    ],
  );
  appendOutputLine('Recommended: close Serato before Build .Stem to avoid stale cache during overwrite.');

  const payload = {
    action: 'build',
    mode: state.mode,
    base: state.values.base,
    vocals: state.values.vocals,
    bass: state.values.bass,
    drums: state.values.drums,
    melody: state.values.melody,
    instrumental: state.values.instrumental,
    stem_delay_ms: state.values.stem_delay_ms,
    final_output_dir: state.originalBasePath || '',
    original_base_path: state.originalBasePath || '',
  };
  startBuildTicker(payload);

  try {
    const result = await window.stemsApi.runBuild(payload);
    const elapsedSec = (stopBuildTicker() / 1000).toFixed(1);
    if (result.ok) {
      setStatus('Build finished successfully');
      if (!state.debugMode) {
        const finalBase = result.report?.final_outputs?.base || result.report?.prepared_outputs?.base || state.values.base;
        const finalSidecar = result.report?.final_outputs?.sidecar || result.report?.output_sidecar || '(unknown)';
        const notes = [];
        if (Array.isArray(result.report?.warnings) && result.report.warnings.length) {
          notes.push(result.report.warnings[0]);
        }
        setRetailOutput(
          'Build complete.',
          [
            `Final base: ${finalBase}`,
            `Final sidecar: ${finalSidecar}`,
            'Recommended: reopen Serato after build, then refresh/import the track.',
            'Import or refresh this base track in Serato.',
          ],
          notes,
        );
      }
      appendOutputLine('');
      appendOutputLine(`Build complete in ${elapsedSec}s.`);
      appendOutputLine('Custom stems injected to .stems file');
      if (result.report) {
        if (result.report.prep_folder) {
          appendOutputLine(`Prepared folder: ${result.report.prep_folder}`);
        }
        if (applyPreparedOutputs(result.report.prepared_outputs)) {
          appendOutputLine('Form inputs updated to prepared files.');
        }
        appendOutputLine(`Output: ${result.report.output_sidecar || '(unknown)'}`);
        if (result.report.final_outputs) {
          appendOutputLine(`Final base: ${result.report.final_outputs.base || '(unknown)'}`);
          appendOutputLine(`Final sidecar: ${result.report.final_outputs.sidecar || '(unknown)'}`);
        }
        appendOutputLine(`Used template: ${result.report.used_existing_template ? 'yes' : 'no'}`);
        appendOutputLine(`ffmpeg: ${result.report.ffmpeg_path || 'not found'}`);
        if (Array.isArray(result.report.warnings) && result.report.warnings.length) {
          appendOutputLine('Warnings:');
          result.report.warnings.forEach((w) => appendOutputLine(`- ${w}`));
        }
      }
      appendOutputLine('');
      appendOutputLine('Move base song and .serato-stems file to desired library location');
      appendOutputLine('Drag base song into Serato library.');
    } else {
      setStatus('Build failed');
      setRetailOutput(
        'Build failed.',
        [
          'Review input files for this step and try again.',
          `Error: ${result.error || 'Unknown error'}`,
        ],
      );
      appendOutputLine('');
      appendOutputLine(`Build failed after ${elapsedSec}s.`);
      appendOutputLine('The console says this one needs another take:');
      appendOutputLine('');
      appendOutputLine(result.traceback || result.error || 'Unknown error');
    }
  } catch (err) {
    const elapsedSec = (stopBuildTicker() / 1000).toFixed(1);
    setStatus('Build failed');
    setRetailOutput(
      'Build failed.',
      [
        'Unexpected issue while building.',
        `Error: ${String(err)}`,
      ],
    );
    appendOutputLine('');
    appendOutputLine(`Build failed after ${elapsedSec}s.`);
    appendOutputLine('Unexpected issue during processing:');
    appendOutputLine('');
    appendOutputLine(String(err));
  } finally {
    stopBuildTicker();
    setProcessing(false);
    buildBtn.disabled = false;
    extractBtn.disabled = false;
    prepBtn.disabled = false;
  }
}

async function runStep1() {
  ensureOriginalBasePath();
  const base = (state.values.base || '').trim();
  const vocals = (state.values.vocals || '').trim();
  const instrumental = (state.values.instrumental || '').trim();
  const runAlign = state.mode === 'two' && state.step1Mode === 'align';

  if (!base) {
    setStatus('Missing required input');
    setOutput('Base audio file is required for Step 1.');
    return;
  }
  if (runAlign) {
    if (!vocals || !instrumental) {
      setStatus('Missing required input');
      setOutput('Align mode requires Base audio, Vocals MP3, and Instrumental MP3.');
      return;
    }
  }

  setProcessing(true);
  extractBtn.disabled = true;
  prepBtn.disabled = true;
  buildBtn.disabled = true;
  const progressToken = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  state.activeProgressToken = progressToken;
  if (runAlign) {
    setStatus('Aligning studio stems to base...');
    setOutput('Running stem alignment...');
    setExtractProgress(false);
    setRetailOutput(
      'Aligning stems to base audio...',
      ['Wait for alignment to complete.', 'Then continue to Prepare Files.'],
    );
  } else if (state.mode === 'four') {
    setStatus('Extracting 4 stems (Kim-2 + Demucs)...');
    setOutput('Running Kim-2 vocals + instrumental, then Demucs instrumental split...');
    setExtractProgress(true, 3, 'Starting extraction...', true);
    setRetailOutput(
      'Extracting 4 stems...',
      ['Stage 1: Kim-2 extracts vocals and instrumental.', 'Stage 2: Demucs splits instrumental into bass, drums, and melody.'],
    );
  } else {
    setStatus('Extracting vocals and instrumental (Kim-2)...');
    setOutput('Running UVR Kim-2 extraction...');
    setExtractProgress(true, 3, 'Starting extraction...', true);
    setRetailOutput(
      'Extracting 2 stems...',
      ['Running Kim-2 to create vocals and instrumental.', 'After completion, continue to Prepare Files.'],
    );
  }

  const payload = {
    action: runAlign ? 'align_studio' : 'extract',
    mode: state.mode,
    progress_token: progressToken,
    base,
    vocals,
    instrumental,
    analysis_seconds: Number(state.values.step1_analysis_seconds || 90),
    max_shift_seconds: Number(state.values.step1_max_shift_seconds || 30),
    vocal_nudge_seconds: Number(state.values.step1_vocal_nudge_seconds || 0),
  };

  try {
    const result = await window.stemsApi.runBuild(payload);
    if (result.ok) {
      if (runAlign) {
        state.mode = 'two';
        const modeInput = document.querySelector('input[name="mode"][value="two"]');
        if (modeInput) modeInput.checked = true;
      }
      applyMode();

      setActionHighlight('prep');
      setStatus(runAlign ? 'Stem alignment finished' : 'Stem extraction finished');
      if (!runAlign) {
        setExtractProgress(true, 100, 'Extraction complete.', false);
        setTimeout(() => setExtractProgress(false), 900);
      }
      setOutput('');
      if (!state.debugMode) {
        const steps = [];
        if (result.report?.extract_folder) {
          steps.push(`Extracted files: ${result.report.extract_folder}`);
        } else if (result.report?.align_folder) {
          steps.push(`Aligned files: ${result.report.align_folder}`);
        }
        steps.push('Review auto-filled files, then click Prepare Files.');
        setRetailOutput(runAlign ? 'Alignment complete.' : 'Extraction complete.', steps);
      }
      if (result.report) {
        if (!runAlign && Array.isArray(result.report.onnx_providers) && result.report.onnx_providers.length) {
          const providerLabel = result.report.onnx_providers.join(', ');
          const fallbackLabel = result.report.onnx_provider_fallback ? ' (CoreML fallback)' : '';
          appendOutputLine(`Extraction backend: ${providerLabel}${fallbackLabel}`);
        }
        if (!runAlign && result.report.demucs_model) {
          appendOutputLine(`Demucs model: ${result.report.demucs_model}`);
          if (result.report.demucs_device) {
            appendOutputLine(`Demucs device: ${result.report.demucs_device}`);
          }
        }
        if (result.report.extract_folder) {
          appendOutputLine(`Extracted stems saved to "${result.report.extract_folder}"`);
        }
        if (result.report.align_folder) {
          appendOutputLine(`Aligned stems saved to "${result.report.align_folder}"`);
          if (typeof result.report.output_duration_seconds === 'number') {
            appendOutputLine(`Aligned output duration: ${result.report.output_duration_seconds.toFixed(3)} s`);
          }
          if (typeof result.report.lag_vocals_to_base_seconds === 'number') {
            appendOutputLine(`Vocals shift vs base: ${result.report.lag_vocals_to_base_seconds.toFixed(3)} s`);
            if (result.report.lag_vocals_method) {
              appendOutputLine(`Vocals align method: ${result.report.lag_vocals_method}`);
            }
            if (typeof result.report.lag_vocals_nudge_seconds === 'number' && result.report.lag_vocals_nudge_seconds !== 0) {
              appendOutputLine(`Vocals nudge applied: ${result.report.lag_vocals_nudge_seconds.toFixed(3)} s`);
            }
          }
          if (typeof result.report.lag_instrumental_to_base_seconds === 'number') {
            appendOutputLine(`Instrumental shift vs base: ${result.report.lag_instrumental_to_base_seconds.toFixed(3)} s`);
          }
        }
        const preparedApplied = applyPreparedOutputs(result.report.prepared_outputs);
        if (preparedApplied) {
          if (runAlign) {
            state.disableBaseMetadataCopy = true;
            appendOutputLine('2-stem fields auto-filled from aligned stems.');
          } else if (state.mode === 'four') {
            state.disableBaseMetadataCopy = false;
            appendOutputLine('4-stem fields auto-filled from extracted stems.');
          } else {
            state.disableBaseMetadataCopy = false;
            appendOutputLine('2-stem fields auto-filled from extracted stems.');
          }
        }
        if (runAlign && preparedApplied) {
          appendOutputLine('Opening manual align timeline...');
          await openManualAlignEditor(result.report);
          appendOutputLine('Manual align closed. Next step: press Prepare Serato Files.');
        } else {
          appendOutputLine('Next step: press Prepare Serato Files.');
        }
      }
    } else {
      setStatus(runAlign ? 'Stem alignment failed' : 'Stem extraction failed');
      setExtractProgress(false);
      setRetailOutput(
        runAlign ? 'Alignment failed.' : 'Extraction failed.',
        [`Error: ${result.error || 'Unknown error'}`, 'Adjust inputs/settings and retry Step 1.'],
      );
      appendOutputLine('');
      appendOutputLine(result.traceback || result.error || 'Unknown error');
    }
  } catch (err) {
    setStatus(runAlign ? 'Stem alignment failed' : 'Stem extraction failed');
    setExtractProgress(false);
    setRetailOutput(
      runAlign ? 'Alignment failed.' : 'Extraction failed.',
      [`Error: ${String(err)}`, 'Retry Step 1.'],
    );
    appendOutputLine('');
    appendOutputLine(String(err));
  } finally {
    state.activeProgressToken = '';
    setProcessing(false);
    extractBtn.disabled = false;
    prepBtn.disabled = false;
    buildBtn.disabled = false;
  }
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function manualHasSolo() {
  return Boolean(manualAlign.tracks.base.solo || manualAlign.tracks.vocals.solo || manualAlign.tracks.instrumental.solo);
}

function timeToPx(seconds, laneWidth) {
  return (seconds / manualAlign.duration) * laneWidth;
}

function pxToTime(px, laneWidth) {
  if (!laneWidth) return 0;
  return (px / laneWidth) * manualAlign.duration;
}

function formatTime(seconds) {
  return `${Math.max(0, seconds).toFixed(2)}s`;
}

function updateTransportTimeDisplay() {
  if (!transportTime) return;
  transportTime.textContent = formatTime(manualAlign.playbackOffset);
}

function updatePlayheadVisual() {
  const ratio = clamp(manualAlign.playbackOffset / manualAlign.duration, 0, 1);
  if (manualPlayheadRuler && manualRuler) {
    const width = manualRuler.clientWidth || 1;
    manualPlayheadRuler.style.left = `${ratio * width}px`;
  }
  ['base', 'vocals', 'instrumental'].forEach((id) => {
    const lane = manualTracks[id].lane;
    const line = manualTracks[id].playhead;
    if (!lane || !line) return;
    const width = lane.clientWidth || 1;
    line.style.left = `${ratio * width}px`;
  });
}

function updateTransportToggleButton() {
  if (!transportPlayToggleBtn) return;
  transportPlayToggleBtn.classList.toggle('is-playing', manualAlign.isPlaying);
  transportPlayToggleBtn.setAttribute('aria-label', manualAlign.isPlaying ? 'Pause' : 'Play');
  const lbl = transportPlayToggleBtn.querySelector('.btn-label') || transportPlayToggleBtn;
  lbl.textContent = manualAlign.isPlaying ? 'Pause' : 'Play';
}

function stopManualPlayback(resetToZero = false) {
  if (manualAlign.resyncTimer) {
    clearTimeout(manualAlign.resyncTimer);
    manualAlign.resyncTimer = 0;
  }
  if (!manualAlign.isPlaying) {
    if (resetToZero) {
      manualAlign.playbackOffset = 0;
      updateTransportTimeDisplay();
    }
    return;
  }
  manualAlign.isPlaying = false;
  if (manualAlign.rafId) {
    cancelAnimationFrame(manualAlign.rafId);
    manualAlign.rafId = 0;
  }
  if (manualAlign.sourceNodes) {
    manualAlign.sourceNodes.forEach((node) => {
      try {
        node.stop();
      } catch (_err) {
        // no-op
      }
    });
  }
  manualAlign.sourceNodes = [];
  if (resetToZero) manualAlign.playbackOffset = 0;
  updateTransportToggleButton();
  updateTransportTimeDisplay();
  updatePlayheadVisual();
}

function manualPlaybackTick() {
  if (!manualAlign.isPlaying || !manualAlign.audioCtx) return;
  const elapsed = manualAlign.audioCtx.currentTime - manualAlign.playbackStartAt;
  manualAlign.playbackOffset = clamp(elapsed, 0, manualAlign.duration);
  updateTransportTimeDisplay();
  updatePlayheadVisual();
  if (manualAlign.playbackOffset >= manualAlign.duration - 0.001) {
    stopManualPlayback(false);
    return;
  }
  manualAlign.rafId = requestAnimationFrame(manualPlaybackTick);
}

function playManualTimeline() {
  if (!manualAlign.audioCtx) return;
  if (manualAlign.isPlaying) return;
  if (manualAlign.audioCtx.state === 'suspended') {
    manualAlign.audioCtx.resume().catch(() => null);
  }

  const sourceNodes = [];
  const now = manualAlign.audioCtx.currentTime;
  const playhead = manualAlign.playbackOffset;
  const hasSolo = manualHasSolo();

  const scheduleTrack = (trackId) => {
    const buffer = manualAlign.buffers[trackId];
    if (!buffer) return;
    const t = manualAlign.tracks[trackId];
    if (t?.mute) return;
    if (hasSolo && !t?.solo) return;
    const offset = trackId === 'base' ? 0 : manualAlign.tracks[trackId].offset;
    const clipStart = trackId === 'base' ? 0 : manualAlign.tracks[trackId].clipStart;
    const clipEnd = trackId === 'base' ? buffer.duration : manualAlign.tracks[trackId].clipEnd;
    const clipLen = Math.max(0, clipEnd - clipStart);
    if (clipLen <= 0.001) return;

    const segmentStart = offset;
    const segmentEnd = offset + clipLen;
    if (segmentEnd <= playhead) return;

    const source = manualAlign.audioCtx.createBufferSource();
    source.buffer = buffer;
    source.connect(manualAlign.audioCtx.destination);

    const startDelay = Math.max(0, segmentStart - playhead);
    const srcOffset = clipStart + Math.max(0, playhead - segmentStart);
    const playableDuration = Math.min(clipEnd - srcOffset, manualAlign.duration - playhead - startDelay);
    if (playableDuration <= 0.001) return;

    source.start(now + startDelay, srcOffset, playableDuration);
    sourceNodes.push(source);
  };

  scheduleTrack('base');
  scheduleTrack('vocals');
  scheduleTrack('instrumental');

  manualAlign.sourceNodes = sourceNodes;
  manualAlign.playbackStartAt = now - playhead;
  manualAlign.isPlaying = true;
  updateTransportToggleButton();
  manualAlign.rafId = requestAnimationFrame(manualPlaybackTick);
}

function resyncPlaybackIfPlaying() {
  if (!manualAlign.isPlaying) return;
  const keepOffset = manualAlign.playbackOffset;
  stopManualPlayback(false);
  manualAlign.playbackOffset = keepOffset;
  playManualTimeline();
}

function requestPlaybackResync() {
  if (!manualAlign.isPlaying) return;
  if (manualAlign.resyncTimer) {
    clearTimeout(manualAlign.resyncTimer);
  }
  manualAlign.resyncTimer = setTimeout(() => {
    manualAlign.resyncTimer = 0;
    resyncPlaybackIfPlaying();
  }, 45);
}

function seekToPointerX(clientX) {
  if (!manualRuler) return;
  const rect = manualRuler.getBoundingClientRect();
  const x = clamp(clientX - rect.left, 0, rect.width || 1);
  const nextTime = pxToTime(x, rect.width || 1);
  manualAlign.playbackOffset = clamp(nextTime, 0, manualAlign.duration);
  updateTransportTimeDisplay();
  updatePlayheadVisual();
}

async function decodeAudioFromPath(path) {
  const raw = await window.stemsApi.readAudioBytes(path);
  if (!raw) throw new Error(`Unable to read audio file: ${path}`);
  const u8 = raw instanceof Uint8Array ? raw : new Uint8Array(raw);
  const buf = u8.buffer.slice(u8.byteOffset, u8.byteOffset + u8.byteLength);
  return manualAlign.audioCtx.decodeAudioData(buf.slice(0));
}

function buildWaveform(buffer, points = WAVEFORM_POINTS) {
  if (!buffer) return [];
  const channels = buffer.numberOfChannels;
  const length = buffer.length;
  if (!length) return [];
  const step = Math.max(1, Math.floor(length / points));
  const out = new Array(points).fill(0);
  for (let i = 0; i < points; i += 1) {
    const start = i * step;
    const end = Math.min(length, start + step);
    let peak = 0;
    for (let c = 0; c < channels; c += 1) {
      const data = buffer.getChannelData(c);
      for (let s = start; s < end; s += 1) {
        const v = Math.abs(data[s]);
        if (v > peak) peak = v;
      }
    }
    out[i] = peak;
  }
  return out;
}

function drawWaveform(canvas, waveform, color = 'rgba(110, 184, 238, 0.7)') {
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(1, Math.floor(rect.width));
  const height = Math.max(1, Math.floor(rect.height));
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const mid = height * 0.5;
  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  const len = waveform.length || 1;
  for (let x = 0; x < width; x += 1) {
    const idx = Math.min(len - 1, Math.floor((x / width) * len));
    const amp = waveform[idx] || 0;
    const h = amp * (height * 0.44);
    ctx.beginPath();
    ctx.moveTo(x + 0.5, mid - h);
    ctx.lineTo(x + 0.5, mid + h);
    ctx.stroke();
  }
}

function renderManualRuler() {
  if (!manualRuler) return;
  const existingPlayhead = manualPlayheadRuler || null;
  manualRuler.querySelectorAll('.manual-ruler-tick, .manual-ruler-label').forEach((el) => el.remove());
  if (existingPlayhead && existingPlayhead.parentElement !== manualRuler) {
    manualRuler.appendChild(existingPlayhead);
  }
  const width = manualRuler.clientWidth || 1;
  const whole = Math.max(1, Math.ceil(manualAlign.duration));
  for (let s = 0; s <= whole; s += 1) {
    const left = (s / manualAlign.duration) * width;
    const tick = document.createElement('div');
    tick.className = 'manual-ruler-tick';
    tick.style.left = `${left}px`;
    manualRuler.appendChild(tick);

    const label = document.createElement('div');
    label.className = 'manual-ruler-label';
    label.style.left = `${left}px`;
    label.textContent = `${s}s`;
    manualRuler.appendChild(label);
  }
}

function setManualSelected(trackId) {
  if (!manualTracks[trackId] || manualTracks[trackId].locked) return;
  manualAlign.selectedTrackId = trackId;
  ['vocals', 'instrumental'].forEach((id) => {
    manualTracks[id].clip.classList.toggle('manual-active', id === trackId);
  });
}

function applyManualButtonStates() {
  ['base', 'vocals', 'instrumental'].forEach((id) => {
    const t = manualAlign.tracks[id];
    manualTracks[id].muteBtn?.classList.toggle('manual-toggle-active', Boolean(t.mute));
    manualTracks[id].soloBtn?.classList.toggle('manual-toggle-active', Boolean(t.solo));
  });
}

function layoutManualClips() {
  const laneWidth = manualTracks.base.lane.clientWidth || 1;
  const setClip = (id) => {
    const clip = manualTracks[id].clip;
    if (id === 'base') {
      clip.style.left = '0px';
      clip.style.width = `${laneWidth}px`;
      return;
    }
    const track = manualAlign.tracks[id];
    const widthSec = Math.max(0.05, track.clipEnd - track.clipStart);
    const leftPx = timeToPx(track.offset, laneWidth);
    const widthPx = Math.max(38, timeToPx(widthSec, laneWidth));
    clip.style.left = `${leftPx}px`;
    clip.style.width = `${widthPx}px`;
  };
  setClip('base');
  setClip('vocals');
  setClip('instrumental');
  drawWaveform(manualTracks.vocals.wave, manualAlign.waveforms.vocals, 'rgba(98, 226, 195, 0.84)');
  drawWaveform(manualTracks.instrumental.wave, manualAlign.waveforms.instrumental, 'rgba(141, 174, 255, 0.82)');
  updateTransportTimeDisplay();
  updatePlayheadVisual();
}

function renderManualAlign() {
  renderManualRuler();
  drawWaveform(manualTracks.base.wave, manualAlign.waveforms.base, 'rgba(166, 189, 218, 0.72)');
  layoutManualClips();
  applyManualButtonStates();
  setManualSelected(manualAlign.selectedTrackId);
}

function hideManualAlignOverlay() {
  stopManualPlayback(false);
  manualAlign.isOpen = false;
  if (manualAlignOverlay) {
    manualAlignOverlay.classList.add('hidden');
    manualAlignOverlay.setAttribute('aria-hidden', 'true');
    manualAlignOverlay.style.display = 'none';
  }
}

async function commitManualAlign() {
  if (!manualAlign.isOpen) return;
  manualAlignConfirmBtn.disabled = true;
  setStatus('Committing manual alignment...');
  appendOutputLine('Rendering manual alignment replacements...');
  try {
    const payload = {
      action: 'manual_align_commit',
      mode: 'two',
      base: state.values.base,
      vocals: state.values.vocals,
      instrumental: state.values.instrumental,
      vocals_offset_seconds: manualAlign.tracks.vocals.offset,
      instrumental_offset_seconds: manualAlign.tracks.instrumental.offset,
      vocals_clip_start_seconds: manualAlign.tracks.vocals.clipStart,
      vocals_clip_end_seconds: manualAlign.tracks.vocals.clipEnd,
      instrumental_clip_start_seconds: manualAlign.tracks.instrumental.clipStart,
      instrumental_clip_end_seconds: manualAlign.tracks.instrumental.clipEnd,
    };
    const result = await window.stemsApi.runBuild(payload);
    const report = result?.report || {};
    const hasCommittedFiles =
      Boolean(report.manual_align_folder) ||
      (Boolean(report?.prepared_outputs?.vocals) && Boolean(report?.prepared_outputs?.instrumental));
    if (!result?.ok && !hasCommittedFiles) {
      throw new Error(result.traceback || result.error || 'manual align commit failed');
    }

    if (applyPreparedOutputs(report.prepared_outputs || null)) {
      appendOutputLine('Manual aligned stems committed and loaded into Step 2.');
    }
    if (report.manual_align_folder) {
      appendOutputLine(`Manual aligned stems saved to "${report.manual_align_folder}"`);
    } else if (!result?.ok && hasCommittedFiles) {
      appendOutputLine('Manual aligned stems were generated; continuing to Step 2.');
    }
    hideManualAlignOverlay();
    try {
      setActionHighlight('prep');
      setStatus('Manual alignment committed. Continue with Prepare Files.');
    } catch (_err) {
      // Keep workflow moving even if a non-critical UI refresh fails.
    }
  } catch (err) {
    appendOutputLine(String(err));
    setStatus('Manual align commit failed');
  } finally {
    manualAlignConfirmBtn.disabled = false;
  }
}

async function openManualAlignEditor(report) {
  if (manualAlignOverlay == null) return;
  stopManualPlayback(true);
  if (!manualAlign.audioCtx) {
    manualAlign.audioCtx = new AudioContext();
  }

  const basePath = state.values.base;
  const vocalsPath = state.values.vocals;
  const instrumentalPath = state.values.instrumental;
  manualAlign.alignFolder = report?.align_folder || '';

  setStatus('Loading manual align editor...');
  const [baseBuf, vocalsBuf, instBuf] = await Promise.all([
    decodeAudioFromPath(basePath),
    decodeAudioFromPath(vocalsPath),
    decodeAudioFromPath(instrumentalPath),
  ]);
  manualAlign.buffers.base = baseBuf;
  manualAlign.buffers.vocals = vocalsBuf;
  manualAlign.buffers.instrumental = instBuf;
  manualAlign.waveforms.base = buildWaveform(baseBuf);
  manualAlign.waveforms.vocals = buildWaveform(vocalsBuf);
  manualAlign.waveforms.instrumental = buildWaveform(instBuf);
  manualAlign.duration = Math.max(1, baseBuf.duration, vocalsBuf.duration, instBuf.duration);
  manualAlign.playbackOffset = 0;
  updateTransportToggleButton();
  manualAlign.tracks.base.offset = 0;
  manualAlign.tracks.base.clipStart = 0;
  manualAlign.tracks.base.clipEnd = baseBuf.duration;
  manualAlign.tracks.base.mute = false;
  manualAlign.tracks.base.solo = false;
  manualAlign.tracks.vocals.offset = 0;
  manualAlign.tracks.vocals.clipStart = 0;
  manualAlign.tracks.vocals.clipEnd = vocalsBuf.duration;
  manualAlign.tracks.vocals.mute = false;
  manualAlign.tracks.vocals.solo = false;
  manualAlign.tracks.instrumental.offset = 0;
  manualAlign.tracks.instrumental.clipStart = 0;
  manualAlign.tracks.instrumental.clipEnd = instBuf.duration;
  manualAlign.tracks.instrumental.mute = false;
  manualAlign.tracks.instrumental.solo = false;
  manualAlign.selectedTrackId = 'vocals';
  manualAlign.isOpen = true;
  manualAlign.initialTracks.vocals = {
    offset: manualAlign.tracks.vocals.offset,
    clipStart: manualAlign.tracks.vocals.clipStart,
    clipEnd: manualAlign.tracks.vocals.clipEnd,
  };
  manualAlign.initialTracks.instrumental = {
    offset: manualAlign.tracks.instrumental.offset,
    clipStart: manualAlign.tracks.instrumental.clipStart,
    clipEnd: manualAlign.tracks.instrumental.clipEnd,
  };

  manualAlignOverlay.classList.remove('hidden');
  manualAlignOverlay.setAttribute('aria-hidden', 'false');
  manualAlignOverlay.style.display = '';
  renderManualAlign();
  setStatus('Manual alignment editor ready');
}

function handleManualClipPointerDown(trackId, event) {
  if (!manualAlign.isOpen || manualTracks[trackId].locked) return;
  event.preventDefault();
  setManualSelected(trackId);
  const lane = manualTracks[trackId].lane;
  const track = manualAlign.tracks[trackId];
  const startX = event.clientX;
  const laneWidth = lane.clientWidth || 1;
  const initialOffset = track.offset;
  const initialEnd = track.clipEnd;
  const mode = event.target?.classList?.contains('manual-clip-handle') ? 'trim' : 'move';

  const onMove = (e) => {
    const dx = e.clientX - startX;
    const dt = pxToTime(dx, laneWidth);
    if (mode === 'move') {
      track.offset = clamp(initialOffset + dt, -track.clipEnd + 0.02, manualAlign.duration);
    } else {
      track.clipEnd = clamp(initialEnd + dt, track.clipStart + 0.05, manualAlign.buffers[trackId].duration);
    }
    layoutManualClips();
    requestPlaybackResync();
  };
  const onUp = () => {
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
  };
  window.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onUp);
}

function manualNudgeSelected(direction) {
  const id = manualAlign.selectedTrackId;
  const t = manualAlign.tracks[id];
  if (!t) return;
  t.offset = clamp(t.offset + direction * NUDGE_SECONDS, -t.clipEnd + 0.02, manualAlign.duration);
  layoutManualClips();
  resyncPlaybackIfPlaying();
}

function resetManualTrack(trackId) {
  const t = manualAlign.tracks[trackId];
  const initial = manualAlign.initialTracks[trackId];
  const buffer = manualAlign.buffers[trackId];
  if (!t || !initial || !buffer) return;
  t.offset = initial.offset;
  t.clipStart = clamp(initial.clipStart, 0, buffer.duration - 0.01);
  t.clipEnd = clamp(initial.clipEnd, t.clipStart + 0.01, buffer.duration);
  layoutManualClips();
  resyncPlaybackIfPlaying();
}

function setupManualAlignHandlers() {
  manualTracks.vocals.clip?.addEventListener('pointerdown', (e) => handleManualClipPointerDown('vocals', e));
  manualTracks.instrumental.clip?.addEventListener('pointerdown', (e) => handleManualClipPointerDown('instrumental', e));
  manualTracks.vocals.clip?.addEventListener('click', () => setManualSelected('vocals'));
  manualTracks.instrumental.clip?.addEventListener('click', () => setManualSelected('instrumental'));

  manualTracks.base.muteBtn?.addEventListener('click', () => {
    manualAlign.tracks.base.mute = !manualAlign.tracks.base.mute;
    applyManualButtonStates();
    resyncPlaybackIfPlaying();
  });
  manualTracks.base.soloBtn?.addEventListener('click', () => {
    manualAlign.tracks.base.solo = !manualAlign.tracks.base.solo;
    applyManualButtonStates();
    resyncPlaybackIfPlaying();
  });
  manualTracks.vocals.muteBtn?.addEventListener('click', () => {
    manualAlign.tracks.vocals.mute = !manualAlign.tracks.vocals.mute;
    applyManualButtonStates();
    resyncPlaybackIfPlaying();
  });
  manualTracks.instrumental.muteBtn?.addEventListener('click', () => {
    manualAlign.tracks.instrumental.mute = !manualAlign.tracks.instrumental.mute;
    applyManualButtonStates();
    resyncPlaybackIfPlaying();
  });
  manualTracks.vocals.soloBtn?.addEventListener('click', () => {
    manualAlign.tracks.vocals.solo = !manualAlign.tracks.vocals.solo;
    applyManualButtonStates();
    resyncPlaybackIfPlaying();
  });
  manualTracks.instrumental.soloBtn?.addEventListener('click', () => {
    manualAlign.tracks.instrumental.solo = !manualAlign.tracks.instrumental.solo;
    applyManualButtonStates();
    resyncPlaybackIfPlaying();
  });
  manualTracks.vocals.resetBtn?.addEventListener('click', () => {
    resetManualTrack('vocals');
  });
  manualTracks.instrumental.resetBtn?.addEventListener('click', () => {
    resetManualTrack('instrumental');
  });

  const beginRulerSeek = (startEvent) => {
    if (!manualAlign.isOpen) return;
    startEvent.preventDefault();
    seekToPointerX(startEvent.clientX);
    resyncPlaybackIfPlaying();
    const onMove = (e) => {
      seekToPointerX(e.clientX);
      requestPlaybackResync();
    };
    const onUp = () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  };
  manualRuler?.addEventListener('pointerdown', beginRulerSeek);
  manualPlayheadRuler?.addEventListener('pointerdown', beginRulerSeek);

  transportRestartBtn?.addEventListener('click', () => {
    stopManualPlayback(true);
  });
  transportPlayToggleBtn?.addEventListener('click', () => {
    if (manualAlign.isPlaying) stopManualPlayback(false);
    else playManualTimeline();
  });
  manualAlignCancelBtn?.addEventListener('click', () => {
    hideManualAlignOverlay();
  });
  manualAlignConfirmBtn?.addEventListener('click', () => {
    commitManualAlign();
  });

  window.addEventListener('keydown', (e) => {
    if (!manualAlign.isOpen) return;
    if (e.key === ' ') {
      e.preventDefault();
      if (manualAlign.isPlaying) stopManualPlayback(false);
      else playManualTimeline();
      return;
    }
    if (e.key === 'ArrowLeft') {
      e.preventDefault();
      manualNudgeSelected(-1);
      return;
    }
    if (e.key === 'ArrowRight') {
      e.preventDefault();
      manualNudgeSelected(1);
    }
  });

  window.addEventListener('resize', () => {
    if (manualAlign.isOpen) {
      renderManualAlign();
    }
  });
}

async function runPrepare() {
  ensureOriginalBasePath();
  state.activeProgressToken = '';
  const validationErr = validate();
  if (validationErr) {
    setProcessing(false);
    setStatus('Missing required input');
    setOutput(validationErr);
    return;
  }

  setProcessing(true);
  buildBtn.disabled = true;
  extractBtn.disabled = true;
  prepBtn.disabled = true;
  setStatus('Preparing Serato files...');
  setExtractProgress(false);
  setOutput('Preparing files...');
  setRetailOutput(
    'Preparing files for build...',
    [
      'Wait while base and stem files are prepared.',
      'Then continue to Build .Stem.',
    ],
  );

  const payload = {
    action: 'prepare',
    mode: state.mode,
    base: state.values.base,
    vocals: state.values.vocals,
    bass: state.values.bass,
    drums: state.values.drums,
    melody: state.values.melody,
    instrumental: state.values.instrumental,
    stem_delay_ms: state.values.stem_delay_ms,
    add_gain_stems: Boolean(state.values.add_gain_stems),
    disable_base_metadata_copy: Boolean(state.disableBaseMetadataCopy),
  };
  try {
    const result = await window.stemsApi.runBuild(payload);
    if (result.ok) {
      setActionHighlight('build');
      setStatus('Prepare finished successfully');
      setOutput('');
      if (!state.debugMode) {
        const folder = result.report?.prep_folder || '(unknown)';
        const notes = [];
        if (Number(result.report?.stem_gain_db || 0) > 0) {
          notes.push(`Stem gain applied: +${Number(result.report.stem_gain_db).toFixed(1)} dB`);
        }
        setRetailOutput(
          'Prepare complete.',
          [
            `Prepared folder: ${folder}`,
            'Before Step 3, close Serato (recommended).',
            'Step 3: click Build .Stem.',
          ],
          notes,
        );
      }
      if (result.report) {
        const folder = result.report.prep_folder || '(unknown)';
        appendOutputLine(`Prepared stems placed in "${folder}"`);
        if (result.report.base_metadata_from_source) {
          const method = result.report.base_metadata_copy_method ? ` via ${result.report.base_metadata_copy_method}` : '';
          appendOutputLine(`Prepared base includes source ID3/art metadata${method}.`);
        }
        if (Number(result.report.stem_gain_db || 0) > 0) {
          appendOutputLine(`Applied stem gain: +${Number(result.report.stem_gain_db).toFixed(1)} dB (base unchanged)`);
        }
        appendOutputLine('Before Build .Stem: close Serato (recommended).');
        appendOutputLine('When ready, press Build Stem File button');
        if (applyPreparedOutputs(result.report.outputs)) {
          appendOutputLine('Form inputs updated to prepared files.');
        }
      }
    } else {
      setStatus('Prepare failed');
      setRetailOutput(
        'Prepare failed.',
        [
          `Error: ${result.error || 'Unknown error'}`,
          'Check required files and retry Prepare.',
        ],
      );
      appendOutputLine('');
      appendOutputLine('Prepare failed.');
      appendOutputLine('');
      appendOutputLine(result.traceback || result.error || 'Unknown error');
    }
  } catch (err) {
    setStatus('Prepare failed');
    setRetailOutput(
      'Prepare failed.',
      [
        `Error: ${String(err)}`,
        'Retry Prepare after checking inputs.',
      ],
    );
    appendOutputLine('');
    appendOutputLine('Prepare failed.');
    appendOutputLine('');
    appendOutputLine(String(err));
  } finally {
    setProcessing(false);
    buildBtn.disabled = false;
    extractBtn.disabled = false;
    prepBtn.disabled = false;
  }
}

function clearAll() {
  hideManualAlignOverlay();
  state.disableBaseMetadataCopy = false;
  state.values = Object.fromEntries(fields.map((f) => [f.id, '']));
  state.values.stem_delay_ms = '0';
  state.values.step1_analysis_seconds = '90';
  state.values.step1_max_shift_seconds = '30';
  state.values.step1_vocal_nudge_seconds = '0';
  state.values.add_gain_stems = '1';
  state.originalBasePath = '';
  document.querySelectorAll('.field-row input').forEach((el) => {
    if (el.id === 'input-stem_delay_ms') {
      el.value = '0';
    } else if (el.id === 'input-step1_analysis_seconds') {
      el.value = '90';
    } else if (el.id === 'input-step1_max_shift_seconds') {
      el.value = '30';
    } else if (el.id === 'input-step1_vocal_nudge_seconds') {
      el.value = '0';
    } else if (el.id === 'input-add_gain_stems') {
      el.checked = true;
    } else {
      el.value = '';
    }
  });
  setStatus('Ready');
  setExtractProgress(false);
  setRetailOutput(
    'Ready.',
    [
      'Step 1: Extract Stems (or Align in 2-stem mode).',
      'Step 2: Prepare Files.',
      'Step 3: Build .Stem.',
    ],
  );
  if (state.debugMode) setOutput('Build output will appear here.');
  setActionHighlight('extract');
  setProcessing(false);
}

function init() {
  // Prevent dropped files from being opened by the renderer window.
  window.addEventListener('dragover', (e) => e.preventDefault());
  window.addEventListener('drop', (e) => e.preventDefault());

  renderFields();
  setActionHighlight('extract');
  setProcessing(false);
  applyStep1ModeUI();
  setupManualAlignHandlers();
  if (window.stemsApi?.onBuildProgress) {
    window.stemsApi.onBuildProgress(handleBuildProgress);
  }
  if (debugModeToggle) {
    debugModeToggle.checked = state.debugMode;
    debugModeToggle.addEventListener('change', (e) => {
      state.debugMode = Boolean(e.target.checked);
      if (state.debugMode) {
        setOutput('Debug mode enabled. Detailed logs will appear here.');
      } else {
        setRetailOutput(
          'Retail mode enabled.',
          [
            'Simple status and instructions are shown here.',
            'Use Debug Mode for full logs.',
          ],
        );
      }
    });
  }
  setExtractProgress(false);
  setRetailOutput(
    'Ready.',
    [
      'Step 1: Extract Stems (or Align in 2-stem mode).',
      'Step 2: Prepare Files.',
      'Step 3: Build .Stem.',
    ],
  );

  document.querySelectorAll('input[name="mode"]').forEach((input) => {
    input.addEventListener('change', (e) => {
      state.mode = e.target.value;
      if (state.mode === 'four') {
        // 4-stem mode now supports Step 1 extraction; always land on extract.
        // Also force Step 1 mode back to extract (align is 2-stem only).
        state.step1Mode = 'extract';
        state.disableBaseMetadataCopy = false;
        const step1ExtractInput = document.querySelector('input[name="step1_mode"][value="extract"]');
        if (step1ExtractInput) step1ExtractInput.checked = true;
        setActionHighlight('extract');
      } else {
        setActionHighlight('extract');
      }
      applyStep1ModeUI();
    });
  });
  document.querySelectorAll('input[name="step1_mode"]').forEach((input) => {
    input.addEventListener('change', (e) => {
      state.step1Mode = e.target.value === 'align' ? 'align' : 'extract';
      if (state.step1Mode === 'extract') {
        state.disableBaseMetadataCopy = false;
      }
      if (state.step1Mode === 'align') {
        state.mode = 'two';
        const modeInput = document.querySelector('input[name="mode"][value="two"]');
        if (modeInput) modeInput.checked = true;
      }
      applyMode();
      applyStep1ModeUI();
    });
  });

  buildBtn.addEventListener('click', () => {
    setActionHighlight('build');
    runBuild();
  });
  extractBtn.addEventListener('click', () => {
    setActionHighlight('extract');
    runStep1();
  });
  prepBtn.addEventListener('click', () => {
    setActionHighlight('prep');
    runPrepare();
  });
  clearBtn.addEventListener('click', clearAll);
}

init();
