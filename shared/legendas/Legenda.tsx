import React, {useMemo} from 'react';
import {getInputProps, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {Palavra, Sinc} from '../lib/sinc';
import type {Tema} from '../tema/temas';

type Pagina = {ini: number; fim: number; palavras: Palavra[]};
const limpa = (s: string) => s.toLowerCase().normalize('NFD').replace(/[^a-z0-9]/g, '');

/** Agrupa as palavras em "páginas" curtas: quebra em pontuação, em pausa e ao estourar o limite. */
export const paginar = (palavras: Palavra[], maxPalavras = 3, maxLetras = 18, pausa = 0.35): Pagina[] => {
  const paginas: Pagina[] = [];
  let atual: Palavra[] = [];
  const fecha = () => {
    if (atual.length) paginas.push({ini: atual[0].ini, fim: atual[atual.length - 1].fim, palavras: atual});
    atual = [];
  };
  palavras.forEach((p, i) => {
    const letras = atual.reduce((n, w) => n + w.t.length + 1, 0) + p.t.length;
    const ant = palavras[i - 1];
    if (atual.length && (atual.length >= maxPalavras || letras > maxLetras || p.ini - ant.fim > pausa || p.cena !== ant.cena)) fecha();
    atual.push(p);
    if (/[.!?…:]$/.test(p.t)) fecha();
  });
  fecha();
  // Cada página fica na tela até a próxima começar (sem piscar), no máximo 0,6 s além da fala.
  paginas.forEach((pg, i) => {
    const prox = paginas[i + 1];
    pg.fim = prox ? Math.min(prox.ini, pg.fim + 0.6) : pg.fim + 0.4;
  });
  return paginas;
};

export type LegendaProps = {
  sinc: Sinc;
  tema: Tema;
  /** Palavras-chave que ficam sempre na cor de destaque. */
  chaves?: string[];
  /** 'ativa' pinta a palavra no momento em que é falada; 'chave' pinta só as palavras-chave. */
  modo?: 'ativa' | 'chave';
  /** Centro vertical da legenda, em px. Padrão: rente ao limite da zona segura, bem abaixo do conteúdo (não disputa com os textos da cena). */
  y?: number;
  tamanho?: number;
  maxPalavras?: number;
  caixaAlta?: boolean;
};

export const Legenda: React.FC<LegendaProps> = ({sinc, tema, chaves = [], modo = 'ativa', y = 1492, tamanho = 58, maxPalavras = 3, caixaAlta = true}) => {
  const frame = useCurrentFrame();
  const {fps, width} = useVideoConfig();
  const t = frame / fps;
  const paginas = useMemo(() => paginar(sinc.palavras, maxPalavras), [sinc, maxPalavras]);
  const setChaves = useMemo(() => new Set(chaves.map(limpa)), [chaves]);
  // Na capa (node ferramentas/video.mjs <pasta> --capa <seg>) a legenda some: palavra solta no meio da miniatura fica feio.
  if ((getInputProps() as {capa?: boolean}).capa) return null;
  const pg = paginas.find((p) => t >= p.ini && t < p.fim);
  if (!pg) return null;
  const entrada = interpolate(t - pg.ini, [0, 0.09], [0.86, 1], {extrapolateRight: 'clamp'});
  return (
    <div
      style={{
        position: 'absolute',
        left: 70,
        width: width - 140,
        top: y,
        transform: `translateY(-50%) scale(${entrada})`,
        textAlign: 'center',
        fontFamily: tema.fonteImpacto,
        fontSize: tamanho,
        lineHeight: 1.05,
        letterSpacing: 1,
        textTransform: caixaAlta ? 'uppercase' : 'none',
        color: tema.texto,
        WebkitTextStroke: `${Math.round(tamanho * 0.11)}px rgba(0,0,0,0.92)`,
        paintOrder: 'stroke fill',
        textShadow: '0 8px 0 rgba(0,0,0,0.35), 0 0 34px rgba(0,0,0,0.45)',
      }}
    >
      {pg.palavras.map((p, i) => {
        const falando = t >= p.ini && t < p.fim + 0.05;
        const chave = setChaves.has(limpa(p.t));
        const cor = chave || (modo === 'ativa' && falando) ? tema.destaque : tema.texto;
        return (
          <span key={i} style={{display: 'inline-block', margin: '0 0.13em', color: cor, transform: falando ? 'scale(1.06)' : undefined}}>
            {p.t.replace(/[,;]$/, '')}
          </span>
        );
      })}
    </div>
  );
};
