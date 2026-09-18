'use client';

import { useEffect, useRef, useState } from 'react';
import { Container, Glass, Scene, WebGpuGlassCore } from '@liquid-dom/core';

// A shared device avoids creating a GPU device for every glass control.
let devicePromise: Promise<GPUDevice> | undefined;
function getDevice() {
  if (!devicePromise) {
    devicePromise = (async () => {
      if (!navigator.gpu) throw new Error('WebGPU is unavailable.');
      const adapter = await navigator.gpu.requestAdapter();
      if (!adapter) throw new Error('No WebGPU adapter is available.');
      const device = await adapter.requestDevice();
      device.lost.then(() => { devicePromise = undefined; });
      return device;
    })().catch((error) => { devicePromise = undefined; throw error; });
  }
  return devicePromise;
}

export function GlassSurface({ radius = 32, tone = 'neutral' }: { radius?: number; tone?: 'neutral' | 'accent' | 'gray' }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const canvas = canvasRef.current;
    const host = canvas?.parentElement?.parentElement;
    if (!canvas || !host) return;
    let disposed = false;
    let frame = 0;
    let core: WebGpuGlassCore | undefined;
    let backdrop: GPUTexture | undefined;
    let observer: ResizeObserver | undefined;
    let cleanupEvents: (() => void) | undefined;
    let context: GPUCanvasContext | null = null;
    setReady(false);
    async function initialize() {
      try {
        const device = await getDevice();
        if (disposed || !canvas || !host) return;
        context = canvas.getContext('webgpu');
        if (!context) throw new Error('Unable to create a WebGPU canvas.');
        const format = navigator.gpu.getPreferredCanvasFormat();
        device.pushErrorScope('validation');
        core = new WebGpuGlassCore({ device, format });
        const setupError = await device.popErrorScope();
        if (setupError) throw new Error(setupError.message);
        if (disposed) { core.destroy(); return; }
        const scene = new Scene();
        const container = scene.add(new Container({
          blur: 8, thickness: 22, ior: 1.46, bezelWidth: 10,
          surfaceProfile: 'convex', dispersion: 0.025,
          tint: tone === 'accent' ? { r: 252 / 255, g: 182 / 255, b: 3 / 255, a: 0.12 } : tone === 'gray' ? { r: 0.62, g: 0.62, b: 0.62, a: 0.16 } : { r: 1, g: 1, b: 1, a: 0.08 },
          lightDirection: -Math.PI / 4, specularStrength: 0.65,
          specularWidth: 2, oppositeSpecularStrength: 0.2,
          shadowColor: { r: 0, g: 0, b: 0, a: 0 },
        }));
        const glass = container.add(new Glass({ cornerRadius: radius, cornerSmoothing: 0.6 }));
        let pixelWidth = 0;
        let pixelHeight = 0;
        let rendering = false;
        let pending = false;
        const render = async () => {
          if (disposed || !core || !context) return;
          if (rendering) { pending = true; return; }
          rendering = true;
          try {
            const bounds = canvas.getBoundingClientRect();
            const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
            const width = Math.max(1, Math.round(bounds.width * dpr));
            const height = Math.max(1, Math.round(bounds.height * dpr));
            if (width > device.limits.maxTextureDimension2D || height > device.limits.maxTextureDimension2D) {
              setReady(false);
              return;
            }
            device.pushErrorScope('validation');
            if (pixelWidth !== width || pixelHeight !== height) {
              pixelWidth = canvas.width = width;
              pixelHeight = canvas.height = height;
              context.configure({ device, format, alphaMode: 'opaque', usage: GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.COPY_DST });
              backdrop?.destroy();
              backdrop = device.createTexture({ size: [width, height], format, usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.RENDER_ATTACHMENT });
              // The page background is intentionally solid. Supply that actual
              // color as a GPU texture instead of capturing HTML into a canvas.
              const encoder = device.createCommandEncoder();
              const pass = encoder.beginRenderPass({ colorAttachments: [{ view: backdrop.createView(), clearValue: tone === 'accent' ? { r: 252 / 255, g: 182 / 255, b: 3 / 255, a: 1 } : tone === 'gray' ? { r: 0.9, g: 0.9, b: 0.9, a: 1 } : { r: 252 / 255, g: 253 / 255, b: 1, a: 1 }, loadOp: 'clear', storeOp: 'store' }] });
              pass.end();
              device.queue.submit([encoder.finish()]);
            }
            glass.width = bounds.width;
            glass.height = bounds.height;
            glass.cornerRadius = Math.min(radius, bounds.width / 2, bounds.height / 2);
            core.render({ scene, width, height, dpr, outputTexture: context.getCurrentTexture(), backdropTexture: backdrop });
            const error = await device.popErrorScope();
            if (error) throw new Error(error.message);
            await device.queue.onSubmittedWorkDone();
            if (!disposed) setReady(true);
          } catch (error) {
            if (!disposed) { setReady(false); console.warn('Liquid DOM rendering failed:', error); }
          } finally {
            rendering = false;
            if (pending && !disposed) { pending = false; schedule(); }
          }
        };
        const schedule = () => {
          cancelAnimationFrame(frame);
          frame = requestAnimationFrame(() => { void render(); });
        };
        const moveLight = (event: PointerEvent) => {
          const bounds = host.getBoundingClientRect();
          container.lightDirection = Math.atan2(event.clientY - bounds.top - bounds.height / 2, event.clientX - bounds.left - bounds.width / 2);
          schedule();
        };
        const resetLight = () => { container.lightDirection = -Math.PI / 4; schedule(); };
        host.addEventListener('pointermove', moveLight);
        host.addEventListener('pointerleave', resetLight);
        window.addEventListener('resize', schedule);
        cleanupEvents = () => {
          host.removeEventListener('pointermove', moveLight);
          host.removeEventListener('pointerleave', resetLight);
          window.removeEventListener('resize', schedule);
        };
        observer = new ResizeObserver(schedule);
        observer.observe(canvas);
        device.lost.then(() => { if (!disposed) setReady(false); });
        schedule();
      } catch (error) {
        if (!disposed) console.warn('Liquid DOM WebGPU initialization failed:', error);
      }
    }
    void initialize();
    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      observer?.disconnect();
      cleanupEvents?.();
      core?.destroy();
      backdrop?.destroy();
      context?.unconfigure();
    };
  }, [radius, tone]);
  return <div className="gpu-glass" aria-hidden="true" data-renderer={ready ? 'liquid-dom-webgpu' : 'initializing'}><canvas ref={canvasRef} data-ready={ready} style={{ opacity: ready ? 1 : 0 }} /></div>;
}
