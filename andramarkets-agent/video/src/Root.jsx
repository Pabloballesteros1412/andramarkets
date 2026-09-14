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
  line: '#3dd6ff',
  alert: '#ff2a5f',
  lime: '#b6ff5a',
  ink: '#eef2f8',
  muted: '#8a94a6',
  card: 'rgba(20,26,36,.72)',
  hair: 'rgba(255,255,255,.07)',
};

const Scene = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  const at = (a, b, from, to, ease) =>
    interpolate(frame, [a * fps, b * fps], [from, to], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: ease,
    });

  const eyebrowO = at(0.15, 0.65, 0, 1);
  const headO = at(0.5, 1.2, 0, 1);
  const headY = at(0.5, 1.2, 16, 0, Easing.out(Easing.cubic));
  const areaO = at(1.2, 2.6, 0, 1);
  const dash = at(1.1, 3.3, 1, 0, Easing.out(Easing.cubic));
  const peakO = at(3.3, 3.7, 0, 1);

  const ripple = spring({frame: frame - 3.35 * fps, fps, config: {damping: 200}});
  const rippleScale = interpolate(ripple, [0, 1], [1, 9]);
  const rippleO = interpolate(ripple, [0, 1], [0.9, 0]);

  const badge = spring({frame: frame - 3.45 * fps, fps, config: {damping: 9, stiffness: 120, mass: 0.7}});
  const capO = at(3.9, 4.4, 0, 1);

  const cardSpring = spring({frame: frame - 4.1 * fps, fps, config: {damping: 200}});
  const cardO = cardSpring;
  const cardY = interpolate(cardSpring, [0, 1], [14, 0]);

  return (
    <AbsoluteFill style={{backgroundColor: C.bg, fontFamily: INTER}}>
      <AbsoluteFill
        style={{
          background:
            'radial-gradient(680px 460px at 50% 42%, rgba(61,214,255,.10), transparent 62%), radial-gradient(520px 380px at 82% 92%, rgba(255,42,95,.10), transparent 60%)',
        }}
      />
      <AbsoluteFill
        style={{
          backgroundImage:
            'linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px), linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px)',
          backgroundSize: '128px 128px',
          opacity: 0.5,
          maskImage: 'linear-gradient(transparent,black 22%,black 82%,transparent)',
          WebkitMaskImage: 'linear-gradient(transparent,black 22%,black 82%,transparent)',
        }}
      />

      <div
        style={{
          position: 'absolute', top: '7.5%', left: '5%',
          fontFamily: GROTESK, fontSize: 30, fontWeight: 500, color: C.ink,
          letterSpacing: '.005em', opacity: eyebrowO, display: 'flex', alignItems: 'center',
        }}
      >
        <span style={{width: 14, height: 14, borderRadius: '50%', background: C.line, marginRight: 16, boxShadow: `0 0 20px ${C.line}`}} />
        Andra Markets
        <span style={{width: 2, height: 24, background: C.muted, opacity: 0.5, margin: '0 22px'}} />
        <span style={{color: C.muted, fontWeight: 400, fontFamily: INTER, fontSize: 28}}>US market close</span>
      </div>

      <div
        style={{
          position: 'absolute', top: '12.5%', left: '5%', right: '34%',
          fontFamily: GROTESK, fontWeight: 700, lineHeight: 1.06, fontSize: 78,
          color: C.ink, opacity: headO, transform: `translateY(${headY}px)`,
        }}
      >
        Valuations hit <span style={{color: C.alert}}>cycle highs</span>
      </div>

      <svg style={{position: 'absolute', inset: 0, width: '100%', height: '100%', overflow: 'visible'}} viewBox="0 0 1920 1080" preserveAspectRatio="none">
        <defs>
          <linearGradient id="areafill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#3dd6ff" stopOpacity="0.30" />
            <stop offset="1" stopColor="#3dd6ff" stopOpacity="0" />
          </linearGradient>
        </defs>
        <line x1="176" y1="921" x2="1763" y2="921" stroke="rgba(255,255,255,.14)" strokeWidth="1" />
        <path d="M235,862 C588,823 823,760 1019,639 C1215,521 1383,404 1591,259 L1591,921 L235,921 Z" fill="url(#areafill)" opacity={areaO} />
        <path
          d="M235,862 C588,823 823,760 1019,639 C1215,521 1383,404 1591,259"
          pathLength="1" fill="none" stroke={C.line} strokeWidth="6" strokeLinecap="round" strokeLinejoin="round"
          strokeDasharray="1" strokeDashoffset={dash}
          style={{filter: 'drop-shadow(0 0 10px rgba(61,214,255,.75))'}}
        />
        <circle cx="1591" cy="259" r="11" fill="#fff" opacity={peakO} style={{filter: 'drop-shadow(0 0 14px #3dd6ff)'}} />
      </svg>

      <div style={{position: 'absolute', left: '82.9%', top: '24%', width: 36, height: 36, marginLeft: -18, marginTop: -18, border: `3px solid ${C.alert}`, borderRadius: '50%', opacity: rippleO, transform: `scale(${rippleScale})`}} />

      <div
        style={{
          position: 'absolute', left: '84%', top: '20%', transform: `translate(-50%,-50%) scale(${badge})`,
          background: C.alert, color: '#fff', fontFamily: GROTESK, fontWeight: 700, fontSize: 46,
          padding: '14px 30px', borderRadius: 999, boxShadow: '0 0 40px rgba(255,42,95,.55)', whiteSpace: 'nowrap',
        }}
      >
        6&times;
      </div>
      <div style={{position: 'absolute', left: '84%', top: '30%', transform: 'translateX(-50%)', fontSize: 24, color: C.muted, opacity: capO, whiteSpace: 'nowrap'}}>
        vs. 25-year average
      </div>

      <div
        style={{
          position: 'absolute', right: '5%', bottom: '9%', minWidth: 320,
          background: C.card, border: `1px solid ${C.hair}`, borderRadius: 18, padding: '22px 26px',
          backdropFilter: 'blur(6px)', opacity: cardO, transform: `translateY(${cardY}px)`,
        }}
      >
        <div style={{fontSize: 22, color: C.muted, fontWeight: 500}}>Risk index</div>
        <div style={{fontFamily: GROTESK, fontWeight: 700, fontSize: 42, marginTop: 6, display: 'flex', alignItems: 'center', gap: 14}}>
          <span style={{color: C.alert, fontSize: 28}}>&#9650;</span> Elevated
        </div>
        <div style={{fontSize: 22, color: C.lime, marginTop: 4}}>+18% week over week</div>
      </div>
    </AbsoluteFill>
  );
};

export const RemotionRoot = () => {
  return (
    <Composition
      id="DailyRecap"
      component={Scene}
      durationInFrames={180}
      fps={30}
      width={1920}
      height={1080}
    />
  );
};
