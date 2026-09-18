// Canonical WAV makes the 10-minute limit independently verifiable on the server.
export async function encodeSpeech(blob: Blob): Promise<Blob> {
  const context = new AudioContext();
  try {
    const decoded = await context.decodeAudioData(await blob.arrayBuffer());
    const frames = Math.min(Math.floor(decoded.duration * 16000), 600 * 16000);
    const offline = new OfflineAudioContext(1, frames, 16000);
    const source = offline.createBufferSource();
    source.buffer = decoded; source.connect(offline.destination); source.start();
    const audio = (await offline.startRendering()).getChannelData(0);
    const buffer = new ArrayBuffer(44 + audio.length * 2);
    const view = new DataView(buffer);
    const tag = (offset: number, value: string) => { [...value].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0))); };
    tag(0, 'RIFF'); view.setUint32(4, buffer.byteLength - 8, true); tag(8, 'WAVE'); tag(12, 'fmt ');
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, 16000, true); view.setUint32(28, 32000, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    tag(36, 'data'); view.setUint32(40, audio.length * 2, true);
    audio.forEach((sample, i) => { const value = Math.max(-1, Math.min(1, sample)); view.setInt16(44 + i * 2, value * (value < 0 ? 32768 : 32767), true); });
    return new Blob([buffer], { type: 'audio/wav' });
  } finally { await context.close(); }
}
