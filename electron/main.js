const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs/promises');
const fsSync = require('fs');

const APP_DIR = path.resolve(__dirname, '..');
const BUNDLED_PYTHON_VERSION = '3.9';

function buildPythonEnv(pythonCmd) {
  const env = { ...process.env, PYTHONNOUSERSITE: '1' };
  const normalized = String(pythonCmd || '');
  const bundledMarker = `${path.sep}Python3.framework${path.sep}`;

  if (normalized.includes(bundledMarker)) {
    const prefix = path.resolve(path.dirname(normalized), '..');
    const pydeps = path.join(APP_DIR, 'tools', '_pydeps');
    env.PYTHONHOME = prefix;
    env.PYTHONPATH = fsSync.existsSync(pydeps) ? pydeps : '';
  }

  return env;
}

function getBundledPythonCandidates() {
  const frameworkRoot = path.join(process.resourcesPath, '..', 'Frameworks', 'Python3.framework');
  const versionRoot = path.join(frameworkRoot, 'Versions', BUNDLED_PYTHON_VERSION);
  return [
    path.join(versionRoot, 'bin', `python${BUNDLED_PYTHON_VERSION}`),
    path.join(versionRoot, 'bin', 'python3'),
  ];
}

function getPythonCandidates() {
  return [
    ...getBundledPythonCandidates(),
    'python3',
    'python',
  ];
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1200,
    height: 860,
    minWidth: 1260,
    minHeight: 700,
    backgroundColor: '#0d1119',
    title: 'Custom Stem Injector',
    titleBarStyle: 'hidden',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
}


app.whenReady().then(() => {
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  app.quit();
});

ipcMain.handle('pick-file', async (_event, kind) => {
  const filters =
    kind === 'mp3'
      ? [{ name: 'MP3', extensions: ['mp3'] }, { name: 'All Files', extensions: ['*'] }]
      : [
          {
            name: 'Audio',
            extensions: ['mp3', 'wav', 'aif', 'aiff', 'm4a', 'flac', 'serato-stems'],
          },
          { name: 'All Files', extensions: ['*'] },
        ];

  const result = await dialog.showOpenDialog({
    title: 'Choose file',
    properties: ['openFile'],
    filters,
  });

  if (result.canceled || !result.filePaths?.length) return '';
  return result.filePaths[0];
});

ipcMain.handle('pick-folder', async () => {
  const result = await dialog.showOpenDialog({
    title: 'Choose output folder',
    properties: ['openDirectory', 'createDirectory'],
  });

  if (result.canceled || !result.filePaths?.length) return '';
  return result.filePaths[0];
});

ipcMain.handle('pick-save-file', async () => {
  const result = await dialog.showSaveDialog({
    title: 'Choose output file',
    defaultPath: 'custom-output.serato-stems',
    filters: [
      { name: 'Serato Stems', extensions: ['serato-stems'] },
      { name: 'All Files', extensions: ['*'] },
    ],
  });

  if (result.canceled || !result.filePath) return '';
  return result.filePath;
});

ipcMain.handle('read-audio-bytes', async (_event, filePath) => {
  const target = String(filePath || '').trim();
  if (!target) return null;
  try {
    const bytes = await fs.readFile(target);
    return bytes;
  } catch (_err) {
    return null;
  }
});

function runBridge(pythonCmd, payload) {
  return new Promise((resolve, reject) => {
    const scriptPath = path.join(APP_DIR, 'tools', 'electron_build_bridge.py');
    const child = spawn(pythonCmd, [scriptPath], {
      cwd: APP_DIR,
      env: buildPythonEnv(pythonCmd),
    });

    let stdout = '';
    let stderr = '';
    let stderrLineBuffer = '';

    child.stdout.on('data', (buf) => {
      stdout += buf.toString('utf8');
    });

    child.stderr.on('data', (buf) => {
      const text = buf.toString('utf8');
      stderr += text;
      stderrLineBuffer += text;
      const lines = stderrLineBuffer.split(/\r?\n/);
      stderrLineBuffer = lines.pop() || '';
      for (const line of lines) {
        const marker = 'PROGRESS_JSON:';
        if (!line.startsWith(marker)) continue;
        try {
          const progress = JSON.parse(line.slice(marker.length));
          if (BrowserWindow.getAllWindows().length > 0) {
            BrowserWindow.getAllWindows().forEach((win) => {
              win.webContents.send('build-progress', progress);
            });
          }
        } catch (_err) {
          // Ignore malformed progress events; keep bridge robust.
        }
      }
    });

    child.on('error', (err) => reject(err));

    child.on('close', (code) => {
      try {
        const parsed = JSON.parse(stdout);
        if (code !== 0) {
          return resolve(parsed);
        }
        resolve(parsed);
      } catch (err) {
        if (code !== 0) {
          return reject(new Error(stderr || stdout || `Bridge exited with code ${code}`));
        }
        reject(new Error(`Invalid bridge response: ${stdout || stderr || err.message}`));
      }
    });

    child.stdin.write(JSON.stringify(payload));
    child.stdin.end();
  });
}

ipcMain.handle('run-build', async (_event, payload) => {
  try {
    const attempts = [];
    for (const pythonCmd of getPythonCandidates()) {
      try {
        return await runBridge(pythonCmd, payload);
      } catch (err) {
        const msg = String(err?.message || err);
        const code = String(err?.code || '');
        const lower = msg.toLowerCase();
        const isMissingCmd =
          code === 'ENOENT' ||
          lower.includes('enoent') ||
          lower.includes('spawn ') ||
          lower.includes('not found');
        attempts.push(`${pythonCmd}: ${msg}`);
        if (!isMissingCmd) throw err;
      }
    }
    throw new Error(`No usable Python runtime found. Attempts: ${attempts.join(' | ')}`);
  } catch (err) {
    return {
      ok: false,
      error: String(err?.message || err),
    };
  }
});
