import React from 'react';
import {AbsoluteFill, Easing, OffthreadVideo, Sequence, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {Sfx, ZonaSegura} from '@shared/componentes/Base';
import {Legenda} from '@shared/legendas/Legenda';
import type {Sinc} from '@shared/lib/sinc';
import {tema} from '@shared/tema/temas';

type Layout = 'cam' | 'largo' | 'jogo' | 'comp' | 'split' | 'tela';
type Plano = {de: number; dur: number; fonte: number; layout: Layout; zoom: boolean; salto: boolean};
export type DadosCorte = {
  titulo: string;
  canal: string;
  url: string;
  plataforma?: string;
  selo?: string | null;
  rotulos?: string[] | null;
  // limiteY: corta o original abaixo dessa linha (px) nos modos de rosto, para esconder faixa de patrocínio do canal
  // tela / camRet: [x0, y0, x1, y1] da área do jogo e da câmera do streamer (modo split)
  // rosto: [cx, cy] centro do rosto quando a câmera ocupa a tela toda (modo cam); sem ele, o recorte é o centro do quadro
  regioes: {jogo?: number[]; comp?: number[]; cam?: number[]; largo?: number[]; limiteY?: number; tela?: number[]; camRet?: number[]; rosto?: number[]};
  enfase?: number[];
  planos: Plano[];
};

const FONTE_W = 1920;
const FONTE_H = 1080;
const SPLIT = 1130; // altura do jogo no modo split; a câmera ocupa o resto
const LEGENDA_Y = 1492;

/** Mostra um retângulo do vídeo original (em px do original) esticado para caber na caixa (w × h), cortando o resto. */
const Quadro: React.FC<{src: string; fonte: number; mudo?: boolean; style: React.CSSProperties}> = ({src, fonte, mudo, style}) => (
  <OffthreadVideo src={src} trimBefore={fonte} muted={mudo} style={style} />
);

const Janela: React.FC<{src: string; fonte: number; x0: number; x1: number; y0?: number; y1?: number; w: number; h: number; mudo?: boolean; zoom?: number; estilo?: React.CSSProperties}> = ({src, fonte, x0, x1, y0 = 0, y1 = FONTE_H, w, h, mudo, zoom = 1, estilo}) => {
  const k = Math.max(w / (x1 - x0), h / (y1 - y0)) * zoom;
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  return (
    <div style={{position: 'absolute', width: w, height: h, overflow: 'hidden', ...estilo}}>
      <Quadro src={src} fonte={fonte} mudo={mudo} style={{position: 'absolute', width: FONTE_W * k, height: FONTE_H * k, left: w / 2 - cx * k, top: h / 2 - cy * k, maxWidth: 'none'}} />
    </div>
  );
};

/** Fundo desfocado. Desenhado pequeno (270×480) e ampliado: o desfoque em tela cheia era a parte mais cara do render. */
const Fundo: React.FC<{src: string; fonte: number; x0: number; x1: number; y0?: number; y1?: number}> = ({src, fonte, x0, x1, y0, y1}) => (
  <div style={{position: 'absolute', left: -40, top: -72, width: 270, height: 480, transform: 'scale(4.3)', transformOrigin: '0 0', filter: 'blur(9px) brightness(0.5)'}}>
    <Janela src={src} fonte={fonte} x0={x0} x1={x1} y0={y0} y1={y1} w={270} h={480} mudo />
  </div>
);

const Rotulo: React.FC<{children: React.ReactNode; cor: string}> = ({children, cor}) => (
  <div style={{fontFamily: tema.fonteImpacto, fontSize: 52, color: '#0C1730', background: cor, padding: '6px 26px', borderRadius: 12, textTransform: 'uppercase', letterSpacing: 2, boxShadow: '0 6px 0 rgba(0,0,0,0.45)'}}>{children}</div>
);

/** Modo cam: recorte (dentro da moldura da câmera, quando há camRet) e altura da faixa na tela. Mais estreito com camRet
 * para a faixa ficar alta e não sobrar fundo escuro embaixo. */
const faixaCam = (r: DadosCorte['regioes']) => {
  const [bx0, by0, bx1, by1] = r.camRet ?? [0, 0, FONTE_W, r.limiteY ?? FONTE_H];
  const larg = Math.min(r.camRet ? 680 : 800, bx1 - bx0);
  return {bx0, by0, bx1, by1, larg, h: Math.round((1080 * (by1 - by0)) / larg)};
};

/** Círculo do rosto: regioes.cam [cx, cy, raio] ou, nas lives, o centro do retângulo da câmera. */
const circuloCam = (r: DadosCorte['regioes']): number[] => {
  if (r.cam) return r.cam;
  const [x0, y0, x1, y1] = r.camRet ?? [1500, 700, 1900, 1060];
  return [(x0 + x1) / 2, (y0 + y1) / 2, Math.min(x1 - x0, y1 - y0) / 2];
};

const PlanoView: React.FC<{p: Plano; d: DadosCorte; src: string}> = ({p, d, src}) => {
  const frame = useCurrentFrame();
  if (p.layout === 'split') {
    const [tx0, ty0, tx1, ty1] = d.regioes.tela ?? [0, 0, FONTE_W, FONTE_H];
    const [kx0, ky0, kx1, ky1] = d.regioes.camRet ?? [1500, 700, 1900, 1060];
    // jogo: recorte central da área do jogo na proporção do painel de cima, com aproximação contínua leve
    const gw = Math.min(tx1 - tx0, ((ty1 - ty0) * 1080) / SPLIT);
    const gcx = (tx0 + tx1) / 2;
    const z = 1 + frame * 0.00018;
    return (
      <AbsoluteFill style={{background: '#000'}}>
        <Janela src={src} fonte={p.fonte} x0={gcx - gw / 2} x1={gcx + gw / 2} y0={ty0} y1={ty1} w={1080} h={SPLIT} zoom={z} />
        <Janela src={src} fonte={p.fonte} x0={kx0} x1={kx1} y0={ky0} y1={ky1} w={1080} h={1920 - SPLIT} mudo estilo={{top: SPLIT}} />
        <div style={{position: 'absolute', left: 0, top: SPLIT - 4, width: 1080, height: 8, background: tema.destaque, boxShadow: '0 0 18px rgba(0,0,0,0.7)'}} />
      </AbsoluteFill>
    );
  }
  if (p.layout === 'tela') {
    const [tx0, ty0, tx1, ty1] = d.regioes.tela ?? [0, 0, FONTE_W, FONTE_H];
    const h = Math.round((1080 * (ty1 - ty0)) / (tx1 - tx0));
    const z = 1 + frame * 0.0002;
    return (
      <AbsoluteFill style={{background: '#0C1730'}}>
        <Fundo src={src} fonte={p.fonte} x0={(tx0 + tx1) / 2 - 304} x1={(tx0 + tx1) / 2 + 304} y0={ty0} y1={ty1} />
        <Janela src={src} fonte={p.fonte} x0={tx0} x1={tx1} y0={ty0} y1={ty1} w={1080} h={h} zoom={z} estilo={{top: 520, borderTop: `6px solid ${tema.destaque}`, borderBottom: `6px solid ${tema.destaque}`}} />
      </AbsoluteFill>
    );
  }
  if (p.layout === 'cam') {
    // leve aproximação contínua + degrau de zoom a cada plano
    // O rosto não enche a tela inteira (ficava colado demais, com a testa cortada): mostra 800 px de largura do
    // original numa faixa central e completa em cima e embaixo com o próprio vídeo desfocado.
    // Lives: a câmera costuma ser uma moldura dentro do overlay (camRet); o recorte fica dentro dela, sem o fundo do overlay.
    const z = (p.zoom ? 1.08 : 1) + frame * 0.00025;
    const {bx0, by0, bx1, by1, larg, h} = faixaCam(d.regioes);
    const cx = Math.min(bx1 - larg / 2, Math.max(bx0 + larg / 2, d.regioes.rosto?.[0] ?? (bx0 + bx1) / 2));
    return (
      <AbsoluteFill style={{background: '#0C1730'}}>
        <Fundo src={src} fonte={p.fonte} x0={cx - 304} x1={cx + 304} y0={by0} y1={by1} />
        <Janela src={src} fonte={p.fonte} x0={cx - larg / 2} x1={cx + larg / 2} y0={by0} y1={by1} w={1080} h={h} zoom={z} estilo={{top: 250}} />
      </AbsoluteFill>
    );
  }
  if (p.layout === 'largo') {
    // plano aberto: as duas pessoas ficam nas bordas, então mostra o quadro quase inteiro (x0..x1, y0..limiteY)
    const [lx0, lx1, ly0] = d.regioes.largo ?? [0, FONTE_W, 0];
    const ly1 = d.regioes.limiteY ?? FONTE_H;
    const h = Math.round((1080 * (ly1 - ly0)) / (lx1 - lx0));
    const z = 1 + frame * 0.0002;
    return (
      <AbsoluteFill style={{background: '#0C1730'}}>
        <Fundo src={src} fonte={p.fonte} x0={FONTE_W / 2 - 304} x1={FONTE_W / 2 + 304} y1={ly1} />
        <Janela src={src} fonte={p.fonte} x0={lx0} x1={lx1} y0={ly0} y1={ly1} w={1080} h={h} zoom={z} estilo={{top: 480, borderTop: `6px solid ${tema.destaque}`, borderBottom: `6px solid ${tema.destaque}`}} />
      </AbsoluteFill>
    );
  }
  const [jx0, jx1] = d.regioes.jogo ?? [FONTE_W / 2 - 304, FONTE_W / 2 + 304];
  const [cx0, cx1] = d.regioes.comp ?? [0, FONTE_W];
  const [ccx, ccy, cr] = circuloCam(d.regioes);
  // rosto do criador recortado do canto do original
  const lado = 280;
  const kc = lado / (cr * 2);
  const Rosto = (
    <div style={{position: 'absolute', left: 60, top: 1150, width: lado, height: lado, borderRadius: '50%', overflow: 'hidden', border: `7px solid ${tema.destaque}`, boxShadow: '0 10px 30px rgba(0,0,0,0.6)'}}>
      <Quadro src={src} fonte={p.fonte} mudo style={{position: 'absolute', width: FONTE_W * kc, height: FONTE_H * kc, left: lado / 2 - ccx * kc, top: lado / 2 - ccy * kc, maxWidth: 'none'}} />
    </div>
  );
  if (p.layout === 'jogo') {
    return (
      <AbsoluteFill style={{background: '#000'}}>
        <Janela src={src} fonte={p.fonte} x0={jx0} x1={jx1} w={1080} h={1920} />
        {d.regioes.cam || d.regioes.camRet ? Rosto : null}
      </AbsoluteFill>
    );
  }
  const h = (1080 * FONTE_H) / (cx1 - cx0);
  const topo = 470;
  return (
    <AbsoluteFill style={{background: '#0C1730'}}>
      <Fundo src={src} fonte={p.fonte} x0={cx0} x1={cx1} />
      <Janela src={src} fonte={p.fonte} x0={cx0} x1={cx1} w={1080} h={h} estilo={{top: topo, borderTop: `6px solid ${tema.destaque}`, borderBottom: `6px solid ${tema.destaque}`}} />
      <div style={{position: 'absolute', left: 540 - 4, top: topo, width: 8, height: h, background: tema.destaque}} />
      {d.rotulos ? (
        <div style={{position: 'absolute', top: topo - 86, left: 0, width: 1080, display: 'flex', justifyContent: 'space-around'}}>
          <Rotulo cor={tema.destaque}>{d.rotulos[0]}</Rotulo>
          <Rotulo cor={tema.destaque2}>{d.rotulos[1]}</Rotulo>
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

/** Zoom rápido com tremida curta em cada pico de voz (grito, risada, susto). */
const Enfase: React.FC<{quadros: number[]; children: React.ReactNode}> = ({quadros, children}) => {
  const f = useCurrentFrame();
  let s = 1;
  let dx = 0;
  let dy = 0;
  for (const e of quadros) {
    const k = f - e;
    if (k < 0 || k >= 16) continue;
    const q = 1 - k / 16;
    s = 1 + 0.09 * q * q;
    if (k < 7) {
      dx = Math.sin(k * 2.1) * 9 * q;
      dy = Math.cos(k * 2.7) * 6 * q;
    }
  }
  return <AbsoluteFill style={{transform: `translate(${dx}px, ${dy}px) scale(${s})`}}>{children}</AbsoluteFill>;
};

/** Título: entra com impacto, maior que o normal, e em ~1,3 s assenta; crédito e selo aparecem nessa hora. */
const Titulo: React.FC<{texto: string; canal: string; plataforma: string; selo?: string | null}> = ({texto, canal, plataforma, selo}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const pop = spring({frame, fps, config: {damping: 12, stiffness: 170}});
  const sobe = interpolate(frame, [1.3 * fps, 1.3 * fps + 10], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.inOut(Easing.cubic)});
  // começa maior já no topo (no meio da tela cobria o rosto) e assenta no tamanho normal
  const escala = interpolate(sobe, [0, 1], [1.12, 1]) * interpolate(pop, [0, 1], [0.55, 1]);
  return (
    <div style={{position: 'absolute', top: 232, left: 70, width: 870, transform: `scale(${escala})`, transformOrigin: '50% 0', opacity: Math.min(1, pop * 1.6)}}>
      <div style={{fontFamily: tema.fonteImpacto, fontSize: 58, lineHeight: 1.08, color: '#fff', background: 'rgba(12,23,48,0.92)', borderLeft: `12px solid ${tema.destaque}`, borderRadius: 14, padding: '14px 22px', textTransform: 'uppercase', letterSpacing: 1.5, boxShadow: '0 10px 30px rgba(0,0,0,0.45)'}}>{texto}</div>
      <div style={{display: 'flex', gap: 10, marginTop: 8, opacity: sobe}}>
        <div style={{fontFamily: tema.fonteCorpo, fontWeight: 700, fontSize: 26, color: '#fff', background: 'rgba(0,0,0,0.6)', borderRadius: 8, padding: '3px 12px', letterSpacing: 1}}>Corte de: {canal} ({plataforma})</div>
        {selo ? <div style={{fontFamily: tema.fonteCorpo, fontWeight: 700, fontSize: 26, color: '#0C1730', background: tema.destaque, borderRadius: 8, padding: '3px 12px', letterSpacing: 1, textTransform: 'uppercase'}}>{selo}</div> : null}
      </div>
    </div>
  );
};

const Progresso: React.FC<{fim: number}> = ({fim}) => {
  const frame = useCurrentFrame();
  return <div style={{position: 'absolute', left: 0, top: 0, height: 9, width: (1080 * Math.min(frame, fim)) / fim, background: tema.destaque, boxShadow: '0 0 12px rgba(0,0,0,0.6)'}} />;
};

/** Legenda: na emenda jogo/câmera quando o plano é split; no lugar de sempre nos outros. */
const LegendaCorte: React.FC<{sinc: Sinc; planos: Plano[]; regioes: DadosCorte['regioes']}> = ({sinc, planos, regioes}) => {
  const frame = useCurrentFrame();
  const atual = planos.find((p) => frame >= p.de && frame < p.de + p.dur) ?? planos[planos.length - 1];
  // split: na emenda jogo/câmera; cam com moldura (lives): logo abaixo da faixa; demais: posição padrão
  const y = atual?.layout === 'split' ? SPLIT : atual?.layout === 'cam' && regioes.camRet ? Math.min(LEGENDA_Y, 250 + faixaCam(regioes).h + 95) : LEGENDA_Y;
  return <Legenda sinc={sinc} tema={tema} y={y} />;
};

/** Cria o componente de vídeo de um corte (o video.tsx de cada corte só chama isto). */
export const criarCorte = (d: DadosCorte): React.FC<{sinc: Sinc; pasta: string; guias?: boolean}> => {
  const Video: React.FC<{sinc: Sinc; pasta: string; guias?: boolean}> = ({sinc, pasta, guias}) => {
    const {fps} = useVideoConfig();
    const src = staticFile(`${pasta}/fonte.mp4`);
    const fim = d.planos.reduce((s, p) => s + p.dur, 0);
    const plataforma = d.plataforma ?? 'Arquivo local';
    // troca entre rosto e plano aberto é só troca de câmera do original: não leva sopro
    const rosto = (l: Layout) => l === 'cam' || l === 'largo';
    const trocas = d.planos.filter((p, i) => i > 0 && p.layout !== d.planos[i - 1].layout && !(rosto(p.layout) && rosto(d.planos[i - 1].layout)));
    return (
      <AbsoluteFill style={{background: '#0C1730'}}>
        <Enfase quadros={d.enfase ?? []}>
          {d.planos.map((p, i) => (
            <Sequence key={i} from={p.de} durationInFrames={p.dur}>
              <PlanoView p={p} d={d} src={src} />
            </Sequence>
          ))}
        </Enfase>
        <Sequence durationInFrames={fim}>
          <Progresso fim={fim} />
          <Titulo texto={d.titulo} canal={d.canal} plataforma={plataforma} selo={d.selo} />
          <LegendaCorte sinc={sinc} planos={d.planos} regioes={d.regioes} />
        </Sequence>
        {/* som: impacto na abertura e sopro só quando muda o enquadramento (sopro em todo corte cansa) */}
        <Sfx nome="impacto" em={0} volume={0.35} />
        {trocas.map((p) => (
          <Sfx key={p.de} nome="swoosh" em={p.de / fps - 0.08} volume={0.25} />
        ))}
        <ZonaSegura mostrar={guias} />
      </AbsoluteFill>
    );
  };
  return Video;
};
