const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('stemsApi', {
  pickFile: (kind) => ipcRenderer.invoke('pick-file', kind),
  pickFolder: () => ipcRenderer.invoke('pick-folder'),
  pickSaveFile: () => ipcRenderer.invoke('pick-save-file'),
  runBuild: (payload) => ipcRenderer.invoke('run-build', payload),
  readAudioBytes: (filePath) => ipcRenderer.invoke('read-audio-bytes', filePath),
  onBuildProgress: (handler) => {
    const wrapped = (_event, payload) => {
      try {
        handler(payload);
      } catch (_err) {
        // no-op
      }
    };
    ipcRenderer.on('build-progress', wrapped);
    return () => ipcRenderer.removeListener('build-progress', wrapped);
  },
  getPathForFile: (file) => {
    try {
      if (!file) return '';
      return webUtils.getPathForFile(file) || '';
    } catch (_err) {
      return '';
    }
  },
});
