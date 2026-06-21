/**
 * MapplsHeatLayer — A lightweight canvas-based heatmap overlay for Mappls
 * and MapLibre GL maps. Drop-in replacement for leaflet.heat.
 *
 * Usage:
 *   const heat = new MapplsHeatLayer(map, points, { radius: 25, gradient: {...} });
 *   heat.setData(newPoints);
 *   heat.remove();
 */

export interface HeatPoint {
  lat: number;
  lon: number;
  intensity: number; // 0..1 normalised
}

export interface HeatLayerOptions {
  radius?: number;
  blur?: number;
  max?: number;
  gradient?: Record<number, string>;
}

const DEFAULT_GRADIENT: Record<number, string> = {
  0.0: '#059669',
  0.4: '#F59E0B',
  0.7: '#F97316',
  1.0: '#DC2626',
};

export class MapplsHeatLayer {
  private map: any;
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private points: HeatPoint[] = [];
  private opts: Required<HeatLayerOptions>;
  private gradientPalette: Uint8ClampedArray;
  private _onMove: () => void;
  private _raf: number | null = null;

  constructor(map: any, points: HeatPoint[], opts: HeatLayerOptions = {}) {
    this.map = map;
    this.points = points;
    this.opts = {
      radius: opts.radius ?? 25,
      blur: opts.blur ?? 16,
      max: opts.max ?? 1.0,
      gradient: opts.gradient ?? DEFAULT_GRADIENT,
    };

    // Create the canvas overlay
    this.canvas = document.createElement('canvas');
    this.canvas.style.cssText =
      'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:1;';
    this.ctx = this.canvas.getContext('2d')!;

    // Insert into the map container
    const container = map.getContainer?.() as HTMLElement | undefined;
    if (container) {
      container.style.position = 'relative';
      container.appendChild(this.canvas);
    }

    this.gradientPalette = this._buildGradient(this.opts.gradient);

    this._onMove = () => this._scheduleRender();

    // Listen for map movement (Mappls uses addListener, MapLibre uses on)
    const bindEvent = map.addListener?.bind(map) ?? map.on?.bind(map);
    if (bindEvent) {
      bindEvent('move', this._onMove);
      bindEvent('zoom', this._onMove);
      bindEvent('resize', this._onMove);
    }

    this._render();
  }

  setData(points: HeatPoint[]): void {
    this.points = points;
    this._scheduleRender();
  }

  setGradient(gradient: Record<number, string>): void {
    this.opts.gradient = gradient;
    this.gradientPalette = this._buildGradient(gradient);
    this._scheduleRender();
  }

  remove(): void {
    if (this._raf) cancelAnimationFrame(this._raf);
    const unbind = this.map.removeListener?.bind(this.map) ?? this.map.off?.bind(this.map);
    if (unbind) {
      unbind('move', this._onMove);
      unbind('zoom', this._onMove);
      unbind('resize', this._onMove);
    }
    this.canvas.remove();
  }

  // ── Internals ──────────────────────────────────────────────────────────

  private _scheduleRender(): void {
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => {
      this._raf = null;
      this._render();
    });
  }

  private _render(): void {
    const container = this.map.getContainer?.() as HTMLElement | undefined;
    if (!container) return;

    const w = container.clientWidth;
    const h = container.clientHeight;

    // Handle devicePixelRatio for sharp rendering
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = w * dpr;
    this.canvas.height = h * dpr;
    this.canvas.style.width = `${w}px`;
    this.canvas.style.height = `${h}px`;
    this.ctx.scale(dpr, dpr);

    this.ctx.clearRect(0, 0, w, h);

    if (this.points.length === 0) return;

    const r = this.opts.radius + this.opts.blur;

    // Draw alpha circles for each point
    this.points.forEach((p) => {
      try {
        // Mappls project expects [lng, lat]
        const px = this.map.project([p.lon, p.lat]);
        if (!px) return;

        const alpha = Math.min(p.intensity / this.opts.max, 1);
        this.ctx.beginPath();

        const grad = this.ctx.createRadialGradient(px.x, px.y, 0, px.x, px.y, r);
        grad.addColorStop(0, `rgba(0,0,0,${alpha})`);
        grad.addColorStop(1, 'rgba(0,0,0,0)');
        this.ctx.fillStyle = grad;
        this.ctx.arc(px.x, px.y, r, 0, Math.PI * 2);
        this.ctx.fill();
      } catch {
        // point out of view — skip
      }
    });

    // Colorize the alpha channel using the gradient palette
    this._colorize(w * dpr, h * dpr);
  }

  private _colorize(w: number, h: number): void {
    const imageData = this.ctx.getImageData(0, 0, w, h);
    const pixels = imageData.data;
    const palette = this.gradientPalette;

    for (let i = 0; i < pixels.length; i += 4) {
      const alpha = pixels[i + 3]; // only the alpha channel matters
      if (alpha === 0) continue;
      const offset = alpha * 4;
      pixels[i] = palette[offset];       // R
      pixels[i + 1] = palette[offset + 1]; // G
      pixels[i + 2] = palette[offset + 2]; // B
      pixels[i + 3] = alpha < 20 ? 0 : Math.min(alpha * 1.5, 200); // semi-transparent
    }

    this.ctx.putImageData(imageData, 0, 0);
  }

  private _buildGradient(stops: Record<number, string>): Uint8ClampedArray {
    const canvas = document.createElement('canvas');
    canvas.width = 256;
    canvas.height = 1;
    const ctx = canvas.getContext('2d')!;
    const grad = ctx.createLinearGradient(0, 0, 256, 0);

    for (const [stop, color] of Object.entries(stops)) {
      grad.addColorStop(Number(stop), color);
    }

    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 256, 1);

    return ctx.getImageData(0, 0, 256, 1).data;
  }
}
