import React from 'react';
import {
  AbsoluteFill,
  Composition,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
  Easing,
} from 'remotion';
import {loadFont as loadInter} from '@remotion/google-fonts/Inter';
import {loadFont as loadGrotesk} from '@remotion/google-fonts/SpaceGrotesk';

const {fontFamily: INTER} = loadInter('normal', {weights: ['400', '500'], subsets: ['latin']});
const {fontFamily: GROTESK} = loadGrotesk('normal', {weights: ['500', '700'], subsets: ['latin']});

const C = {
  bg: '#0c0f14',
  cyan: '#3dd6ff',
  up: '#b6ff5a',
  down: '#ff2a5f',
  ink: '#eef2f8',
  muted: '#8a94a6',
  card: 'rgba(20,26,36,.72)',
  hair: 'rgba(255,255,255,.07)',
};

const SAMPLE = {
  date: '2026-09-12',
  headline: 'Risk appetite firms as the S&P grinds higher',
  spx: {last: 5432.1, chg: 0.84, prev_close: 5386.9, series: [5386.9, 5390, 5395, 5388, 5402, 5410, 5405, 5418, 5425, 5420, 5430, 5432.1]},
  risk: {score: 0.42, label: 'Constructive'},
};

const pct = (v) => `${v >= 0 ? '+' : '\u2212'}${Math.abs(v).toFixed(2)}%`;
const signed = (v) => `${v >= 0 ? '+' : '\u2212'}${Math.abs(v).toFixed(2)}`;

// plot rectangle inside the 1920x1080 frame
const PX0 = 176, PX1 = 1700, PY0 = 300, PY1 = 880;

const Scene = ({data}) => {
  const d = data || SAMPLE;
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  const chg = d.spx?.chg ?? 0;
  const up = chg >= 0;
  const badgeCol = up ? C.up : C.down;
  const riskColor = (d.risk?.score ?? 0) >= 0 ? C.up : C.down;

  // Intraday bars against the previous close; when the run only had daily
  // closes (demo runs, a failed intraday fetch) the line is the last sessions
  // and the baseline is where they started, labelled as such.
  let series = Array.isArray(d.spx?.series) ? d.spx.series.filter((x) => typeof x === 'number') : [];
  const daily = d.spx?.interval === '1d' && series.length >= 2;
  const prev = daily ? series[0] : d.spx?.prev_close ?? (series.length ? series[0] : 0);
  const baseLabel = daily ? `${series.length} sessions ago` : 'prev close';
  if (series.length < 2) series = [prev, d.spx?.last ?? prev];
  // The line is coloured by the move it draws: the session intraday, the
  // whole span when it shows daily closes.
  const col = daily ? (series[series.length - 1] >= prev ? C.up : C.down) : badgeCol;

  const lo = Math.min(prev, ...series);
  const hi = Math.max(prev, ...series);
  const pad = (hi - lo) * 0.12 || 1;
  const minV = lo - pad, maxV = hi + pad;
  const mapX = (i) => PX0 + (i / (series.length - 1)) * (PX1 - PX0);
  const mapY = (v) => PY1 - ((v - minV) / (maxV - minV)) * (PY1 - PY0);

  const linePath = series.map((v, i) => `${i === 0 ? 'M' : 'L'}${mapX(i).toFixed(1)},${mapY(v).toFixed(1)}`).join(' ');
  const baseY = mapY(prev);
  const areaPath = `${linePath} L${mapX(series.length - 1).toFixed(1)},${baseY.toFixed(1)} L${mapX(0).toFixed(1)},${baseY.toFixed(1)} Z`;
  const endX = mapX(series.length - 1), endY = mapY(series[series.length - 1]);

  // Two lines at most above the plot (PY0): model headlines run 60 to 90
  // characters, which wrapped to three lines at 72px and crossed the chart.
  const headSize = (d.headline || '').length > 48 ? 56 : 72;

  const at = (a, b, from, to, ease) =>
    interpolate(frame, [a * fps, b * fps], [from, to], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});

  const eyebrowO = at(0.15, 0.65, 0, 1);
  const headO = at(0.5, 1.2, 0, 1);
  const headY = at(0.5, 1.2, 16, 0, Easing.out(Easing.cubic));
  const baseO = at(0.9, 1.5, 0, 1);
  const areaO = at(1.4, 2.8, 0, 1);
  const dash = at(1.1, 3.4, 1, 0, Easing.out(Easing.cubic));
  const peakO = at(3.4, 3.8, 0, 1);

  const ripple = spring({frame: frame - 3.45 * fps, fps, config: {damping: 200}});
  const rippleScale = interpolate(ripple, [0, 1], [1, 9]);
  const rippleO = interpolate(ripple, [0, 1], [0.9, 0]);
  const badge = spring({frame: frame - 3.55 * fps, fps, config: {damping: 9, stiffness: 120, mass: 0.7}});
  const cardSpring = spring({frame: frame - 4.2 * fps, fps, config: {damping: 200}});
  const cardY = interpolate(cardSpring, [0, 1], [14, 0]);

  return (
    <AbsoluteFill style={{backgroundColor: C.bg, fontFamily: INTER}}>
      <AbsoluteFill style={{background: 'radial-gradient(680px 460px at 50% 42%, rgba(61,214,255,.08), transparent 62%), radial-gradient(520px 380px at 82% 92%, rgba(255,42,95,.08), transparent 60%)'}} />
      <AbsoluteFill style={{backgroundImage: 'linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px), linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px)', backgroundSize: '128px 128px', opacity: 0.5, maskImage: 'linear-gradient(transparent,black 22%,black 82%,transparent)', WebkitMaskImage: 'linear-gradient(transparent,black 22%,black 82%,transparent)'}} />

      <div style={{position: 'absolute', top: '7.5%', left: '5%', fontFamily: GROTESK, fontSize: 30, fontWeight: 500, color: C.ink, letterSpacing: '.005em', opacity: eyebrowO, display: 'flex', alignItems: 'center'}}>
        <span style={{width: 14, height: 14, borderRadius: '50%', background: C.cyan, marginRight: 16, boxShadow: `0 0 20px ${C.cyan}`}} />
        Andra Markets
        <span style={{width: 2, height: 24, background: C.muted, opacity: 0.5, margin: '0 22px'}} />
        <span style={{color: C.muted, fontWeight: 400, fontFamily: INTER, fontSize: 28}}>US market close</span>
      </div>

      <div style={{position: 'absolute', top: '12.5%', left: '5%', right: '8%', fontFamily: GROTESK, fontWeight: 700, lineHeight: 1.08, fontSize: headSize, color: C.ink, opacity: headO, transform: `translateY(${headY}px)`}}>
        {d.headline}
      </div>

      <svg style={{position: 'absolute', inset: 0, width: '100%', height: '100%', overflow: 'visible'}} viewBox="0 0 1920 1080" preserveAspectRatio="none">
        <defs>
          <linearGradient id="areafill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={col} stopOpacity="0.28" />
            <stop offset="1" stopColor={col} stopOpacity="0" />
          </linearGradient>
        </defs>
        <line x1={PX0} y1={baseY} x2={PX1} y2={baseY} stroke={C.muted} strokeWidth="2" strokeDasharray="10 10" opacity={0.55 * baseO} />
        <text x={PX1} y={baseY - 14} fill={C.muted} fontSize="22" textAnchor="end" fontFamily={INTER} opacity={baseO}>{baseLabel}</text>
        <path d={areaPath} fill="url(#areafill)" opacity={areaO} />
        <path d={linePath} pathLength="1" fill="none" stroke={col} strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" strokeDasharray="1" strokeDashoffset={dash} style={{filter: `drop-shadow(0 0 10px ${col}aa)`}} />
        <circle cx={endX} cy={endY} r="11" fill="#fff" opacity={peakO} style={{filter: `drop-shadow(0 0 14px ${col})`}} />
      </svg>

      <div style={{position: 'absolute', left: `${(endX / 1920) * 100}%`, top: `${(endY / 1080) * 100}%`, width: 36, height: 36, marginLeft: -18, marginTop: -18, border: `3px solid ${col}`, borderRadius: '50%', opacity: rippleO, transform: `scale(${rippleScale})`}} />

      <div style={{position: 'absolute', left: `${(endX / 1920) * 100}%`, top: `${(endY / 1080) * 100}%`, transform: `translate(-50%,-140%) scale(${badge})`, background: badgeCol, color: '#0c0f14', fontFamily: GROTESK, fontWeight: 700, fontSize: 42, padding: '12px 26px', borderRadius: 999, boxShadow: `0 0 40px ${badgeCol}66`, whiteSpace: 'nowrap'}}>
        {pct(chg)}
      </div>

      <div style={{position: 'absolute', right: '5%', bottom: '9%', minWidth: 340, background: C.card, border: `1px solid ${C.hair}`, borderRadius: 18, padding: '22px 26px', backdropFilter: 'blur(6px)', opacity: cardSpring, transform: `translateY(${cardY}px)`}}>
        <div style={{fontSize: 22, color: C.muted, fontWeight: 500}}>Cross-asset risk</div>
        <div style={{fontFamily: GROTESK, fontWeight: 700, fontSize: 40, marginTop: 6, display: 'flex', alignItems: 'center', gap: 14, color: riskColor}}>
          <span style={{fontSize: 26}}>{(d.risk?.score ?? 0) >= 0 ? '\u25B2' : '\u25BC'}</span> {d.risk?.label}
        </div>
        <div style={{fontSize: 22, color: C.muted, marginTop: 4}}>score {signed(d.risk?.score ?? 0)}</div>
      </div>
    </AbsoluteFill>
  );
};

export const RemotionRoot = () => {
  return (
    <Composition id="DailyRecap" component={Scene} durationInFrames={180} fps={30} width={1920} height={1080} defaultProps={{data: SAMPLE}} />
  );
};
