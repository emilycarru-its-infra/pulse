// Pan and zoom for an SVG canvas. The transform is written straight to the content group, so a
// drag costs no re-render. Drag or wheel pans; pinch, Ctrl- or Cmd-wheel zooms; + - 0 and the
// arrow keys work when the canvas has focus. Ported from the Vantage admin portal's lake map.

window.Pulse = window.Pulse || {};

Pulse.viewport = function (svg, content, { minK = 0.05, maxK = 8, onChange = () => {} } = {}) {
  const view = { x: 0, y: 0, k: 1 };
  let frame = 0;
  let drag = null;
  let dragged = false;
  let touched = false;
  let home = null;
  const clamp = (k) => Math.min(maxK, Math.max(minK, k));
  const still = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function apply() {
    content.setAttribute("transform", `translate(${view.x},${view.y}) scale(${view.k})`);
    onChange(view.k);
  }

  function moveTo(target, animate = true) {
    cancelAnimationFrame(frame);
    if (!animate || still()) {
      Object.assign(view, target);
      return apply();
    }
    const from = { ...view };
    const start = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - start) / 320);
      const e = 1 - Math.pow(1 - t, 3);
      view.x = from.x + (target.x - from.x) * e;
      view.y = from.y + (target.y - from.y) * e;
      view.k = from.k + (target.k - from.k) * e;
      apply();
      if (t < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
  }

  /** Frame a rectangle {x, y, w, h} of the canvas, never zooming past maxZoom. */
  function frameRect(r, animate = true, maxZoom = maxK) {
    const box = svg.getBoundingClientRect();
    if (!box.width) return;
    const pad = 24;
    const k = clamp(Math.min((box.width - pad * 2) / r.w, (box.height - pad * 2) / r.h, maxZoom));
    moveTo({ k, x: (box.width - r.w * k) / 2 - r.x * k, y: (box.height - r.h * k) / 2 - r.y * k }, animate);
  }

  function zoomAt(factor, cx, cy, animate = false) {
    const box = svg.getBoundingClientRect();
    const px = cx ?? box.width / 2;
    const py = cy ?? box.height / 2;
    const next = clamp(view.k * factor);
    const ratio = next / view.k;
    moveTo({ k: next, x: px - (px - view.x) * ratio, y: py - (py - view.y) * ratio }, animate);
  }

  function panBy(dx, dy) {
    view.x += dx;
    view.y += dy;
    apply();
  }

  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    touched = true;
    const box = svg.getBoundingClientRect();
    if (e.ctrlKey || e.metaKey) zoomAt(Math.exp(-e.deltaY * 0.01), e.clientX - box.left, e.clientY - box.top);
    else panBy(-e.deltaX, -e.deltaY);
  }, { passive: false });

  // Safari reports a trackpad pinch as gesture events rather than a modified wheel.
  let gestureK = 1;
  svg.addEventListener("gesturestart", (e) => { e.preventDefault(); gestureK = 1; });
  svg.addEventListener("gesturechange", (e) => {
    e.preventDefault();
    touched = true;
    const box = svg.getBoundingClientRect();
    zoomAt(e.scale / gestureK, e.clientX - box.left, e.clientY - box.top);
    gestureK = e.scale;
  });

  // Two-finger pinch on touch screens.
  const pointers = new Map();
  let pinch = null;

  svg.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) };
      drag = null;
      return;
    }
    dragged = false;
    drag = { id: e.pointerId, x: e.clientX, y: e.clientY, moved: false };
  });
  svg.addEventListener("pointermove", (e) => {
    if (pointers.has(e.pointerId)) pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinch && pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      const box = svg.getBoundingClientRect();
      zoomAt(d / pinch.d, (a.x + b.x) / 2 - box.left, (a.y + b.y) / 2 - box.top);
      pinch.d = d;
      dragged = touched = true;
      return;
    }
    if (!drag || drag.id !== e.pointerId) return;
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    if (!drag.moved) {
      if (Math.hypot(dx, dy) < 4) return;
      drag.moved = dragged = touched = true;
      // Capture only once it is a real drag, so a plain click still reaches what is under it.
      svg.setPointerCapture(e.pointerId);
      svg.classList.add("panning");
    }
    drag.x = e.clientX;
    drag.y = e.clientY;
    panBy(dx, dy);
  });
  const end = (e) => {
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinch = null;
    if (drag?.moved && svg.hasPointerCapture(e.pointerId)) svg.releasePointerCapture(e.pointerId);
    svg.classList.remove("panning");
    drag = null;
  };
  svg.addEventListener("pointerup", end);
  svg.addEventListener("pointercancel", end);

  svg.addEventListener("keydown", (e) => {
    const step = 80;
    touched = true;
    if (e.key === "+" || e.key === "=") zoomAt(1.25, undefined, undefined, true);
    else if (e.key === "-" || e.key === "_") zoomAt(0.8, undefined, undefined, true);
    else if (e.key === "0" && home) frameRect(home);
    else if (e.key === "ArrowLeft") panBy(step, 0);
    else if (e.key === "ArrowRight") panBy(-step, 0);
    else if (e.key === "ArrowUp") panBy(0, step);
    else if (e.key === "ArrowDown") panBy(0, -step);
    else return;
    e.preventDefault();
  });

  // Until the reader moves the view themselves, a resize re-frames the home view.
  new ResizeObserver(() => { if (!touched && home) frameRect(home, false); }).observe(svg);

  return {
    frameRect,
    zoomAt,
    panBy,
    get k() { return view.k; },
    /** The rectangle 0 and a resize go back to. */
    setHome(r, animate = false) { home = r; touched = false; frameRect(r, animate); },
    home() { touched = false; if (home) frameRect(home); },
    touch() { touched = true; },
    /** True when the gesture that just ended was a pan, so its click should be ignored. */
    wasDrag: () => dragged,
  };
};
