'use client';
import { useEffect, useRef, useState, type RefObject } from 'react';

export function useFileDrop(target: RefObject<HTMLElement | null>, onDrop: (files: File[]) => void) {
  const [dragging, setDragging] = useState(false);
  const receive = useRef(onDrop);
  useEffect(() => { receive.current = onDrop; }, [onDrop]);
  useEffect(() => {
    const element = target.current;
    if (!element) return;
    let depth = 0;
    const isFile = (event: DragEvent) => Array.from(event.dataTransfer?.types || []).includes('Files')
      || Array.from(event.dataTransfer?.items || []).some(item => item.kind === 'file')
      || !!event.dataTransfer?.files.length;
    const reset = () => { depth = 0; setDragging(false); };
    const enter = (event: DragEvent) => {
      if (!isFile(event)) return;
      event.preventDefault(); depth += 1; setDragging(true);
    };
    const over = (event: DragEvent) => {
      if (!isFile(event)) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
    };
    const leave = (event: DragEvent) => {
      depth = Math.max(0, depth - 1);
      if (!depth || !event.relatedTarget || !element.contains(event.relatedTarget as Node)) reset();
    };
    const drop = (event: DragEvent) => {
      if (!isFile(event)) return;
      event.preventDefault(); event.stopPropagation(); reset();
      const transfer = event.dataTransfer;
      if (!transfer) return;
      const files = Array.from(transfer.files);
      if (!files.length) {
        for (const item of Array.from(transfer.items || [])) {
          const file = item.kind === 'file' ? item.getAsFile() : null;
          if (file) files.push(file);
        }
      }
      if (files.length) receive.current(files);
    };
    // Outside the composer, prevent navigation without showing an overlay or uploading.
    const preventNavigation = (event: DragEvent) => {
      if (!isFile(event)) return;
      event.preventDefault();
      if (event.type === 'drop') reset();
      else if (event.dataTransfer && !element.contains(event.target as Node)) event.dataTransfer.dropEffect = 'none';
    };
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') reset(); };
    element.addEventListener('dragenter', enter);
    element.addEventListener('dragover', over);
    element.addEventListener('dragleave', leave);
    element.addEventListener('drop', drop);
    window.addEventListener('dragover', preventNavigation);
    window.addEventListener('drop', preventNavigation);
    window.addEventListener('dragend', reset);
    window.addEventListener('blur', reset);
    window.addEventListener('keydown', key);
    return () => {
      element.removeEventListener('dragenter', enter);
      element.removeEventListener('dragover', over);
      element.removeEventListener('dragleave', leave);
      element.removeEventListener('drop', drop);
      window.removeEventListener('dragover', preventNavigation);
      window.removeEventListener('drop', preventNavigation);
      window.removeEventListener('dragend', reset);
      window.removeEventListener('blur', reset);
      window.removeEventListener('keydown', key);
    };
  }, [target]);
  return dragging;
}
