import React from 'react';
import {AbsoluteFill, Html5Audio, Sequence, interpolate, staticFile, useVideoConfig} from 'remotion';
import {ZONA_SEGURA} from '../tema/temas';

type NomeSfx = 'impacto' | 'swoosh';
const GANHO_SFX = 0.5;
const MAX_SFX = 0.8;

export const ZonaSegura: React.FC<{mostrar?: boolean}> = ({mostrar}) =>
  mostrar ? (
    <AbsoluteFill>
      <div
        style={{
          position: 'absolute',
          top: ZONA_SEGURA.topo,
          bottom: ZONA_SEGURA.base,
          left: ZONA_SEGURA.esquerda,
          right: ZONA_SEGURA.direita,
          border: '4px dashed #00ff88',
        }}
      />
    </AbsoluteFill>
  ) : null;

export const Sfx: React.FC<{nome: NomeSfx; em: number; volume?: number; tom?: number; max?: number}> = ({nome, em, volume = 0.4, tom = 1, max = MAX_SFX}) => {
  const {fps} = useVideoConfig();
  const quadros = Math.max(2, Math.round(max * fps));
  const fade = Math.min(quadros - 1, Math.round(0.15 * fps));
  return (
    <Sequence from={Math.max(0, Math.round(em * fps))} durationInFrames={quadros} layout="none">
      <Html5Audio src={staticFile(`audio/sfx/${nome}.wav`)} volume={(f) => volume * GANHO_SFX * interpolate(f, [quadros - fade, quadros], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})} playbackRate={tom} />
    </Sequence>
  );
};
