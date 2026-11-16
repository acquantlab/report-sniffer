// The sniffer: a small rolled banknote lying on its side, drawn with a few thin lines.
// Its nose (the open end, on the right) stops at the left edge of each figure, and the figure it reads
// is typed out in a small terminal readout above it.
// Positions are in document pixels; (x, y) is the tip of the nose.

export const COLORS = { back: "#000000", frame: "#ff9f1a", mark: "#f4f1e8", ping: "#e07b00", sight: "#1f6fe0" };

const FONT = '"IBM Plex Mono", "JetBrains Mono", "SF Mono", "Cascadia Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace';
const LEN = 42, HGT = 12, END = 2.8;     // length, height and depth of the end ellipses, in units of S

// the roll with its nose at the origin, pointing right; glow 0..1 lights the nose while it reads
export function drawRoll(ctx, S, glow = 0) {
  const L = LEN * S, h = HGT * S / 2, e = END * S, lw = Math.max(1, 1.15 * S);
  ctx.lineJoin = "round"; ctx.lineCap = "round"; ctx.lineWidth = lw;
  ctx.fillStyle = COLORS.back; ctx.strokeStyle = COLORS.frame;
  ctx.beginPath();
  ctx.moveTo(-e, -h); ctx.lineTo(-L, -h);
  ctx.ellipse(-L, 0, e, h, 0, -Math.PI / 2, Math.PI / 2, true);
  ctx.lineTo(-e, h);
  ctx.ellipse(-e, 0, e, h, 0, Math.PI / 2, -Math.PI / 2, true);
  ctx.closePath(); ctx.fill(); ctx.stroke();
  // the open end, with the turn of the paper inside
  ctx.beginPath(); ctx.ellipse(-e, 0, e, h, 0, 0, Math.PI * 2); ctx.fill();
  if (glow > 0) { ctx.globalAlpha = 0.55 * glow; ctx.fillStyle = COLORS.frame; ctx.fill(); ctx.globalAlpha = 1; }
  ctx.stroke();
  ctx.lineWidth = lw * 0.75;
  ctx.beginPath(); ctx.ellipse(-e, 0, e * 0.42, h * 0.45, 0, 0.7, 5.7); ctx.stroke();
  // the edge of the note along the roll
  ctx.lineWidth = lw * 0.6; ctx.globalAlpha = 0.75;
  ctx.beginPath(); ctx.moveTo(-L + 1.5 * S, -h + 2.6 * S); ctx.lineTo(-e * 2.2, -h + 2.6 * S); ctx.stroke();
  ctx.globalAlpha = 1;
  ctx.fillStyle = COLORS.mark; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.font = `700 ${6.5 * S}px ${FONT}`;
  ctx.fillText("$", -L * 0.55, 1.4 * S);
}

export class Sniffer {
  constructor(U = 1) {
    this.S = Math.max(1, Math.min(1.8, U * 1.3));   // small next to the text, but never too small to see
    this.x = 0; this.y = 0;
    this.vel = { x: 0, y: 0 }; this.bv = { x: 0, y: 0 };
    this.speed = 1;
    this.tilt = 0; this.glow = 0;
    this.readout = null;                  // the figure being read, typed out above the roll
  }

  place(x, y) {
    this.x = x; this.y = y;
    this.vel = { x: 0, y: 0 }; this.bv = { x: 0, y: 0 };
    this.tilt = 0; this.glow = 0; this.readout = null;
  }

  // a figure is read: it is typed out, one character at a time, in a small terminal readout above the roll
  sniff(text) {
    const s = String(text || "").replace(/\s+/g, " ").trim().slice(0, 24);
    this.readout = s ? { text: s, t: 0, type: Math.max(0.1, 0.03 * s.length) / Math.sqrt(this.speed), hold: 0.9 / Math.sqrt(this.speed) } : null;
  }

  // follow a moving goal with a critically damped spring: it glides, and never bounces
  update(goal, dt) {
    dt = Math.max(1e-4, Math.min(dt, 0.05));
    const k = 360, c = 2 * Math.sqrt(k);
    this.bv.x += (k * (goal.x - this.x) - c * this.bv.x) * dt;
    this.bv.y += (k * (goal.y - this.y) - c * this.bv.y) * dt;
    const px = this.x, py = this.y;
    this.x += this.bv.x * dt; this.y += this.bv.y * dt;
    this.vel = { x: this.vel.x * 0.85 + (this.x - px) / dt * 0.15, y: this.vel.y * 0.85 + (this.y - py) / dt * 0.15 };
    // the nose dips a little towards where it is going
    const want = Math.max(-0.3, Math.min(0.3, this.vel.y / (1500 * this.S)));
    this.tilt += (want - this.tilt) * Math.min(1, dt * 9);
    const r = this.readout;
    if (r) { r.t += dt; if (r.t > r.type + r.hold + 0.3) this.readout = null; }
    const busy = !!r && r.t < r.type;
    this.glow += ((busy ? 1 : 0) - this.glow) * Math.min(1, dt * (busy ? 18 : 5));
  }

  // ctx is in document coordinates
  draw(ctx) {
    const S = this.S;
    ctx.save();
    ctx.translate(this.x, this.y);
    ctx.save();
    ctx.rotate(this.tilt);
    drawRoll(ctx, S, this.glow);
    ctx.restore();
    const r = this.readout;
    if (r) {
      // black chip, accent digits, a block cursor while it types; its right edge sits over the nose
      const fs = 8.5 * S, pad = 3 * S, n = Math.ceil(Math.min(1, r.t / r.type) * r.text.length);
      ctx.font = `600 ${fs}px ${FONT}`;
      const cw = ctx.measureText("0").width, w = r.text.length * cw + 2 * pad + cw, h = fs + 2 * pad;
      const x = -w + 2 * S, y = -HGT * S / 2 - 3 * S - h;
      ctx.globalAlpha = Math.min(1, r.t / 0.08, (r.type + r.hold + 0.3 - r.t) / 0.3);
      ctx.fillStyle = COLORS.back; ctx.fillRect(x, y, w, h);
      ctx.fillStyle = COLORS.frame; ctx.fillRect(x, y + h - Math.max(1, 0.8 * S), w, Math.max(1, 0.8 * S));
      ctx.textAlign = "left"; ctx.textBaseline = "middle";
      ctx.fillText(r.text.slice(0, n), x + pad, y + h / 2 + 0.5 * S);
      if (n < r.text.length || Math.floor(r.t / 0.4) % 2 === 0) ctx.fillRect(x + pad + n * cw, y + pad, cw * 0.8, fs);
    }
    ctx.restore();
  }
}

// ------------------------------------------------------------------ home page: the roll inhaling a tape of figures

const TAPE = ["REVENUE 31,615.6", "NET INCOME 4,491.9", "EPS 9.95", "FCF 1,618.5", "MARGIN 17.8%", "TOTAL ASSETS 48,594.8",
  "CASH 5,147.2", "DEBT 14,353.1", "CAPEX 407.7", "EQUITY 20,777.4", "YOY +6.5%", "SHARES 451.3"];

export function hero(cv, reduced = false) {
  const ctx = cv.getContext("2d"), S = 1.7, H = 40, nose = LEN * S + 10;
  let tape = "", next = 0, off = 0, glow = 0, last = performance.now();
  const draw = (now) => {
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    const W = cv.clientWidth, dpr = devicePixelRatio || 1;
    if (W && !cv.hidden && cv.offsetParent) {
      if (cv.width !== Math.round(W * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
      const css = getComputedStyle(document.documentElement);
      const digits = css.getPropertyValue("--text").trim() || "#ece9df", letters = css.getPropertyValue("--muted").trim() || "#878c96";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      ctx.font = `500 13px ${FONT}`; ctx.textAlign = "left"; ctx.textBaseline = "middle";
      const cw = ctx.measureText("0").width;
      while (tape.length * cw < W + 200) tape += "   " + TAPE[next++ % TAPE.length];
      off += 42 * dt;
      let eaten = false;
      while (off >= cw) { off -= cw; eaten = eaten || tape[0] !== " "; tape = tape.slice(1); }
      glow += ((eaten ? 1 : 0) - glow) * Math.min(1, dt * (eaten ? 30 : 4));
      for (let i = 0; i < tape.length; i++) {
        const x = nose + 6 + i * cw - off;
        if (x > W) break;
        if (tape[i] === " ") continue;
        ctx.globalAlpha = Math.max(0, Math.min(1, (x - nose) / 42, (W - x) / 160));
        ctx.fillStyle = /[\d.,%+]/.test(tape[i]) ? digits : letters;
        ctx.fillText(tape[i], x, H / 2 + 1);
      }
      ctx.globalAlpha = 1;
      ctx.save(); ctx.translate(nose, H / 2); drawRoll(ctx, S, glow); ctx.restore();
    }
    if (!reduced) requestAnimationFrame(draw);
  };
  requestAnimationFrame(draw);
}
